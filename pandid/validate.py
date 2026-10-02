"""Validate a flowsheet's model and drawn geometry.

Findings have two severities:

- **errors**: contradictions the engine cannot honour, such as
  overlapping pinned units or negative or non-finite coordinates.
  ``render()`` raises on these rather than draw a wrong sheet.
- **warnings**: a valid but imperfect drawing, such as a stream crossing
  a unit, an excessive detour, control letters out of order, or a
  counted nozzle with no line. They are collected on ``fs.warnings``.

:func:`validate` runs two passes:

- :func:`model_issues` reads what the author wrote (pins, tags, nozzle
  counts, stream names) and needs no layout. A render runs it before
  building geometry, so a contradiction such as ``pin(x=nan)`` is
  reported instead of breaking the router
  (:meth:`pandid.flowsheet.Flowsheet._prepare_to_draw`).
- :func:`geometry_issues` reads resolved geometry: overlaps, coincident
  nozzles, crossings, detours and elevations. It checks the units that
  have a frame, so one unplaced balloon does not hide every overlap.

``route-not-settled``, ``instrument-unplaced`` and ``deprecated`` are
recorded by earlier phases and read back here; see
:mod:`pandid.deprecation`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.layout.conflicts import boxes_overlap, segment_crosses_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_TOL = 1.0  # px tolerance so touching edges are not flagged as overlaps

#: Distance in px a drawn coordinate may sit from its pin before
#: ``pin-not-honored``. A pinned axis is copied onto the frame, so only
#: float rounding through a nozzle offset should remain.
_PIN_TOL = 0.05

#: Distance in px a segment may be off square and still count as
#: orthogonal. A sloping segment is also invisible to
#: ``route-crosses-unit``, which is why ``route-diagonal`` reports it.
_SQUARE_TOL = 0.5

#: ``(kind, variant)`` pairs a run is meant to change centreline through,
#: so ``run-off-elevation`` ignores them. An eccentric reducer is flat on
#: top, so its two nozzles differ in height by design. A unit whose
#: nozzles merely sit at different heights, such as a pump, does not
#: belong here; ``tests/test_validate.py`` checks the geometry.
OFFSET_BY_DESIGN = frozenset({
    ("reducer", "eccentric"),
})

#: ``(group, name)`` of supplementary parts whose shape is derived from
#: the body's box, so they distort when the body is drawn at another
#: aspect. Only the item 20.6 drive motor, a circle sized from the shell
#: (:func:`pandid.render.iso_parts.agitator_overlays`); other parts are
#: lines, bars and decks that stay correct on a stretched shell.
#: ``tests/test_validate.py`` measures the circle.
ROUND_PARTS = frozenset({
    (20, "motor"),
})

#: Fraction a symbol carrying a :data:`ROUND_PARTS` mark may depart from
#: its natural aspect before ``symbol-out-of-aspect``. Above the about 1%
#: that whole-unit sizes cannot avoid, and below the 7% and 22% ovals
#: ``agitator_overlays`` is designed to prevent.
_ASPECT_TOL = 0.02

#: Required order of control-function letters in a tag (BS ISO
#: 15519-2:2015 5.2.4), so ``FIC`` is right and ``FCI`` is wrong. Only
#: these letters move; the first letter (measured variable), modifiers
#: (``D``, ``H``, ``L``, ``P``) and unsequenced ISA letters (``T``, ``E``,
#: ``Y``, ``V``) keep their place. See :func:`_is_control_function` for
#: letters that act as modifiers. ``M`` is listed by the clause but no
#: defined control function uses it.
CONTROL_FUNCTION_SEQUENCE = "IRCSMZA"


@dataclass(frozen=True)
class Issue:
    """A single validation finding.

    Attributes
    ----------
    severity : str
        ``"error"`` or ``"warning"``.
    code : str
        Short kebab-case category.
    message : str
        Human-readable description.
    """
    severity: str        # "error" | "warning"
    code: str            # short kebab-case category
    message: str

    def __str__(self) -> str:
        """Return ``[severity] code: message``."""
        return f"[{self.severity}] {self.code}: {self.message}"


def _overlap(a: tuple[float, float, float, float],
             b: tuple[float, float, float, float]) -> bool:
    """Check overlap with the shared drawing-box predicate.

    Parameters
    ----------
    a, b : tuple[float, float, float, float]
        Unit box coordinates.

    Returns
    -------
    bool
        Whether the unit interiors overlap.
    """
    return boxes_overlap(a, b)


def _is_control_function(letters: str, i: int) -> bool:
    """Return whether ``letters[i]`` is a control function ISO 5.2.4 orders.

    Two cases are not: the first letter, which is the measured variable,
    and the ``C`` after ``S`` in a position tag such as ``ZSC``, where it
    means closed (ANSI/ISA-5.1-2009 Table 5.2.1). ``FSC`` and ``ZAC`` are
    still checked.

    Parameters
    ----------
    letters : str
        Tag letters.
    i : int
        Letter index.

    Returns
    -------
    bool
        Whether the letter is sequenced.
    """
    c = letters[i].upper()
    if i == 0 or c not in CONTROL_FUNCTION_SEQUENCE:
        return False
    return not (c == "C" and letters[0].upper() == "Z"
                and letters[i - 1].upper() == "S")


def _control_functions(letters: str) -> list[str]:
    """Return the sequenced letters of a tag, in the order written.

    Parameters
    ----------
    letters : str
        Tag letters.

    Returns
    -------
    list[str]
        Control-function letters.
    """
    return [c for i, c in enumerate(letters) if _is_control_function(letters, i)]


def _in_sequence(letters: str) -> str:
    """Return the tag letters with control functions in ISO 15519-2 order.

    Only control-function letters move; modifiers keep their positions.

    Parameters
    ----------
    letters : str
        Tag letters.

    Returns
    -------
    str
        Reordered letters.
    """
    ordered = iter(sorted(_control_functions(letters),
                          key=lambda c: CONTROL_FUNCTION_SEQUENCE.index(c.upper())))
    return "".join(
        next(ordered) if _is_control_function(letters, i) else c
        for i, c in enumerate(letters)
    )


def _family_stem(port_name: str) -> str | None:
    """Return the family stem of a numbered port.

    ``in_3`` gives ``"in"``; ``inlet``, ``sig_in`` and ``tube_out`` give
    ``None``. Read from the unit's port names rather than the symbol, since
    :class:`~pandid.units.Block` has no port series. Whether the count was
    stated explicitly is checked by the caller.

    Parameters
    ----------
    port_name : str
        Port name.

    Returns
    -------
    str or None
        Stem before ``_<digits>``, or ``None``.
    """
    stem, sep, index = port_name.rpartition("_")
    return stem if sep and stem and index.isdigit() else None


def _and(names: list[str]) -> str:
    """Join names as ``"a"``, ``"a and b"`` or ``"a, b and c"``.

    Parameters
    ----------
    names : list[str]
        Names to join.

    Returns
    -------
    str
        Joined phrase.
    """
    return " and ".join(filter(None, [", ".join(names[:-1]), *names[-1:]]))


def _square(x1, y1, x2, y2) -> bool:
    """Return whether a segment lies along an axis.

    Parameters
    ----------
    x1, y1, x2, y2 : float
        Segment end points.

    Returns
    -------
    bool
        True within :data:`_SQUARE_TOL`.
    """
    return abs(x1 - x2) < _SQUARE_TOL or abs(y1 - y2) < _SQUARE_TOL


def _seg_crosses_box(x1, y1, x2, y2, box) -> bool:
    """Check whether an orthogonal segment passes through a unit box.

    Parameters
    ----------
    x1, y1, x2, y2 : float
        Segment coordinates.
    box : tuple[float, float, float, float]
        Unit box coordinates.

    Returns
    -------
    bool
        Whether the segment crosses the box interior.
    """
    return segment_crosses_box((x1, y1), (x2, y2), box)


def _pinned_y(unit) -> bool:
    """Return whether a unit has an explicit pixel ``y`` pin.

    A ``row`` pin is a grid cell, not a coordinate, and does not count.

    Parameters
    ----------
    unit : Unit
        Unit to check.

    Returns
    -------
    bool
        Whether ``pin_.y`` is set.
    """
    pin = getattr(unit, "pin_", None)
    return pin is not None and getattr(pin, "y", None) is not None


def _off_elevation(su, sp, du, dp) -> tuple[float, float, bool] | None:
    """Return how far two connected nozzles miss a straight run.

    Parameters
    ----------
    su, du : Unit
        Source and destination units.
    sp, dp : ResolvedPort
        Their resolved ports.

    Returns
    -------
    tuple[float, float, bool] or None
        ``(offset, span, source_is_shorter)``: the vertical miss, the
        shorter unit's height it is measured against, and which end that
        is. ``None`` when the run is not a facing E/W pair, the offset is
        by design or sub-pixel, or it clears the shorter unit.
    """
    from pandid.portgeom import unit_box

    # Only facing E/W nozzles share one elevation; vertical faces make a
    # riser, and a run that doubles back is not a straight line.
    if {sp.face, dp.face} != {"E", "W"} or (sp.face == "E") != (dp.point[0] > sp.point[0]):
        return None

    # The fitting is meant to step; see OFFSET_BY_DESIGN.
    for u in (su, du):
        if (u.kind, getattr(u, "variant", "default")) in OFFSET_BY_DESIGN:
            return None

    offset = abs(dp.point[1] - sp.point[1])
    if offset <= _TOL:
        return None  # sub-pixel; nothing is drawn differently

    # Compare with the shorter drawn unit's height: an unadjusted nozzle
    # offset is smaller than that, while a deliberate change of elevation
    # clears the unit. Half the height misses real cases.
    sb, db = unit_box(su, su.frame), unit_box(du, du.frame)
    sh, dh = sb[3] - sb[1], db[3] - db[1]
    span = min(sh, dh)
    return (offset, span, sh <= dh) if offset < span else None


def _crowded(heads: list[tuple[float, str]], floor: float
             ) -> tuple[float, str, str] | None:
    """Return the tightest adjacent pair of arrowheads on a face, if too tight.

    Pairs under :data:`_TOL` are left to ``coincident-ports``.

    Parameters
    ----------
    heads : list[tuple[float, str]]
        ``(position along the face, port name)`` for each arrowhead.
    floor : float
        Minimum pitch.

    Returns
    -------
    tuple[float, str, str] or None
        ``(pitch, nearer port, further port)``, or ``None``.
    """
    order = sorted(heads)
    pairs = sorted((b[0] - a[0], a[1], b[1]) for a, b in zip(order, order[1:]))
    return next((p for p in pairs if _TOL < p[0] < floor), None)


def model_issues(fs: "Flowsheet", *, tabulates: bool = True) -> list["Issue"]:
    """Return the findings that need no layout, errors first.

    These run before a render builds geometry. ``gravity-turned`` is here
    because a turn comes only from the pin, which layout copies onto the
    frame unchanged; the frame is preferred when there is one.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.
    tabulates : bool, default=True
        :func:`~pandid.render.svg.tabulates_boundary_flows` for the
        diagram. Only ``stream-table-missing`` reads it: ISO 10628-1
        4.3.2 d) requires a stream table on a PFD, not on a P&ID (4.4.2)
        or BFD (4.2).

    Returns
    -------
    list[Issue]
        Errors, then warnings.
    """
    from difflib import get_close_matches

    from pandid import units
    from pandid.deprecation import findings as deprecation_findings
    from pandid.portgeom import resolve_size
    from pandid.render.svg import LABEL_POSITIONS
    from pandid.render.symbols import default_registry
    from pandid.units import Instrument

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- deprecated API (recorded at the call) ---
    warnings.extend(deprecation_findings(fs))

    # --- pin sanity ---
    for u in fs.units:
        pin = u.pin_
        if pin is None:
            continue
        for axis, v in (("x", pin.x), ("y", pin.y)):
            if v is None:
                continue
            if not math.isfinite(v):
                errors.append(Issue("error", "pin-not-finite",
                                    f"{u.name} pinned {axis}={v!r} is not a finite number"))
            elif v < 0:
                errors.append(Issue("error", "pin-out-of-bounds",
                                    f"{u.name} pinned {axis}={v} is negative (off-sheet)"))

    # --- a label side no renderer places ---
    # An error: an unknown label_pos would draw the tag at the top and,
    # being an explicit choice, skip the search that moves tags off ink.
    # Checked here rather than in Unit.__init__ because a spec sets the
    # attribute directly; every drawing path validates the model first.
    for u in fs.units:
        side = getattr(u, "label_pos", None)
        # Empty means unset; readers use ``label_pos or "top"``.
        if not side or side in LABEL_POSITIONS:
            continue
        close = get_close_matches(str(side).strip().lower(), LABEL_POSITIONS, n=1, cutoff=0.6)
        errors.append(Issue(
            "error", "label-pos-unknown",
            f"{u.name} asks for label_pos={side!r}, which no side answers to"
            + (f" (did you mean {close[0]!r}?)" if close else "")
            + f". Use one of {', '.join(LABEL_POSITIONS)}, or leave label_pos "
              f"unset and let the engine put the tag on the first face no "
              f"nozzle leaves from"))

    # --- a kind the symbol library has no artwork for ---
    # SymbolRegistry.get draws an unregistered kind as a blank 60x60 box,
    # which is right for an external Unit subclass but silent for a typo.
    # Reported here, once per kind, because the registry is asked on every
    # port resolution and never sees the unit.
    catalogue = sorted({getattr(units, name).kind for name in units.__all__
                        if default_registry.variants(getattr(units, name).kind)})
    unknown: set[str] = set()
    for u in fs.units:
        if default_registry.variants(u.kind) or u.kind in unknown:
            continue
        unknown.add(u.kind)
        # Describe the box the registry actually draws.
        blank = default_registry.get(u.kind)
        close = get_close_matches(u.kind, catalogue, n=1, cutoff=0.6)
        warnings.append(Issue(
            "warning", "symbol-kind-unknown",
            f"{u.name} is a {u.kind!r}, which no symbol is registered for"
            + (f" (did you mean {close[0]!r}?)" if close else "")
            + f"; it is drawn as a blank {blank.width:g}x{blank.height:g} box with "
              f"no ports. Register artwork for it with "
              f"default_registry.register({u.kind!r}, Symbol(...))"))

    # --- turned symbols whose function is gravity ---
    # ISO 15519-1:2010 11.4.2 excepts symbols whose function depends on
    # gravity from turning, naming the open tank (2061) and the cyclone
    # (X 2618). A warning: the sheet still draws, and
    # tests/test_symbol_invariants turns every symbol. Mirroring is not
    # covered. Read from the frame when placed, else the pin.
    for u in fs.units:
        placed = u.frame if u.frame is not None else u.pin_
        turn = int(getattr(placed, "orientation", 0) or 0)
        variant = getattr(u, "variant", "default")
        # Leave an unknown variant to the renderer; looking it up here
        # would raise.
        if not turn or variant not in default_registry.variants(u.kind):
            continue
        if not default_registry.for_unit(u).gravity_fixed:
            continue
        # ISO's remedy is a symbol drawn in the wanted orientation; suggest
        # the lying variant where one exists.
        lying = ("horizontal" if variant != "horizontal"
                 and "horizontal" in default_registry.variants(u.kind) else "")
        warnings.append(Issue(
            "warning", "gravity-turned",
            f"{u.name} is turned {turn}°; ISO 15519-1:2010 11.4.2 excepts "
            f"symbols where gravity is a functionality from turning, and a "
            f"{u.kind}/{variant} is one of them"
            + (f". Use variant={lying!r}, which is that equipment drawn lying "
               f"down rather than the upright one turned" if lying else "")))

    # --- a round mark drawn as an oval ---
    # An explicit width/height is the final box
    # (:func:`pandid.portgeom.resolve_size`), so a box of another shape
    # stretches the artwork. That is fine for a shell but distorts the
    # marks in :data:`ROUND_PARTS`. Changing a symbol's artwork can make a
    # hard-coded example size wrong, so this is checked. Read from the
    # model, before layout; resolve_size already handles quarter turns and
    # label-sized boundary flags.
    for u in fs.units:
        variant = getattr(u, "variant", "default")
        if variant not in default_registry.variants(u.kind):
            continue
        sym = default_registry.for_unit(u)
        marks = [ov for ov in sym.overlays if (ov.group, ov.name) in ROUND_PARTS]
        if not marks:
            continue
        # Compare the drawn box with the natural box, swapped for a turn.
        placed = u.frame if u.frame is not None else u.pin_
        w, h = resolve_size(u, placed)
        nat_w, nat_h = sym.width, sym.height
        if int(getattr(placed, "orientation", 0) or 0) in (90, 270):
            nat_w, nat_h = nat_h, nat_w
        if min(w, h, nat_w, nat_h) <= 0:
            continue
        across, down = w / nat_w, h / nat_h
        out_of_shape = max(across, down) / min(across, down) - 1.0
        if out_of_shape <= _ASPECT_TOL:
            continue
        # Suggest the width that fits the current height.
        fits = nat_w / nat_h * h
        iso = [default_registry.part(ov.group, ov.name).iso for ov in marks]
        named = _and([f"ISO item {p.item} {p.reg}" for p in iso])
        warnings.append(Issue(
            "warning", "symbol-out-of-aspect",
            f"{u.name} is drawn {w:g}x{h:g} on a {u.kind}/{variant} whose own box "
            f"is {nat_w:g}x{nat_h:g}, so the artwork is scaled x{across:.3f} across "
            f"and x{down:.3f} down -- {out_of_shape * 100:.0f}% out of shape. That "
            f"drawing carries {named}, a circle whose size the composition works out "
            f"from the box above, so at this one it is drawn as an oval. Give "
            f"{u.name} a box of the same shape, {u.name}.width = {fits:.4g} for the "
            f"height it has, or leave width= and height= unset and let the symbol "
            f"size itself"))

    # --- tag spelling ---
    # A warning, since house styles differ. One finding per tag, so a
    # repeated interlock square reports once.
    spelled: set[str] = set()
    for u in fs.units:
        if not isinstance(u, Instrument) or u.tag in spelled:
            continue
        spelled.add(u.tag)
        ordered = _in_sequence(u.type)
        if ordered == u.type:
            continue
        sequence = ", ".join(CONTROL_FUNCTION_SEQUENCE[:-1]) + f", and {CONTROL_FUNCTION_SEQUENCE[-1]}"
        warnings.append(Issue(
            "warning", "letter-sequence",
            f"{u.tag} spells its control functions {u.type!r}; ISO 15519-2:2015 5.2.4 "
            f"orders them {sequence}, so this tag reads {ordered!r}"))

    # --- a counted nozzle with no line on it ---
    # A numbered nozzle family is a count the author wrote (n_inlets=4),
    # so an unconnected member is a missing stream; the gap also spaces
    # the drawn lines wrongly. Declared single nozzles (drains, vents,
    # duties, spare sides) are offers and may stay open. One finding per
    # family. No standard requires this; the drawing contradicts its own
    # declaration. tests/test_validate.py measures the examples.
    for u in fs.units:
        families: dict[str, list[str]] = {}
        for name in u.ports:
            stem = _family_stem(name)
            if stem is not None:
                families.setdefault(stem, []).append(name)
        for stem, members in families.items():
            # Process ports only: a bare signal port is normal.
            if any(u.ports[n].role == "signal" for n in members):
                continue
            # A sole member with a live alias (Reactor.feed, Column.feed,
            # Tank.inlet) is offered by the class, not counted by the
            # author, so skip it. Aliases are instance attributes outside
            # ``ports``; the port's own attribute (``in_1``) is in ports and
            # does not count, so Mixer(n_inlets=1) is still checked.
            sole = u.ports[members[0]]
            if len(members) == 1 and any(
                name not in u.ports and not name.startswith("_") and value is sole
                for name, value in vars(u).items()
            ):
                continue
            members.sort(key=lambda member: int(member.rpartition("_")[2]))
            loose = [m for m in members if u.ports[m].stream is None]
            if not loose:
                continue
            n, piped = len(members), len(members) - len(loose)
            # Abbreviate as ``in_1..in_4`` only for an unbroken run.
            run = [f"{stem}_{i}" for i in range(1, n + 1)]
            named = (f"{members[0]}..{members[-1]}" if n > 2 and members == run
                     else _and(members))
            # Offer both cures: connect, or build with fewer.
            it = "it" if len(loose) == 1 else "them"
            cure = (f"Connect {it}, or build {u.name} with the {piped} it uses."
                    if piped else
                    f"Connect {it}: nothing is piped to {u.name} at all.")
            warnings.append(Issue(
                "warning", "nozzle-unconnected",
                f"{_and([f'{u.name}.{m}' for m in loose])} "
                f"{'carries' if len(loose) == 1 else 'carry'} no stream. "
                f"{u.name} was built with {n} numbered "
                f"nozzle{'' if n == 1 else 's'}, {named}, and {piped} of them "
                f"{'is' if piped == 1 else 'are'} piped, so the sheet asserts "
                f"{n} connections and draws {piped}. {cure}"))

    # --- a counted number landing on a name already taken ---
    # The stream table has one column per name, so two streams with one
    # name lose a column. Authors share names on purpose (one run drawn in
    # several connect calls, or one line number over several segments), so
    # only names the counter invented are reported: renumber_streams
    # promises an unused name. A warning, since the cure is a rename.
    counted: dict[str, list] = {}
    taken: dict[str, int] = {}
    for group in fs._stream_groups():
        # Counted only when no stream has an explicit name or line number.
        chosen = any(not s.auto_named or s.has_line_number for s in group)
        name = group[0].name
        taken[name] = taken.get(name, 0) + 1
        if not chosen:
            counted.setdefault(name, []).append(group)
    # Signal and duty lines share the counter, so include them.
    for s in fs.streams:
        if s.kind == "material":
            continue
        taken[s.name] = taken.get(s.name, 0) + 1
        if s.auto_named and not s.has_line_number:
            counted.setdefault(s.name, []).append([s])
    for name, groups in counted.items():
        if taken[name] < 2:
            continue
        # Name the ends of the counted runs so they can be found.
        where = _and([f"{g[0].source.owner.name} to {g[-1].dest.owner.name}"
                      for g in groups[:2]])
        plural = "run" if len(groups) == 1 else "runs"
        warnings.append(Issue(
            "warning", "stream-name-reused",
            f"{taken[name]} streams answer to {name!r}, and auto-numbering "
            f"chose it for the {plural} {where}. The stream table is one column "
            f"per name, so those runs share a column and one of them is not "
            f"tabulated at all, while both are drawn with the same label. "
            f"Name the counted run yourself, connect(..., name=...), or move "
            f"the series clear of the names already in use with "
            f"Flowsheet(stream_number_start=...)"))

    # --- a title-block cell that cannot hold what it was given ---
    # The strip (ISO 5457 position, ISO 7200 content) is fixed, so a long
    # value is shrunk, abbreviated or overflows, per
    # :func:`~pandid.render.furniture.title_strip_layout`. Silently altered
    # values, such as a truncated drawing number, must be reported. Widths
    # are constants, so this needs no layout; renderers replace these
    # findings with their own (``_FIT_CODES`` in :mod:`pandid.render.svg`).
    if fs.title_block is not None:
        from datetime import datetime

        from pandid.render.furniture import (company_overflow,
                                             title_strip_fit,
                                             undrawn_signatories)
        from pandid.render.svg import fit_issue

        tb = fs.title_block
        # Pass the fallbacks unchosen, as the renderers do, so blank
        # handling matches the drawn sheet.
        warnings.extend(fit_issue(*found) for found in title_strip_fit(
            tb, fs.name, datetime.now().strftime("%Y-%m-%d")))

        # --- a company name that wraps out through the strip ---
        # The company cell grows by wrapping, and the wrapped stack can
        # overflow the strip top and bottom.
        over = company_overflow(tb)
        if over is not None:
            rows, room, need = over
            warnings.append(Issue(
                "warning", "title-block-company-overflows",
                f"company={tb.company!r} wraps to {rows} lines and needs "
                f"{need:.0f} of the {room:.0f} units the strip is deep "
                f"({need / room:.1f}x), so it is drawn out through the top and "
                f"the bottom of the block. The cell breaks between words and "
                f"never inside one: shorten the name, or state the trading name "
                f"the drawing office puts on a sheet"))

        # --- a signatory the strip does not letter ---
        # drawn_by, checked_by and approved_by fill the newest revision
        # row's BY / CHK'D / APP'D cells
        # (:func:`~pandid.render.furniture.undrawn_signatories`). They go
        # undrawn when there is no revision, or when the newest revision
        # names its own signatory. ISO 7200 4.3 makes the creator and
        # approver mandatory, so both cases are reported, separately since
        # the cures differ. No row is invented for them.
        unfilled = [f"{field}={value!r}"
                    for field, value, displaced in undrawn_signatories(tb)
                    if not displaced]
        overridden = [f"{field}={value!r} ({displaced} is drawn)"
                      for field, value, displaced in undrawn_signatories(tb)
                      if displaced]
        if unfilled:
            warnings.append(Issue(
                "warning", "title-block-signatory-undrawn",
                f"the title block sets {_and(unfilled)}, and the sheet draws "
                f"{'none of them' if len(unfilled) > 1 else 'it nowhere'}. "
                f"Those fields fill the BY / CHK'D / APP'D cells of the newest "
                f"revision row, and a block with no revisions has no row for "
                f"them to fill. Add the revision they signed, "
                f"revisions=[Revision('0', '<date>', '<description>')], or "
                f"name them on it directly with Revision(..., by=, checked=, "
                f"approved=)"))
        if overridden:
            warnings.append(Issue(
                "warning", "title-block-signatory-undrawn",
                f"the title block sets {_and(overridden)}, so the sheet draws "
                f"the revision's name and not the block's. The row is the more "
                f"specific claim and keeps the cell; what is left is a "
                f"block-level value on no sheet. Drop it, or take the name off "
                f"the revision and let the block fill the row"))

    # --- an ingoing or outgoing material with nothing to report ---
    # ISO 10628-1:2014 4.3.2 d) requires a PFD to state each ingoing and
    # outgoing material's flow rate. The stream table keeps a boundary
    # column even when empty (:func:`pandid.render.furniture._table_streams`);
    # this says what a column of dashes means. Only on a sheet that
    # tabulates other streams: a sheet with no properties at all is
    # handled below.
    runs = fs._named_runs()
    if any(s.properties for segments in runs.values() for s in segments):
        for name, segments in runs.items():
            if any(s.properties for s in segments):
                continue
            flags = list(dict.fromkeys(
                p.owner.name for s in segments for p in (s.source, s.dest)
                if isinstance(p.owner, units._Boundary)))
            if not flags:
                continue
            warnings.append(Issue(
                "warning", "boundary-flow-missing",
                f"{name} crosses the sheet edge at {_and(flags)} and states no "
                f"property, on a sheet whose other streams state theirs. ISO "
                f"10628-1:2014 4.3.2 d) has a process flow diagram name every "
                f"ingoing and outgoing material and state its flow rate or "
                f"quantity, so the stream table keeps this column "
                f"rather than dropping it the way it drops an empty internal "
                f"one -- and every cell in it reads '-'. Write what the line "
                f"carries, properties={{'Flow (kg/h)': ...}} on it, or state "
                f"that there is nothing to report with a blank value, which "
                f"keeps the column on purpose"))
    else:
        # --- a PFD with material crossing its edge and no table at all ---
        # ISO 10628-1:2014 4.3.2 c) and d) still apply to a PFD with no
        # stream table. ``tabulates`` is true only for a PFD
        # (:func:`~pandid.render.svg.tabulates_boundary_flows`): a P&ID
        # answers 4.4.2, and a BFD lists flow rate as optional (4.2.3). One
        # finding for the sheet.
        if tabulates:
            crossed = list(dict.fromkeys(
                name for name, segments in runs.items()
                if any(isinstance(p.owner, units._Boundary)
                       for s in segments for p in (s.source, s.dest))))
            if crossed:
                warnings.append(Issue(
                    "warning", "stream-table-missing",
                    f"{_and(crossed)} cross{'es' if len(crossed) == 1 else ''} "
                    f"the sheet edge and nothing on the sheet is tabulated. "
                    f"ISO 10628-1:2014 4.3.2 d) has a process flow diagram "
                    f"name every ingoing and outgoing material and state its "
                    f"flow rate or quantity. Set properties="
                    f"{{'Flow (kg/h)': ...}} on the lines that carry one and "
                    f"render(show_stream_table=True) to report it."))

    return errors + warnings


def geometry_issues(fs: "Flowsheet", *, arrows: bool = True) -> list["Issue"]:
    """Return the findings that need resolved geometry, errors first.

    Before :meth:`~pandid.flowsheet.Flowsheet.layout` and
    :meth:`~pandid.flowsheet.Flowsheet.route` have run these are silent
    rather than wrong: nothing is placed, ``route_converged`` starts true
    and ``unplaced_instruments`` starts empty.

    Parameters
    ----------
    fs : Flowsheet
        Drawing whose resolved geometry is checked.
    arrows : bool, default=True
        Whether this rendering draws arrowheads on process lines (a PFD or
        BFD, not a P&ID); :func:`pandid.render.svg.draws_arrowheads`
        decides, via :meth:`pandid.flowsheet.Flowsheet.validate`.

    Returns
    -------
    list[Issue]
        Geometry findings with errors before warnings.
    """
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.portgeom import (is_anchored, pin_intent, port_faces,
                                 port_point, resolve_port, unit_box)
    from pandid.render.symbols import (ARROWHEAD, MIN_HEAD_CLEARANCE,
                                       MIN_NOZZLE_PITCH, default_registry,
                                       label_span, wears_arrowhead)
    from pandid.streams import SIGNAL_KINDS, Stream
    from pandid.units import Block

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- routing settled? (recorded by route()) ---
    # Placing instruments and routing around them can alternate on a
    # dense sheet; the drawing is coherent but which state it caught is
    # arbitrary.
    if not fs.route_converged:
        warnings.append(Issue(
            "warning", "route-not-settled",
            f"attached instruments were still moving after {MAX_PLACEMENT_PASSES} "
            "routing passes; a balloon may sit slightly off the line it taps. "
            "Pin the balloon-carrying lines with via() to settle it"))

    search_result = getattr(fs, "_layout_search_result", None)
    if search_result is not None and search_result.status != "converged":
        code = (
            "layout-search-budget-exhausted"
            if search_result.status == "budget_exhausted"
            else "layout-search-unresolved"
        )
        warnings.append(Issue(
            "warning", code,
            f"layout search {search_result.status} with "
            f"{len(search_result.conflicts)} named conflicts after "
            f"{search_result.exact_trials} exact trials"
        ))

    # --- a balloon nothing could place (recorded by layout) ---
    # An attached instrument is placed from its host, so a chain of them
    # must end on a placed unit. Read from place_attached's record,
    # because ``frame is None`` alone cannot tell "not laid out yet" from
    # "gave up". An error: the renderer refuses a frameless unit.
    for u in fs.unplaced_instruments:
        # Name what is actually missing for each kind of host.
        where = (f"stream {u.host.name}, which has an end nothing placed"
                 if isinstance(u.host, Stream) else
                 f"{u.host.name}, which is unplaced itself")
        errors.append(Issue(
            "error", "instrument-unplaced",
            f"{u.name} has no position on the sheet: it hangs off {where}. An "
            f"attached balloon takes its frame from its host, so a chain of "
            f"them has to end on something the layout places, and this one "
            f"closes on itself. Attach {u.name} to the line or the equipment "
            f"it reads, {u.name}.attach(<stream or unit>), or build it with no "
            f"anchor at all, which lays it out like any other unit"))

    # --- geometric checks (need resolved frames) ---
    # Check the placed units, so one unplaced balloon does not hide the
    # rest.
    placed = [u for u in fs.units if u.frame is not None]
    if placed:
        # Soft: a placement the sheet did not honour.
        #
        # A pinned axis is copied exactly, so a different drawn coordinate
        # means something moved the unit afterwards. One check covers every
        # cause, comparing :func:`~pandid.portgeom.pin_intent` with the
        # frame. A warning: the drawing is coherent, just not as asked.
        for u in placed:
            # Messages, worded per axis kind.
            missed: list[str] = []
            for axis, (port_name, want) in pin_intent(u).items():
                drawn = (port_point(u, u.frame, port_name)[0 if axis == "x" else 1]
                         if port_name is not None else getattr(u.frame, axis))
                if abs(drawn - want) > _PIN_TOL:
                    nozzle = f".{port_name}" if port_name is not None else ""
                    missed.append(f"{u.name}{nozzle} was pinned {axis}={want:g} and is "
                                  f"drawn at {drawn:g}, {abs(drawn - want):g} away")
            # Grid ranks: compare the pinned col/row with the frame's. Skip a
            # rank superseded by an absolute pin on the same axis
            # (:func:`pandid.layout.control._place_free`); the coordinate
            # is checked above.
            pin = u.pin_
            for axis, absolute in (("col", "x"), ("row", "y")) if pin is not None else ():
                want, rank = getattr(pin, axis), getattr(u.frame, axis)
                if want is None or rank == want or getattr(pin, absolute) is not None:
                    continue
                missed.append(f"{u.name} was pinned {axis}={want} and is "
                              + (f"drawn in {axis}={rank}" if rank is not None
                                 else f"drawn with no {axis} of its own"))
            # An attached balloon has no grid rank, so suggest what works.
            cure = ("An attached balloon stands in no grid: it is placed from "
                    "its host, or from an absolute pin. Say where with "
                    f"{u.name}.pin(x=..., y=...), aim it with "
                    f"{u.name}.attach(at=..., offset=..., angle=...), or "
                    "detach it to have it laid out like any other unit"
                    if getattr(u, "host", None) is not None else
                    "A pinned axis is honoured exactly, so something moved "
                    "this unit after the solver read the pin")
            for said in missed:
                warnings.append(Issue("warning", "pin-not-honored", f"{said}. {cure}"))

        boxes = [(u, unit_box(u, u.frame)) for u in placed]
        # Only streams with both ends placed have a drawn path.
        drawn = [s for s in fs.streams if s.source.owner.frame is not None
                 and s.dest.owner.frame is not None]

        # A block's name is lettered inside its box, so an explicit width
        # that is too narrow overruns it. A warning, under its own code:
        # SvgRenderer replaces ``text-overruns-cell`` findings with its own.
        for u, box in boxes:
            if not isinstance(u, Block) or not u.tag:
                continue
            room = box[2] - box[0]
            needed = label_span(str(u.tag))
            if room + _TOL >= needed:
                continue
            warnings.append(Issue(
                "warning", "label-overruns-symbol",
                f"{u.name} letters {str(u.tag)!r} inside a box {room:g} units wide, "
                f"and the name needs {needed:g}: it is drawn about "
                f"{(needed - room) / 2:.0f} units out through each side. Widen the "
                f"block, or leave width= unset and let it size itself to the name"))

        # Hard: a nozzle drawn off the body it belongs to.
        #
        # A line to it would stop in blank paper. Registered symbols keep
        # nozzles on their box by construction (the invariant suite and
        # :func:`~pandid.render.symbols.spread`), so this guards third-party
        # symbols and new families. Unanchored ports fall back to the box
        # centre and are left to ``coincident-ports``. Measured against
        # :func:`~pandid.portgeom.unit_box`, the router's obstacle, with
        # ``_TOL`` for nozzles on the edge.
        for u, box in boxes:
            for name in u.ports:
                if not is_anchored(u, name):
                    continue
                px, py = port_point(u, u.frame, name)
                if (box[0] - _TOL <= px <= box[2] + _TOL
                        and box[1] - _TOL <= py <= box[3] + _TOL):
                    continue
                errors.append(Issue(
                    "error", "nozzle-off-body",
                    f"{u.name}.{name} is drawn at ({px:.1f}, {py:.1f}), outside "
                    f"{u.name}'s own box ({box[0]:.1f}, {box[1]:.1f}) to "
                    f"({box[2]:.1f}, {box[3]:.1f}): a line to it stops in blank "
                    f"paper beside the symbol rather than on it. The symbol places "
                    f"this nozzle, so the drawing is what has to change -- give "
                    f"{u.name} a box the family fits in, or put the connection on "
                    f"a face with room for it"))

        # Hard: overlapping unit bodies.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i][1], boxes[j][1]):
                    errors.append(Issue("error", "unit-overlap",
                                        f"{boxes[i][0].name} and {boxes[j][0].name} overlap"))

        # Hard: two live connections on one unit landing on the same
        # point. The runtime half of
        # :meth:`pandid.render.symbols.Symbol.coincident_ports`, since face
        # choice is known only on the finished sheet. Units with
        # :attr:`pandid.units.Unit.ONE_NOZZLE_MANY_RUNS` (boundary flags)
        # are exempt: every run on a flag meets at its mark.
        for u in placed:
            if type(u).ONE_NOZZLE_MANY_RUNS:
                continue
            seen: dict[tuple[float, ...], str] = {}
            for name, port in u.ports.items():
                if port.stream is None:
                    continue
                pt = tuple(round(v, 3) for v in port_point(u, u.frame, name))
                first = seen.get(pt)
                if first is None:
                    seen[pt] = name
                    continue
                # Unanchored ports share the box centre: a symbol gap, so
                # only a warning.
                anchored = is_anchored(u, name) and is_anchored(u, first)
                issue = Issue(
                    "error" if anchored else "warning", "coincident-ports",
                    f"{u.name}.{first} and {u.name}.{name} are both connected and "
                    f"both resolve to ({pt[0]}, {pt[1]})"
                    + ("" if anchored else "; the symbol anchors no nozzle for one "
                       "of them, so both fall back to the centre of the box"))
                (errors if anchored else warnings).append(issue)

        # Soft: arrowheads on one face too close to tell apart. Two heads
        # (:data:`pandid.render.symbols.ARROWHEAD`) at pitch p leave
        # ``p - ARROWHEAD`` of paper, which must be at least
        # MIN_HEAD_CLEARANCE (ISO 128-20). Both ports of a pair must carry
        # a head. The message suggests a box size, scaling the face extent
        # by the shortfall, and a move only where the symbol offers
        # another face.
        for u in placed if arrows else ():
            heads: dict[str, list[tuple[float, str]]] = {}
            for name, port in u.ports.items():
                s = port.stream
                # The head is at the destination end only.
                if s is None or s.dest is not port:
                    continue
                if not wears_arrowhead(s, default_registry):
                    continue
                at = resolve_port(u, u.frame, name)
                along = at.point[1] if at.face in ("E", "W") else at.point[0]
                heads.setdefault(at.face, []).append((along, name))
            for face, on_face in heads.items():
                tight = _crowded(on_face, MIN_NOZZLE_PITCH)
                if tight is None:
                    continue
                pitch, first, second = tight
                across, dim = ((u.frame.h, "height") if face in ("E", "W")
                               else (u.frame.w, "width"))
                room = math.ceil(across * MIN_NOZZLE_PITCH / pitch)
                crowd = (f", the tightest of the {len(on_face)} it carries there"
                         if len(on_face) > 2 else "")
                # Word the message for a thin gap or an overlap.
                gap = pitch - ARROWHEAD
                measured = (
                    f"which leaves {gap:.1f}px of paper between two "
                    f"{ARROWHEAD:.0f}px arrowheads -- under the "
                    f"{MIN_HEAD_CLEARANCE:.0f}px ISO 128-20:1996 4.4 asks between "
                    f"parallel lines, twice the weight this sheet draws them at"
                    if gap > 0 else
                    f"which overlaps two {ARROWHEAD:.0f}px arrowheads by "
                    f"{-gap:.1f}px, so the two heads are drawn over each other")
                # Suggest a move only where the artwork offers another face.
                movable = [n for n in (first, second)
                           if len(port_faces(u, n, u.frame)) > 1]
                elsewhere = (f", or move {u.name}.{movable[0]} onto another face "
                             f"with nozzle()" if movable else "")
                warnings.append(Issue(
                    "warning", "nozzles-crowded",
                    f"{u.name}.{first} and {u.name}.{second} are {pitch:.1f}px apart "
                    f"on {u.name}'s {face} face{crowd}, {measured}. Give the unit a "
                    f"box with room for them, {u.name}.{dim} = {room}{elsewhere}"))

        # Soft: a route passing through a unit body it does not connect
        # to, and grossly indirect routes.
        # Each unit's host, read once: asking per segment misses the
        # attribute on every unit that has none, which dominated this loop.
        hosted = [(u, box, getattr(u, "host", None)) for u, box in boxes]
        for s in drawn:
            if not (s.route and s.route.waypoints):
                continue
            src_u, dst_u = s.source.owner, s.dest.owner
            sp = port_point(src_u, src_u.frame, s.source.name)
            dp = port_point(dst_u, dst_u.frame, s.dest.name)
            pts = [sp] + list(s.route.waypoints) + [dp]

            for k in range(len(pts) - 1):
                (x1, y1), (x2, y2) = pts[k], pts[k + 1]
                for u, box, host in hosted:
                    if u is src_u or u is dst_u or host is s:
                        continue  # in-line elements own their line
                    if _seg_crosses_box(x1, y1, x2, y2, box):
                        warnings.append(Issue("warning", "route-crosses-unit",
                                              f"stream {s.name} crosses {u.name}"))
                        break

            # Soft: a segment drawn on the slant. BS ISO 15519-1:2010 12.1
            # wants horizontal or vertical lines but allows oblique ones
            # where clearer, so this warns. A single off-axis via() point is
            # the usual cause. route-detour cannot see it (same Manhattan
            # length) and route-crosses-unit ignores sloping segments. One
            # finding per stream.
            slopes = [(a, b) for a, b in zip(pts, pts[1:]) if not _square(*a, *b)]
            if slopes:
                (x1, y1), (x2, y2) = slopes[0]
                more = ("" if len(slopes) == 1 else
                        f", the first of {len(slopes)} on it")
                # Offer the corners that do not double the line back. On an
                # automatic route a slope means stale geometry, so suggest
                # routing again.
                corners = [c for c in ((x1, y2), (x2, y1))
                           if all(math.dist(c, p) > _SQUARE_TOL for p in pts)]
                named = " or ".join(f"({cx:g}, {cy:g})"
                                    for cx, cy in corners or [(x1, y2), (x2, y1)])
                cure = (f"via() states the exact points the line is drawn through and "
                        f"squares nothing up, so each consecutive pair -- the two "
                        f"nozzles included -- has to share an x or a y. Add the "
                        f"corner it turns at, {named}"
                        if s.route.manual else
                        "the router draws right angles only, so this is a path "
                        "resolved against geometry that has since moved: route() "
                        "again after the last change to the sheet")
                warnings.append(Issue(
                    "warning", "route-diagonal",
                    f"stream {s.name} is drawn on the slant, ({x1:g}, {y1:g}) to "
                    f"({x2:g}, {y2:g}){more}. ISO 15519-1:2010 12.1 has connecting "
                    f"lines oriented horizontally or vertically, and a diagonal is "
                    f"also invisible to the check that reports a line crossing a "
                    f"vessel. {cure}"))

            length = sum(abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1])
                         for k in range(len(pts) - 1))
            direct = abs(dp[0] - sp[0]) + abs(dp[1] - sp[1])
            if direct > 1 and length > 3.0 * direct:
                warnings.append(Issue("warning", "route-detour",
                                      f"stream {s.name} routes {length:.0f}px for a "
                                      f"{direct:.0f}px span ({length / direct:.1f}x)"))

        # Soft: a horizontal run whose ends nearly share an elevation.
        # Pinning units by their top-left corner leaves nozzles slightly
        # off level, and the router draws a step. ``pin(port=...)`` is the
        # cure.
        for s in drawn:
            # Signal lines have no elevation to be off.
            if s.kind in SIGNAL_KINDS:
                continue
            su, du = s.source.owner, s.dest.owner
            # Only where an elevation was pinned by hand; layout may move
            # free units.
            if not (_pinned_y(su) or _pinned_y(du)):
                continue
            src = resolve_port(su, su.frame, s.source.name)
            dst = resolve_port(du, du.frame, s.dest.name)
            near = _off_elevation(su, src, du, dst)
            if near is None:
                continue
            offset, span, at_source = near
            # Suggest pinning the shorter unit's nozzle to the other's level.
            if at_source:
                dev, port, target = su, s.source.name, dst.point[1]
            else:
                dev, port, target = du, s.dest.name, src.point[1]
            warnings.append(Issue(
                "warning", "run-off-elevation",
                f"stream {s.name} runs from {su.name}.{s.source.name} to "
                f"{du.name}.{s.dest.name}, whose nozzles are {offset:.1f}px apart "
                f"-- inside the {span:.0f}px {dev.name} measures across the run, so "
                f"the line steps into it and back out instead of changing elevation. "
                f"That is corner arithmetic rather than a step: pin the nozzle, "
                f"{dev.name}.pin(port={port!r}, y={target:g})"))

    # Soft: two parallel runs closer than ISO 10628-1 5.3.2 allows: twice
    # the wider line and at least 1 mm, which is ``max(2 * wider, 4)``
    # drawing units (one unit is 0.25 mm; pandid.render.weights.M). Only
    # runs that overlap in projection count.
    warnings.extend(_crowded_lines(fs))

    return errors + warnings


def _crowded_lines(fs: "Flowsheet") -> list["Issue"]:
    """Return ``lines-crowded`` findings for parallel runs (ISO 10628-1 5.3.2).

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    list[Issue]
        One warning per crowded pair, tightest first.
    """
    from pandid.render.svg import stream_polyline, _stream_rung
    from pandid.render.weights import M
    from pandid.streams import SIGNAL_KINDS

    unit_mm = 2.5 / M           # one drawing unit as a physical width
    floor_mm = 1.0              # the clause's absolute minimum

    segments = []
    # Only streams with both ends placed have a drawn path.
    for s in fs.streams:
        if s.source.owner.frame is None or s.dest.owner.frame is None:
            continue
        w = _stream_rung(s.kind in SIGNAL_KINDS).width
        points = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                segments.append((s, "h", min(x1, x2), max(x1, x2), y1, w))
            elif x1 == x2 and y1 != y2:
                segments.append((s, "v", min(y1, y2), max(y1, y2), x1, w))

    seen: dict = {}
    for i, (sa, axis, a_lo, a_hi, a_at, aw) in enumerate(segments):
        for sb, b_axis, b_lo, b_hi, b_at, bw in segments[i + 1:]:
            if b_axis != axis or a_at == b_at:
                continue
            gap = abs(a_at - b_at) - aw / 2 - bw / 2
            need = max(2 * max(aw, bw), floor_mm / unit_mm)
            if gap >= need - 1e-9:
                continue
            # Count only pairs that run together for at least the required
            # gap, not segments that merely abut end to end.
            overlap = min(a_hi, b_hi) - max(a_lo, b_lo)
            if overlap <= need:
                continue
            key = tuple(sorted((id(sa), id(sb))))
            if key not in seen or gap < seen[key][0]:
                seen[key] = (gap, need, sa, sb, axis, a_at, b_at)

    out = []
    for gap, need, sa, sb, axis, a_at, b_at in sorted(seen.values(), key=lambda v: v[0]):
        a, b = sa.name or sa.kind, sb.name or sb.kind
        where = "x" if axis == "v" else "y"
        out.append(Issue(
            "warning", "lines-crowded",
            f"{a} and {b} run parallel at {where} {a_at:g} and {b_at:g}, leaving "
            f"{gap:.1f}px ({gap * unit_mm:.2f} mm) of paper between them -- under "
            f"the {need:.0f}px ISO 10628-1 5.3.2 asks between parallel lines, "
            f"twice the wider of the two and never less than 1 mm. Pin one of "
            f"them with via() to open the pair out"))
    return out


def validate(fs: "Flowsheet", *, arrows: bool = True,
             tabulates: bool = True) -> list["Issue"]:
    """Return all validation issues for the flowsheet, errors first.

    Runs :func:`model_issues` and :func:`geometry_issues` on the sheet as
    it stands. A render runs them separately, before and after geometry
    (:meth:`pandid.flowsheet.Flowsheet._prepare_to_draw`).

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.
    arrows : bool, default=True
        Passed to :func:`geometry_issues`.
    tabulates : bool, default=True
        Passed to :func:`model_issues`.

    Returns
    -------
    list[Issue]
        Errors, then warnings.
    """
    found = model_issues(fs, tabulates=tabulates) + geometry_issues(fs, arrows=arrows)
    return ([i for i in found if i.severity == "error"]
            + [i for i in found if i.severity == "warning"])

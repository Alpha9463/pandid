"""Validate a flowsheet's model and drawn geometry.

An error is a contradiction a render refuses; a warning is a valid
but imperfect drawing, collected on ``fs.warnings``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid._checks import suggest
from pandid.layout.conflicts import _SQUARE_TOL, boxes_overlap, segment_crosses_box
from pandid.portgeom import COMPASS

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_TOL = 1.0  # tolerance in px

#: Distance in px a drawn coordinate may sit from its pin.
_PIN_TOL = 0.05

#: ``(kind, variant)`` pairs whose nozzles step in height by design.
OFFSET_BY_DESIGN = frozenset({
    ("reducer", "eccentric"),
})

#: ``(group, name)`` of round parts that a stretched body distorts.
ROUND_PARTS = frozenset({
    (20, "motor"),
})

#: Fraction a :data:`ROUND_PARTS` symbol may depart from its aspect.
_ASPECT_TOL = 0.02

#: Order of control-function letters in a tag (ISO 15519-2 5.2.4).
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
    severity: str
    code: str
    message: str

    def __str__(self) -> str:
        """Return ``[severity] code: message``.

        Returns
        -------
        str
            Formatted finding.
        """
        return f"[{self.severity}] {self.code}: {self.message}"


def _overlap_cure(a, b) -> str:
    """Return a sentence naming the call that clears an overlap.

    Parameters
    ----------
    a, b : Unit
        The two overlapping units.

    Returns
    -------
    str
        Advice naming a ``pin()``, ``attach()`` or placement call.
    """
    from pandid.streams import Stream

    def attached(u) -> bool:
        """Return whether a unit hangs off a host.

        Parameters
        ----------
        u : Unit
            Unit to test.

        Returns
        -------
        bool
            Whether ``u`` has a host.
        """
        return getattr(u, "host", None) is not None

    def pinned(u) -> bool:
        """Return whether a unit is pinned on an axis that places it.

        Parameters
        ----------
        u : Unit
            Unit to test.

        Returns
        -------
        bool
            Whether ``u`` has a pin that places it.
        """
        pin = u.pin_
        axes = ("x", "y") if attached(u) else ("col", "row", "x", "y")
        return pin is not None and any(getattr(pin, f) is not None for f in axes)

    def how(u) -> str:
        """Return the ``pin()`` call that moves a unit.

        Parameters
        ----------
        u : Unit
            Unit to move.

        Returns
        -------
        str
            Call text, naming the port each axis is pinned by.
        """
        pin = u.pin_
        if not attached(u) and pin is not None and pin.x is None and pin.y is None:
            return f"call .pin(col=..., row=...) on {u.name}"
        # Name the port each axis is pinned by.
        ports = getattr(u, "_pin_ports", None) or {}
        calls = ([(ports.get("x"), "x=..., y=...")] if ports.get("x") == ports.get("y")
                 else [(ports.get("x"), "x=..."), (ports.get("y"), "y=...")])
        return " and ".join(
            f"call .pin({'' if port is None else f'port={port!r}, '}{axes}) on {u.name}"
            for port, axes in calls)

    for u, other in ((b, a), (a, b)):
        host = getattr(u, "host", None)
        if host is None or pinned(u):
            continue
        stream = isinstance(host, Stream)
        where = (f"how far along {host.name} it taps, 0 to 1 (now {u.at:g})" if stream else
                 f"the face of {host.name} it sits by, 'N', 'S', 'E' or 'W' (now {u.at!r})")
        kept = ((f", angle={u.angle!r}" if u.angle != 90.0 else "")
                + (f", relation={u.relation!r}" if u.relation != "sensing" else ""))
        pin = u.pin_
        grid = (f". Its col= and row= pin does not move an attached balloon; an "
                f"x= and y= pin does: {how(u)}"
                if pin is not None and (pin.col is not None or pin.row is not None) else "")
        return (f"{u.name} hangs off {host.name}, so say where on it: at= is "
                f"{where}, and offset= how far it stands off (now {u.offset:g}). "
                f"Change them on add_instrument(), or call .attach(<the {host.name} "
                f"{'stream' if stream else 'unit'}>, at=..., offset=...{kept}) on "
                f"{u.name}{grid}")
    if pinned(a) and pinned(b):
        return f"Both are pinned, so move one pin clear of the other: {how(b)}"
    for u, other in ((b, a), (a, b)):
        if pinned(u):
            return f"{u.name} is pinned there, so move its pin clear of {other.name}: {how(u)}"
    return (f"Neither is pinned, so the layout placed both there. Pin one clear of "
            f"the other: {how(b)}")


def _is_control_function(letters: str, i: int) -> bool:
    """Return whether ``letters[i]`` is a sequenced control function.

    The first letter and the ``C`` of a ``ZSC`` position tag are not.

    Parameters
    ----------
    letters : str
        Functional letters of a tag.
    i : int
        Index of the letter to test.

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
        Functional letters of a tag.

    Returns
    -------
    list[str]
        Control-function letters.
    """
    return [c for i, c in enumerate(letters) if _is_control_function(letters, i)]


def _in_sequence(letters: str) -> str:
    """Return a tag with its control-function letters reordered.

    Parameters
    ----------
    letters : str
        Functional letters of a tag.

    Returns
    -------
    str
        Letters with the control functions in sequence.
    """
    ordered = iter(sorted(_control_functions(letters),
                          key=lambda c: CONTROL_FUNCTION_SEQUENCE.index(c.upper())))
    return "".join(
        next(ordered) if _is_control_function(letters, i) else c
        for i, c in enumerate(letters)
    )


def _family_stem(port_name: str) -> str | None:
    """Return the stem of a numbered port, or ``None``.

    Parameters
    ----------
    port_name : str
        Port name, such as ``"in_2"``.

    Returns
    -------
    str or None
        Stem before ``_<n>``, or ``None`` if the name is not numbered.
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
        Joined names.
    """
    return " and ".join(filter(None, [", ".join(names[:-1]), *names[-1:]]))


def _square(x1, y1, x2, y2) -> bool:
    """Return whether a segment lies along an axis.

    Parameters
    ----------
    x1, y1 : float
        Start point.
    x2, y2 : float
        End point.

    Returns
    -------
    bool
        Whether the segment is horizontal or vertical.
    """
    return abs(x1 - x2) < _SQUARE_TOL or abs(y1 - y2) < _SQUARE_TOL


def _corners(pts):
    """Return a drawn path as its ends and turning points.

    Parameters
    ----------
    pts : list[tuple[float, float]]
        Drawn path.

    Returns
    -------
    list[tuple[float, float]]
        Ends and corners, without repeated or collinear points.
    """
    out: list = []
    for p in pts:
        if out and math.dist(p, out[-1]) <= _SQUARE_TOL:
            continue
        if len(out) > 1 and any(abs(out[-2][i] - out[-1][i]) < _SQUARE_TOL
                                and abs(out[-1][i] - p[i]) < _SQUARE_TOL for i in (0, 1)):
            out.pop()
            if math.dist(p, out[-1]) <= _SQUARE_TOL:
                continue
        out.append(p)
    return out


def _pierced_end(path, ends):
    """Return the end of a run whose line is drawn through its own unit.

    Parameters
    ----------
    path : list[tuple[float, float]]
        :func:`_corners` of the drawn path, source nozzle first.
    ends : sequence
        ``(unit, port, box, face)`` per end, or ``None`` if unanchored.

    Returns
    -------
    tuple or None
        The pierced end's ``(unit, port, box, face)``, or ``None``.
    """
    last = len(path) - 2
    tips = ((0, ends[0], path[0], path[1]), (last, ends[1], path[-1], path[-2]))
    for end in ends:
        if end is None:
            continue
        clear = set()
        for k, other, nozzle, far in tips:
            if other is None or other[0] is not end[0]:
                continue
            dx, dy = COMPASS[other[3]]
            if (far[0] - nozzle[0]) * dx + (far[1] - nozzle[1]) * dy >= -_SQUARE_TOL:
                clear.add(k)
        for k in range(len(path) - 1):
            if k not in clear and segment_crosses_box(path[k], path[k + 1], end[2]):
                return end
    return None


def _pinned_y(unit) -> bool:
    """Return whether a unit has an explicit pixel ``y`` pin.

    Parameters
    ----------
    unit : Unit
        Unit to test.

    Returns
    -------
    bool
        Whether ``unit`` is pinned in ``y``.
    """
    pin = getattr(unit, "pin_", None)
    return pin is not None and getattr(pin, "y", None) is not None


def _off_elevation(su, sp, du, dp) -> tuple[float, float, bool] | None:
    """Return how far two facing E/W nozzles miss a straight run.

    ``span`` is the shorter unit's height; an offset that clears it is a
    change of elevation.

    Parameters
    ----------
    su : Unit
        Source unit.
    sp : ResolvedPort
        Source port.
    du : Unit
        Destination unit.
    dp : ResolvedPort
        Destination port.

    Returns
    -------
    tuple[float, float, bool] or None
        ``(offset, span, source_is_shorter)``, or ``None`` for no miss.
    """
    from pandid.portgeom import unit_box

    # Only E/W nozzles that face each other.
    if {sp.face, dp.face} != {"E", "W"} or (sp.face == "E") != (dp.point[0] > sp.point[0]):
        return None

    for u in (su, du):
        if (u.kind, getattr(u, "variant", "default")) in OFFSET_BY_DESIGN:
            return None

    offset = abs(dp.point[1] - sp.point[1])
    if offset <= _TOL:
        return None  # sub-pixel

    # An offset under the shorter unit's height is a miss; one that
    # clears it is a change of elevation.
    sb, db = unit_box(su, su.frame), unit_box(du, du.frame)
    sh, dh = sb[3] - sb[1], db[3] - db[1]
    span = min(sh, dh)
    return (offset, span, sh <= dh) if offset < span else None


def _crowded(heads: list[tuple[float, str]], floor: float
             ) -> tuple[float, str, str] | None:
    """Return the tightest adjacent pair over 1 px and under ``floor``.

    Parameters
    ----------
    heads : list[tuple[float, str]]
        ``(position along the face, port name)`` for each arrowhead.
    floor : float
        Minimum pitch.

    Returns
    -------
    tuple[float, str, str] or None
        ``(pitch, port, port)`` of the tightest pair, or ``None``.
    """
    order = sorted(heads)
    pairs = sorted((b[0] - a[0], a[1], b[1]) for a, b in zip(order, order[1:]))
    return next((p for p in pairs if _TOL < p[0] < floor), None)


def model_issues(fs: "Flowsheet", *, tabulates: bool = True) -> list["Issue"]:
    """Return the findings that need no layout, errors first.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.
    tabulates : bool, default=True
        Whether the diagram owes a stream table.

    Returns
    -------
    list[Issue]
        Errors, then warnings.
    """
    from pandid import units
    from pandid.deprecation import findings as deprecation_findings
    from pandid.portgeom import resolve_size
    from pandid.render.svg import LABEL_POSITIONS
    from pandid.render.symbols import default_registry
    from pandid.units import Instrument

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- deprecated API ---
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
    for u in fs.units:
        side = getattr(u, "label_pos", None)
        # Empty means unset.
        if not side or side in LABEL_POSITIONS:
            continue
        errors.append(Issue(
            "error", "label-pos-unknown",
            f"{u.name} asks for label_pos={side!r}, which no side answers to"
            + suggest(str(side).strip().lower(), LABEL_POSITIONS)
            + f". Use one of {', '.join(LABEL_POSITIONS)}, or leave label_pos "
              f"unset and let the engine put the tag on the first face no "
              f"nozzle leaves from"))

    # --- a kind the symbol library has no artwork for ---
    # One finding per kind.
    catalogue = sorted({getattr(units, name).kind for name in units.__all__
                        if default_registry.variants(getattr(units, name).kind)})
    unknown: set[str] = set()
    for u in fs.units:
        if default_registry.variants(u.kind) or u.kind in unknown:
            continue
        unknown.add(u.kind)
        # The blank box the registry draws for it.
        blank = default_registry.get(u.kind)
        warnings.append(Issue(
            "warning", "symbol-kind-unknown",
            f"{u.name} is a {u.kind!r}, which no symbol is registered for"
            + suggest(u.kind, catalogue)
            + f"; it is drawn as a blank {blank.width:g}x{blank.height:g} box with "
              f"no ports. Register artwork for it with "
              f"default_registry.register({u.kind!r}, Symbol(...))"))

    # --- a turned gravity-fixed symbol (ISO 15519-1 11.4.2) ---
    for u in fs.units:
        placed = u.frame if u.frame is not None else u.pin_
        turn = int(getattr(placed, "orientation", 0) or 0)
        variant = getattr(u, "variant", "default")
        # Skip a variant the registry has no artwork for.
        if not turn or variant not in default_registry.variants(u.kind):
            continue
        if not default_registry.for_unit(u).gravity_fixed:
            continue
        # Suggest the lying variant where one exists.
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
    for u in fs.units:
        variant = getattr(u, "variant", "default")
        if variant not in default_registry.variants(u.kind):
            continue
        sym = default_registry.for_unit(u)
        marks = [ov for ov in sym.overlays if (ov.group, ov.name) in ROUND_PARTS]
        if not marks:
            continue
        # Compare with the natural box, swapped for a turn.
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
    # One finding per tag.
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
    # One finding per numbered nozzle family.
    for u in fs.units:
        families: dict[str, list[str]] = {}
        for name in u.ports:
            stem = _family_stem(name)
            if stem is not None:
                families.setdefault(stem, []).append(name)
        for stem, members in families.items():
            # Process ports only.
            if any(u.ports[n].role == "signal" for n in members):
                continue
            # Skip a sole member the class offers under an alias, such
            # as ``Reactor.feed``.
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
            # Abbreviate an unbroken run of 3 or more as ``in_1..in_n``.
            run = [f"{stem}_{i}" for i in range(1, n + 1)]
            named = (f"{members[0]}..{members[-1]}" if n > 2 and members == run
                     else _and(members))
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
    # Only names the counter chose are reported.
    counted: dict[str, list] = {}
    taken: dict[str, int] = {}
    for group in fs._stream_groups():
        # Counted unless a stream has an explicit name or line number.
        chosen = any(not s.auto_named or s.has_line_number for s in group)
        name = group[0].name
        taken[name] = taken.get(name, 0) + 1
        if not chosen:
            counted.setdefault(name, []).append(group)
    # Signal and duty lines share the counter.
    for s in fs.streams:
        if s.kind == "material":
            continue
        taken[s.name] = taken.get(s.name, 0) + 1
        if s.auto_named and not s.has_line_number:
            counted.setdefault(s.name, []).append([s])
    for name, groups in counted.items():
        if taken[name] < 2:
            continue
        # Name the ends of the first two counted runs.
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
    if fs.title_block is not None:
        from datetime import datetime

        from pandid.render.furniture import (company_overflow,
                                             title_strip_fit,
                                             undrawn_signatories)
        from pandid.render.svg import fit_issue

        tb = fs.title_block
        # Pass the fallbacks as the renderers do.
        warnings.extend(fit_issue(*found) for found in title_strip_fit(
            tb, fs.name, datetime.now().strftime("%Y-%m-%d")))

        # --- a company name that wraps out through the strip ---
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
        # A signatory with no revision row, and one the newest revision
        # overrides, are reported separately.
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
    # ISO 10628-1 4.3.2 d), when any stream states a property.
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
        # --- a PFD with material crossing its edge and no table ---
        # ISO 10628-1 4.3.2 d); one finding for the sheet.
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

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.
    arrows : bool, default=True
        Whether process lines carry arrowheads.

    Returns
    -------
    list[Issue]
        Errors, then warnings.
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
    if not fs.route_converged:
        warnings.append(Issue(
            "warning", "route-not-settled",
            f"attached instruments were still moving after {MAX_PLACEMENT_PASSES} "
            "routing passes; a balloon may sit slightly off the line it taps. "
            "Pin the balloon-carrying lines with via() to settle it"))

    # --- a balloon nothing could place (recorded by layout) ---
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
    placed = [u for u in fs.units if u.frame is not None]
    if placed:
        # Soft: a placement the sheet did not honour.
        for u in placed:
            missed: list[str] = []
            for axis, (port_name, want) in pin_intent(u).items():
                drawn = (port_point(u, u.frame, port_name)[0 if axis == "x" else 1]
                         if port_name is not None else getattr(u.frame, axis))
                if abs(drawn - want) > _PIN_TOL:
                    nozzle = f".{port_name}" if port_name is not None else ""
                    missed.append(f"{u.name}{nozzle} was pinned {axis}={want:g} and is "
                                  f"drawn at {drawn:g}, {abs(drawn - want):g} away")
            # Check that a stated turn or mirror is drawn as stated.
            pin = u.pin_
            if pin is not None and u._turn_stated and u.frame.orientation % 360 != pin.orientation % 360:
                missed.append(f"{u.name} was pinned orientation={pin.orientation:g} and is "
                              f"drawn at {u.frame.orientation:g}")
            if pin is not None and u._mirror_stated and (
                    (u.frame.mirrored, u.frame.mirror_y) != (pin.mirrored, pin.mirror_y)):
                missed.append(f"{u.name} was pinned with mirrored="
                              f"{(pin.mirrored, pin.mirror_y)} and is drawn with "
                              f"{(u.frame.mirrored, u.frame.mirror_y)}")
            # Compare pinned col/row with the frame's, skipping an axis
            # with an absolute pin.
            pin = u.pin_
            for axis, absolute in (("col", "x"), ("row", "y")) if pin is not None else ():
                want, rank = getattr(pin, axis), getattr(u.frame, axis)
                if want is None or rank == want or getattr(pin, absolute) is not None:
                    continue
                missed.append(f"{u.name} was pinned {axis}={want} and is "
                              + (f"drawn in {axis}={rank}" if rank is not None
                                 else f"drawn with no {axis} of its own"))
            # Suggest what moves an attached balloon.
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

        # Grid pins in order: a lower col is drawn further west, and a
        # lower row higher up its column.
        graded = [u for u in placed if u.kind != "instrument" and u.pin_ is not None]
        for a in graded:
            for b in graded:
                pa, pb, fa, fb = a.pin_, b.pin_, a.frame, b.frame
                assert pa is not None and pb is not None and fa is not None and fb is not None
                if (pa.col is not None and pb.col is not None and pa.x is None and pb.x is None
                        and pa.col < pb.col and fa.cx >= fb.cx):
                    said = f"{a.name} was pinned col={pa.col}, west of {b.name}'s col={pb.col}"
                elif (pa.row is not None and pb.row is not None and pa.y is None and pb.y is None
                      and pa.col == pb.col and pa.row < pb.row and fa.cy >= fb.cy):
                    said = f"{a.name} was pinned row={pa.row}, above {b.name}'s row={pb.row}"
                else:
                    continue
                warnings.append(Issue("warning", "pin-not-honored",
                                      f"{said}, and is not drawn so. Something moved one of "
                                      "them after layout read the pins"))

        boxes = [(u, unit_box(u, u.frame)) for u in placed]
        # Only streams with both ends placed have a drawn path.
        drawn = [s for s in fs.streams if s.source.owner.frame is not None
                 and s.dest.owner.frame is not None]

        # Soft: a block name wider than its box.
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

        # Hard: an anchored nozzle drawn off its unit's box.
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

        # Hard: overlapping unit bodies, with the call that moves one.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes_overlap(boxes[i][1], boxes[j][1]):
                    a, b = boxes[i][0], boxes[j][0]
                    errors.append(Issue("error", "unit-overlap",
                                        f"{a.name} and {b.name} overlap. {_overlap_cure(a, b)}"))

        # Hard: two live connections on one unit landing on one point.
        # Boundary flags are exempt.
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
                # Unanchored ports share the box centre: a warning.
                anchored = is_anchored(u, name) and is_anchored(u, first)
                issue = Issue(
                    "error" if anchored else "warning", "coincident-ports",
                    f"{u.name}.{first} and {u.name}.{name} are both connected and "
                    f"both resolve to ({pt[0]}, {pt[1]})"
                    + ("" if anchored else "; the symbol anchors no nozzle for one "
                       "of them, so both fall back to the centre of the box"))
                (errors if anchored else warnings).append(issue)

        # Soft: arrowheads on one face closer than MIN_NOZZLE_PITCH.
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
                # Suggest a move only where another face is offered.
                movable = [n for n in (first, second)
                           if len(port_faces(u, n, u.frame)) > 1]
                elsewhere = (f", or move {u.name}.{movable[0]} onto another face "
                             f"with nozzle()" if movable else "")
                warnings.append(Issue(
                    "warning", "nozzles-crowded",
                    f"{u.name}.{first} and {u.name}.{second} are {pitch:.1f}px apart "
                    f"on {u.name}'s {face} face{crowd}, {measured}. Give the unit a "
                    f"box with room for them, {u.name}.{dim} = {room}{elsewhere}"))

        # Soft: a route through a unit body it does not connect to, and
        # grossly indirect routes.
        hosted = [(u, box, getattr(u, "host", None)) for u, box in boxes]
        for s in drawn:
            # Skip a stream with no route.
            if s.route is None:
                continue
            src_u, dst_u = s.source.owner, s.dest.owner
            sp = port_point(src_u, src_u.frame, s.source.name)
            dp = port_point(dst_u, dst_u.frame, s.dest.name)
            pts = [sp] + list(s.route.waypoints) + [dp]

            for k in range(len(pts) - 1):
                for u, box, host in hosted:
                    if u is src_u or u is dst_u or host is s:
                        continue  # the stream's ends and balloons
                    if segment_crosses_box(pts[k], pts[k + 1], box):
                        warnings.append(Issue("warning", "route-crosses-unit",
                                              f"stream {s.name} crosses {u.name}"))
                        break

            # Soft: a line drawn through a unit it connects to.
            path = _corners(pts)
            ends = [(u, name, unit_box(u, u.frame), resolve_port(u, u.frame, name).face)
                    if is_anchored(u, name) else None
                    for u, name in ((src_u, s.source.name), (dst_u, s.dest.name))]
            pierced = _pierced_end(path, ends) if len(path) > 1 else None
            if pierced is not None:
                u, name, _, face = pierced
                verb = "leaves from" if pierced is ends[0] else "runs to"
                cure = ("via() draws exactly the points it is given, so add the corners "
                        "that bring the line round to that face"
                        if s.route.manual else
                        f"Clear room beyond that face for the router, or put the nozzle on "
                        f"the side the line comes from: call .nozzle({name!r}, ...) on {u.name}")
                warnings.append(Issue(
                    "warning", "route-crosses-unit",
                    f"stream {s.name} is drawn through {u.name}, which it {verb}. A line "
                    f"meets its own unit only at the nozzle, from beyond the face the "
                    f"nozzle is on, and {u.name}.{name} is on the {face} face. {cure}"))

            # Soft: a segment drawn on the slant (ISO 15519-1 12.1). One
            # finding per stream.
            slopes = [(a, b) for a, b in zip(pts, pts[1:]) if not _square(*a, *b)]
            if slopes:
                (x1, y1), (x2, y2) = slopes[0]
                more = ("" if len(slopes) == 1 else
                        f", the first of {len(slopes)} on it")
                # Offer the corners that do not double the line back.
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
        for s in drawn:
            # Skip signal lines.
            if s.kind in SIGNAL_KINDS:
                continue
            su, du = s.source.owner, s.dest.owner
            # Only where an elevation was pinned by hand.
            if not (_pinned_y(su) or _pinned_y(du)):
                continue
            src = resolve_port(su, su.frame, s.source.name)
            dst = resolve_port(du, du.frame, s.dest.name)
            near = _off_elevation(su, src, du, dst)
            if near is None:
                continue
            offset, span, at_source = near
            # Suggest pinning the shorter unit's nozzle level.
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

    # Soft: parallel runs closer than ISO 10628-1 5.3.2 allows.
    warnings.extend(_crowded_lines(fs))

    return errors + warnings


def _crowded_lines(fs: "Flowsheet") -> list["Issue"]:
    """Return ``lines-crowded`` findings (ISO 10628-1 5.3.2).

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.

    Returns
    -------
    list[Issue]
        One warning per pair of crowded parallel runs.
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
            # Count only pairs that run together for more than ``need``.
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

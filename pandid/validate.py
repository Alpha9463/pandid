"""Flowsheet validation.

Separates two kinds of problems:

- **errors**: genuine contradictions the engine cannot honor
  (overlapping pinned units, negative or non-finite coordinates).
  ``render()`` raises on these rather than emit a wrong drawing.
- **warnings**: the drawing is valid but imperfect (a stream crosses a
  unit body, a route detours excessively, a tag spells its letters in an
  order no standard uses, a nozzle a count asked for has no line on it).
  Collected on ``fs.warnings`` for the caller; never fatal.

The findings are made in two halves, and :func:`validate` is both of
them run in turn:

- :func:`model_issues` reads what the author wrote down -- pins, tags,
  nozzle counts, stream names -- and touches neither a
  :class:`~pandid.geometry.Frame` nor a :class:`~pandid.geometry.Route`.
  It answers on a sheet that has never been laid out.
- :func:`geometry_issues` reads the resolved geometry: overlaps,
  coincident nozzles, crossings, detours, elevations.

The split exists so a render can check the model **before** it builds
any geometry, which is the order every render entry point documents.
``pin(x=nan)`` is the case that forced it: ``pin-not-finite`` names that
contradiction exactly, and the same coordinate is one the router starts
from and never comes back from, so validating after ``route()`` made a
perfect finding about a drawing nobody could obtain.
:meth:`pandid.flowsheet.Flowsheet._prepare_to_draw` is where the order
is written down.

Geometric checks need resolved frames, and are made over the units that
have one. Not over the whole sheet or none of it: a balloon layout could
not place is one unit without geometry rather than a sheet without any,
and gating the block on the whole list let a single one of them hide
every overlap on an otherwise fully placed drawing.

Most findings are made by inspecting the finished flowsheet. Three are
collected from where an earlier phase parked them: ``route-not-settled``
and ``instrument-unplaced``, which only ``route()`` and ``layout()`` can
know, and ``deprecated``, which leaves no trace in the topology or the
geometry. See :mod:`pandid.deprecation`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_TOL = 1.0  # px tolerance so touching edges are not flagged as overlaps

#: How far off square a drawn segment may be and still read as
#: orthogonal, in px. Half a pixel: under it the line is on the axis and
#: over it the sheet shows a slope.
#:
#: The two rules that use it are the same question asked twice.
#: :func:`_seg_crosses_box` calls a segment vertical or horizontal to
#: decide which side of a box to measure it against, and answers *no
#: crossing* for anything else -- so a segment this rejects is invisible
#: to ``route-crosses-unit`` as well as sloping, which is the second
#: reason ``route-diagonal`` reports it.
_SQUARE_TOL = 0.5

#: ``(kind, variant)`` pairs a run is *meant* to change centreline
#: through, so ``run-off-elevation`` has nothing to tell an author who
#: put one in a line.
#:
#: An eccentric reducer is flat on top, so its two nozzles both face
#: along the run and read as one elevation to :func:`_off_elevation`
#: while drawing a 2.4px rise. Straightening it is the one change that
#: would break the fitting.
#:
#: A device that merely *has* its nozzles at different heights does not
#: belong here: a pump's discharge is above its suction and the author
#: still has to put the downstream nozzle on it. Membership is a rule
#: with no geometry behind it, so ``tests/test_validate.py`` asserts the
#: geometry over every quarter turn rather than taking it on faith.
OFFSET_BY_DESIGN = frozenset({
    ("reducer", "eccentric"),
})

#: ``(group, name)`` of every supplementary part whose *shape* is worked
#: out from the body's own box, so that a body drawn in a box of another
#: shape draws the part in the wrong one.
#:
#: One entry. :func:`pandid.render.iso_parts.agitator_overlays` places
#: item 20.6's drive motor as ``a third of the shell's width`` by
#: ``whatever fraction of this body's height that is`` -- which is the
#: only way to say "round" in a coordinate system with no units, and is
#: written down as such in that function. The rectangle it lands on is a
#: square at the body's natural box and a rectangle at any other, and
#: what is drawn inside it is a circle.
#:
#: **The narrowness is the measurement.** The other thirty-six
#: registered parts are lines, bars and decks -- a tray deck is 100 x 20
#: and is drawn 100 x 20 on any shell, a leg is a channel section, a
#: settling arrow is a stroke -- and the whole point of stretching a
#: shell is that a vessel is drawn at the proportions the plant has. A
#: rule phrased as "the box is not the symbol's shape" reports
#: ``19_absorber_stripper``'s amine contactor, drawn 110 x 340 on a
#: 100 x 200 symbol because twenty trays need the room, and its cure
#: would be a 170 x 340 column no draughtsman would draw.
#:
#: Membership is a rule with no geometry behind it, so
#: ``tests/test_validate.py`` measures the circle rather than taking it
#: on faith: round on the natural box, oval off it.
ROUND_PARTS = frozenset({
    (20, "motor"),
})

#: How far out of shape a symbol carrying a :data:`ROUND_PARTS` mark may
#: be drawn before ``symbol-out-of-aspect`` says so, as a fraction.
#:
#: Two per cent, and both bounds are measured.
#:
#: *Below*, because an author works in whole drawing units and cannot
#: write 62 : 131,7778 down exactly. Over every whole height from 100 to
#: 400 units, the best whole width for the two stirred bodies the library
#: draws lands within 1,02 % of their aspect -- and where the author
#: picks both numbers it is far closer, 72 x 153 being 0,02 % out. A
#: threshold under that would report arithmetic rather than a drawing.
#:
#: *Above*, because ``agitator_overlays`` names 7 % oval on the plain
#: stirred tank and 22 % on the jacketed one as the defect it derives the
#: motor's height to avoid. A threshold above those would leave the
#: finding unable to say what the library already treats as wrong.
_ASPECT_TOL = 0.02

#: The order the control-function letters of a tag have to appear in. BS
#: ISO 15519-2:2015 §5.2.4, *Sequence of letter codes for control
#: functions*, fixes that order as I, R, C, S, M, Z, A, and works it
#: through on three tags: ``ICA``, ``CS`` and ``ICZA``.
#:
#: So ``FIC`` is right and ``FCI`` is wrong. Only these seven letters
#: are ordered: the first letter of a tag is the measured variable
#: (Table 2) and everything else is either a modifier (Table 3: ``D``,
#: ``H``, ``L``, ``P``) or an ISA function letter ISO does not sequence
#: (``T``, ``E``, ``Y``, ``V``), so those keep the position the author
#: gave them. A letter that *is* here can still be a modifier where it
#: qualifies a position switch rather than naming a function; see
#: :func:`_is_control_function`.
#:
#: ``M`` is carried because §5.2.4 lists it and is unreachable: the
#: clause orders it, and the control functions it orders are defined
#: without one, so no conforming tag has a letter to put in that slot.
CONTROL_FUNCTION_SEQUENCE = "IRCSMZA"


@dataclass(frozen=True)
class Issue:
    """A single validation finding."""
    severity: str        # "error" | "warning"
    code: str            # short kebab-case category
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


def _overlap(a: tuple[float, float, float, float],
             b: tuple[float, float, float, float]) -> bool:
    return not (a[2] - _TOL <= b[0] or b[2] - _TOL <= a[0]
                or a[3] - _TOL <= b[1] or b[3] - _TOL <= a[1])


def _is_control_function(letters: str, i: int) -> bool:
    """Is ``letters[i]`` one of the letters §5.2.4 puts in order?

    Two letters that are in :data:`CONTROL_FUNCTION_SEQUENCE` are not
    control functions where they stand.

    **The first**, which is the measured variable: ``C`` opens a
    conductivity tag as legitimately as it closes ``FIC``.

    **The ``C`` that closes a position switch.** ANSI/ISA-5.1-2009 Table
    5.2.1 reads ``Z`` as *Position, dimension* and ``S`` as *Switch*, and
    a position switch is qualified by the position it switches at:
    ``O`` for open and ``C`` for closed, which do for a valve what the
    ``H`` and ``L`` of ``LAH`` do for a measurement. So the ``C`` in
    ``ZSC`` is a modifier and keeps its place, exactly as that ``H``
    does. Read as *Control (closed loop)* it made ``ZSC`` -- a standard
    ISA valve-position switch -- a tag the library reported a conformance
    warning against, and offered ``ZCS`` as the cure.

    ``O`` needs no exception of its own: it is not one of the seven
    letters, which is why ``ZSO`` was never reported. That was luck
    rather than a correct reading, and this is the reading.

    Narrow on purpose. Only a **position** tag qualifies its switch this
    way, so ``FSC`` -- flow, switching and control, spelled out of order
    -- is still reported, and so is ``ZAC``, whose ``C`` closes no
    switch.
    """
    c = letters[i].upper()
    if i == 0 or c not in CONTROL_FUNCTION_SEQUENCE:
        return False
    return not (c == "C" and letters[0].upper() == "Z"
                and letters[i - 1].upper() == "S")


def _control_functions(letters: str) -> list[str]:
    """The sequenced letters of a tag, in the order it spells them."""
    return [c for i, c in enumerate(letters) if _is_control_function(letters, i)]


def _in_sequence(letters: str) -> str:
    """*letters*, with its control functions in ISO 15519-2 order.

    Only those letters move. A modifier keeps the position it was given,
    since ``H`` in ``LAH`` says which limit alarmed and reordering it
    would say something else. :func:`_is_control_function` decides which
    is which, and is asked here rather than restated, so the letters
    taken out cannot differ from the slots put back.
    """
    ordered = iter(sorted(_control_functions(letters),
                          key=lambda c: CONTROL_FUNCTION_SEQUENCE.index(c.upper())))
    return "".join(
        next(ordered) if _is_control_function(letters, i) else c
        for i, c in enumerate(letters)
    )


def _family_stem(port_name: str) -> str | None:
    """The family ``port_name`` is a numbered member of, else ``None``.

    ``in_3`` answers ``"in"``; ``inlet``, ``sig_in`` and ``tube_out``
    answer None, because a trailing word is not a number and a nozzle
    without one is declared outright by its class.

    Five classes build a numbered member -- ``Mixer(n_inlets=)``,
    ``Splitter(n_outlets=)``, ``Column``/``Reactor(n_feeds=)``,
    ``Column(n_draws=)`` and ``Block(inputs=)``, which
    ``tests/test_port_annotations`` pins in ``_DECLARED_FAMILIES``. Each
    spells its family as a stem, an underscore and a 1-based index;
    nothing else numbers a port. Whether a *count was written down* for
    this particular member is a question this function cannot answer --
    ``feed_1`` is spelled the same whether ``n_feeds`` was named or left
    at its default of one -- and is not its job: see the caller for the
    live-alias check that answers it instead.

    Read off the **unit's own port list** and not the symbol's
    :class:`~pandid.render.symbols.PortSeries`, which writes the same
    naming rule down. :class:`~pandid.units.Block` has no series at all:
    its family is split across up to four faces, so ``block_symbol``
    authors an anchor per connection -- and a check that asked the
    symbol would be silent on the one class whose whole connection list
    is counted.
    """
    stem, sep, index = port_name.rpartition("_")
    return stem if sep and stem and index.isdigit() else None


def _and(names: list[str]) -> str:
    """``"a"``, ``"a and b"``, ``"a, b and c"``: a sentence's join."""
    return " and ".join(filter(None, [", ".join(names[:-1]), *names[-1:]]))


def _square(x1, y1, x2, y2) -> bool:
    """True if this segment is drawn along an axis rather than sloping."""
    return abs(x1 - x2) < _SQUARE_TOL or abs(y1 - y2) < _SQUARE_TOL


def _seg_crosses_box(x1, y1, x2, y2, box) -> bool:
    """True if an orthogonal segment passes through a box's interior.

    A sloping one answers ``False`` whatever it runs over, which is why
    ``route-diagonal`` exists: see :data:`_SQUARE_TOL`.
    """
    bx0, by0, bx1, by1 = box
    if abs(x1 - x2) < _SQUARE_TOL:  # vertical
        return bx0 + _TOL < x1 < bx1 - _TOL and min(y1, y2) < by1 - _TOL and max(y1, y2) > by0 + _TOL
    if abs(y1 - y2) < _SQUARE_TOL:  # horizontal
        return by0 + _TOL < y1 < by1 - _TOL and min(x1, x2) < bx1 - _TOL and max(x1, x2) > bx0 + _TOL
    return False


def _pinned_y(unit) -> bool:
    """True when this unit's elevation was written down by hand.

    ``pin(row=...)`` is a grid cell rather than a coordinate, so it is
    not a number anyone did nozzle arithmetic on and does not count.
    """
    pin = getattr(unit, "pin_", None)
    return pin is not None and getattr(pin, "y", None) is not None


def _off_elevation(su, sp, du, dp) -> tuple[float, float, bool] | None:
    """How far these two connected nozzles near-miss by, else ``None``.

    *su*/*du* are the units at the two ends of one stream and *sp*/*dp*
    their resolved ports. Answers ``(offset, span, source_is_shorter)``:
    the miss, the extent it was measured against, and which end that
    extent belongs to -- all three together, so the message cannot name
    one device and quote the other one's height at it.
    """
    from pandid.portgeom import unit_box

    # Only a pair of nozzles that both face along the run has one
    # elevation: a vertical face is a deliberate turn, and two of them
    # make a riser, where the difference in y is the run's *length*.
    # Opposite faces, and the destination on the side the source points
    # at, so a run that leaves east and arrives from the east -- having
    # doubled back -- is not measured as a step in a straight line.
    if {sp.face, dp.face} != {"E", "W"} or (sp.face == "E") != (dp.point[0] > sp.point[0]):
        return None

    # Offset by design: the fitting is *for* the step. See
    # OFFSET_BY_DESIGN.
    for u in (su, du):
        if (u.kind, getattr(u, "variant", "default")) in OFFSET_BY_DESIGN:
            return None

    offset = abs(dp.point[1] - sp.point[1])
    if offset <= _TOL:
        return None  # sub-pixel; nothing is drawn differently

    # The threshold is the shorter symbol's own extent across the run,
    # taken off the *drawn* box so a unit given an explicit height is
    # measured at the size it got. A nozzle offset the author did not
    # subtract is bounded by how tall the shorter device is, while a
    # deliberate change of elevation clears that device entirely.
    #
    # Half that extent is measurably wrong: over this repo's examples
    # eight of the misses land on exactly half and two land just past it
    # (a sight glass 6.3 off a 12.5 body), so half either drops them to
    # a floating-point tie-break or misses them outright.
    sb, db = unit_box(su, su.frame), unit_box(du, du.frame)
    sh, dh = sb[3] - sb[1], db[3] - db[1]
    span = min(sh, dh)
    return (offset, span, sh <= dh) if offset < span else None


def _crowded(heads: list[tuple[float, str]], floor: float
             ) -> tuple[float, str, str] | None:
    """The tightest adjacent pair of heads on one face, if too tight.

    *heads* is every nozzle on the face that wears one, as
    ``(position along the face, port name)``. Answers
    ``(pitch, nearer port, further port)``.

    Adjacent pairs only, and one finding per face: what an author does
    about it -- a bigger box, or a nozzle moved off the face -- is one
    action.

    A pair under ``_TOL`` is left alone, because two nozzles on one
    point are already ``coincident-ports``, which is the truer thing to
    say about them.
    """
    order = sorted(heads)
    pairs = sorted((b[0] - a[0], a[1], b[1]) for a, b in zip(order, order[1:]))
    return next((p for p in pairs if _TOL < p[0] < floor), None)


def model_issues(fs: "Flowsheet", *, arrows: bool = True) -> list["Issue"]:
    """The findings that read the model alone (errors first).

    Nothing here touches a :class:`~pandid.geometry.Frame` or a
    :class:`~pandid.geometry.Route`, so every one of these answers on a
    sheet that has never been laid out -- which is exactly where a
    render asks them, before it hands the sheet to an engine that has to
    assume the coordinates in it are numbers.

    ``gravity-turned`` belongs here and not with the geometry because a
    quarter turn is *intent*: :class:`~pandid.geometry.Pin` is the only
    thing that sets one, and layout copies it onto the
    :class:`~pandid.geometry.Frame` unchanged
    (:mod:`pandid.layout`), so the pin and the frame cannot disagree
    about it. The check still prefers the frame where there is one,
    since that is the placement that got drawn.

    ``arrows`` is :func:`~pandid.render.svg.draws_arrowheads` on the
    diagram this is about, and is true by default because so is the
    diagram it defaults to. One finding reads it: ``stream-table-missing``
    answers ISO 10628-1 4.3.2, a *process flow diagram*'s clause, and is
    silent on a sheet drawn as a P&ID, which answers to 4.4.2 instead.
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

    # --- deprecated API (recorded at the call, not recomputed here) ---
    # The only finding here that is not about the drawing. A deprecated
    # call leaves no trace in the geometry, so nothing later in this
    # function could detect it; :mod:`pandid.deprecation` records it as
    # it happens and this reads it back.
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
    # Hard, and hard for the reason an unregistered *variant* is: a value
    # outside :data:`~pandid.render.svg.LABEL_POSITIONS` used to fall
    # through both backends' side tables to ``top``, draw the tag on the
    # wrong side of the symbol, and say nothing.
    #
    # The wrong side is the smaller half of it. A stated ``label_pos`` is
    # read as a deliberate choice, so
    # :meth:`~pandid.render.svg.SvgRenderer._tag_item` skips the search
    # that steps a tag clear of the ink under it -- and a typo therefore
    # both misplaces the tag and nails it there, on a pipe if that is
    # where ``top`` lands. Neither half is visible from the drawing
    # unless the author already knows which side they asked for.
    #
    # Here rather than in ``Unit.__init__`` because a spec file sets the
    # attribute directly and a unit built before the renderer is asked
    # anything is not yet wrong. This is the earliest point every path
    # into a drawing passes through: a model error raises before any
    # geometry exists (:meth:`pandid.flowsheet.Flowsheet._prepare_to_draw`),
    # so the render refuses rather than emitting the wrong sheet.
    for u in fs.units:
        side = getattr(u, "label_pos", None)
        # Falsy is *unset*, not a sixth side: layout and the renderer
        # both spell the question ``label_pos or "top"``, so an empty
        # string already means "you choose" everywhere it is read.
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
    # ``SymbolRegistry.get`` answers an unregistered *kind* with a blank
    # 60x60 box under the id ``sym_generic``. That is deliberate for a
    # `Unit` subclass from outside this package, which has no artwork to
    # find; what it is not is a way of saying so. The two spellings of
    # one mistake were handled oppositely -- an unregistered *variant* of
    # a registered kind raises and names the catalogue, and the same typo
    # one key up drew an empty rectangle with no ports on the sheet, in
    # both backends, with nothing on ``fs.warnings``.
    #
    # Made here rather than in the registry because ``get`` is asked for
    # a symbol on every port resolution, so one unit would report the
    # same loss a dozen times in a render, and because the finding is
    # about the *unit*, which the registry never sees.
    catalogue = sorted({getattr(units, name).kind for name in units.__all__
                        if default_registry.variants(getattr(units, name).kind)})
    unknown: set[str] = set()
    for u in fs.units:
        if default_registry.variants(u.kind) or u.kind in unknown:
            continue
        unknown.add(u.kind)
        # The registry's own answer for this kind, measured rather than
        # restated: what the sheet draws is what the finding describes.
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
    # ISO 15519-1:2010 §11.4.2, *Orientation of graphical symbols*,
    # excepts from turning any symbol for a component or device whose
    # function depends on gravity, and names two of them: the open tank
    # (2061) and the cyclone separator (X 2618), drawn at Figure 22 b).
    # Those must not be turned.
    #
    # Soft despite the clause's *must not*: the sheet draws and every
    # nozzle lands on ink, so the only thing wrong is what the drawing
    # says about the plant. Refusing would also stop the library
    # checking its own artwork, since ``tests/test_symbol_invariants``
    # turns every registered symbol through 90° and 270°.
    #
    # Mirroring is left alone: §11.4.2 excepts *turning* only.
    #
    # Read off the resolved frame where there is one, since that is the
    # placement that got drawn, and off the pin before layout has run.
    # The solver reseeds from the pin, so the two agree.
    for u in fs.units:
        placed = u.frame if u.frame is not None else u.pin_
        turn = int(getattr(placed, "orientation", 0) or 0)
        variant = getattr(u, "variant", "default")
        # A variant no symbol answers to is the renderer's complaint to
        # make, with the catalogue to hand; asking for the artwork here
        # would raise out of a function whose contract is to report.
        if not turn or variant not in default_registry.variants(u.kind):
            continue
        if not default_registry.for_unit(u).gravity_fixed:
            continue
        # ISO's own way out, from the lettering paragraph of the same
        # clause: draw a fresh symbol in the orientation actually wanted
        # rather than turning this one. Two families ship one, the lying
        # drum, so name it where it exists.
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
    # An explicit ``width``/``height`` is taken as the *final* box
    # (:func:`pandid.portgeom.resolve_size`), so a box of a different
    # shape from the symbol's own scales the artwork unevenly. That is
    # ordinary and wanted for a shell -- a vessel is drawn at the
    # proportions the plant has -- and it is a defect for the one mark
    # the library sizes from the body's own box: see :data:`ROUND_PARTS`.
    #
    # **Nothing was watching the two ends of that arrangement.** The box
    # is written in an example and the aspect is a property of the
    # artwork, so a change to the artwork moves the aspect out from under
    # a number nobody edits. That is what happened: adding item 20.6's
    # motor took the stirred reactor's box from 62 x 100 to 62 x 131,8,
    # and ``examples/10_ethanol_pfd.py``'s hard-coded 80 x 100 -- right
    # the day it was written -- became a 70 % stretch that drew the motor
    # as a flat oval, on the gallery, with nothing said.
    #
    # Read off the model rather than the frame. ``resolve_size`` is what
    # layout sizes the box with, so the two agree, and answering before
    # anything is placed is the earlier and better moment to be told.
    #
    # Two things this deliberately does not fire on, because
    # ``resolve_size`` already accounts for both. A **quarter turn** swaps
    # the symbol's own box, so a 12 x 25 arrestor drawn 25 x 12 is
    # measured against 25 x 12 and is not a stretch. A **boundary flag**
    # is sized to the label it has to hold, so its own box is the wide
    # one and the pennant is not stretched either. Neither could reach
    # here in any case -- a flag and a fitting carry no parts -- but a
    # measurement that needed them excluded by name would be measuring
    # the wrong thing.
    for u in fs.units:
        variant = getattr(u, "variant", "default")
        if variant not in default_registry.variants(u.kind):
            continue
        sym = default_registry.for_unit(u)
        marks = [ov for ov in sym.overlays if (ov.group, ov.name) in ROUND_PARTS]
        if not marks:
            continue
        # The box that gets drawn, and the box the artwork is round in.
        # The quarter turn swaps the second exactly as ``resolve_size``
        # swaps it for the first.
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
        # The cure is a box of the right shape, so the message does the
        # arithmetic: the height the author asked for, kept, and the
        # width that goes with it. Named that way round because height is
        # what an author sizes a vertical body by.
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

    # --- tag spelling --- Soft, not hard: the
    # letters still read, and a sheet whose house style differs from
    # ISO's is not a sheet the engine should refuse to draw. One finding
    # per tag, so an interlock square drawn four times says it once.
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
    # The sheet draws a unit taking four streams and shows three, so it
    # asserts a stream that does not exist. Issue #183 is the defect it
    # came from: a loop over ``(1, 2, 3)`` wiring ``in_2``, ``in_3`` and
    # ``in_4``.
    #
    # **The narrowness is the measurement.** Every shipped example leaves
    # ports carrying no stream, and every one is legitimate -- signal
    # connections, dry exchanger sides, duties, reliefs, drains, vents,
    # station drain legs that end off the sheet, and single nozzles a
    # class offers and a service did not need. A nozzle a class
    # *declares* is offered whether the sheet uses it or not, and leaving
    # one open is a drawing decision. A **numbered** nozzle is not
    # offered, it is asked for: ``n_inlets=4`` is a number the author
    # wrote, so a bare member of that family is that number not being
    # met. None of them is one.
    #
    # Counts are deliberately not written down here. Three figures in
    # this comment and its twin in docs/api.md drifted as the corpus
    # grew, and by 0.1.3 the same paragraph carried two that contradicted
    # each other. ``tests/test_validate.py`` measures the corpus; prose
    # states the rule.
    #
    # It shows on the paper too. A family is spread evenly for however
    # many members it has, connected or not, so a mixer with
    # ``n_inlets=4`` and three lines draws them 11.7px apart around a
    # 17.5px hole instead of 17.5px apart -- the missing nozzle moves
    # every line that *is* drawn.
    #
    # One finding per family, not per member: two dangling inlets on one
    # mixer is one wrong count with one thing to do about it.
    #
    # No standard is cited because none legislates it. ISO 15519-1
    # clause 12 governs how a connecting line is drawn and never that a
    # connection point must carry one; the words "nozzle" and
    # "connection point" do not appear in it. This is the drawing
    # contradicting its own declaration, which needs no external
    # authority.
    for u in fs.units:
        families: dict[str, list[str]] = {}
        for name in u.ports:
            stem = _family_stem(name)
            if stem is not None:
                families.setdefault(stem, []).append(name)
        for stem, members in families.items():
            # **Process nozzles only**, the scope issue #183 sets. A
            # balloon's ``pv`` is bare when the instrument is placed
            # against its equipment rather than tapped off a line, and
            # an actuator with no output is a hand valve; neither is
            # answered by counting. No shipped class numbers a signal
            # port, so this holds the door for one that might.
            if any(u.ports[n].role == "signal" for n in members):
                continue
            # A live alias for this family's sole member -- Reactor.feed,
            # Column.feed -- means the singular spelling still answers
            # for it, exactly as it did back when the port itself was
            # named ``feed`` rather than ``feed_1`` (see
            # Unit._canonical_port_name). The class offers that one un-
            # asked, the same as any other fixed nozzle, so it is not "a
            # count that went unmet" -- only a family with no alias at
            # all, or one raised past its aliased arity, is.
            if len(members) == 1 and getattr(u, stem, None) is u.ports[members[0]]:
                continue
            members.sort(key=lambda member: int(member.rpartition("_")[2]))
            loose = [m for m in members if u.ports[m].stream is None]
            if not loose:
                continue
            n, piped = len(members), len(members) - len(loose)
            # ``in_1..in_4`` only where the run really is 1 to n. No
            # constructor here leaves a gap in the middle, but a
            # hand-written ``PORTS`` list can, and ``in_1..in_7`` said
            # of four nozzles would be the message inventing three.
            run = [f"{stem}_{i}" for i in range(1, n + 1)]
            named = (f"{members[0]}..{members[-1]}" if n > 2 and members == run
                     else _and(members))
            # Name the whole run and the arithmetic over it. Only the
            # author knows whether a line was meant and missed or a
            # nozzle never wanted, so the message offers both cures
            # rather than guessing.
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
    # The stream table is one column per distinct
    # name, so two streams answering to one name are drawn as two lines
    # and tabulated as one: a column, and the properties in it,
    # disappear off the sheet. Both lines also carry the same label, so
    # the drawing asserts they are the same stream.
    #
    # **Only a name the counter invented is reported**, and that
    # narrowness is the whole check. Sharing a name is ordinary: a run
    # drawn in several `connect` calls is one stream and is meant to be
    # labelled once, and `examples/10_ethanol_pfd.py` draws `S-305` over
    # five of them while `examples/11_ethanol_pid.py` gives four pairs
    # of segments one line number each. Neither is a defect and neither
    # can be told from a mistyped duplicate, because both are the author
    # writing one name twice on purpose.
    #
    # `renumber_streams`'s grouping does not separate them either: those
    # nine shipped runs sit across two to four groups apiece, since what
    # joins two segments into a group is an inline valve or fitting and
    # a condenser, a drum or a pump is not one.
    #
    # What *is* separable is a name nobody chose. A group with no
    # explicit name and no line-number components is named by counting,
    # and the count's one promise -- `renumber_streams`, and
    # `docs/api.md` under "Stream numbering" -- is that it hands out a
    # name no other stream answers to. A counted name that collides is
    # that promise broken, whoever caused it, and there is no reading of
    # it the author intended.
    #
    # Soft, not hard: every line is drawn and the sheet is readable, and
    # the cure is a rename the author has to choose. What was wrong with
    # it before was the silence.
    counted: dict[str, list] = {}
    taken: dict[str, int] = {}
    for group in fs._stream_groups():
        # The group's name comes from the counter only when nobody named
        # it: an explicit `name=` outranks the count, and line-number
        # components build a name out of what the author wrote down.
        chosen = any(not s.auto_named or s.has_line_number for s in group)
        name = group[0].name
        taken[name] = taken.get(name, 0) + 1
        if not chosen:
            counted.setdefault(name, []).append(group)
    # A signal or duty line is numbered off the same counter and shares
    # the sequence with the process runs, so it can be collided with too.
    for s in fs.streams:
        if s.kind == "material":
            continue
        taken[s.name] = taken.get(s.name, 0) + 1
        if s.auto_named and not s.has_line_number:
            counted.setdefault(s.name, []).append([s])
    for name, groups in counted.items():
        if taken[name] < 2:
            continue
        # Name the ends of the counted runs, so an author looking at a
        # sheet of identical labels knows which one to go to.
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

    # --- an ingoing or outgoing material with nothing to report ---
    # ISO 10628-1:2014 4.3.2, *Process flow diagram*, lists what a PFD
    # must carry at a minimum. Item d) is the name of each ingoing and
    # outgoing material together with its flow rate or quantity, and item
    # f) is the operating conditions that characterise the process.
    #
    # The stream table is where a sheet answers that, and it drops a
    # column with nothing in it -- an internal one, which 4.3.3 a)
    # leaves optional. At the sheet edge the clause above is a *shall*,
    # so the column is kept however empty it is
    # (:func:`pandid.render.furniture._table_streams`): dropping it
    # would conceal the omission rather than show it, and conceal
    # exactly what the standard asks to be reported. This says in words
    # what a column of dashes means, since a sheet full of them is easy
    # to read past.
    #
    # **Only on a sheet that tabulates something**, and that narrowness
    # is the check. A sheet with no properties anywhere has not left a
    # feed out, it has not taken the practice up at all -- and pandid
    # ships ``show_stream_table=False``, so that is the library's
    # decision as much as the author's and wants its own answer rather
    # than a finding per boundary line on every drawing. Fourteen of the
    # twenty shipped examples are in that state and none of them is what
    # this is for. A sheet that tabulates its other streams and not this
    # one has left it out, and the author is the only one who can say
    # what belongs in it.
    #
    # Soft, not hard. The sheet draws, the column is there and the line
    # is named on it; what is missing is a number nobody but the author
    # has.
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
        # The check above answers a sheet that has taken up tabulating and
        # left one column short. This is the sheet that has not taken up
        # the practice at all -- pandid ships ``show_stream_table=False``,
        # so a render before this line is ever reached has already chosen
        # not to draw one. ISO 10628-1:2014 4.3.2 c) and d) make the route
        # and the denomination and flow rate of every ingoing and outgoing
        # material a process flow diagram's minimum content regardless, so
        # a PFD with a Feed or a Product and nothing tabulated anywhere is
        # short of it whether or not the author ever opened the stream
        # table's door.
        #
        # A P&ID answers a different clause, 4.4.2, which does not ask for
        # this, so the check reads ``arrows``: true exactly when the sheet
        # this render is for is a PFD (see
        # :func:`~pandid.render.svg.draws_arrowheads`).
        #
        # One finding for the sheet and not one per line: unlike the check
        # above, there is no other column here to contrast an empty one
        # against, so there is one thing to say rather than one per line
        # that says it.
        #
        # Soft, not hard, for the same reason the check above is: the
        # sheet draws either way, and what is missing is data nobody but
        # the author has.
        if arrows:
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
    """The findings that read the resolved geometry (errors first).

    Everything here needs frames, routes, or a note an earlier phase
    left behind, so none of it can be asked of a sheet before
    :meth:`~pandid.flowsheet.Flowsheet.layout` and
    :meth:`~pandid.flowsheet.Flowsheet.route` have run. Asked early it
    is silent rather than wrong: ``route_converged`` starts true and
    ``unplaced_instruments`` starts empty, so a sheet that has not been
    laid out is told nothing about placements nothing has attempted.

    ``arrows`` says whether the drawing being checked puts an arrowhead
    on the end of a process line, which a PFD does and a P&ID does not.
    It is a property of the *render* rather than of the flowsheet, and
    it is a boolean rather than a diagram name so that the spelling of
    that name stays one question, asked in
    :func:`pandid.render.svg.draws_arrowheads`.
    :meth:`pandid.flowsheet.Flowsheet.validate` resolves it.
    """
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.portgeom import (is_anchored, port_faces, port_point,
                                 resolve_port, unit_box)
    from pandid.render.symbols import (_LABEL_EM, _LABEL_PAD, ARROWHEAD,
                                       MIN_HEAD_CLEARANCE, MIN_NOZZLE_PITCH,
                                       default_registry, wears_arrowhead)
    from pandid.streams import SIGNAL_KINDS, Stream
    from pandid.units import Block

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- routing settled? (reported by route(), not recomputed here)
    # --- Placing an instrument moves an obstacle and routing around an
    # obstacle moves an instrument, so a dense sheet can trade between
    # two arrangements instead of settling on one. The drawing is still
    # coherent -- the lines are drawn to where the balloons are -- but
    # which arrangement it caught is arbitrary, and the author cannot
    # see that without being told.
    if not fs.route_converged:
        warnings.append(Issue(
            "warning", "route-not-settled",
            f"attached instruments were still moving after {MAX_PLACEMENT_PASSES} "
            "routing passes; a balloon may sit slightly off the line it taps. "
            "Pin the balloon-carrying lines with via() to settle it"))

    # --- a balloon nothing could place (recorded by layout, not
    # --- recomputed here) --- An attached instrument takes its frame
    # from its host, so a chain of them has to end on something the
    # ranker positions. One that does not is left frameless by
    # :func:`~pandid.layout.attach.place_attached`, which sweeps until a
    # pass places nothing and then stops.
    #
    # Read from where that sweep parked it rather than looked for here,
    # because ``frame is None`` on its own does not say which of two
    # things happened: layout has not run, or layout ran and gave up.
    # Only the sweep can tell them apart, and a sheet validated before
    # layout must not be told its balloons are unplaceable.
    #
    # Hard, not soft. There is no drawing to warn about: the renderer
    # refuses a frameless unit outright, so the instrument the author
    # asked for reaches no sheet. Saying it here names the balloon and
    # the cure, in place of a bare "lacks a frame" out of the middle of
    # a bounding-box sweep.
    for u in fs.unplaced_instruments:
        # A stream host is not placed itself; what stops it anchoring a
        # balloon is an end that never was, so name the thing that is
        # actually missing in each case.
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
    # Over the units that have one, not over the whole sheet or none of
    # it. Before layout nothing is placed and there is nothing to check;
    # after it the only frameless unit is a balloon reported above as
    # ``instrument-unplaced``, and one of those used to take every
    # overlap, coincidence and crowded face on the sheet down with it --
    # including for the units that placed perfectly.
    placed = [u for u in fs.units if u.frame is not None]
    if placed:
        boxes = [(u, unit_box(u, u.frame)) for u in placed]
        # A stream with an unplaced end has no drawn path, so there is
        # no line to measure a crossing, a detour or an elevation
        # against.
        drawn = [s for s in fs.streams if s.source.owner.frame is not None
                 and s.dest.owner.frame is not None]

        # A block letters its name *inside* its box, so a box too narrow
        # for the name draws the name out through both sides of it and
        # across whatever is beside it. `block_symbol` widens a box it
        # sizes itself, which is why this can only happen to a block
        # given a `width` of its own -- and an explicit width wins
        # outright, so the drawing is what the author asked for and the
        # finding is soft. It had no channel at all: the renderer has a
        # `text-overruns-cell` code for exactly this shape of defect and
        # only sheet furniture ever raised it.
        #
        # Under its own code, not `text-overruns-cell`: `SvgRenderer`
        # replaces every finding under one of those with its own before
        # returning, so a finding made here under that code would be
        # deleted by the render it is about.
        for u, box in boxes:
            if not isinstance(u, Block) or not u.tag:
                continue
            room = box[2] - box[0]
            needed = _LABEL_EM * len(str(u.tag)) + _LABEL_PAD
            if room + _TOL >= needed:
                continue
            warnings.append(Issue(
                "warning", "label-overruns-symbol",
                f"{u.name} letters {str(u.tag)!r} inside a box {room:g} units wide, "
                f"and the name needs {needed:g}: it is drawn about "
                f"{(needed - room) / 2:.0f} units out through each side. Widen the "
                f"block, or leave width= unset and let it size itself to the name"))

        # Hard: overlapping unit bodies.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i][1], boxes[j][1]):
                    errors.append(Issue("error", "unit-overlap",
                                        f"{boxes[i][0].name} and {boxes[j][0].name} overlap"))

        # Hard: two live connections on one unit landing on the same
        # point, so one stream terminates on top of the other. The
        # runtime half of the symbol-level duplicate-nozzle rule
        # (:meth:`pandid.render.symbols.Symbol.coincident_ports`), and
        # the only half that can see it: a symbol may legitimately offer
        # one face to two faceless connections, and which placement each
        # port took is a property of the finished sheet.
        for u in placed:
            seen: dict[tuple[float, ...], str] = {}
            for name, port in u.ports.items():
                if port.stream is None:
                    continue
                pt = tuple(round(v, 3) for v in port_point(u, u.frame, name))
                first = seen.get(pt)
                if first is None:
                    seen[pt] = name
                    continue
                # A port the symbol never anchored fell back to the
                # centre of the box, where every other unanchored port
                # also is. That is a gap in the symbol rather than a
                # contradiction on the sheet, so it does not stop the
                # drawing.
                anchored = is_anchored(u, name) and is_anchored(u, first)
                issue = Issue(
                    "error" if anchored else "warning", "coincident-ports",
                    f"{u.name}.{first} and {u.name}.{name} are both connected and "
                    f"both resolve to ({pt[0]}, {pt[1]})"
                    + ("" if anchored else "; the symbol anchors no nozzle for one "
                       "of them, so both fall back to the centre of the box"))
                (errors if anchored else warnings).append(issue)

        # Soft: nozzles on one face pitched closer than the arrowheads
        # they carry can be told apart at. A PFD ends every process line
        # in a filled triangle (:data:`pandid.render.symbols.ARROWHEAD`)
        # as wide across the run as it is long, so two on one face at
        # pitch p leave ``p - ARROWHEAD`` of paper between two solid
        # shapes; below MIN_HEAD_CLEARANCE that is thinner than ISO
        # 128-20 allows between parallel lines.
        #
        # The floor is a *clearance*, not a multiple of the head, and
        # that is the correction that matters: 10_ethanol_pfd's M-301
        # leaves 2.5px and is a defect, while the same corpus's mixers
        # at a 20px pitch leave 8px, which a reader resolves without
        # effort. A rule phrased as "2.5x the head" reports both.
        #
        # *Both* nozzles of a pair have to wear a head. A splitter takes
        # its heads at the far ends of its branches, so its outlet face
        # carries bare 2px lines however tightly they are pitched.
        #
        # The cure is the box, so the message does the arithmetic. The
        # drawn pitch is linear in the extent of the box across the
        # face, so the extent that clears the floor is the one the unit
        # has, scaled by how far short it fell. A symbol that keeps its
        # aspect is centred rather than stretched and would not answer
        # to that; none reaches here, since the only ports one carries
        # are a balloon's and a signal line wears no head.
        #
        # Moving a nozzle is offered only where the symbol has another
        # face for it. Everything this fires on today is placed by a
        # port series, and a series declares one face.
        for u in placed if arrows else ():
            heads: dict[str, list[tuple[float, str]]] = {}
            for name, port in u.ports.items():
                s = port.stream
                # The head is the path's ``marker-end``, so it lands on
                # the nozzle the stream arrives at and on no other.
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
                # Two heads at this pitch either leave a strip of paper
                # too thin to read or have run into each other. Same
                # finding, but the measurement is worded for the one
                # that happened rather than quoting a clearance of
                # "-0.3px".
                gap = pitch - ARROWHEAD
                measured = (
                    f"which leaves {gap:.1f}px of paper between two "
                    f"{ARROWHEAD:.0f}px arrowheads -- under the "
                    f"{MIN_HEAD_CLEARANCE:.0f}px ISO 128-20:1996 4.4 asks between "
                    f"parallel lines, twice the weight this sheet draws them at"
                    if gap > 0 else
                    f"which overlaps two {ARROWHEAD:.0f}px arrowheads by "
                    f"{-gap:.1f}px, so the two heads are drawn over each other")
                # Only where the artwork really offers somewhere else to
                # put it.
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
        for s in drawn:
            if not (s.route and s.route.waypoints):
                continue
            src_u, dst_u = s.source.owner, s.dest.owner
            sp = port_point(src_u, src_u.frame, s.source.name)
            dp = port_point(dst_u, dst_u.frame, s.dest.name)
            pts = [sp] + list(s.route.waypoints) + [dp]

            for k in range(len(pts) - 1):
                (x1, y1), (x2, y2) = pts[k], pts[k + 1]
                for u, box in boxes:
                    if u is src_u or u is dst_u or getattr(u, "host", None) is s:
                        continue  # in-line elements own their line
                    if _seg_crosses_box(x1, y1, x2, y2, box):
                        warnings.append(Issue("warning", "route-crosses-unit",
                                              f"stream {s.name} crosses {u.name}"))
                        break

            # Soft: a segment drawn on the slant. BS ISO 15519-1:2010
            # §12.1 wants connecting lines run horizontally or
            # vertically, but lets a line go oblique where doing so
            # makes the diagram clearer -- the exception is why this
            # warns rather than refuses, and the exception is also why
            # nothing can decide for the author.
            #
            # One ``via()`` waypoint is what produces it. ``via`` states
            # the middle of the path and nothing squares the two ends up
            # against it, so a single point off the axis of both nozzles
            # leaves two sloping segments where the author expected an
            # elbow. ``tests/test_route_invariants`` and
            # ``tests/test_render`` hold the shipped corpus orthogonal,
            # so the sheets in this repo are clean and an author drawing
            # their own had nothing watching at all.
            #
            # Neither route finding beside it can see this.
            # ``route-detour`` measures Manhattan length, and a
            # diagonal's is exactly the elbow's that replaces it -- the
            # same dx and the same dy -- so squaring one up does not move
            # the ratio by a pixel. ``route-crosses-unit`` is blind to a
            # sloping segment outright (:data:`_SQUARE_TOL`), so a
            # diagonal run straight through a vessel is reported by
            # nothing at all.
            #
            # One finding per stream: the whole path is one ``via()``
            # call and one thing to fix.
            slopes = [(a, b) for a, b in zip(pts, pts[1:]) if not _square(*a, *b)]
            if slopes:
                (x1, y1), (x2, y2) = slopes[0]
                more = ("" if len(slopes) == 1 else
                        f", the first of {len(slopes)} on it")
                # Only the author knows which corner they meant, so the
                # message offers the ones the segment allows rather than
                # guessing -- less any that is already a point on the
                # path, since turning at one of those doubles the line
                # back on itself instead of squaring it. With a single
                # ``via()`` waypoint that leaves exactly one.
                #
                # Off a manual route the cure is the ``via()`` call; off
                # an automatic one there is nothing to edit, since the
                # router draws right angles only and a slope there is a
                # path resolved against geometry that has since moved.
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

        # Soft: a horizontal run whose two ends nearly, but not quite,
        # share an elevation. Units are pinned by their top-left corner,
        # so a row pinned to convenient corner-y values puts its
        # *nozzles* wherever each symbol happens to carry them and the
        # router draws a step into the device and back out. Nothing
        # errors and no nozzle leaves its ink; the sheet is silently,
        # subtly wrong.
        #
        # ``pin(port=...)`` is the cure, so the message names it.
        for s in drawn:
            # A signal line carries a measurement, not a fluid, so it
            # has no elevation to be off. Its balloon end is placed by
            # ``add_instrument``'s anchor and ``offset=`` rather than by
            # a pin.
            if s.kind in SIGNAL_KINDS:
                continue
            su, du = s.source.owner, s.dest.owner
            # This finding's whole content is that a hand-written
            # elevation was arrived at by corner arithmetic, so it is
            # only raised where a hand-written elevation exists. On an
            # auto-laid-out sheet the engine is free to move them.
            if not (_pinned_y(su) or _pinned_y(du)):
                continue
            src = resolve_port(su, su.frame, s.source.name)
            dst = resolve_port(du, du.frame, s.dest.name)
            near = _off_elevation(su, src, du, dst)
            if near is None:
                continue
            offset, span, at_source = near
            # Name the shorter device and the elevation to put it on:
            # its own half-height is the arithmetic that went missing.
            # Which end that is comes back from the call that measured
            # ``span``, so the sentence cannot name one device and quote
            # the other one's height at it.
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

    return errors + warnings


def validate(fs: "Flowsheet", *, arrows: bool = True) -> list["Issue"]:
    """Return all validation issues for the flowsheet (errors first).

    Both halves -- :func:`model_issues` and :func:`geometry_issues` --
    over the sheet as it stands, which is what a caller asking "what is
    wrong with this?" means. A render asks the two separately and at
    different moments; see
    :meth:`pandid.flowsheet.Flowsheet._prepare_to_draw`.

    ``arrows`` is :func:`geometry_issues`' argument, passed straight
    through, and :func:`model_issues`' -- the one finding that reads it
    there answers a clause that governs a PFD and not a P&ID, the same
    fact ``arrows`` already carries.
    """
    found = model_issues(fs, arrows=arrows) + geometry_issues(fs, arrows=arrows)
    return ([i for i in found if i.severity == "error"]
            + [i for i in found if i.severity == "warning"])

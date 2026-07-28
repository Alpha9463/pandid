"""Flowsheet validation.

Separates two kinds of problems:

- **errors**: genuine contradictions the engine cannot honor (overlapping
  pinned units, negative/non-finite coordinates). ``render()`` raises on these
  rather than emit a silently-wrong drawing.
- **warnings**: the drawing is valid but imperfect (a stream crosses a unit
  body, a route detours excessively, a tag spells its letters in an order no
  standard uses). Collected on ``fs.warnings`` for the caller to inspect; never
  fatal.

Geometric checks need resolved frames, so they are skipped until layout has run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_TOL = 1.0  # px tolerance so touching edges are not flagged as overlaps

#: ``(kind, variant)`` pairs a run is *meant* to change centreline through, so
#: ``run-off-elevation`` has nothing to tell an author who put one in a line.
#:
#: One member, and it is the fitting whose entire purpose is the step. An
#: eccentric reducer is flat on top, so the small end's centreline is the higher
#: of the two, which is the whole reason it is specified on a pump suction where
#: a concentric reducer would leave a pocket against the roof of the line for
#: vapour to collect in (see the reasoning beside its ``KIND_MAP`` entry in
#: ``scripts/vendor_symbols.py``). Both its nozzles face along the run, so the
#: pair *does* read as one elevation to :func:`_off_elevation`, and the 2.4px
#: rise it draws would otherwise be reported as arithmetic the author dropped.
#: Straightening it is the one change that would break the fitting.
#:
#: The relief valves -- ``valve/angle``, ``valve/psv``, ``valve/relief`` -- are
#: *not* here, and deliberately so, because none of them has a step to be
#: excused for. The first two turn the run a quarter, so no placement puts both
#: their nozzles along one elevation and the face test below never reaches them.
#: The third passes the run straight up; laid on its side it does offer a
#: horizontal pair, and that pair is level. A name in this set is a rule with no
#: geometry behind it, which is how such a set grows silently, so
#: ``tests/test_validate.py`` asserts the geometry over every quarter turn
#: instead of taking the exemption on faith.
#:
#: A device that merely *has* its two nozzles at different heights does not
#: belong here either. A pump's discharge is drawn above its suction, and the
#: author still has to put the downstream nozzle on the discharge: the step is
#: real, so reporting a downstream unit that missed it is the finding working.
#: What separates the eccentric reducer is that acting on the report -- moving
#: the far end onto the near end's elevation -- would undo the device.
OFFSET_BY_DESIGN = frozenset({
    ("reducer", "eccentric"),
})

#: The order the control-function letters of a tag have to appear in.
#: BS ISO 15519-2:2015 §5.2.4, *Sequence of letter codes for control functions*:
#:
#:     Letter codes for control function shall be represented in following
#:     sequence: I, R, C, S, M, Z, and A, for example:
#:     * ICA   Indication, control (closed loop) and alarm;
#:     * CS    Control (closed loop) and switching (open loop);
#:     * ICZA  Indication, control (closed loop), switching (open loop) safety
#:             relevant, and alarm.
#:
#: So ``FIC`` is right and ``FCI`` is wrong. Only these seven letters are
#: ordered: the first letter of a tag is the measured variable (Table 2) and
#: everything else in the string is either a modifier (Table 3: ``D``, ``H``,
#: ``L``, ``P``) or an ISA function letter ISO does not sequence (``T``, ``E``,
#: ``Y``, ``V``), so those keep the position the author gave them.
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


def _control_functions(letters: str) -> list[str]:
    """The sequenced letters of a tag, in the order it spells them.

    The first letter is the measured variable and is skipped: ``C`` opens a
    conductivity tag as legitimately as it closes ``FIC``.
    """
    return [c for c in letters[1:] if c.upper() in CONTROL_FUNCTION_SEQUENCE]


def _in_sequence(letters: str) -> str:
    """*letters* with its control-function letters put into ISO 15519-2 order.

    Only those letters move. A modifier keeps the position it was given, since
    ``H`` in ``LAH`` says which limit alarmed and reordering it would say
    something else.
    """
    ordered = iter(sorted(_control_functions(letters),
                          key=lambda c: CONTROL_FUNCTION_SEQUENCE.index(c.upper())))
    return letters[:1] + "".join(
        next(ordered) if c.upper() in CONTROL_FUNCTION_SEQUENCE else c
        for c in letters[1:]
    )


def _seg_crosses_box(x1, y1, x2, y2, box) -> bool:
    """True if an orthogonal segment passes through a box's interior."""
    bx0, by0, bx1, by1 = box
    if abs(x1 - x2) < 0.5:  # vertical
        return bx0 + _TOL < x1 < bx1 - _TOL and min(y1, y2) < by1 - _TOL and max(y1, y2) > by0 + _TOL
    if abs(y1 - y2) < 0.5:  # horizontal
        return by0 + _TOL < y1 < by1 - _TOL and min(x1, x2) < bx1 - _TOL and max(x1, x2) > bx0 + _TOL
    return False


def _pinned_y(unit) -> bool:
    """True when this unit's elevation was written down by hand.

    ``pin(row=...)`` is a grid cell rather than a coordinate, so it is not a
    number anyone did nozzle arithmetic on and does not count.
    """
    pin = getattr(unit, "pin_", None)
    return pin is not None and getattr(pin, "y", None) is not None


def _off_elevation(su, sp, du, dp) -> tuple[float, float, bool] | None:
    """How far these two connected nozzles near-miss by, or None if they don't.

    *su*/*du* are the units at the two ends of one stream and *sp*/*dp* their
    resolved ports. Answers ``(offset, span, source_is_shorter)``: the miss, the
    extent it was measured against, and which end that extent belongs to. All
    three together, so the message cannot name one device and quote the other
    one's height at it.
    """
    from pandid.portgeom import unit_box

    # A run is a line at one elevation, and only a pair of nozzles that both
    # face along it has one. A pair with a vertical face is a deliberate turn,
    # and a pair with two of them is a riser or a drop, where the difference in
    # y is the *length* of the run rather than a miss. Opposite faces, and the
    # destination on the side the source points at, so the two are looking at
    # each other: a run that leaves east and arrives from the east has already
    # doubled back on itself, and a jog inside a detour is not a step in a
    # straight line.
    if {sp.face, dp.face} != {"E", "W"} or (sp.face == "E") != (dp.point[0] > sp.point[0]):
        return None

    # Offset by design: the fitting is *for* the step. See OFFSET_BY_DESIGN.
    for u in (su, du):
        if (u.kind, getattr(u, "variant", "default")) in OFFSET_BY_DESIGN:
            return None

    offset = abs(dp.point[1] - sp.point[1])
    if offset <= _TOL:
        return None  # sub-pixel; nothing is drawn differently

    # The threshold is the shorter symbol's own extent across the run, taken
    # off the *drawn* box so a unit given an explicit height is measured at the
    # size it got. The reasoning: the miss this catches is a nozzle offset the
    # author did not subtract, and a nozzle is somewhere inside its own symbol,
    # so the whole family of them -- half a valve's height, a strainer's 10
    # against a valve's 7.5, a sight glass's 6.25 against a vessel's 70 -- is
    # bounded by how tall the shorter of the two devices is and never exceeds
    # it. A deliberate change of elevation is a step between *runs*: it clears
    # the shorter symbol entirely, because a drawing that put the second run
    # inside the first one's body would not read as two runs.
    #
    # Half that extent is the tempting number, since half a symbol height is the
    # commonest single cause. It is measurably wrong: over this repo's own
    # examples eight of the misses land on exactly half and two land just past
    # it (a sight glass 6.3 off a 12.5 body), so half either drops them to a
    # floating-point tie-break or misses them outright.
    sb, db = unit_box(su, su.frame), unit_box(du, du.frame)
    sh, dh = sb[3] - sb[1], db[3] - db[1]
    span = min(sh, dh)
    return (offset, span, sh <= dh) if offset < span else None


def validate(fs: "Flowsheet") -> list["Issue"]:
    """Return all validation issues for the flowsheet (errors first)."""
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.portgeom import is_anchored, port_point, resolve_port, unit_box
    from pandid.render.symbols import default_registry
    from pandid.streams import SIGNAL_KINDS
    from pandid.units import Instrument

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- routing settled? (reported by route(), not recomputed here) ---
    # Placing an instrument moves an obstacle and routing around an obstacle
    # moves an instrument, so a dense sheet can trade between two arrangements
    # instead of settling on one. The drawing is still coherent, since the lines
    # are drawn to where the balloons are, but which of the arrangements it
    # caught is arbitrary, and an author who wants a repeatable sheet has to pin
    # the line with via(). That is only worth saying because they cannot see it.
    if not fs.route_converged:
        warnings.append(Issue(
            "warning", "route-not-settled",
            f"attached instruments were still moving after {MAX_PLACEMENT_PASSES} "
            "routing passes; a balloon may sit slightly off the line it taps. "
            "Pin the balloon-carrying lines with via() to settle it"))

    # --- pin sanity (no frames required) ---
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

    # --- turned symbols whose function is gravity (no frames required) ---
    # ISO 15519-1:2010 §11.4.2, *Orientation of graphical symbols*:
    #
    #     Exceptions for turning are symbols representing components or devices
    #     where gravity is a functionality, for example symbol 2061: Open tank
    #     or symbol X 2618: Cyclone separator; see Figure 22 b). Such symbols
    #     must not be turned.
    #
    # Soft, and deliberately so, despite the clause's "must not" being the
    # strongest phrasing in it. An error is for something the engine cannot
    # honour, and this it can: the sheet draws, every nozzle lands on ink, and
    # the only thing wrong with it is what it says about the plant. It is the
    # same kind of finding as ``letter-sequence`` -- a standard's rule the author
    # may have a reason to break, reported rather than enforced. Refusing would
    # also make the library unable to check its own artwork, since
    # ``tests/test_symbol_invariants`` turns every registered symbol through 90°
    # and 270° to prove its ports stay on the drawing, which is a geometry check
    # and not a drawing of a plant.
    #
    # Mirroring is left alone: §11.4.2 excepts *turning* only, and flipping a
    # tank left to right to put its nozzles on the other side is a placement the
    # clause permits.
    #
    # Read off the resolved frame where there is one, since that is the placement
    # that got drawn, and off the pin before layout has run. The solver reseeds
    # from the pin, so the two agree.
    for u in fs.units:
        placed = u.frame if u.frame is not None else u.pin_
        turn = int(getattr(placed, "orientation", 0) or 0)
        variant = getattr(u, "variant", "default")
        # A variant no symbol answers to is the renderer's complaint to make,
        # with the catalogue to hand; asking for the artwork here would raise out
        # of a function whose whole contract is to report rather than raise.
        if not turn or variant not in default_registry.variants(u.kind):
            continue
        if not default_registry.for_unit(u).gravity_fixed:
            continue
        # ISO's own way out, from the lettering paragraph of the same clause:
        # "a new symbol should be created to the actual orientation". Two
        # families ship one, the lying drum, so name it where it exists instead
        # of leaving the author to find it.
        lying = ("horizontal" if variant != "horizontal"
                 and "horizontal" in default_registry.variants(u.kind) else "")
        warnings.append(Issue(
            "warning", "gravity-turned",
            f"{u.name} is turned {turn}°; ISO 15519-1:2010 11.4.2 excepts "
            f"symbols where gravity is a functionality from turning, and a "
            f"{u.kind}/{variant} is one of them"
            + (f". Use variant={lying!r}, which is that equipment drawn lying "
               f"down rather than the upright one turned" if lying else "")))

    # --- tag spelling (no frames required) ---
    # Soft, not hard: the letters still read, and a sheet whose house style
    # differs from ISO's is not a sheet the engine should refuse to draw. One
    # finding per tag, so an interlock square drawn four times says it once.
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

    # --- geometric checks (need resolved frames) ---
    if fs.units and all(u.frame is not None for u in fs.units):
        boxes = [(u, unit_box(u, u.frame)) for u in fs.units]

        # Hard: overlapping unit bodies.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i][1], boxes[j][1]):
                    errors.append(Issue("error", "unit-overlap",
                                        f"{boxes[i][0].name} and {boxes[j][0].name} overlap"))

        # Hard: two live connections on one unit landing on the same point, so
        # one stream terminates exactly on top of the other. This is the runtime
        # half of the symbol-level duplicate-nozzle rule
        # (:meth:`pandid.render.symbols.Symbol.coincident_ports`), and the only
        # half that can see it: a symbol may legitimately offer one face to two
        # faceless connections, and which placement each port took (and what
        # mirroring then did to it) is a property of the finished sheet.
        for u in fs.units:
            seen: dict[tuple[float, ...], str] = {}
            for name, port in u.ports.items():
                if port.stream is None:
                    continue
                pt = tuple(round(v, 3) for v in port_point(u, u.frame, name))
                first = seen.get(pt)
                if first is None:
                    seen[pt] = name
                    continue
                # A port the symbol never anchored has no placement to collide
                # with: it fell back to the centre of the box, where every
                # other unanchored port also is. A missing nozzle is a gap in
                # the symbol, not a contradiction on the sheet, so it does not
                # stop the drawing.
                anchored = is_anchored(u, name) and is_anchored(u, first)
                issue = Issue(
                    "error" if anchored else "warning", "coincident-ports",
                    f"{u.name}.{first} and {u.name}.{name} are both connected and "
                    f"both resolve to ({pt[0]}, {pt[1]})"
                    + ("" if anchored else "; the symbol anchors no nozzle for one "
                       "of them, so both fall back to the centre of the box"))
                (errors if anchored else warnings).append(issue)

        # Soft: a route passing through a unit body it does not connect to,
        # and grossly indirect routes.
        for s in fs.streams:
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
                        continue  # an in-line element sits on its own line by design
                    if _seg_crosses_box(x1, y1, x2, y2, box):
                        warnings.append(Issue("warning", "route-crosses-unit",
                                              f"stream {s.name} crosses {u.name}"))
                        break

            length = sum(abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1])
                         for k in range(len(pts) - 1))
            direct = abs(dp[0] - sp[0]) + abs(dp[1] - sp[1])
            if direct > 1 and length > 3.0 * direct:
                warnings.append(Issue("warning", "route-detour",
                                      f"stream {s.name} routes {length:.0f}px for a "
                                      f"{direct:.0f}px span ({length / direct:.1f}x)"))

        # Soft: a horizontal run whose two ends nearly, but not quite, share an
        # elevation. Units are pinned by their top-left corner, so a row pinned
        # to convenient corner-y values puts its *nozzles* wherever each symbol
        # happens to carry them, and the router draws a step into the device and
        # a step back out. Nothing errors and no nozzle leaves its ink: the
        # sheet is merely, silently, subtly wrong, which is what makes it worth
        # a finding rather than a docstring.
        #
        # ``pin()`` already has the cure and authors do not reach for it, so the
        # message names it, the way ``gravity-turned`` names the lying drum
        # instead of leaving the author to find it.
        for s in fs.streams:
            # A signal line carries a measurement, not a fluid, so it has no
            # elevation to be off. Its balloon end is placed by
            # ``add_instrument(on=..., offset=...)`` rather than by a pin, and
            # advice to pin a nozzle the author never positioned is advice to
            # hand-place a sheet that did not ask to be hand-placed.
            if s.kind in SIGNAL_KINDS:
                continue
            su, du = s.source.owner, s.dest.owner
            # Same reason, for process lines: this finding's whole content is
            # that a hand-written elevation was arrived at by corner arithmetic,
            # so it is only raised where a hand-written elevation exists. On an
            # auto-laid-out sheet the elevations are the engine's own, and it is
            # already free to move them.
            if not (_pinned_y(su) or _pinned_y(du)):
                continue
            src = resolve_port(su, su.frame, s.source.name)
            dst = resolve_port(du, du.frame, s.dest.name)
            near = _off_elevation(su, src, du, dst)
            if near is None:
                continue
            offset, span, at_source = near
            # Name the shorter device and the elevation to put it on. It is the
            # one whose own half-height is the arithmetic that went missing, and
            # the one the step reads as a dogleg *around* rather than as a
            # second run. Which end that is comes back from the same call that
            # measured ``span``, so the sentence cannot name one device and
            # quote the other one's height at it.
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

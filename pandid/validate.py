"""Flowsheet validation.

Separates two kinds of problems:

- **errors**: genuine contradictions the engine cannot honor
  (overlapping pinned units, negative or non-finite coordinates).
  ``render()`` raises on these rather than emit a wrong drawing.
- **warnings**: the drawing is valid but imperfect (a stream crosses a
  unit body, a route detours excessively, a tag spells its letters in an
  order no standard uses, a nozzle a count asked for has no line on it).
  Collected on ``fs.warnings`` for the caller; never fatal.

Geometric checks need resolved frames, so they are skipped until layout
has run.

Most findings are made by inspecting the finished flowsheet. Two are
collected from where an earlier phase parked them:
``route-not-settled``, which only ``route()`` can know, and
``deprecated``, which leaves no trace in the topology or the geometry.
See :mod:`pandid.deprecation`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_TOL = 1.0  # px tolerance so touching edges are not flagged as overlaps

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

#: The order the control-function letters of a tag have to appear in. BS
#: ISO 15519-2:2015 §5.2.4, *Sequence of letter codes for control
#: functions*:
#:
#:     Letter codes for control function shall be represented in
#:     following sequence: I, R, C, S, M, Z, and A, for example:
#:     * ICA   Indication, control (closed loop) and alarm;
#:     * CS    Control (closed loop) and switching (open loop);
#:     * ICZA  Indication, control (closed loop), switching (open
#:             loop) safety relevant, and alarm.
#:
#: So ``FIC`` is right and ``FCI`` is wrong. Only these seven letters
#: are ordered: the first letter of a tag is the measured variable
#: (Table 2) and everything else is either a modifier (Table 3: ``D``,
#: ``H``, ``L``, ``P``) or an ISA function letter ISO does not sequence
#: (``T``, ``E``, ``Y``, ``V``), so those keep the position the author
#: gave them.
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

    The first letter is the measured variable and is skipped: ``C``
    opens a conductivity tag as legitimately as it closes ``FIC``.
    """
    return [c for c in letters[1:] if c.upper() in CONTROL_FUNCTION_SEQUENCE]


def _in_sequence(letters: str) -> str:
    """*letters*, with its control functions in ISO 15519-2 order.

    Only those letters move. A modifier keeps the position it was given,
    since ``H`` in ``LAH`` says which limit alarmed and reordering it
    would say something else.
    """
    ordered = iter(sorted(_control_functions(letters),
                          key=lambda c: CONTROL_FUNCTION_SEQUENCE.index(c.upper())))
    return letters[:1] + "".join(
        next(ordered) if c.upper() in CONTROL_FUNCTION_SEQUENCE else c
        for c in letters[1:]
    )


def _family_stem(port_name: str) -> str | None:
    """The family ``port_name`` is a numbered member of, else ``None``.

    ``in_3`` answers ``"in"``; ``inlet``, ``sig_in`` and ``tube_out``
    answer None, because a trailing word is not a number and a nozzle
    without one is declared outright by its class.

    A numbered nozzle exists **because a count was written down**, and
    five classes build one -- ``Mixer(n_inlets=)``,
    ``Splitter(n_outlets=)``, ``Column``/``Reactor(n_feeds=)`` and
    ``Block(inputs=)``, which ``tests/test_port_annotations`` pins in
    ``_DECLARED_FAMILIES``. Each spells its family as a stem, an
    underscore and a 1-based index; nothing else numbers a port.

    Read off the **unit's own port list** and not the symbol's
    :class:`~pandid.render.symbols.PortSeries`, which writes the same
    naming rule down. :class:`~pandid.units.Block` has no series at all:
    its family is split across up to four faces, so ``block_symbol``
    authors an anchor per connection -- and a check that asked the
    symbol would be silent on the one class whose whole connection list
    is counted.

    A family of one is still a family: ``Mixer(n_inlets=1)`` spells its
    result ``in_1``, while a one-feed column's ``feed`` is silent here
    because the singular spelling says the nozzle was not counted.
    """
    stem, sep, index = port_name.rpartition("_")
    return stem if sep and stem and index.isdigit() else None


def _and(names: list[str]) -> str:
    """``"a"``, ``"a and b"``, ``"a, b and c"``: a sentence's join."""
    return " and ".join(filter(None, [", ".join(names[:-1]), *names[-1:]]))


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


def validate(fs: "Flowsheet", *, arrows: bool = True) -> list["Issue"]:
    """Return all validation issues for the flowsheet (errors first).

    ``arrows`` says whether the drawing being checked puts an arrowhead
    on the end of a process line, which a PFD does and a P&ID does not.
    It is a property of the *render* rather than of the flowsheet, and
    it is a boolean rather than a diagram name so that the spelling of
    that name stays one question, asked in
    :func:`pandid.render.svg.draws_arrowheads`.
    :meth:`pandid.flowsheet.Flowsheet.validate` resolves it.
    """
    from pandid.deprecation import findings as deprecation_findings
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.portgeom import (is_anchored, port_faces, port_point,
                                 resolve_port, unit_box)
    from pandid.render.symbols import (ARROWHEAD, MIN_HEAD_CLEARANCE,
                                       MIN_NOZZLE_PITCH, default_registry,
                                       wears_arrowhead)
    from pandid.streams import SIGNAL_KINDS
    from pandid.units import Instrument

    errors: list[Issue] = []
    warnings: list[Issue] = []

    # --- deprecated API (recorded at the call, not recomputed here) ---
    # The only finding here that is not about the drawing. A deprecated
    # call leaves no trace in the geometry, so nothing later in this
    # function could detect it; :mod:`pandid.deprecation` records it as
    # it happens and this reads it back.
    warnings.extend(deprecation_findings(fs))

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

    # --- turned symbols whose function is gravity (no frames required)
    # --- ISO 15519-1:2010 §11.4.2, *Orientation of graphical symbols*:
    #
    #     Exceptions for turning are symbols representing
    #     components or devices where gravity is a functionality,
    #     for example symbol 2061: Open tank or symbol X 2618:
    #     Cyclone separator; see Figure 22 b). Such symbols must
    #     not be turned.
    #
    # Soft despite the clause's "must not": the sheet draws and every
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
        # clause: "a new symbol should be created to the actual
        # orientation". Two families ship one, the lying drum, so name
        # it where it exists.
        lying = ("horizontal" if variant != "horizontal"
                 and "horizontal" in default_registry.variants(u.kind) else "")
        warnings.append(Issue(
            "warning", "gravity-turned",
            f"{u.name} is turned {turn}°; ISO 15519-1:2010 11.4.2 excepts "
            f"symbols where gravity is a functionality from turning, and a "
            f"{u.kind}/{variant} is one of them"
            + (f". Use variant={lying!r}, which is that equipment drawn lying "
               f"down rather than the upright one turned" if lying else "")))

    # --- tag spelling (no frames required) --- Soft, not hard: the
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

    # --- a counted nozzle with no line on it (no frames required) ---
    # The sheet draws a unit taking four streams and shows three, so it
    # asserts a stream that does not exist. Issue #183 is the defect it
    # came from: a loop over ``(1, 2, 3)`` wiring ``in_2``, ``in_3`` and
    # ``in_4``.
    #
    # **The narrowness is the measurement.** Across the fourteen shipped
    # examples 252 ports carry no stream and every one is legitimate --
    # 165 signal connections, 26 dry exchanger sides, 14 duties, 14
    # reliefs, 14 drains, 11 vents, 8 station drain legs that end off
    # the sheet. A nozzle a class *declares* is offered whether the
    # sheet uses it or not, and leaving one open is a drawing decision.
    # A **numbered** nozzle is not offered, it is asked for:
    # ``n_inlets=4`` is a number the author wrote, so a bare member of
    # that family is that number not being met. None of the 252 is one.
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

    # --- geometric checks (need resolved frames) ---
    if fs.units and all(u.frame is not None for u in fs.units):
        boxes = [(u, unit_box(u, u.frame)) for u in fs.units]

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
        for u in fs.units if arrows else ():
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
                        continue  # in-line elements own their line
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

        # Soft: a horizontal run whose two ends nearly, but not quite,
        # share an elevation. Units are pinned by their top-left corner,
        # so a row pinned to convenient corner-y values puts its
        # *nozzles* wherever each symbol happens to carry them and the
        # router draws a step into the device and back out. Nothing
        # errors and no nozzle leaves its ink; the sheet is silently,
        # subtly wrong.
        #
        # ``pin(port=...)`` is the cure, so the message names it.
        for s in fs.streams:
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

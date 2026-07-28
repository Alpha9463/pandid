"""Flowsheet validation.

Separates two kinds of problems:

- **errors** — genuine contradictions the engine cannot honor (overlapping
  pinned units, negative/non-finite coordinates). ``render()`` raises on these
  rather than emit a silently-wrong drawing.
- **warnings** — the drawing is valid but imperfect (a stream crosses a unit
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

#: The order the control-function letters of a tag have to appear in.
#: BS ISO 15519-2:2015 §5.2.4, *Sequence of letter codes for control functions*:
#:
#:     Letter codes for control function shall be represented in following
#:     sequence: I, R, C, S, M, Z, and A, for example:
#:     — ICA   Indication, control (closed loop) and alarm;
#:     — CS    Control (closed loop) and switching (open loop);
#:     — ICZA  Indication, control (closed loop), switching (open loop) safety
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


def validate(fs: "Flowsheet") -> list["Issue"]:
    """Return all validation issues for the flowsheet (errors first)."""
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.portgeom import is_anchored, port_point, unit_box
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
        # faceless connections, and which placement each port took — and what
        # mirroring then did to it — is a property of the finished sheet.
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
                # with — it fell back to the centre of the box, where every
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

    return errors + warnings

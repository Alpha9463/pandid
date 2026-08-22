"""Where the sheet is cut in two: process, then control.

A P&ID is drawn in that order and read in that order. The pipes and the
equipment they join are the drawing; the instrumentation is furniture
hung on it afterwards, and a signal wire has never moved a pipe. The
engine draws the same boundary:

- **Stage 1, process.** Every unit that carries material, and every
  stream of kind ``"material"``. Positioned, coordinated and routed.
- **Stage 2, control.** Every instrument -- attached to a host *and*
  free-standing -- and every signal run, placed against stage 1's
  frozen geometry and then routed around it.

The old engine cut at *has a host* instead, which is a different line in
two ways that both hurt. A free-standing controller carried a rank, so
the signal from its transmitter was read as a step along the flow and
pushed it a full column east; and the control loop it closed was a cycle
in the flow graph, so phase 0 tore one of its wires and the two ends of
that wire were then placed with no relationship to each other. Cutting
at process-versus-control leaves no control loop in the flow graph to
tear.

Freezing stage 1 also breaks the loop behind
:data:`~pandid.layout.attach.MAX_PLACEMENT_PASSES`: a balloon can no
longer move a process line, so placement and routing stop chasing each
other. The cost is that a signal line can never ask a process line to
move aside, and for a P&ID that is the correct priority.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import _Slot
    from pandid.streams import Stream
    from pandid.units import Unit


def slot(unit: "Unit") -> "_Slot":
    """The solver scratch state every unit carries during a run.

    ``None`` only before :func:`pandid.layout._seed_slots`, which is the
    first thing ``layout()`` does, so every phase below can say so
    rather than checking. Asserted rather than assumed: a phase reading
    a slot that is not there has been called out of order, and that is
    worth stopping for.
    """
    assert unit._slot is not None, f"{unit.name} has no slot; layout ran out of order"
    return unit._slot


def is_control(unit: "Unit | None") -> bool:
    """True for a balloon, whether or not it hangs on anything.

    The question is what the unit *is*, not what it is tied to: a
    free-standing controller is as much instrumentation as one taped to
    the line it reads, and the sheet is laid out around neither.
    """
    return unit is not None and unit.kind == "instrument"


def process_units(fs: "Flowsheet") -> list["Unit"]:
    """The units stage 1 places: everything that carries material."""
    return [u for u in fs.units if not is_control(u)]


def control_units(fs: "Flowsheet") -> list["Unit"]:
    """The balloons stage 2 places, in the order the sheet holds them."""
    return [u for u in fs.units if is_control(u)]


def is_process_stream(stream: "Stream") -> bool:
    """True for a run stage 1 positions against.

    Kind, not endpoint: an ``"energy"`` line is a duty rather than a
    pipe and states no order between the two boxes it joins, and a
    signal is a measurement. Only material puts one unit downstream of
    another.
    """
    src, dst = stream.source.owner, stream.dest.owner
    return (stream.kind == "material" and src is not None and dst is not None
            and not is_control(src) and not is_control(dst))


def process_streams(fs: "Flowsheet") -> list["Stream"]:
    """The runs stage 1 positions against."""
    return [s for s in fs.streams if is_process_stream(s)]


def signal_streams(fs: "Flowsheet") -> list["Stream"]:
    """Every run stage 2 draws: the wires, and the duties beside them.

    An energy line is grouped with the signals because stage 1 does not
    position against it, so it is drawn against frozen geometry exactly
    as a wire is -- not because it is one.
    """
    return [s for s in fs.streams if not is_process_stream(s)]

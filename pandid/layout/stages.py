"""Split a sheet into its process stage and its control stage.

Stage 1 places and routes process units (everything that carries
material) and material streams. Stage 2 places instruments and routes
signal and energy lines against the frozen stage 1 geometry, so a signal
never moves a process line. Free-standing and attached instruments both
belong to stage 2, so a control loop never forms a cycle in the process
graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import _Slot
    from pandid.streams import Stream
    from pandid.units import Unit


def slot(unit: "Unit") -> "_Slot":
    """Return the solver state a unit carries during layout.

    Parameters
    ----------
    unit : Unit
        Unit being laid out.

    Returns
    -------
    _Slot
        Scratch placement seeded by :func:`pandid.layout._seed_slots`.

    Raises
    ------
    AssertionError
        If layout has not seeded the slot, meaning a pass ran out of order.
    """
    assert unit._slot is not None, f"{unit.name} has no slot; layout ran out of order"
    return unit._slot


def is_control(unit: "Unit | None") -> bool:
    """Return whether a unit is an instrument balloon.

    Parameters
    ----------
    unit : Unit or None
        Unit to test.

    Returns
    -------
    bool
        ``True`` for any instrument, attached or free-standing.
    """
    return unit is not None and unit.kind == "instrument"


def process_units(fs: "Flowsheet") -> list["Unit"]:
    """Return the units stage 1 places.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Unit]
        Every unit that is not an instrument, in flowsheet order.
    """
    return [u for u in fs.units if not is_control(u)]


def control_units(fs: "Flowsheet") -> list["Unit"]:
    """Return the instruments stage 2 places.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Unit]
        Every instrument, in flowsheet order.
    """
    return [u for u in fs.units if is_control(u)]


def is_process_stream(stream: "Stream") -> bool:
    """Return whether stage 1 places units against a stream.

    Only a material stream between two process units states an order;
    an energy line is a duty and a signal is a measurement.

    Parameters
    ----------
    stream : Stream
        Stream to test.

    Returns
    -------
    bool
        Whether the stream is material and joins two process units.
    """
    src, dst = stream.source.owner, stream.dest.owner
    return (stream.kind == "material" and src is not None and dst is not None
            and not is_control(src) and not is_control(dst))


def process_streams(fs: "Flowsheet") -> list["Stream"]:
    """Return the streams stage 1 places units against.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Stream]
        Process streams, in flowsheet order.
    """
    return [s for s in fs.streams if is_process_stream(s)]


def signal_streams(fs: "Flowsheet") -> list["Stream"]:
    """Return the streams stage 2 routes.

    Energy lines are included because stage 1 does not place against them.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Stream]
        Every stream that is not a process stream, in flowsheet order.
    """
    return [s for s in fs.streams if not is_process_stream(s)]

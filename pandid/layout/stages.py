"""Split a sheet into its process stage and its control stage.

Stage 1 is process units and material streams; stage 2 is instruments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import _Slot
    from pandid.streams import Stream
    from pandid.units import Unit


def slot(unit: "Unit") -> "_Slot":
    """Return the solver slot a unit carries during layout.

    Parameters
    ----------
    unit : Unit
        Unit being laid out.

    Returns
    -------
    _Slot
        The unit's slot.

    Raises
    ------
    AssertionError
        If layout has not seeded the slot.
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
        True for an instrument.
    """
    return unit is not None and unit.kind == "instrument"


def process_units(fs: "Flowsheet") -> list["Unit"]:
    """Return every unit that is not an instrument.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Unit]
        Process units, in flowsheet order.
    """
    return [u for u in fs.units if not is_control(u)]


def is_process_stream(stream: "Stream") -> bool:
    """Return whether a material stream joins two process units.

    Parameters
    ----------
    stream : Stream
        Stream to test.

    Returns
    -------
    bool
        True for a material stream between two process units.
    """
    src, dst = stream.source.owner, stream.dest.owner
    return (stream.kind == "material" and src is not None and dst is not None
            and not is_control(src) and not is_control(dst))


def process_streams(fs: "Flowsheet") -> list["Stream"]:
    """Return the process streams, in flowsheet order.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Stream]
        Material streams between process units.
    """
    return [s for s in fs.streams if is_process_stream(s)]

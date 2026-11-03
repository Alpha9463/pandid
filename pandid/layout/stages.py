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
    """Return the solver slot a unit carries during layout."""
    assert unit._slot is not None, f"{unit.name} has no slot; layout ran out of order"
    return unit._slot


def is_control(unit: "Unit | None") -> bool:
    """Return whether a unit is an instrument balloon."""
    return unit is not None and unit.kind == "instrument"


def process_units(fs: "Flowsheet") -> list["Unit"]:
    """Return every unit that is not an instrument."""
    return [u for u in fs.units if not is_control(u)]


def is_process_stream(stream: "Stream") -> bool:
    """Return whether a material stream joins two process units."""
    src, dst = stream.source.owner, stream.dest.owner
    return (stream.kind == "material" and src is not None and dst is not None
            and not is_control(src) and not is_control(dst))


def process_streams(fs: "Flowsheet") -> list["Stream"]:
    """Return the process streams, in flowsheet order."""
    return [s for s in fs.streams if is_process_stream(s)]

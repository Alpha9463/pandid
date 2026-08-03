"""State: the thermodynamic condition of a stream or port.

This is the seam a mass/energy-balance engine writes to. It carries no
property calculations itself; a pluggable thermo backend attaches those.
Keeping this slot on :class:`~pandid.ports.Port` and
:class:`~pandid.streams.Stream` means such an engine can be added
without reshaping the topology model.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class State:
    """Composition and conditions at a point in the flowsheet."""

    # Mole (or mass) fractions by species.
    components: dict[str, float] = field(default_factory=dict)
    molar_flow: float | None = None
    mass_flow: float | None = None
    T: float | None = None          # temperature
    P: float | None = None          # pressure
    vapor_fraction: float | None = None
    enthalpy: float | None = None

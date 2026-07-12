"""State — the thermodynamic condition of a stream or port.

This is the seam the (future, commercial) mass/energy-balance engine writes to.
It carries no property calculations itself in v1; a pluggable thermo backend
attaches those later. Keeping this slot on :class:`~pfd.ports.Port` and
:class:`~pfd.streams.Stream` now means the balance engine can be added without
reshaping the topology model (design spec §4, §10, §12).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class State:
    """Composition and intensive/extensive conditions at a point in the flowsheet."""

    components: dict[str, float] = field(default_factory=dict)  # mole (or mass) fractions by species
    molar_flow: float | None = None
    mass_flow: float | None = None
    T: float | None = None          # temperature
    P: float | None = None          # pressure
    vapor_fraction: float | None = None
    enthalpy: float | None = None

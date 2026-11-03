"""Stream state: the conditions a balance engine may record."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class State:
    """Composition and conditions at a point in the flowsheet.

    Attributes
    ----------
    components : dict[str, float]
        Mole or mass fraction by species.
    molar_flow, mass_flow : float or None
        Flow rates.
    T : float or None
        Temperature.
    P : float or None
        Pressure.
    vapor_fraction : float or None
        Vapour fraction.
    enthalpy : float or None
        Enthalpy.
    """

    components: dict[str, float] = field(default_factory=dict)
    molar_flow: float | None = None
    mass_flow: float | None = None
    T: float | None = None
    P: float | None = None
    vapor_fraction: float | None = None
    enthalpy: float | None = None

"""Component: an entry in a flowsheet's chemical-species registry.

Carries no thermophysical data yet; a future mass/energy balance backend
attaches property calculations here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Component:
    name: str
    formula: str | None = None

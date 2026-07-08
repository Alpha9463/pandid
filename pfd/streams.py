"""Stream — a connection from one outlet Port to one inlet Port.

`kind` is "material" or "energy". `is_recycle` is COMPUTED later by the layout
engine's cycle-detection phase and must never be set by API callers. `tear_hint`
lets a caller nudge which stream is chosen as a tear/back-edge in ambiguous
cycles; it is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.ports import Port


@dataclass
class Stream:
    name: str
    source: Port
    dest: Port
    kind: str = "material"
    is_recycle: bool = False
    tear_hint: bool = False

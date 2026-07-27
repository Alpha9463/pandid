from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

class Renderer(Protocol):
    """Protocol for a render backend: turns a laid-out flowsheet into a
    serialized drawing (an SVG string today; a future WebRenderer could return
    its own markup). File I/O and format selection live in ``Flowsheet.render``.
    """
    def render(self, fs: "Flowsheet", **opts) -> str:
        ...

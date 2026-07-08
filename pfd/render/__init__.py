from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

class Renderer(Protocol):
    """Protocol for rendering a flowsheet to a file."""
    def render(self, fs: "Flowsheet", path: str, **opts) -> None:
        ...

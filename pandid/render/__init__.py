"""Render backends for laid-out flowsheets: SVG and draw.io."""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

# Project URL written into every rendered file. Stated here because a source
# checkout has no distribution metadata to read it from.
HOMEPAGE = "https://github.com/Alpha9463/pandid"


def generator() -> str:
    """Return the generator string written into rendered files.

    The SVG writes it into a comment and ``dc:creator``, draw.io into
    ``mxfile/@agent``. It reads ``__version__`` at call time, so tests can
    change the version and check that goldens do not move.

    Returns
    -------
    str
        ``"pandid <version>"``.
    """
    from pandid import __version__
    return f"pandid {__version__}"


class Renderer(Protocol):
    """Protocol for a render backend.

    A backend turns a laid-out flowsheet into a serialized drawing. File
    I/O and format selection belong to ``Flowsheet.render``.
    """
    def render(self, fs: "Flowsheet", **opts) -> str:
        """Return the drawing for a laid-out flowsheet.

        Parameters
        ----------
        fs : Flowsheet
            Laid-out and routed flowsheet.
        **opts
            Backend options.

        Returns
        -------
        str
            Serialized drawing.
        """
        ...

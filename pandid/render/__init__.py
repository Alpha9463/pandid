from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

# Where the project lives, written into every file it renders. Kept beside
# :func:`generator` rather than read out of the installed distribution's
# metadata, because a source checkout has no distribution metadata to read and
# a sheet drawn from one should still say where the code came from.
HOMEPAGE = "https://github.com/Alpha9463/pandid"


def generator() -> str:
    """What drew this file: the package name and the version that drew it.

    Both backends write this -- the SVG into a comment and a ``dc:creator``, the
    draw.io export into ``mxfile/@agent`` -- so it is composed once here rather
    than formatted the same way twice.

    A *function* and not a module constant, deliberately. A constant would
    capture ``__version__`` at import time, which is the one moment a test
    cannot get in front of: proving that a version bump does not move the
    goldens means setting ``pandid.__version__`` and rendering, and that only
    works if the string is read when the render happens.

    The import is local for the same reason it is safe either way: ``pandid``
    assigns ``__version__`` before it imports anything, so even a caller that
    reached here through a partially initialised package would find it.
    """
    from pandid import __version__
    return f"pandid {__version__}"


class Renderer(Protocol):
    """Protocol for a render backend: turns a laid-out flowsheet into a
    serialized drawing (an SVG string today; a future WebRenderer could return
    its own markup). File I/O and format selection live in ``Flowsheet.render``.
    """
    def render(self, fs: "Flowsheet", **opts) -> str:
        ...

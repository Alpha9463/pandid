"""Line widths for drawn elements, as multiples of the grid module.

Every stroke either backend draws takes its width from
:class:`LineWeight` (ISO 15519-1 6.2).
"""

import enum

#: The grid module M, 2.5 mm, in drawing units of 0.25 mm.
M = 10.0


class LineWeight(enum.Enum):
    """Line-weight class of a drawn element, with its width.

    ``MAIN_FLOW``
        Every material run.

    ``EQUIPMENT``
        Symbol outlines, block and splitter frames, and off-page flags.

    ``DETAIL``
        Trimmed symbols (:attr:`~.symbols.Symbol.trim`), control and
        data lines, instrument taps, flange marks, :mod:`~.iso_parts`
        parts and line-number leaders.

    ``MAIN_FLOW`` and ``EQUIPMENT`` are 0.2 M wide and ``DETAIL`` 0.1 M
    (ISO 15519-1 6.2 Table 1). Widths are in :data:`_MODULES`.
    """

    MAIN_FLOW = "main flow"
    EQUIPMENT = "equipment"
    DETAIL = "detail"

    @property
    def modules(self) -> float:
        """Return this class's width as a multiple of :data:`M`."""
        return _MODULES[self]

    @property
    def width(self) -> float:
        """Return this class's width in drawing units."""
        return self.modules * M


# Each class's width as a multiple of M.
_MODULES: "dict[LineWeight, float]" = {
    LineWeight.MAIN_FLOW: 0.2,
    LineWeight.EQUIPMENT: 0.2,
    LineWeight.DETAIL: 0.1,
}

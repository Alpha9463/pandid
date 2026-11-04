"""Line-weight classes and their widths in drawing units."""

import enum

#: The grid module M, 2.5 mm, in drawing units of 0.25 mm.
M = 10.0


class LineWeight(enum.Enum):
    """Line-weight class of a drawn element (ISO 15519-1 6.2).

    Attributes
    ----------
    MAIN_FLOW : LineWeight
        Material runs; 0.2 M wide.
    EQUIPMENT : LineWeight
        Symbol outlines, frames and off-page flags; 0.2 M wide.
    DETAIL : LineWeight
        Trim symbols, signal lines, taps and leaders; 0.1 M wide.
    """

    MAIN_FLOW = "main flow"
    EQUIPMENT = "equipment"
    DETAIL = "detail"

    @property
    def width(self) -> float:
        """Return this class's width in drawing units.

        Returns
        -------
        float
            Width in drawing units.
        """
        return _MODULES[self] * M


# Each class's width as a multiple of M.
_MODULES: "dict[LineWeight, float]" = {
    LineWeight.MAIN_FLOW: 0.2,
    LineWeight.EQUIPMENT: 0.2,
    LineWeight.DETAIL: 0.1,
}

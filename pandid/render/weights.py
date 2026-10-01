"""Line widths for drawn elements, as multiples of the grid module.

ISO 15519-1 6.2 states process-drawing line widths as multiples of the
grid module M. This module defines M, the three classes a drawn element
belongs to (:class:`LineWeight`) and their widths in drawing units.

It imports nothing from pandid, so ``svg``, ``drawio``, ``symbols``,
``iso_parts`` and ``furniture`` can all read widths from one place. Every
stroke either backend emits names a :class:`LineWeight` member;
``tests/test_line_weight.py`` fails on a numeric literal in a
``stroke-width`` or ``strokeWidth``.

Not covered: sheet furniture (border, zone ticks, frame, title strip,
tables and boxes), which ISO 10628-1 5.3.1 does not reach and which
``furniture`` rules itself; the unissued debug overlay; and the paths
inside symbol artwork, which state their own widths and are compensated
at render time. For a symbol the ladder sets only the class of its
outline (``EQUIPMENT`` or ``DETAIL``).
"""

import enum

#: The grid module, in drawing units: ISO 14617-1 4.3's 2.5 mm grid as
#: ISO 10628-1 5.3.1 sets it for a flow diagram, so one unit is 0.25 mm.
M = 10.0


class LineWeight(enum.Enum):
    """Line-weight class of a drawn element, with its width.

    ``MAIN_FLOW``
        Every material run.

    ``EQUIPMENT``
        Symbol outlines, block and splitter frames, and off-page flags.

    ``DETAIL``
        Trimmed symbols (:attr:`~.symbols.Symbol.trim`), control and data
        lines, instrument taps, flange marks, :mod:`~.iso_parts` parts and
        line-number leaders.

    ISO 15519-1 6.2 Table 1 gives the process row widths of 0.1 M and
    0.2 M, with 0.4 M optional. ``MAIN_FLOW`` and ``EQUIPMENT`` take 0.2 M
    and ``DETAIL`` 0.1 M, the 2:1 ratio 6.2 asks for, so a run matches the
    vessel it enters. The optional 0.4 M is not used: pandid symbols are
    much smaller than issued equipment drawings, so a 0.4 M run would look
    like a heavy bar against its equipment. ``DETAIL`` is the 5.3.1
    minimum.

    ``MAIN_FLOW`` stays separate from ``EQUIPMENT`` although the widths
    match, so the class decision is recorded and can diverge later (for
    subsidiary flow or energy lines; see :func:`~.svg._stream_rung`). Dash
    patterns (5.3.5) are a separate property.

    Member values are names, since equal values would merge members;
    widths are in :data:`_MODULES`.
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
        """Return this class's width in drawing units.

        2, 2 and 1 units, which is 0.5, 0.5 and 0.25 mm at unit scale. A
        fixed ``page_size`` scales the whole drawing uniformly
        (``svg.SvgRenderer._fit``), keeping the ratios; a sheet scaled down
        far enough takes ``DETAIL`` below the 5.3.1 minimum, which nothing
        checks.
        """
        return self.modules * M


# Each class's multiple of M, kept outside the enum because equal member
# values would merge MAIN_FLOW and EQUIPMENT.
_MODULES: "dict[LineWeight, float]" = {
    LineWeight.MAIN_FLOW: 0.2,
    LineWeight.EQUIPMENT: 0.2,
    LineWeight.DETAIL: 0.1,
}

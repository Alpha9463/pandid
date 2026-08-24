"""The line widths a sheet is drawn in, and nothing else.

ISO 10628-1 5.3.1 gives three widths, each as a multiple of the grid
module M. That is the whole of this module: the module, the three rungs
as their multiples of it, and the width each rung comes out at in
drawing units.

**Why a module of its own, and a leaf one.** Five files draw: ``svg``,
``drawio``, ``symbols``, ``iso_parts`` and ``furniture``. ``svg``
imports ``symbols``, ``drawio`` imports both, and ``iso_parts`` imported
nothing at all -- so there was no existing file all five could read a
width from, and the widths were written down four times instead
(``svg._PROCESS_STROKE`` and ``svg._EQUIPMENT_STROKE``, a hand copy of
the second in ``drawio``, ``iso_parts.PART_STROKE``, and a bare ``2 *
2.0`` in ``symbols``). Two of those had already disagreed with 5.3.1;
one of them is #490. This file imports nothing of pandid's, so every
drawing file can read it and none of them needs a copy.

**The ladder is the only way to state a width.** :class:`LineWeight` has
three members and no fourth, and every stroke either backend emits names
one of them. A drawn element added later therefore cannot be given a
width without first being put in a class -- which is the decision 5.3.1
actually asks an implementer to make, and the one that was skipped when
a main flow line and the vessel it enters were both simply written
``2``. ``tests/test_line_weight.py`` holds both renderers to it by
reading the source: a numeric literal in a ``stroke-width`` or a
``strokeWidth`` is a test failure, so the enum cannot be routed around.

**What is not on the ladder.** Sheet furniture -- the border, the zone
ticks, the drawing frame, the title strip, the stream table and the
notes and legend boxes -- is not part of the flow diagram, and 5.3.1
does not reach it; ``furniture`` keeps its own rules. The debugging
overlay (``debug``) is not issued and is not drawn on any sheet that
is. Symbol *artwork* states its own widths inside each stencil and is
compensated at render time, which is #305's arrangement and unchanged
here: what the ladder settles for a symbol is the class its outline is
drawn in (:data:`LineWeight.EQUIPMENT` or :data:`LineWeight.DETAIL`),
not the weight of each path inside the drawing.
"""

import enum

#: The grid module, in pandid drawing units.
#:
#: ISO 14617-1 4.3's dotted grid, at the 2,5 mm ISO 10628-1 5.3.1 gives
#: it for a flow diagram. One unit is therefore 0,25 mm exactly, which
#: is what makes :class:`LineWeight` below a set of physical widths
#: rather than a set of relative ones -- see :attr:`LineWeight.width`.
#:
#: Lived in ``iso_parts`` until #490, where it sized the Table 2 artwork
#: and nothing else. It is the sheet's module and not that module's, and
#: the widths are stated against it, so it moved here and ``iso_parts``
#: reads it from here.
M = 10.0


class LineWeight(enum.Enum):
    """The three widths of ISO 10628-1 5.3.1, as multiples of :data:`M`.

    One member per class the clause distinguishes, named for what a
    rung means rather than for how heavy it is, so that putting an
    element on one is a statement about the element. What pandid draws
    on each:

    ``MAIN_FLOW``
        5.3.1 a), 0,4 M. Every material run.

    ``EQUIPMENT``
        5.3.1 b), 0,2 M. Symbol outlines, the frames a block or a
        splitter draws, and the off-page flags.

    ``DETAIL``
        5.3.1 c), 0,1 M. Trimmed symbols
        (:attr:`~.symbols.Symbol.trim`), control and data lines,
        instrument taps, flange marks, the parts in
        :mod:`~.iso_parts`, and the leader a line number is written on.

    The ratio between them is 4:2:1 and it is the point of the ladder,
    not a by-product: the value of each member is its own multiple of
    the module, so no rung can be moved without the arithmetic moving
    with it. Every neighbouring pair stands at the 2:1 ISO 15519-1 6.2
    asks of two widths on one drawing.

    ``DETAIL`` is also 5.3.1's floor, and there is no member under it to
    pick.

    **Where 15519-1 and 10628-1 differ, 10628-1 wins.** 15519-1 6.2
    Table 1 gives the process-industry row 0,1 M, 0,2 M and a
    parenthesised 0,4 M without splitting the symbols; 10628-1 1
    declares itself a collective application standard of 15519 for
    exactly the documents this library draws, and its 5.3.1 makes the
    split. That is the reading followed here, and it is why an equipment
    outline is ``EQUIPMENT`` and not ``DETAIL``.

    **The energy rung is already here.** #489 adds energy streams, and
    5.3.1 b) is the rung they belong on: ``LineWeight.EQUIPMENT``, with
    no new member and no arithmetic -- one branch in
    :func:`~.svg._stream_rung`. Whether such a line is *dashed* is
    5.3.5's question and not this file's; a width and a dash pattern are
    separate properties of a line, and nothing here couples them.
    """

    MAIN_FLOW = 0.4
    EQUIPMENT = 0.2
    DETAIL = 0.1

    @property
    def width(self) -> float:
        """The width this rung is drawn at, in drawing units.

        The member's multiple of :data:`M`, so 4, 2 and 1 units -- and,
        since a unit is 0,25 mm, the 1,0 mm, 0,5 mm and 0,25 mm 5.3.1
        gives beside the multiples.

        A drawing unit is not a millimetre on every issued sheet: a
        fixed ``page_size`` fits the whole drawing under one uniform
        scale (``svg.SvgRenderer._fit``), which moves every pen on it
        together. The ratio therefore survives any sheet size and the
        millimetre reading holds at unit scale; a sheet fitted *down*
        far enough carries its ``DETAIL`` rung below the 5.3.1 floor in
        physical terms, and nothing here or anywhere else in the package
        checks that.
        """
        return self.value * M

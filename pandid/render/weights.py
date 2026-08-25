"""The line widths a sheet is drawn in, and nothing else.

ISO 15519-1 6.2 gives a process drawing its widths as multiples of the
grid module M. That is the whole of this module: the module, the three
classes a drawn element can be put in, and the width each comes out at
in drawing units.

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
width without first being put in a class -- which is the decision the
clause actually asks an implementer to make, and the one that was
skipped when a main flow line and the vessel it enters were both simply
written ``2``. That two of the three classes then *resolve* to one
width is a separate question, settled in :class:`LineWeight`; naming the
class is required either way, which is what keeps the answer changeable
in one place. ``tests/test_line_weight.py`` holds both renderers to it
by reading the source: a numeric literal in a ``stroke-width`` or a
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
    """The classes a drawn element is put in, and the width of each.

    One member per class, named for what a rung *means* rather than for
    how heavy it is, so that putting an element on one is a statement
    about the element. What pandid draws on each:

    ``MAIN_FLOW``
        Every material run.

    ``EQUIPMENT``
        Symbol outlines, the frames a block or a splitter draws, and the
        off-page flags.

    ``DETAIL``
        Trimmed symbols (:attr:`~.symbols.Symbol.trim`), control and
        data lines, instrument taps, flange marks, the parts in
        :mod:`~.iso_parts`, and the leader a line number is written on.

    **Two widths across three classes.** ISO 15519-1 6.2 Table 1 gives
    the process-industry row two widths outright, 0,1 M and 0,2 M, and a
    third of 0,4 M *in parentheses* -- offered, not required.
    ``MAIN_FLOW`` and ``EQUIPMENT`` both take 0,2 M and ``DETAIL`` takes
    0,1 M, so the sheet stands at the 2:1 6.2 asks of any two widths on
    one drawing, and a run is drawn at the weight of the vessel it
    enters. That is what a process drawing office rules and what the
    shipped sheets look like.

    **Why the parenthesised rung is not taken.** #502 read ISO 10628-1
    5.3.1 as splitting a) from b) and gave a material run 0,4 M -- twice
    the equipment. On paper the clause supports it; on the sheet it does
    not survive, because 5.3.1's widths are absolute and this library's
    symbols are not drawn at the size the clause assumes. A pandid
    symbol spans about six grid modules (median of the registry; the
    largest reach twenty), where an issued drawing's equipment spans far
    more. At 0,4 M a run therefore came out at 1:15 against the symbol
    it entered, where an issued sheet rules about 1:60 -- so the runs
    read as heavy black bars against hairline plant. The ratio a reader
    actually sees is the one between the ink on the page, and the only
    rung that puts it where a drawing office puts it is 0,2 M.

    ``DETAIL`` is 5.3.1's floor, and there is no member under it to
    pick.

    **Three classes and not two, though two of them share a width.**
    The class is the decision 5.3.1 asks an implementer to make and the
    one that was skipped when a run and a vessel were both simply
    written ``2``; keeping ``MAIN_FLOW`` distinct is what holds that
    decision in the code, and is the seam the two open issues attach
    to -- #497's subsidiary flow lines and #489's energy carriers, which
    is one branch in :func:`~.svg._stream_rung` and no new member.
    Whether such a line is *dashed* is 5.3.5's question and not this
    file's; a width and a dash pattern are separate properties of a
    line, and nothing here couples them.

    The value of a member is a name and carries no arithmetic, because
    two of the three would otherwise collide and Python would fold them
    into one member. The widths are :data:`_MODULES`.
    """

    MAIN_FLOW = "main flow"
    EQUIPMENT = "equipment"
    DETAIL = "detail"

    @property
    def modules(self) -> float:
        """This rung's width as its multiple of :data:`M`."""
        return _MODULES[self]

    @property
    def width(self) -> float:
        """The width this rung is drawn at, in drawing units.

        The member's multiple of :data:`M`, so 2, 2 and 1 units -- and,
        since a unit is 0,25 mm, 0,5 mm on the first two and 0,25 mm on
        the third.

        A drawing unit is not a millimetre on every issued sheet: a
        fixed ``page_size`` fits the whole drawing under one uniform
        scale (``svg.SvgRenderer._fit``), which moves every pen on it
        together. The ratio therefore survives any sheet size and the
        millimetre reading holds at unit scale; a sheet fitted *down*
        far enough carries its ``DETAIL`` rung below the 5.3.1 floor in
        physical terms, and nothing here or anywhere else in the package
        checks that.
        """
        return self.modules * M


#: Each rung's multiple of :data:`M`. Held beside the enum rather than
#: as the member values because ``MAIN_FLOW`` and ``EQUIPMENT`` draw at
#: one width, and two members of an ``Enum`` sharing a value become one
#: member with two names -- which would erase the class distinction the
#: ladder exists to make.
_MODULES: "dict[LineWeight, float]" = {
    LineWeight.MAIN_FLOW: 0.2,
    LineWeight.EQUIPMENT: 0.2,
    LineWeight.DETAIL: 0.1,
}

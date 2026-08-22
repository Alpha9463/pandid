"""The generic ``Block``: the one symbol a block flow diagram is drawn from.

A block is unlike every other kind here in one way that all of these tests turn
on: its drawing is not authored in advance. The count on each face is the
author's, so the symbol is *built* from the unit, and the box is sized to what
it has to hold rather than the connections being squeezed into a box drawn for
some other count. So the invariants the shipped registry is held to --
``tests/test_symbol_invariants.py`` -- reach only the one shape a ``Block``
asked for by name is drawn in, and every other shape is checked here.
"""

from __future__ import annotations

import math

import pytest

from pandid import Flowsheet, units
from pandid.portgeom import port_faces, port_point, resolve_size
from pandid.ports import Port
from pandid.render.symbols import (
    ARROWHEAD,
    BLOCK_MIN_HEIGHT,
    BLOCK_MIN_WIDTH,
    BLOCK_PITCH,
    PortSeries,
    block_span,
    default_registry,
    spread,
)

FACES = ("N", "S", "E", "W")


def _outline(sym):
    """The rectangle a block is drawn as, as four segments."""
    corners = [(0.0, 0.0), (sym.width, 0.0), (sym.width, sym.height), (0.0, sym.height)]
    return list(zip(corners, corners[1:] + corners[:1]))


def _distance(p, segments):
    px, py = p
    best = math.inf
    for (ax, ay), (bx, by) in segments:
        dx, dy = bx - ax, by - ay
        t = 0.0
        if dx or dy:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


# ---------------------------------------------------------------------------
# The declaration: a count, or a face per connection.
# ---------------------------------------------------------------------------


def test_a_block_asked_for_by_name_is_one_line_through_a_box():
    """The archetype: a section with a feed on the left and a product on the right."""
    b = units.Block("Reaction")
    assert list(b.ports) == ["in_1", "out_1"]
    assert b.input_faces == ("W",)
    assert b.output_faces == ("E",)
    assert b.in_1.direction == "inlet"
    assert b.out_1.direction == "outlet"


def test_a_count_puts_every_connection_on_the_face_its_kind_defaults_to():
    b = units.Block("Reaction", inputs=3, outputs=2)
    assert list(b.ports) == ["in_1", "in_2", "in_3", "out_1", "out_2"]
    assert b.input_faces == ("W", "W", "W")
    assert b.output_faces == ("E", "E")


def test_a_face_list_names_one_face_per_connection_in_order():
    b = units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"])
    assert b.input_faces == ("W", "W", "N")
    assert b.output_faces == ("E", "S")
    assert b.face("in_3") == "N"
    assert b.face("out_2") == "S"


def test_the_face_takes_every_spelling_nozzle_takes():
    """One vocabulary for "the top of this block", whichever call states it."""
    b = units.Block("B", inputs=["top", "bottom", "left", "right"], outputs=["n", "s"])
    assert b.input_faces == ("N", "S", "W", "E")
    assert b.output_faces == ("N", "S")


def test_a_block_may_be_all_source_or_all_sink():
    """A section at the edge of a sheet, drawn with nothing arriving at it."""
    assert units.Block("Import", inputs=0, outputs=2).input_faces == ()
    assert units.Block("Export", inputs=2, outputs=0).output_faces == ()


def test_a_block_with_no_connections_at_all_is_refused():
    with pytest.raises(ValueError, match="rectangle with a word in it"):
        units.Block("Nothing", inputs=0, outputs=0)


@pytest.mark.parametrize("bad", ["W", "WN", 1.5, None, True, ["W", "Q"], ["W", 2]])
def test_a_declaration_that_is_neither_a_count_nor_faces_is_refused(bad):
    """A bare string is the one worth naming: ``inputs="W"`` is a sequence of one
    face and would read as exactly what was meant, right up until ``"WN"``."""
    with pytest.raises(ValueError):
        units.Block("B", inputs=bad)


def test_a_negative_count_is_refused():
    with pytest.raises(ValueError, match="cannot be negative"):
        units.Block("B", inputs=-1)


def test_the_connections_and_the_faces_they_are_on_are_two_different_accessors():
    """``inlets`` is the ports; ``input_faces`` is the compass letters.

    The rename this pair exists for. ``b.inputs`` returned ``['W', 'W', 'N']``,
    and any reader of that name expects the connections themselves. ``Block``
    was unreleased, so the two are now named for what they return, and the
    constructor keeps ``inputs=`` because "the inputs are on these faces" is
    what the argument says.
    """
    b = units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"])
    assert [p.name for p in b.inlets] == ["in_1", "in_2", "in_3"]
    assert [p.name for p in b.outlets] == ["out_1", "out_2"]
    assert b.input_faces == ("W", "W", "N")
    assert b.output_faces == ("E", "S")
    assert b.inlets[2] is b.in_3
    assert all(p is b.ports[p.name] for p in (*b.inlets, *b.outlets))


def test_a_moved_connection_keeps_its_place_in_the_family_and_changes_its_face():
    """Two accessors, one record. ``nozzle()`` rewrites the declaration, so the
    face moves and the family does not: the whole reason a block's connections
    are numbered across the family rather than per face is that moving one never
    renames it."""
    b = units.Block("B", inputs=1, outputs=2).nozzle("out_2", "S")
    assert [p.name for p in b.outlets] == ["out_1", "out_2"]
    assert b.output_faces == ("E", "S")


def test_a_block_with_nothing_arriving_has_an_empty_inlet_family():
    """``()`` and not ``None``: a section at the edge of a sheet is a legitimate
    thing to draw, and a caller iterating its inlets should get no iterations
    rather than a ``TypeError``."""
    edge = units.Block("Import", inputs=0, outputs=2)
    assert edge.inlets == ()
    assert [p.name for p in edge.outlets] == ["out_1", "out_2"]
    assert list(edge.inlets) == []


def test_a_block_declares_no_variants_and_owns_its_whole_kind():
    """No device subclass: a block is a block, and there is nothing about a
    section of plant for a second drawing to say."""
    assert units.Block.VARIANTS == ()
    assert units.Block._generic_class() is units.Block
    assert default_registry.variants("block") == ["default"]


# ---------------------------------------------------------------------------
# The box sizes itself to what it carries.
# ---------------------------------------------------------------------------


def test_the_pitch_is_measured_off_the_arrowhead_the_renderer_draws():
    """Not a guessed constant. The renderer emits the head at
    ``markerUnits="userSpaceOnUse"``, so its ``markerWidth`` is its real size on
    the sheet, and this reads that back out of a rendered sheet rather than
    trusting the two to have stayed in step."""
    fs = Flowsheet("one line")
    f = fs.add(units.Feed("F"))
    p = fs.add(units.Product("P"))
    fs.connect(f.outlet, p.inlet)
    svg = fs.to_svg()
    assert f'markerWidth="{ARROWHEAD:g}" markerHeight="{ARROWHEAD:g}"' in svg
    assert BLOCK_PITCH == 2.5 * ARROWHEAD


def test_a_default_block_is_drawn_at_the_registered_size():
    """The registry answers for a ``(kind, variant)``, and what it answers for a
    block has to be the drawing a ``Block("X")`` really gets -- that is what lets
    the shared symbol-invariant suite measure a block at all."""
    registered = default_registry.get("block")
    assert (registered.width, registered.height) == (BLOCK_MIN_WIDTH, BLOCK_MIN_HEIGHT)
    assert units.Block("X").symbol().ports == registered.ports
    assert units.Block("X").symbol().svg == registered.svg


@pytest.mark.parametrize("count", range(1, 13))
@pytest.mark.parametrize("face", FACES)
def test_the_box_grows_so_a_run_of_connections_keeps_its_pitch(count, face):
    """The whole point. ``PortSeries`` squeezes a family that runs out of room,
    which is right for a mixer -- its triangle is a piece of plant drawn at the
    size a mixer is drawn at -- and wrong for a block, whose box means nothing
    and so has nothing to trade against legibility."""
    b = units.Block("B", inputs=[face] * count, outputs=0)
    sym = b.symbol()
    along = sym.height if face in ("W", "E") else sym.width
    assert along >= block_span(count)
    points = [sym.ports[f"in_{i}"] for i in range(1, count + 1)]
    axis = 1 if face in ("W", "E") else 0
    gaps = [b[axis] - a[axis] for a, b in zip(points, points[1:])]
    assert all(gap == pytest.approx(BLOCK_PITCH) for gap in gaps)


def test_eight_inputs_over_two_faces_makes_a_bigger_block_not_a_crushed_one():
    """The case a block flow diagram is actually for: one box gathering many
    streams. Five on one wall and three on another, each still a pitch apart."""
    b = units.Block("Utilities", inputs=["W"] * 5 + ["N"] * 3, outputs=["E"] * 2 + ["S"] * 2)
    sym = b.symbol()
    assert sym.height == block_span(5)
    assert sym.width >= block_span(3)
    assert sym.coincident_ports() == []


def test_a_lone_connection_sits_in_the_middle_of_its_face():
    """One in and one out is the commonest block there is, and a nozzle a quarter
    of the way down its wall would step every stream on a BFD down the sheet."""
    sym = units.Block("B").symbol()
    assert sym.ports["in_1"] == (0.0, sym.height / 2)
    assert sym.ports["out_1"] == (sym.width, sym.height / 2)


def test_the_box_clears_the_name_it_letters_inside_itself():
    short = units.Block("R").symbol()
    long = units.Block("Product Recovery and Refrigeration").symbol()
    assert short.width == BLOCK_MIN_WIDTH
    assert long.width > short.width
    assert long.label_pos == "center"


def test_a_width_the_author_gave_wins_over_the_name():
    """An explicit width is the author's answer to the same question, as
    ``resolve_size`` has it everywhere else. It is also what keeps one port
    layout to one drawing however the block is named."""
    named = units.Block("Product Recovery and Refrigeration", width=140)
    assert named.symbol().width == BLOCK_MIN_WIDTH  # the artwork, before the box
    assert resolve_size(named) == (140, BLOCK_MIN_HEIGHT)


# ---------------------------------------------------------------------------
# ...and refuses a box that cannot hold them.
# ---------------------------------------------------------------------------


def test_a_box_too_small_for_its_connections_is_refused_at_construction():
    with pytest.raises(ValueError, match=r"4 connections on the W face"):
        units.Block("B", inputs=4, height=60)


def test_the_refusal_says_what_to_give_instead():
    with pytest.raises(ValueError) as excinfo:
        units.Block("B", inputs=4, height=60)
    message = str(excinfo.value)
    assert f"{ARROWHEAD:g}-unit arrowheads" in message
    assert "height=120" in message  # 4 x the pitch


def test_a_box_big_enough_is_taken_and_spreads_the_run_wider():
    """The artwork is stretched into the box, so a taller box than the block
    sized itself to opens the run out rather than leaving it bunched."""
    b = units.Block("B", inputs=3, height=300)
    frame = _frame(b)
    y = [port_point(b, frame, f"in_{i}")[1] for i in (1, 2, 3)]
    assert all(hi - lo >= BLOCK_PITCH for lo, hi in zip(y, y[1:]))


def test_one_connection_on_a_face_has_no_spacing_to_crush():
    """The three extreme box shapes the invariant suite forces every symbol into
    are all smaller than a block on one axis, and a lone nozzle in a short box is
    not a defect -- there is nothing for it to be too close to."""
    for box in ((300.0, 60.0), (60.0, 300.0), (140.0, 140.0)):
        units.Block("B", width=box[0], height=box[1])


def test_a_box_shrunk_after_construction_is_refused_where_it_is_set():
    """The size and the drawing are one question here, so ``width``/``height``
    are properties and a size the drawing cannot be made at is refused on the
    assignment -- the guard ``Conveyor.length`` has, for the same reason."""
    b = units.Block("B", inputs=4)
    with pytest.raises(ValueError, match="4 connections on the W face"):
        b.height = 60
    assert b.height is None


@pytest.mark.parametrize("box", [(60.0, 150.0), (120.0, 150.0)])
def test_a_quarter_turn_cannot_smuggle_a_crushed_run_past_the_guard(box):
    """The reported hole, and the reason the check goes through ``resolve_size``
    rather than comparing ``width``/``height`` in symbol axes.

    A turn draws the box's upright faces *across* the sheet while an explicit
    width/height stays the final box, so five inlets that fit the 150 height
    standing up were squeezed into the 60 width lying down: 12 apart, exactly
    one arrowhead, five heads touching."""
    b = units.Block("R", inputs=5, outputs=1, width=box[0], height=box[1])
    with pytest.raises(ValueError, match="turned a quarter"):
        b.pin(x=1000, y=140, orientation=90)
    assert b.pin_ is None  # ...and the refused placement was not committed


@pytest.mark.parametrize("placement", [{}, {"orientation": 90}, {"orientation": 270}])
@pytest.mark.parametrize("mirror", [{}, {"mirrored": "x"}, {"mirrored": "y"}])
def test_an_auto_sized_block_keeps_its_pitch_at_every_placement(placement, mirror):
    """Safe by construction, and this is what says so: ``resolve_size`` swaps
    the symbol's own axes with the turn, so the box and the artwork are the same
    shape however the block is placed."""
    fs = Flowsheet("turned")
    b = fs.add(units.Block("R", inputs=5, outputs=1)).pin(x=400, y=400, **placement, **mirror)
    fs.layout()
    points = [port_point(b, b.frame, f"in_{i}") for i in range(1, 6)]
    gaps = [math.dist(a, c) for a, c in zip(points, points[1:])]
    assert all(gap == pytest.approx(BLOCK_PITCH) for gap in gaps)


def test_a_turn_that_still_fits_is_allowed():
    """The guard is about the pitch, not about turning: a square-enough box
    holds the run either way up."""
    b = units.Block("R", inputs=5, outputs=1, width=200, height=200)
    b.pin(x=100, y=100, orientation=90)
    assert b.pin_.orientation == 90


# ---------------------------------------------------------------------------
# Every nozzle on drawn ink, on every face, at every count and box shape.
# ---------------------------------------------------------------------------

#: The same three shapes ``tests/test_symbol_invariants.py`` forces every symbol
#: into, and the same tolerance. One of them is the wrong shape for any block.
_ODD_BOXES = ((300.0, 300.0), (400.0, 160.0), (200.0, 400.0))
_GEOM_TOL = 2.0


@pytest.mark.parametrize("count", [1, 2, 5, 9])
def test_every_nozzle_lands_on_the_rectangle_at_every_count(count):
    b = units.Block("B", inputs=[f for f in FACES for _ in range(count)], outputs=0)
    sym = b.symbol()
    outline = _outline(sym)
    for name, point in sym.ports.items():
        assert _distance(point, outline) <= _GEOM_TOL, f"{name} at {point}"
    assert sym.coincident_ports() == []


@pytest.mark.parametrize("box", _ODD_BOXES)
@pytest.mark.parametrize(
    "placement", ({}, {"orientation": 90, "mirrored": "x"}, {"orientation": 270, "mirrored": "y"})
)
def test_every_nozzle_follows_the_artwork_into_a_box_of_any_shape(box, placement):
    """A block given a box of its own is drawn at that box, so this is where the
    artwork and the nozzles could drift apart. Measured against the *placed*
    rectangle read back off the frame, which is the box the renderer drew."""
    fs = Flowsheet("odd boxes")
    b = units.Block(
        "B", inputs=["W", "W", "N", "N"], outputs=["E", "S", "S"], width=box[0], height=box[1]
    )
    fs.add(b).pin(x=300, y=300, **placement)
    fs.layout()
    frame = b.frame
    corners = [
        (frame.x, frame.y),
        (frame.x + frame.w, frame.y),
        (frame.x + frame.w, frame.y + frame.h),
        (frame.x, frame.y + frame.h),
    ]
    placed = list(zip(corners, corners[1:] + corners[:1]))
    for name in b.ports:
        point = port_point(b, frame, name)
        assert _distance(point, placed) <= _GEOM_TOL, f"{name} at {point} in {box} {placement}"


def test_no_two_connections_ever_land_on_one_point():
    """Two nozzles at one coordinate stack two streams on one pixel. A block is
    the kind most exposed to it, since every one of its connections is placed by
    the same rule on one of only four faces."""
    for n in range(0, 6):
        for m in range(0, 6):
            if not n and not m:
                continue
            faces = [FACES[i % 4] for i in range(n)]
            outs = [FACES[(i + 1) % 4] for i in range(m)]
            sym = units.Block("B", inputs=faces, outputs=outs).symbol()
            assert sym.coincident_ports() == [], f"inputs={faces} outputs={outs}"
            assert len(set(sym.ports.values())) == n + m


def test_a_declared_face_is_the_boxs_own_side_and_a_turn_moves_it():
    """The documented divergence from ``Unit.nozzle``, pinned so it stays
    documented: ``face()`` answers about the box and ``port_faces()`` about the
    sheet, and a turned block is where the two part company."""
    fs = Flowsheet("turned")
    b = fs.add(units.Block("B", inputs=["N"], outputs=["E"])).pin(x=200, y=200, orientation=90)
    assert b.face("in_1") == "N"  # the side of the box it was declared on...
    assert port_faces(b, "in_1") == ["E"]  # ...and the side of the sheet drawn


def test_ports_on_answers_the_lookup_face_does_not():
    b = units.Block("B", inputs=["W", "N", "W"], outputs=["N"])
    assert [p.name for p in b.ports_on("W")] == ["in_1", "in_3"]
    assert [p.name for p in b.ports_on("top")] == ["in_2", "out_1"]
    assert b.ports_on("S") == ()
    with pytest.raises(ValueError, match="is not a face"):
        b.ports_on("sideways")


def test_ports_on_hands_back_the_ports_and_not_their_names():
    """The third way of asking for a family, and it answers in the same currency.

    Names would put a caller through ``[b.port(n) for n in b.ports_on("N")]`` --
    out to a string and back through the very dict ``inlets`` exists to spare
    them, under a name that says "ports". The same defect the ``inputs``
    rename fixes, in the same unreleased class.
    """
    b = units.Block("B", inputs=["W", "N", "W"], outputs=["N"])
    on_north = b.ports_on("N")
    assert isinstance(on_north, tuple)
    assert all(isinstance(p, Port) for p in on_north)
    assert on_north[0] is b.in_2
    # ...and the same ports the families hold, reached the other way round.
    assert all(p is b.ports[p.name] for p in on_north)
    # ``Port`` is an unhashable dataclass, so identity by hand rather than sets.
    assert all(any(p is q for q in b.inlets) for p in b.ports_on("W"))


def test_a_connection_is_offered_the_one_face_it_was_declared_with():
    """There is no menu, and that is the answer to the question the issue asked:
    a ``PortSeries`` names a single face, so a series member has exactly one
    placement and ``nozzle()`` cannot pick between placements that do not exist.
    A block does not need it to, because its face is a declaration."""
    b = units.Block("B", inputs=["W", "N"], outputs=["E"])
    assert port_faces(b, "in_1") == ["W"]
    assert port_faces(b, "in_2") == ["N"]
    assert port_faces(b, "out_1") == ["E"]


def test_a_series_member_really_does_offer_only_its_series_face():
    """The finding above, checked against the machinery it is a claim about: a
    Mixer's inlets are a ``PortSeries`` on the west, and no amount of asking
    moves one to the south."""
    m = units.Mixer("M-1", n_inlets=3)
    assert port_faces(m, "in_2") == ["W"]
    with pytest.raises(ValueError, match="can be piped from W as drawn"):
        m.nozzle("in_2", "S")


# ---------------------------------------------------------------------------
# nozzle(): moving a connection means changing the declaration.
# ---------------------------------------------------------------------------


def test_nozzle_moves_a_connection_and_the_ink_follows():
    b = units.Block("B", inputs=1, outputs=2)
    assert b.face("out_2") == "E"
    b.nozzle("out_2", "S")
    assert b.face("out_2") == "S"
    assert port_faces(b, "out_2") == ["S"]
    sym = b.symbol()
    assert sym.ports["out_2"] == (sym.width / 2, sym.height)


def test_nozzle_keeps_one_record_of_where_a_connection_is():
    """It writes the declaration, not ``Unit._port_faces``: the latter overrides
    a placement the symbol authored, and here the declaration *is* the placement.
    Two records would be two answers about one nozzle."""
    b = units.Block("B", inputs=1, outputs=1).nozzle("out_1", "top")
    assert b._port_faces == {}
    assert b.output_faces == ("N",)


def test_nozzle_still_refuses_a_face_that_is_not_one():
    with pytest.raises(ValueError, match="is not a face"):
        units.Block("B").nozzle("in_1", "up")


def test_nozzle_on_an_unknown_connection_names_the_ones_there_are():
    with pytest.raises(KeyError, match="in_1"):
        units.Block("B").nozzle("in_9", "N")


def test_a_move_that_would_crush_the_destination_face_leaves_the_block_alone():
    # Three on the west fit the 90 the block sized itself to; a fourth needs 120.
    b = units.Block("B", inputs=3, outputs=1, width=200, height=block_span(3))
    with pytest.raises(ValueError, match="4 connections on the W face"):
        b.nozzle("out_1", "W")
    assert b.face("out_1") == "E"
    assert port_faces(b, "out_1") == ["E"]


def test_the_layout_engine_never_moves_a_connection_off_its_declared_face():
    """A block's faces are the author's statement, and the face selector only
    ever chooses between placements a symbol offers more than one of."""
    fs = Flowsheet("faces")
    src = fs.add(units.Feed("F")).pin(x=100, y=600)
    b = fs.add(units.Block("B", inputs=["N"], outputs=["E"])).pin(x=400, y=300)
    fs.connect(src.outlet, b.in_1)
    fs.layout()
    assert b.frame.port_faces == {}
    assert port_point(b, b.frame, "in_1")[1] == b.frame.y


# ---------------------------------------------------------------------------
# order_on(): where a connection sits *along* the face it is on.
#
# The face says which wall; this says where on it. Without it a face carrying
# both kinds draws every input before every output, because ``_faces`` is filled
# inputs-first and ``block_symbol`` groups it in insertion order -- which made
# the ordinary BFD recycle (in on the side nearer its source) inexpressible.
# Issue #192; ``examples/12_block_flow_diagram.py`` is the sheet.
# ---------------------------------------------------------------------------


def _along(block, face):
    """Where each connection on ``face`` sits along it, in the drawn order."""
    sym = block.symbol()
    axis = 1 if face in ("W", "E") else 0
    return [(p.name, sym.ports[p.name][axis]) for p in block.ports_on(face)]


def test_the_declared_order_is_inputs_then_outputs_until_something_says_otherwise():
    """The default this exists to override, pinned so the override has a job."""
    b = units.Block("B", inputs=["W", "S"], outputs=["E", "S"])
    assert [name for name, _ in _along(b, "S")] == ["in_2", "out_2"]


def test_order_on_puts_the_connections_along_the_face_in_the_order_given():
    b = units.Block("B", inputs=["W", "S"], outputs=["E", "S"])
    assert b.order_on("S", [b.out_2, b.in_2]) is b  # chains, like pin() and nozzle()
    placed = _along(b, "S")
    assert [name for name, _ in placed] == ["out_2", "in_2"]
    # ...and it is the *drawing* that moved, not just the bookkeeping: first is
    # the low end of the face, and the two are still a full pitch apart.
    assert placed[0][1] < placed[1][1]
    assert placed[1][1] - placed[0][1] == pytest.approx(BLOCK_PITCH)


def test_order_on_is_ports_ons_writer_and_takes_what_it_hands_back():
    """The pair is worth having only if the two speak one currency, which is why
    this takes ports: reversing a wall is then one expression."""
    b = units.Block("B", inputs=["S", "S"], outputs=["S"])
    b.order_on("S", b.ports_on("S")[::-1])
    assert [p.name for p in b.ports_on("S")] == ["out_1", "in_2", "in_1"]
    assert [name for name, _ in _along(b, "S")] == ["out_1", "in_2", "in_1"]


@pytest.mark.parametrize("face", FACES)
def test_the_order_runs_the_way_the_family_is_numbered_on_every_face(face):
    """West first on N/S, north first on W/E -- the direction ``spread`` lays a
    family out in, so an ordered face reads like a declared one."""
    b = units.Block("B", inputs=[face, face], outputs=[face])
    b.order_on(face, [b.out_1, b.in_2, b.in_1])
    placed = _along(b, face)
    assert [name for name, _ in placed] == ["out_1", "in_2", "in_1"]
    assert [t for _, t in placed] == sorted(t for _, t in placed)


def test_three_or_more_on_a_face_are_placed_exactly_as_named():
    b = units.Block("B", inputs=["N", "N"], outputs=["N", "N"])
    b.order_on("N", [b.out_2, b.in_1, b.out_1, b.in_2])
    assert [name for name, _ in _along(b, "N")] == ["out_2", "in_1", "out_1", "in_2"]


def test_ordering_one_face_leaves_every_other_face_where_it_was():
    b = units.Block("B", inputs=["N", "S", "N"], outputs=["S", "N"])
    before = _along(b, "N")
    b.order_on("S", [b.out_1, b.in_2])
    assert _along(b, "N") == before


def test_the_order_is_the_boxs_own_and_a_mirror_moves_the_box_with_it():
    """The same contract the face itself has: ``order_on`` is a declaration, so
    it cannot be about a ``pin()`` that has not happened. A mirrored block draws
    the first member on the *right* of the sheet, and that is not a bug in the
    ordering -- it is the mirror doing what ``Block`` says a mirror does."""
    fs = Flowsheet("mirrored")
    b = fs.add(units.Block("B", inputs=["W", "S"], outputs=["E", "S"])).pin(x=400, y=300)
    b.order_on("S", [b.out_2, b.in_2])
    fs.layout()
    upright = {name: port_point(b, b.frame, name)[0] for name in ("out_2", "in_2")}
    assert upright["out_2"] < upright["in_2"]

    b.pin(mirrored=True)
    fs.layout()
    flipped = {name: port_point(b, b.frame, name)[0] for name in ("out_2", "in_2")}
    assert flipped["out_2"] > flipped["in_2"]
    # The declaration is untouched by the transform, which is what lets the two
    # be set in either order.
    assert [p.name for p in b.ports_on("S")] == ["out_2", "in_2"]


def test_the_order_survives_a_quarter_turn_onto_the_faces_it_draws_across():
    """A turn draws the south wall up the sheet's east side; the order the box
    declared is still the order along it."""
    fs = Flowsheet("turned")
    b = fs.add(units.Block("B", inputs=["S", "S"], outputs=["N"])).pin(x=400, y=300, orientation=90)
    b.order_on("S", [b.in_2, b.in_1])
    fs.layout()
    assert port_faces(b, "in_1") == ["W"]
    first, second = (port_point(b, b.frame, n)[1] for n in ("in_2", "in_1"))
    assert first < second


def test_a_connection_moved_onto_an_ordered_face_lands_in_declaration_order():
    """``nozzle`` says which side and nothing about where along it, so a late
    arrival takes its declared place rather than joining the end. Documented
    rather than special-cased: order the face once it has its members."""
    b = units.Block("B", inputs=["W", "S"], outputs=["E", "S"])
    b.order_on("S", [b.out_2, b.in_2])
    b.nozzle("in_1", "S")
    assert [p.name for p in b.ports_on("S")] == ["in_1", "out_2", "in_2"]
    b.order_on("S", [b.out_2, b.in_2, b.in_1])  # ...and saying so again is the fix
    assert [p.name for p in b.ports_on("S")] == ["out_2", "in_2", "in_1"]


def test_two_blocks_of_one_shape_ordered_differently_are_drawn_differently():
    """The symbol is cached on the faces tuple, which the order is part of, and
    the ``<defs>`` entry is keyed on the box -- so the two share one rectangle
    and keep their own nozzles, which is what both of those are for."""
    fs = Flowsheet("twins")
    a = fs.add(units.Block("A", inputs=["W", "S"], outputs=["E", "S"])).pin(x=200, y=200)
    b = fs.add(units.Block("B", inputs=["W", "S"], outputs=["E", "S"])).pin(x=600, y=200)
    b.order_on("S", [b.out_2, b.in_2])
    fs.layout()
    assert a.symbol().id_suffix == b.symbol().id_suffix
    assert fs.to_svg().count('<symbol id="sym_block_120x80"') == 1
    a_in, a_out = (port_point(a, a.frame, n)[0] for n in ("in_2", "out_2"))
    b_in, b_out = (port_point(b, b.frame, n)[0] for n in ("in_2", "out_2"))
    assert a_in < a_out and b_in > b_out


def test_a_face_ordered_twice_takes_the_last_word():
    """Idempotent and total, so the result does not depend on what came before."""
    b = units.Block("B", inputs=["S", "S"], outputs=["S"])
    b.order_on("S", [b.out_1, b.in_1, b.in_2])
    b.order_on("S", [b.in_2, b.out_1, b.in_1])
    assert [p.name for p in b.ports_on("S")] == ["in_2", "out_1", "in_1"]


# --- what it refuses, and what each refusal tells the author to do -----------


def test_naming_only_some_of_a_face_is_refused_and_prints_the_face_to_copy():
    b = units.Block("B", inputs=["S", "S"], outputs=["S"])
    with pytest.raises(ValueError, match=r"names 1 of the 3 .*leaves in_2, out_1 unplaced"):
        b.order_on("S", [b.in_1])
    assert [p.name for p in b.ports_on("S")] == ["in_1", "in_2", "out_1"]


def test_naming_one_connection_twice_is_refused():
    b = units.Block("B", inputs=["S"], outputs=["S"])
    with pytest.raises(ValueError, match="names 'in_1' twice"):
        b.order_on("S", [b.in_1, b.in_1])


def test_a_connection_on_another_face_names_the_nozzle_call_that_moves_it():
    b = units.Block("B", inputs=["W", "S"], outputs=["S"])
    with pytest.raises(ValueError, match=r"nozzle\('in_1', 'S'\)"):
        b.order_on("S", [b.in_1, b.in_2, b.out_1])


def test_another_units_port_is_refused_by_identity_and_not_by_name():
    """Both blocks have an ``in_1``; matching on the name would have quietly
    ordered this one's by the other one's port object."""
    b = units.Block("B", inputs=["S"], outputs=["S"])
    other = units.Block("Other", inputs=["S"], outputs=["S"])
    with pytest.raises(ValueError, match="is a connection of 'Other'"):
        b.order_on("S", [other.in_1, b.out_1])


def test_the_names_are_refused_and_the_message_points_at_the_ports():
    """A ``Sequence[Port]`` is what a checker can see through; strings are the
    spelling this API exists not to go back to."""
    b = units.Block("B", inputs=["S"], outputs=["S"])
    with pytest.raises(TypeError, match="takes the connections themselves"):
        b.order_on("S", ["out_1", "in_1"])


def test_order_on_still_refuses_a_face_that_is_not_one():
    b = units.Block("B", inputs=["S"], outputs=["S"])
    with pytest.raises(ValueError, match="is not a face"):
        b.order_on("sideways", [b.in_1, b.out_1])


def test_a_refused_ordering_leaves_the_drawing_exactly_as_it_was():
    b = units.Block("B", inputs=["S", "S"], outputs=["S"])
    before = _along(b, "S")
    for bad in ([b.in_2], [b.in_1, b.in_1, b.in_1], ["in_1", "in_2", "out_1"]):
        with pytest.raises((ValueError, TypeError)):
            b.order_on("S", bad)
    assert _along(b, "S") == before


def test_an_empty_face_has_nothing_to_order_and_says_so_by_doing_nothing():
    """``ports_on`` answers an empty face with ``()``; its writer takes ``()``."""
    b = units.Block("B", inputs=["W"], outputs=["E"])
    assert b.order_on("N", []) is b
    assert b.ports_on("N") == ()


def test_ordering_a_face_cannot_make_a_block_undrawable():
    """The one mutator that never re-checks the box, because it changes no
    face's count -- the box that held the run a moment ago still does."""
    b = units.Block("B", inputs=3, outputs=1, width=200, height=block_span(3))
    b.order_on("W", [b.in_3, b.in_1, b.in_2])
    assert [p.name for p in b.ports_on("W")] == ["in_3", "in_1", "in_2"]


# --- and it is written down, so a sheet read back is the sheet drawn ---------


def test_an_ordered_face_round_trips_through_a_spec():
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Loop", inputs=["W", "S"], outputs=["E", "S"]))
    b.order_on("S", [b.out_2, b.in_2])
    spec = to_dict(fs)
    (entry,) = [u for u in spec["units"] if u["kind"] == "Block"]
    assert entry["port_order"] == {"S": ["out_2", "in_2"]}

    read = from_dict(spec)
    assert [p.name for p in read.units[0].ports_on("S")] == ["out_2", "in_2"]
    assert to_dict(read) == spec


def test_a_block_nobody_reordered_writes_no_order_at_all():
    """The key is absent from every sheet until somebody asks for it, so an
    ordinary block's entry reads the way a hand-written one would."""
    from pandid.spec import to_dict

    fs = Flowsheet("bfd")
    fs.add(units.Block("Loop", inputs=["W", "S"], outputs=["E", "S"]))
    (entry,) = [u for u in to_dict(fs)["units"] if u["kind"] == "Block"]
    assert "port_order" not in entry


def test_only_a_block_or_a_tank_or_a_vessel_takes_an_order_and_a_bad_one_names_the_face():
    from pandid.spec import SpecError, from_dict

    with pytest.raises(SpecError, match="only a Block or a Tank or a Vessel takes 'port_order'"):
        from_dict({"name": "s", "units": [{"kind": "Pump", "name": "P-1", "port_order": {}}]})
    with pytest.raises(SpecError, match=r"port_order.S"):
        from_dict(
            {
                "name": "s",
                "units": [
                    {
                        "kind": "Block",
                        "name": "B",
                        "inputs": ["S"],
                        "outputs": ["S"],
                        "port_order": {"S": ["in_1"]},
                    }
                ],
            }
        )


# ---------------------------------------------------------------------------
# The spreading rule is shared, not reimplemented.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", range(1, 9))
@pytest.mark.parametrize("extent", [0.7, 1.0])
def test_a_port_series_spreads_its_members_with_the_shared_rule(count, extent):
    """``PortSeries.placement`` and ``block_symbol`` are one rule with two
    callers, so a mixer's inlets and a block's connections cannot drift apart."""
    series = PortSeries("in_", "W", pitch=20.0, extent=extent, at=None)
    for i in range(count):
        assert series.placement(i, count, 50.0, 96.0)[1] == pytest.approx(
            spread(i, count, 96.0, 20.0, extent)
        )


# ---------------------------------------------------------------------------
# The rest of the package.
# ---------------------------------------------------------------------------


def test_a_block_is_not_scheduled_equipment():
    """A BFD box stands for a whole section of plant, whose equipment list is a
    document of its own. Scheduling one would say that "Reaction" is a thing
    somebody buys."""
    from pandid.document import _MAJOR_EQUIPMENT, equipment_list

    assert "block" not in _MAJOR_EQUIPMENT
    fs = Flowsheet("bfd")
    fs.add(units.Block("Reaction"))
    fs.add(units.Pump("P-101"))
    assert [row[0] for row in equipment_list(fs).rows] == ["P-101"]
    # ...but an author who wants a block index can still ask for one by name.
    assert equipment_list(fs, include=["Reaction"]).rows == [("Reaction", "Process Block")]


def test_a_block_round_trips_through_a_spec():
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"]))
    feed = fs.add(units.Feed("NG"))
    out = fs.add(units.Product("Syngas"))
    fs.connect(feed.outlet, b.in_2)
    fs.connect(b.out_2, out.inlet)

    spec = to_dict(fs)
    (entry,) = [u for u in spec["units"] if u["kind"] == "Block"]
    assert entry["inputs"] == ["W", "W", "N"]
    assert entry["outputs"] == ["E", "S"]

    read = from_dict(spec)
    got = [u for u in read.units if isinstance(u, units.Block)][0]
    assert got.input_faces == b.input_faces
    assert got.output_faces == b.output_faces
    assert list(got.ports) == list(b.ports)
    assert to_dict(read) == spec


def test_a_connection_moved_by_nozzle_is_written_back_where_it_was_moved_to():
    """The single record earns its keep here: a spec writes the declaration, so
    a block read back is the block that was drawn and not the one first asked
    for."""
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("bfd")
    fs.add(units.Block("Reaction", inputs=1, outputs=2)).nozzle("out_2", "S")
    (entry,) = [u for u in to_dict(fs)["units"] if u["kind"] == "Block"]
    assert entry["outputs"] == ["E", "S"]
    assert "port_faces" not in entry
    assert from_dict(to_dict(fs)).units[0].face("out_2") == "S"


def test_a_source_only_block_survives_the_round_trip():
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("bfd")
    fs.add(units.Block("Import", inputs=0, outputs=["S", "E"]))
    read = from_dict(to_dict(fs))
    assert read.units[0].input_faces == ()
    assert read.units[0].output_faces == ("S", "E")


def test_a_spec_writes_the_bare_count_where_every_face_is_the_default():
    """The shorthand the constructor takes, so the file a sheet writes reads the
    way a hand-written one would."""
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("bfd")
    fs.add(units.Block("Reaction", inputs=3, outputs=1))
    (entry,) = [u for u in to_dict(fs)["units"] if u["kind"] == "Block"]
    assert entry["inputs"] == 3
    assert entry["outputs"] == 1
    assert from_dict(to_dict(fs)).units[0].input_faces == ("W", "W", "W")


def test_a_spec_may_name_the_faces_as_a_count_or_a_list():
    from pandid.spec import from_dict

    fs = from_dict(
        {
            "name": "bfd",
            "units": [{"kind": "Block", "name": "R", "inputs": ["N", "W"], "outputs": 2}],
        }
    )
    assert fs.units[0].input_faces == ("N", "W")
    assert fs.units[0].output_faces == ("E", "E")


def test_a_spec_refuses_connection_faces_on_anything_but_a_block_a_tank_or_a_vessel():
    from pandid.spec import SpecError, from_dict

    with pytest.raises(SpecError, match="only a Block or a Tank or a Vessel takes 'inputs'"):
        from_dict({"name": "x", "units": [{"kind": "Pump", "name": "P-1", "inputs": 2}]})


def test_a_spec_refuses_a_bare_string_of_faces():
    from pandid.spec import SpecError, from_dict

    with pytest.raises(SpecError, match="must be a list"):
        from_dict({"name": "x", "units": [{"kind": "Block", "name": "R", "inputs": "W"}]})


def test_a_block_flow_diagram_renders():
    """End to end, with connections arriving on three different faces."""
    fs = Flowsheet("bfd")
    ng = fs.add(units.Feed("Natural Gas"))
    steam = fs.add(units.Feed("Steam"))
    ref = fs.add(units.Block("Reforming", inputs=["W", "N"], outputs=["E"]))
    syn = fs.add(units.Block("Synthesis", inputs=["W", "S"], outputs=["E", "S"]))
    nh3 = fs.add(units.Product("NH3"))
    purge = fs.add(units.Product("Purge"))
    recycle = fs.add(units.Feed("Recycle"))
    fs.connect(ng.outlet, ref.in_1)
    fs.connect(steam.outlet, ref.in_2)
    fs.connect(ref.out_1, syn.in_1)
    fs.connect(recycle.outlet, syn.in_2)
    fs.connect(syn.out_1, nh3.inlet)
    fs.connect(syn.out_2, purge.inlet)
    svg = fs.to_svg()
    assert "Reforming" in svg
    assert not [i for i in fs.validate() if i.severity == "error"]


def _frame(unit):
    """The unit placed once, so a port can be resolved without a whole sheet."""
    fs = Flowsheet("jig")
    fs.add(unit).pin(x=0, y=0)
    fs.layout()
    return unit.frame

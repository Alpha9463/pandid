#!/usr/bin/env python3
"""Generate pandid/render/_vendored_symbols.py from draw.io (jgraph/drawio) P&ID
stencils (Apache-2.0). See NOTICE for attribution.

Each mapped symbol is converted from mxGraph stencil XML to plain SVG by
scripts/mxgraph_to_svg.py, and its ports are resolved either from the stencil's
named <constraint> anchors ("W"/"E"/"N"/"S"/...) or placed explicitly on a
bounding-box edge as ``(edge, along)`` for shapes that lack a needed anchor.

The shape's ``aspect`` comes across with it, as ``Symbol.stretchable``: the
stencil author already answered whether the drawing may be reshaped to fill a
box of another shape (``variable``) or has to keep its proportions (``fixed``),
and that is the same question a unit given an explicit width and height asks.
It is named in each emitted symbol's comment, and only a ``fixed`` shape carries
the keyword, since stretchable is the default on both sides.

``ADAPTED_ELSEWHERE`` records the stencil-derived symbols this generator cannot
emit (the parametric ones) and where they are written instead.

``STENCIL_PATCHES`` records the corrections applied to the vendored stencils on
the way through, for the shapes draw.io draws wrongly. The vendored XML stays
exactly as vendored; the correction is written in the stencil's own language
here, so the deviation from upstream is in this file rather than hidden in a
mirrored data file.

Run:  python scripts/vendor_symbols.py
"""
import math
import pathlib
import xml.etree.ElementTree as ET

import sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from mxgraph_to_svg import shapes_in, convert_shape, stencil_namespace  # noqa: E402
from pandid.portgeom import outward_dir  # noqa: E402  (the one place a face is derived)

STENCILS = HERE / "vendor_data" / "drawio"
OUT = HERE.parent / "pandid" / "render" / "_vendored_symbols.py"

# (kind, variant) -> (stencil, shape_name, {port_name: "constraint" | (edge, along)})
KIND_MAP = {
    # Valves: inline family (inlet W / outlet E).
    #
    # ``actuator`` is where a controller's output lands. It is a signal terminal
    # and not a nozzle: nothing flows through it, so the line stops at the valve
    # rather than reaching into it, and the port belongs on the edge of the
    # symbol's own extent, at the point the operator would be mounted on. A
    # coordinate inboard of that edge draws the signal ending inside the body,
    # since the router steers to the edge and the renderer draws to the
    # coordinate. Coordinates are in the stencil's own space, which SCALE then
    # reduces: by the kind's own 0.25 for everything drawn on valves.xml's
    # ~98-unit module, and by a factor of its own for the three shapes that are
    # not on it (``psv``, ``relief``, ``butterfly_pneumatic``); see SCALE.
    ("valve", "default"):   ("valves", "Gate Valve",        {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "gate"):      ("valves", "Gate Valve",        {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "globe"):     ("valves", "Globe Valve",       {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "ball"):      ("valves", "Ball Valve",        {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "butterfly"): ("valves", "Butterfly Valve 1", {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "check"):     ("valves", "Check Valve 1",     {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.25)}),
    # Saunders / weir diaphragm valve: a *body*, not an operator. The stencil
    # draws the weir as an arc inside the bowtie and puts nothing on top of it,
    # so what is bolted to its stem is not stated -- the same silence a gate or
    # a ball body keeps. Up to 0.1.1 this drawing was filed under ``control``,
    # which is what issue #136 is about: the variant an engineer types for a
    # control valve drew a hand valve with a weir in it and no actuator at all.
    ("valve", "saunders"):  ("valves", "Diaphragm",         {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "needle"):    ("valves", "Needle",            {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "three_way"): ("valves", "Three-Way Valve",   {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    # A PSV's centreline is taken by its own inlet and outlet; the pilot/solenoid
    # connection goes on the side of the spring bonnet instead.
    ("valve", "relief"):    ("valves", "Relief PRV",        {"inlet": "S", "outlet": "N",
                             "actuator": ("AT", 40.0, 24.0)}),
    # Angle body: the seat turns the flow a quarter, so this one is piped from
    # below and out to the side. The stem rises from the vertex where the two
    # halves meet, so the actuator sits above it on that vertex's centreline
    # rather than on the middle of the top edge.
    ("valve", "angle"):     ("valves", "Angle",             {"inlet": "S", "outlet": "E",
                             "actuator": ("N", 30.0)}),
    # Spring-loaded angle safety valve: the PSV a real sheet draws, with the
    # spring bonnet on top of the inlet leg. The stem runs to y = 0.
    ("valve", "psv"):       ("valves", "Safety PSV 1",      {"inlet": "S", "outlet": "E",
                             "actuator": ("AT", 21.0, 0.0)}),
    # Bleeder: the small drain valve tapped off a header. The stencil draws it
    # vertical: the tap runs down from (12.5, 0) into a bowtie whose open
    # bottom bar at y = 75 discharges, so it is piped from above and down, not
    # across. ("Bleeder Valve 2" draws the same valve hanging off a length of
    # header, which is what settles that top line as the tap and not a stem.)
    #
    # The actuator stays on the top face, as on every other valve, but the tap
    # already owns the centreline, so it is set over to x = 24 rather than
    # stacked on the inlet.
    ("valve", "bleed"):     ("valves", "Bleeder Valve 1",   {"inlet": "N", "outlet": "S",
                             "actuator": ("N", 24.0)}),
    # These two stencils name an "N" constraint, but draw.io puts it on the
    # inboard ink (the plug's upper seat line, the pinch sleeve's crown) rather
    # than on the top of the shape, so both are placed on the edge instead.
    ("valve", "plug"):      ("valves", "Plug",              {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "pinch"):     ("valves", "Pinch Valve",       {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),

    # --- Valves that draw their operator ---
    #
    # Unlike the bare bodies above, these stencils draw the operator on top of
    # the valve, so ``actuator`` lands on its crown (the top of the motor/
    # solenoid/hydraulic box, or the apex of a diaphragm dome), which is where a
    # controller output or interlock signal physically terminates.
    #
    # The three letter-box operators share one body and differ only in the
    # letter, so they must stay three separate variants.
    #
    # "Solenoid Valve Closed" is draw.io's name for the mechanism's rest state,
    # not something its drawing says. The three shapes are identical but for the
    # letter (same background body path, same operator box, no <fillcolor>
    # anywhere), and the library ships no open counterpart to differ from. So
    # the symbol does not depict a closed valve, and the darkened body of
    # ``Valve(normal_position="closed")`` is the only thing on it that states a
    # position. Contrast the genuine state pairs elsewhere in the library (the
    # Figure 8 blinds, the open/blind discs), where the two shapes differ by a
    # <fillcolor> and the fill is the convention.
    ("valve", "motor"):     ("valves", "Motor Operated Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "solenoid"):  ("valves", "Solenoid Valve Closed",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "hydraulic"): ("valves", "Hydraulic Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    # The control valve. A diaphragm actuator -- a dome on a short stem -- drawn
    # *above* the body, which is what ISO 15519-2 Table 5 means by listing
    # "valves incl. actuators" as basic information for a P&ID, and what
    # ``professional_examples/P&ID_301.pdf`` draws on all six of its CVs.
    #
    # Filed under ``control`` because that is what an engineer types. Up to
    # 0.1.1 this drawing answered to ``pneumatic`` -- the signal medium, which
    # is not a kind of valve -- while ``control`` drew the Saunders body now
    # registered above. Issue #136.
    ("valve", "control"):   ("valves", "Pneumatic Operated",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "manual"):    ("valves", "Manual Operated Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    # Knife gate: rising stem through a handwheel bar spanning x 30..70 at y = 0.
    ("valve", "knife"):     ("valves", "Knife Valve",
                             {"inlet": "W", "outlet": "E", "actuator": "N"}),
    ("valve", "butterfly_pneumatic"): ("valves", "Pneumatic Operated Butterfly Valve",
                                       {"inlet": "W", "outlet": "E", "actuator": "N"}),
    # Self-acting pressure regulator: the dome is its own diaphragm, so the
    # "actuator" is the external pilot connection rather than a signal terminus.
    # The stencil draws that pilot line running up from the dome crown to the
    # top of the shape, which is where the port goes.
    ("valve", "regulator"): ("valves", "Back Pressure Regulator 1",
                             {"inlet": "W", "outlet": "E", "actuator": ("N", 49.0)}),
    # Rotating equipment.
    #
    # draw.io's <constraint> anchors are generic compass points on the bounding
    # box, not process nozzles: on a centrifugal pump "N" lands on the *corner*
    # of the discharge stub and "E" in the middle of the volute. Where the
    # stencil draws a real nozzle, place the port on its mouth explicitly so
    # the line leaves the flange rather than the casing.
    ("pump", "default"):       ("pumps", "Centrifugal Pump 1",
                                {"suction": ("W", 30.0), "discharge": ("E", 10.0)}),
    ("pump", "gear"):          ("pumps", "Gear Pump",
                                {"suction": ("W", 41.5), "discharge": ("E", 41.5)}),
    ("pump", "screw"):         ("pumps", "Screw Pump",         {"suction": "W", "discharge": "E"}),
    ("compressor", "default"): ("compressors", "Centrifugal Compressor",
                                {"suction": ("W", 30.0), "discharge": ("E", 10.0)}),
    ("compressor", "reciprocating"): ("compressors", "Reciprocating Compressor",
                                      {"suction": "W", "discharge": ("E", 25.0)}),
    ("blower", "default"):     ("compressors", "Compressor", {"suction": "W", "discharge": "N"}),
    # Heat exchangers.
    #
    # A nozzle is named for the SIDE OF THE EQUIPMENT it is on (shell or tube)
    # and never for the duty the stream happens to carry. Which fluid goes in
    # the shell and which in the tubes is a design decision an engineer makes
    # deliberately (fouling service goes tube side, since tubes can be cleaned;
    # condensing vapour goes shell side), so it is a fact about the exchanger and
    # belongs on the drawing. Hot and cold invert between operating cases while
    # the nozzle stays where it is, and they did not even land on the same face
    # from one variant to the next.
    #
    # The ISO circle-and-zigzag: the zigzag is the tube, entering at W and
    # leaving at E, and the circle around it is the shell, so the shell nozzles
    # take N and S.
    ("hex", "default"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                         {"tube_in": "W", "tube_out": "E", "shell_in": "N", "shell_out": "S"}),
    # Kettle reboiler. The stencil draws a channel head at x 0..16.5 separated
    # from the shell by a tubesheet (the rect at x 16.5..19.5), so the left stub
    # is the TUBE side (the heating medium), not a process connection. The
    # process boils in the shell: liquid in at the bottom, vapour off the top.
    # Piping the column bottoms to that left stub would run it straight into the
    # steam side, which is what the plain W anchor does.
    #
    # Only one channel-head opening is drawn, so ``tube_out`` has to take the
    # shell's far dished head. It is the heating-medium return and the one nozzle
    # here whose name is truer than its position; a second opening on the head
    # would have to be invented, and a nozzle is drawn where the stencil draws
    # one.
    #
    # ``bottoms`` is the draw at the weir end: what does not boil overflows the
    # plate at x = 86.5 and leaves the bottom of the shell, which is how a
    # tower's bottoms product actually gets off the sheet.
    ("hex", "kettle"):  ("heat_exchangers", "Reboiler",
                         {"shell_in": ("AT", 45.8, 30.0), "shell_out": ("N", 64.0),
                          "tube_in": ("W", 22.5), "tube_out": ("E", 15.0),
                          "bottoms": ("AT", 85.0, 30.0)}),
    # Heater and cooler are one stencil pair: the same circle and zigzag, with
    # the diagonal arrow pointing in (heat added) or out (heat removed). Taking
    # the cooler from anywhere else breaks the pairing: "Heat Exchanger
    # (Spiral)" is a different piece of equipment entirely and, at 100x100,
    # draws a utility cooler larger than the reactor upstream of it. draw.io
    # files the heat-removed one under "Condenser".
    #
    # The third connection is the utility one: steam into the heater, cooling
    # medium out of the cooler. It is named for what lands on it rather than for
    # the duty, on the same principle as the exchanger nozzles above.
    ("heater", "default"): ("heat_exchangers", "Heater",
                            {"inlet": "W", "outlet": "E", "utility_in": "S"}),
    ("cooler", "default"): ("heat_exchangers", "Condenser",
                            {"inlet": "W", "outlet": "E", "utility_out": "N"}),
    # A real exchanger style in its own right, just not what a Cooler is drawn as.
    #
    # Two spiral channels, neither of them a shell or a tube, so the sides are
    # lettered. Only side A's pair is drawn as stubs, on the outer coil at
    # (10, 50) and (90, 50); the second channel's connections are axial and a
    # plan view cannot draw them, so side B takes the casing's own N and S faces.
    ("hex", "spiral"):     ("heat_exchangers", "Heat Exchanger (Spiral)",
                            {"side_a_in": "W", "side_a_out": "E",
                             "side_b_in": "N", "side_b_out": "S"}),
    # Vessels / columns / reactors / separators / tanks.
    #
    # The generic ISO 10628 vessel: a vertical cylinder with dished heads, the
    # same stencil the column is drawn from. "Barrel, Drum" is a 44-gallon
    # shipping barrel (hoop bands and all), which is a container rather than a
    # piece of process equipment.
    #
    # Sharing the stencil with the column is why SCALE reproportions this one:
    # a tower is slender because it is full of trays, and a drum drawn to the
    # same proportions reads as a small tower on a sheet carrying both. See
    # SCALE for the box it comes out at.
    #
    # Ports are the barrel's, and the dished variant's: in one shell wall and
    # out the other at mid-height, with the vapour connection on the crown of
    # the top head at (50, 0). Switching a vessel between variants is a change
    # of artwork, not of piping, so the two must offer the same nozzles in the
    # same places. Both process nozzles are at mid-height, which is on the
    # straight shell (it spans y 15..185) at any box the unit is drawn at,
    # rather than on a head, where the ink curves away from the box edge.
    #
    # ``relief`` and ``drain`` are the two nozzles issue #222 added to Vessel
    # and Tank, and every one of the seventeen stencils in those two families
    # places them by the same two rules, which are the roles' own meanings and
    # not a layout convention:
    #
    #   relief -- on the CROWN, beside the vent. CHEE4001 p.7: "The PSV should
    #       be placed, whenever possible, directly on the system to be
    #       protected, vertically, upward, and at the top of the container."
    #       Measured onto the head's own arc or slope rather than onto the box's
    #       top edge, for the reason the roofs below are: a head rises inside
    #       its bounding box, so a nozzle on the edge floats above the ink.
    #   drain -- on the vessel's LOWEST DRAWN POINT, because that is what a
    #       drain is. Where the stencil draws a support -- legs, a skirt, the
    #       sphere's frame -- the low point is INBOARD of the box's bottom, and
    #       the nozzle goes on the vessel rather than on the steel: a drain out
    #       of the bottom of a leg is worse than a drain that leaves sideways.
    #
    # That second case has a consequence worth stating rather than discovering.
    # ``portgeom.outward_dir`` reads a nozzle's face off the nearest box edge,
    # so on ``vessel/legs`` and ``vessel/skirted``, whose 40 x 122.69 box is a
    # third leg by height, the bottom head's centre is nearer a side wall (20)
    # than the box's floor (27.3) and the drain comes out WEST at the symbol's
    # own aspect. Give the unit a box less than about 2.2 times as tall as it is
    # wide -- 60 x 120, which is what ``examples/14`` draws V-604 at -- and it
    # comes out south. Supports pushing a nozzle's face around is #225's
    # territory, and papering over it here with a second placement rule would
    # put the drain somewhere that is not the low point in order to get a face.
    ("vessel", "default"): ("vessels", "Pressurized Vessel",
                            {"inlet": ("W", 100.0), "outlet": ("E", 100.0),
                             "vent": ("N", 50.0),
                             # Unscaled: SCALE reproportions this one by
                             # (0.62, 0.5), so the relief's (25, 2) lands at
                             # (15.5, 1.0) and the drain's apex at (31, 100).
                             # The top head is an ellipse rx 50 ry 15 about
                             # (50, 15); x = 25 is half a radius off the crown,
                             # putting it at y = 15 - 15*sin(120 deg) = 2.
                             "relief": ("AT", 25.0, 2.0),
                             "drain": ("S", 50.0)}),
    # Feed enters on the left; the returns come back on the RIGHT, which is the
    # side the overhead and reboiler systems are drawn on. reflux_in sits high
    # and boilup_in low on the straight shell wall (which spans y 15..185), with
    # the two duty arrows spaced between them.
    #
    # The feeds are a family: an extractive tower takes its solvent above the
    # feed tray. They stay on the west wall, and every member of it, at every
    # count, lands strictly between the two duty arrows' heights. Those two are
    # the INNERMOST fixed nozzles on the wall opposite (65 and 145, against
    # reflux_in's 35 and boilup_in's 175), so a band bounded by them is bounded
    # by all four: no feed is drawn at the elevation of a return or of a duty
    # arrow, however many feeds there are.
    #
    # The arithmetic. The band is 65..145, which is 80 units of the 200-unit
    # shell centred on 105, so ``at`` is 105. (It was 130, the height the
    # single-feed nozzle was drawn at before the family existed, and a family
    # centred 25 below its own band runs off the bottom of it at the second
    # feed.) The band's *width* is the widest whole number of pitches that fits
    # inside it: 2 x 35 = 70, since 3 x 35 = 105 is more than the 80 there is.
    # So extent = 70 / 200 = 0.35, and the outermost members land on
    # 105 -+ 35 = 70 and 140. The (80 - 70) / 2 = 5 units left under each arrow
    # are the point of not spending the whole band rather than a margin picked
    # by eye: at extent 0.4 the outermost feeds land exactly ON 65 and 145,
    # level with a duty arrow on the wall opposite, so the two leave the vessel
    # at one elevation and read as one line drawn across it.
    #
    # For a reader: one, two or three feeds sit at the declared 35 pitch, and
    # the fourth is where PortSeries begins squeezing the run into ``extent``
    # rather than running it off the ends.
    ("column", "default"): ("vessels", "Pressurized Vessel",
                            {"feed": ("SERIES", "W", 105, 35, 0.35),
                             "distillate": ("N", 50), "bottoms": ("S", 50),
                             "reflux_in": ("E", 35), "boilup_in": ("E", 175),
                             "condenser_duty": ("E", 65), "reboiler_duty": ("E", 145)}),
    # The packed tower: the same shell, with two beds of packing between their
    # support grids. This is the one column stencil that draws an internal, so
    # an absorber or a stripper stops coming out as a bare drum.
    #
    # Every nozzle is the default column's, restated in the tower's own 97-unit
    # shell: SCALE puts the shape in a 62 x 200 box, so 16.975 lands on 35,
    # 31.525 on 65, 70.325 on 145, 84.875 on 175 and the feed family's centre
    # 50.925 on 105, the heights every column sheet is already drawn to. The two
    # products take the head crowns at (7, 0) and (7, 97); everything else is on
    # the straight shell, which spans y 3.5..93.5 on both walls.
    #
    # The family's ``extent`` is a fraction of the face rather than a length, so
    # it is the one number here that is NOT restated: 0.35 is the same 0.35 the
    # default column declares, and it has to be, since both towers come out
    # 200 tall and their duty arrows land on the same 65 and 145. The pitch and
    # the centre do scale (16.975 -> 35, 50.925 -> 105), which is what puts this
    # tower's feed band on exactly the default column's.
    ("column", "packed"): ("vessels", "Tower With Packing",
                           {"feed": ("SERIES", "W", 50.925, 16.975, 0.35),
                            "distillate": ("N", 7), "bottoms": ("S", 7),
                            "reflux_in": ("E", 16.975), "boilup_in": ("E", 84.875),
                            "condenser_duty": ("E", 31.525),
                            "reboiler_duty": ("E", 70.325)}),
    # The stirred tank, and the conventional CSTR: the same plain dished-head
    # cylinder the vessel, the flash drum and the column are cut from, in the
    # drum's 62 x 100 box, with an ISO group-28 agitator composed *into* it by
    # ``pandid.units.Reactor``.
    #
    # That is ISO item 1.27 X8006's construction -- a dished-end vessel, an
    # agitator on a shaft through the top head, a drive above it -- rather than
    # the "Mixing Reactor" stencil's rectangle with a V bottom and its motor box
    # perched outside the shell. The stencil is kept, under ``mixing`` below.
    #
    # The nozzles are the drum's, in the drum's places: the product out of the
    # bottom head, the duty on the straight east wall (which spans y 7.5..92.5)
    # and the charge nozzles down the west one.
    #
    # **The vent is on the shell, not on the crown**, and that is 1.27 again
    # rather than a preference. The crown of a stirred vessel carries the shaft
    # and nothing else, because the motor is drawn on the shaft above it -- and
    # pandid's own geometry says the same thing from the other side: a nozzle's
    # face is the box edge it is nearest, the composed box is a third of the
    # body's height taller than the body, and every point on a 62-wide crown is
    # then nearer a side wall than the top. A vent left up there would take its
    # stream out through the shell. So it sits at (62, 10), on the straight east
    # wall just under the tangent line at y 7.5, which is where the off-gas
    # leaves a vessel whose head is occupied.
    ("reactor", "default"): ("vessels", "Pressurized Vessel",
                             {"feed": ("SERIES", "W", 100.0, 28.0, 0.32),
                              "outlet": ("S", 50.0), "duty": ("E", 100.0),
                              "vent": ("AT", 100.0, 20.0)}),
    # The drawing ``default`` used to be, kept under a name that says what it is
    # rather than deleted: a box with a stirrer perched on top of it is still
    # what some plants draw, and a reader with an old sheet has to be able to
    # reproduce it.
    #
    # vent sits on the vessel's top edge, clear of the agitator shaft at x 24..26.
    # The charge nozzles spread along the straight west wall, which spans
    # y 32.4..77.4: the vessel is dished below that and open above it.
    ("reactor", "mixing"): ("vessels", "Mixing Reactor",
                            {"feed": ("SERIES", "W", 48.2, 14, 0.32),
                             "outlet": "S", "duty": "E",
                             "vent": ("AT", 40.0, 32.4)}),
    # The jacketed stirred tank -- ISO item 1.27 X8006 itself, which is the
    # jacketed one: the same shell with a heating/cooling jacket wrapped round
    # it. Shares its stencil with ``vessel/jacketed``, because a jacketed
    # reactor and a jacketed vessel are one piece of equipment differing in what
    # is in it. The duty connection is the jacket's, so it takes the jacket band
    # rather than the shell wall.
    #
    # The vent is off the crown for the reason ``default``'s is, and lands at
    # (46, 10): the shell's own east wall, which the outline draws from y 7.69
    # to 87.69, at the one height above the jacket band (y 12.69..82.69) -- so
    # the line leaves over the jacket rather than through it.
    ("reactor", "jacketed"): ("vessels", "Vessel (Dished Ends, Heating-Cooling Jacket)",
                              {"feed": ("SERIES", "W", 47.7, 14, 0.32),
                               "outlet": ("S", 26.0), "duty": ("E", 47.7),
                               "vent": ("AT", 46.0, 10.0)}),
    # The flash drum: the same plain dished-head cylinder the vessel and the
    # column are drawn from, with the phases named. ``vessel``/``horizontal``
    # and ``separator``/``horizontal`` are already one stencil ("Drum or
    # Condenser") differing only in what its nozzles are called, because a
    # separator IS a vessel the author wants the vapour and liquid products
    # named on; the vertical pair was the odd one out, and this makes the
    # family consistent in both attitudes.
    #
    # It is also what the class actually claims. A Separator is documented as
    # the generic flash drum or phase separator, and "Knock-out Drum" asserts
    # two internals the model never said were there:
    #
    # * a LEVEL GAUGE, drawn as a rect and two verticals hanging off the right
    #   shell wall at x 40..51. pandid draws instruments as ISA-5.1 balloons on
    #   signal lines (``pandid/loops.py``), so a gauge baked into the equipment
    #   artwork is drawn a second time the moment a real LG or LT is added.
    # * a DEMISTER PAD, the crosshatch at y 17.69..27.69. A mesh pad is a design
    #   decision about entrainment, not something every flash drum has.
    #
    # Neither is lost: ``knockout`` below is that stencil, kept under a name
    # that says what it draws, for the author who does want the mesh pad.
    #
    # Ports are the vessel's, in the vessel's places, since switching a vessel
    # for a separator is a change of what the nozzles are called and not of
    # where they are: feed in the west shell wall at mid-height (the straight
    # shell spans y 15..185, so it is on ink at any box the unit is drawn at,
    # rather than on a head where the ink curves away from the box edge), and
    # the two products on the head crowns at (50, 0) and (50, 200), which is
    # exactly where the column takes its distillate and its bottoms.
    ("separator", "default"): ("vessels", "Pressurized Vessel",
                               {"feed": ("W", 100.0),
                                "vapor": ("N", 50.0), "liquid": ("S", 50.0)}),
    # The knock-out drum, with its mesh pad and its level gauge, under the name
    # of the thing it draws. Its nozzles are the ones it has always carried, on
    # its own 51 x 95.38 body: the feed on the west shell wall (which spans
    # y 7.69..87.69) and the two products on the head crowns, whose arcs reach
    # y = 0 and y = 95.38 because a 40-wide chord scales rx = 13 / ry = 5 up
    # until ry is the 7.69 the shell is inset by.
    ("separator", "knockout"): ("vessels", "Knock-out Drum",
                                {"feed": ("W", 55), "vapor": ("N", 25), "liquid": ("S", 25)}),
    # Both roofs rise inside the bounding box, so a nozzle on the box's top edge
    # floats above the drawn ink. Anything put on the roof goes on the roof
    # itself: the dome crown, and the cone apex.
    #
    # A tank takes a third roof nozzle the vessels above do not: ``vent``, the
    # conservation vent a fixed roof breathes through. It flanks the crown, and
    # ``relief`` flanks it on the other side, so the roof connections read left
    # to right in the order a reader meets them and neither of the two is nearer
    # the middle than the other. Both are measured onto the roof's own ink, and
    # ``drain`` onto the floor clear of the draw-off: see the ``vessel/default``
    # block above for the rule and for what it costs.
    #
    # WHERE A TANK FILLS (#226). The fill is on the SHELL, low, and the crown is
    # the alternate rather than the default. Splash-filling a flammable liquid
    # into a vapour space generates static, so bottom entry -- or a fill pipe
    # carried down to the floor -- is ordinary practice for a motor spirit or an
    # ethanol tank, and a fill line drawn onto the crown with nothing said about
    # a downcomer reads as the splash fill. Being honest about the evidence:
    # none of the three documents on disk says anything about tank filling,
    # static or downcomers, so this is ordinary practice and is claimed as
    # nothing more -- unlike the relief above it, which CHEE4001 p.7 places
    # outright.
    #
    # It is a default and not a rule, which is the whole of what #226 asked for:
    # top entry with an internal downcomer is a real arrangement and a sheet
    # reaches it with ``nozzle("inlet", "N")``. West and east are both offered
    # because a fill header runs down whichever side the plot puts it on, and
    # the layout engine picks from where the peer landed.
    #
    # The dished roof is an arc of r = 75 over a 100-wide chord springing from
    # y = 25.46, so its centre is at (50, 25.46 + sqrt(75^2 - 50^2)) = (50,
    # 81.36) and its crown at (50, 6.36). x = 35 and x = 65 are 15 either side
    # of that crown, at y = 81.36 - sqrt(75^2 - 15^2) = 7.9. The shell is a
    # plain rect from y = 25.46 to 95.46, so the fill takes its wall at y = 85,
    # ten above the floor.
    ("tank", "default"):  ("vessels", "Tank (Dished Roof)",
                           {"inlet": [("W", 85), ("E", 85), ("AT", 50.0, 6.4)],
                            "outlet": ("S", 50),
                            "vent": ("AT", 35.0, 7.9),
                            "relief": ("AT", 65.0, 7.9),
                            "drain": ("S", 20)}),
    # The conical roof runs (0, 20) - (50, 0) - (100, 20), so a nozzle halfway
    # along either slope is at (25, 10) and (75, 10). The floor is a plain line
    # across y = 90, so the drain takes it directly, 30 clear of the outlet, and
    # the shell walls span y 20..90, so the fill takes them at y = 80.
    ("tank", "conical"):  ("vessels", "Tank (Conical Roof)",
                           {"inlet": [("W", 80), ("E", 80), ("N", 50)],
                            "outlet": ("S", 50),
                            "vent": ("AT", 25.0, 10.0),
                            "relief": ("AT", 75.0, 10.0),
                            "drain": ("S", 20)}),
    # Fittings.
    #
    # A reducer is a trapezoid between a large face and a small one, and both
    # faces are pipe: the run leaves the small end at whatever the reduced line
    # size is. fittings.xml's "Reducer" is not that shape. It is a triangle,
    # 70 x 50 to a point at (70, 25), so its E anchor sits on the apex and the
    # line it reduces to comes out with no width at all: a reducer drawn as a
    # blind cone. So ``default`` is piping.xml's Concentric Reducer, the same
    # shape ``concentric`` names, on the pattern ``valve``/``gate`` and
    # ``fitting``/``flange`` already follow: the unqualified name draws the
    # ordinary member of the family, and the qualified one says which member
    # that is. Nothing maps the triangle; a shape that draws the device wrongly
    # is not a style to be kept under another name.
    #
    # Both bodies are drawn 12.5 tall, since a reducer's drawn height is the
    # pipe it sits in and two of them in one run have to agree about that; see
    # SCALE.
    ("reducer", "default"): ("piping", "Concentric Reducer",
                             {"inlet": "W", "outlet": "E"}),
    ("reducer", "concentric"): ("piping", "Concentric Reducer",
                                {"inlet": "W", "outlet": "E"}),
    # Eccentric: flat on top, so the two ends share a roof and the small end's
    # centreline is the HIGHER of the two, which is the whole point of it on a
    # pump suction, where a concentric reducer would leave a pocket against the
    # roof of the line for vapour to collect in. The stencil's own E anchor is
    # on that raised centreline (y = 4.5 of 15, against the W anchor's 7.5) and
    # not at mid-height, so it is taken as named rather than placed.
    #
    # Flat on the *bottom* is the same fitting rolled over, for the line that
    # has to drain rather than vent, and it is a placement rather than a second
    # drawing: ``pin(mirrored="y")`` turns the body over, and both nozzles stay
    # on the west and east faces the run enters and leaves by.
    ("reducer", "eccentric"): ("piping", "Eccentric Reducer",
                               {"inlet": "W", "outlet": "E"}),
    # In-line devices: one class, because a strainer, a sight glass and a
    # rupture disc are the same thing to the flowsheet (a pair of faces on a
    # line) and differ only in what is drawn between them. The default is the
    # plain flanged joint, which is what an unqualified "fitting" draws.
    #
    # Every port here sits on a bounding-box edge that the stencil actually
    # strokes, so they take the shapes' own W/E anchors.
    ("fitting", "default"):        ("fittings", "Flanged Connection",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "flange"):         ("fittings", "Flanged Connection",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer"):       ("fittings", "Strainer", {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer_cone"):  ("fittings", "Strainer (Cone)",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "rupture_disc"):   ("fittings", "Rupture Disc", {"inlet": "W", "outlet": "E"}),
    ("fitting", "sight_glass"):    ("fittings", "Viewing Glass", {"inlet": "W", "outlet": "E"}),
    ("fitting", "sight_glass_lit"): ("fittings", "Viewing Glass (Lighting)",
                                     {"inlet": "W", "outlet": "E"}),
    ("fitting", "silencer"):       ("fittings", "Silencer", {"inlet": "W", "outlet": "E"}),
    # Expansion joint: the lens is widest at mid-height, which is exactly where
    # the two anchors sit: one on each arc's extremum.
    ("fitting", "expansion_joint"): ("fittings", "Compensator",
                                     {"inlet": "W", "outlet": "E"}),
    # The four arrestor bodies encode different certifications (plain, explosion-
    # proof, detonation-proof, fire-resistant) and are drawn differently, so each
    # is its own variant rather than an alias.
    ("fitting", "flame_arrestor"): ("fittings", "Flame Arrestor",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "flame_arrestor_explosion_proof"): (
        "fittings", "Flame Arrestor (Explosion-Proof)", {"inlet": "W", "outlet": "E"}),
    ("fitting", "flame_arrestor_detonation_proof"): (
        "fittings", "Flame Arrestor (Detonation-Proof)", {"inlet": "W", "outlet": "E"}),
    ("fitting", "flame_arrestor_fire_resistant"): (
        "fittings", "Flame Arrestor (Fire-Resistant)", {"inlet": "W", "outlet": "E"}),
    ("fitting", "coupling"):       ("fittings", "Coupling", {"inlet": "W", "outlet": "E"}),
    # The clamp brackets stand proud of the pipe, so this shape's anchors are
    # inboard of the box (x = 10 and 40), on the pipe ends the clamp grips.
    ("fitting", "clamped_coupling"): ("fittings", "Clamped Flange Coupling",
                                      {"inlet": "W", "outlet": "E"}),
    ("fitting", "hose"):           ("fittings", "Hose", {"inlet": "W", "outlet": "E"}),
    # Restriction orifice. fittings.xml's "Orifice Plate" is NOT this: it is a
    # paddle-on-a-handle overlay meant to be dropped on top of a line, with no
    # flow path and no connections. valves.xml draws the in-line plate.
    ("fitting", "orifice"):        ("valves", "Orifice", {"inlet": "W", "outlet": "E"}),
    ("fitting", "rotameter"):      ("valves", "Rotameter", {"inlet": "W", "outlet": "E"}),
    ("fitting", "static_mixer"):   ("mixers", "In-Line Static Mixer",
                                    {"inlet": "W", "outlet": "E"}),

    # --- Primary flow elements (flow_sensors.xml) ---
    #
    # The device an FE balloon reads: a venturi, a meter body, a probe in the
    # line. They are in-line devices with a pair of faces, which is what a
    # Fitting is, so they are variants of it rather than a class of their own:
    # nothing about the flowsheet changes because the thing in the run measures
    # rather than strains. (A ``FlowElement`` class would read better on an
    # equipment list, and is worth its own change; it is not this one.)
    #
    # Every shape here names W and E on its own outline and every one of them is
    # stroked (the meter bodies are a plain rectangle, and the two profiling
    # elements close their bodies with a straight face at each end), so all of
    # them take the stencil's own anchors.
    #
    # These are drawn on a 50-unit module rather than valves.xml's ~100, so
    # SCALE halves them at 0.5 instead of 0.25 and they come out beside a
    # 24.5 x 15.0 valve at the same length. See SCALE.
    #
    # The venturi is the one a differential-pressure loop is actually drawn
    # with: a converging throat and a diverging recovery cone, closed by a flat
    # face at each end where the flanges are. The stencil's N anchor is on the
    # throat rather than the top of the box, and a Fitting has no third port to
    # put it on, so it is left where it is.
    ("fitting", "venturi"):        ("flow_sensors", "Venturi",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "flow_nozzle"):    ("flow_sensors", "Flow Nozzle",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "coriolis"):       ("flow_sensors", "Coriolis",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "vortex"):         ("flow_sensors", "Vortex",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "ultrasonic"):     ("flow_sensors", "Ultrasonic",
                                    {"inlet": "W", "outlet": "E"}),
    # "turbine_meter", not "turbine": a Turbine is already a piece of rotating
    # equipment in this library, and a variant reading as one would be a trap.
    ("fitting", "turbine_meter"):  ("flow_sensors", "Turbine",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "positive_displacement"): ("flow_sensors", "Positive Displacement",
                                           {"inlet": "W", "outlet": "E"}),
    ("fitting", "v_cone"):         ("flow_sensors", "V-cone",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "wedge"):          ("flow_sensors", "Wedge",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "target"):         ("flow_sensors", "Target",
                                    {"inlet": "W", "outlet": "E"}),
    # The two impulse probes. draw.io spells the averaging one "Averging"; the
    # shape name has to be the stencil's, so the typo is carried here and
    # corrected in the variant name.
    ("fitting", "pitot"):          ("flow_sensors", "Pitot Tube",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "averaging_pitot"): ("flow_sensors", "Averging Pitot Tube",
                                     {"inlet": "W", "outlet": "E"}),

    # --- In-line piping devices (piping.xml) ---
    #
    # Drawn on the same 50-unit module as the flow elements above and scaled
    # with them. Each takes its stencil's own W and E, which are on the pipe
    # stubs the shape draws rather than on bare box corners.
    #
    # The three strainer bodies a piping drawing actually names. They are drawn
    # lying in the run, unlike "strainer"/"strainer_cone" above, which come from
    # fittings.xml's 40 x 80 upright box and stand across it.
    ("fitting", "strainer_y"):      ("piping", "Y-Type Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer_basket"): ("piping", "Basket Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer_duplex"): ("piping", "Duplex Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    # Bellows: four convolutions between two flanges, which is the expansion
    # joint a piping drawing draws. "expansion_joint" above is fittings.xml's
    # Compensator, a plain lens between two faces; both are kept, because a
    # variant is a style and neither is wrong.
    ("fitting", "bellows"):        ("piping", "Expansion Joint",
                                    {"inlet": "W", "outlet": "E"}),
    # Blade on a pivot between two flanges. ("Damper2" is the same drawing with
    # the pivot filled in draw.io's theme colour rather than black, and this
    # converter paints no fills, so it would be a duplicate.)
    ("fitting", "damper"):         ("piping", "Damper", {"inlet": "W", "outlet": "E"}),
    # Removable spool: the length of pipe taken out to break a line for
    # maintenance, drawn as a pipe between two flanges.
    ("fitting", "spool"):          ("piping", "Removable Spool",
                                    {"inlet": "W", "outlet": "E"}),
    # Spectacle blind (figure-8 blind): two discs on a common tie, one bored
    # through and one solid, bolted between a pair of flanges. Which of them is
    # in the line is the whole of what it says, so it is the one in-line device
    # the stencil set draws in two states -- see CLOSED_SHAPES, and
    # ``Fitting(normal_position=...)``, which is how a user asks for the other.
    #
    # The stencil is 20 x 80: the two discs stacked at y 0..40, then a 40-long
    # tie down to a lone "S" constraint at (10, 80). That constraint is where
    # draw.io means the drawing to be dropped on a line, which would make this a
    # flag on a stalk rather than a device in a run -- and a Fitting is a pair of
    # faces on a line. So the run is taken THROUGH the disc in function, which
    # is the lower one: the stencil pair fills that disc in the closed state and
    # the upper, parked one in the open state, so a line drawn through it meets
    # solid ink exactly when the line is blanked. Both points are on the
    # ellipse's own extrema (it spans y 20..40 about x = 10, r = 10), and the
    # tie hangs below the run as the handle it is.
    #
    # Piping the two ends N and S instead -- along the stencil's own axis, with
    # the tie read as pipe -- draws every blind across its run, since face
    # selection only chooses among declared alternates and nothing turns a unit
    # but the author's own pin(). A blind sits in the run it isolates.
    ("fitting", "blind"):          ("piping", "Open Figure 8 Blind",
                                    {"inlet": ("W", 30.0), "outlet": ("E", 30.0)}),

    # --- Variants (style choices within a class; same ports) ---
    # Heat exchanger styles.
    ("hex", "shell_tube"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": "N", "shell_out": "S"}),
    # U-tube: the channel head is the box at x 0..15, split into two chambers by
    # the pass partition the stencil draws at y = 15, and the shell runs from the
    # tubesheet at x = 15 to a dished head that bulges to x = 91.75. A U-tube
    # bundle turns round inside the shell, so BOTH tube connections are on that
    # channel head, one chamber each. That is the same arrangement "hairpin"
    # below is drawn with, and the reason the variant is called u_tube at all.
    #
    # draw.io offers one W anchor, on the partition itself at (0, 15), and an E
    # anchor on the shell's far head. Taking the pair would put a tube nozzle on
    # the shell, so the two chambers are addressed directly instead and the E
    # anchor goes unused. The shell keeps N and S, which are on its walls.
    ("hex", "u_tube"):     ("heat_exchangers", "U-Tube Heat Exchanger",
                            {"tube_in": ("W", 7.5), "tube_out": ("W", 22.5),
                             "shell_in": "N", "shell_out": "S"}),
    # Horizontal shell-and-tube in elevation: the exchanger a real sheet draws
    # for an overhead condenser or a feed cooler. (The "shell_tube" variant above
    # is the ISO circle-and-zigzag; despite the name it is not this shape.)
    # Tube side runs through the heads at x 0..15 and 85..100; the shell nozzles
    # sit between the tubesheets, which is where draw.io's NE/SW anchors land.
    ("hex", "straight_tubes"): ("heat_exchangers", "Heat Exchanger (Straight Tubes)",
                                {"tube_in": ("W", 15), "tube_out": ("E", 15),
                                 "shell_in": ("N", 75), "shell_out": ("S", 25)}),
    # The same circle-and-zigzag as "default", inside a box and with the
    # heat-removed arrow across it, so the sides read the same way: zigzag W->E
    # is the tube, the circle around it is the shell.
    ("hex", "condenser"):  ("heat_exchangers", "Condenser",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": "N", "shell_out": "S"}),
    # Plate: a pack of plates with the two circuits drawn as an X across it,
    # (10, 0)->(90, 30) and (10, 30)->(90, 0). Neither circuit is a shell or a
    # tube and the two are physically interchangeable, so they are lettered
    # rather than named, and each one follows the diagonal the stencil actually
    # draws: NW to SE and SW to NE. Pairing along the top and bottom edges
    # instead, as the old naming did, crossed both streams over the ink.
    ("hex", "plate"):      ("heat_exchangers", "Heat Exchanger (Plate)",
                            {"side_a_in": "NW", "side_a_out": "SE",
                             "side_b_in": "SW", "side_b_out": "NE"}),
    # Finned tubes: the same casing as "straight_tubes", with a finned tube in
    # place of the bundle, so it takes that variant's nozzles exactly and is a
    # drop-in change of artwork. It is a shell-and-tube exchanger and not an air
    # cooler: the stencil draws a closed casing with tubesheets at x = 15 and 85
    # and no fan, so the N/S pair is a piped shell connection. draw.io's own N/S
    # anchors are at x = 7 and 93, which is over the channel heads rather than
    # between the tubesheets. A shell nozzle cannot be on the tube side.
    ("hex", "finned"):     ("heat_exchangers", "Heat Exchanger (Finned Tubes)",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": ("N", 75), "shell_out": ("S", 25)}),
    # Air cooler (fin-fan). The only piped side is the tube bundle, drawn across
    # the bottom at y = 80 where the stencil's own W/E anchors sit. There is no
    # shell: the other side is air, and it is not piped either. An induced-draft
    # bay pulls it in under the bundle and discharges it through the fan on top,
    # so air_in and air_out sit on the plenum's own bottom and top faces on the
    # fan's centreline.
    ("hex", "air_cooled"): ("heat_exchangers", "Heat Exchanger (Finned Tubes, Fan)",
                            {"tube_in": ("W", 80), "tube_out": ("E", 80),
                             "air_in": ("S", 50), "air_out": ("N", 50)}),
    # Double pipe, drawn as a hairpin. The two bands at y 5..15 and y 35..45 are
    # the OUTER pipe's walls and the line drawn down the middle of each is the
    # inner pipe: it enters the west face at y = 10 and y = 40, where the stencil
    # draws its flange ticks, and its return bend swings out to x = 90, clear of
    # the annulus's own bend at x = 70. The annulus is the side that is stubbed
    # up at (10, 0) and down at (10, 50), so N and S are the shell connections
    # and the west pair is the tube.
    #
    # Both fluids enter at the same end and turn round at the far one, which is
    # why neither side has an east nozzle. Counter-current: the tube enters low
    # at (0, 40) where the annulus leaves.
    ("hex", "double_pipe"): ("heat_exchangers", "Double Pipe Heat Exchanger",
                             {"shell_in": "N", "shell_out": "S",
                              "tube_in": "SW", "tube_out": "NW"}),
    # Hairpin: a U-tube in a shell, with no <connections> at all. The tube ends
    # are the two flared openings on the west face (y 7..10 and y 20..23); the
    # shell draws four stubs, and the pair taken is the diagonal one, far end
    # top and near end bottom, matching "straight_tubes". Like the double pipe
    # above, the tube returns to the end it came in at, so both tube nozzles are
    # on the west face.
    ("hex", "hairpin"):    ("heat_exchangers", "Hairpin Exchanger",
                            {"tube_in": ("W", 8.5), "tube_out": ("W", 21.5),
                             "shell_in": ("N", 72.5), "shell_out": ("S", 17.5)}),
    # Thin-film (wiped-film) evaporator: the one evaporator in the set, and the
    # one exchanger whose two sides are a jacket and a product side rather than a
    # shell and tubes. The product runs top to bottom: feed onto the wiper at the
    # shell's top face, which is drawn at y = 10 rather than on the box edge, and
    # concentrate out of the cone apex at (40, 120). The port is offset to x = 20
    # to keep the inlet line off the rotor shaft the stencil draws down the
    # centre. The jacket is opened on both walls at y = 30, so that is where the
    # heating medium goes in and comes out.
    ("hex", "thin_film"):  ("heat_exchangers", "Thin-Film Evaporator",
                            {"product_in": ("AT", 20.0, 10.0), "product_out": ("S", 40),
                             "jacket_in": ("W", 30), "jacket_out": ("E", 30)}),
    # Pump / compressor styles.
    ("pump", "vacuum"):           ("pumps", "Vacuum Pump",
                                   {"suction": ("W", 25.0), "discharge": ("E", 25.0)}),
    # Peristaltic (hose) pump: the tube runs over the rollers and leaves the top
    # of the head, so the only connections the stencil draws are the two stubs
    # at (20, 0) and (40, 0). The casing circle would take a W/E pair and keep
    # this in line with the rest of the pumps, but it would put both nozzles on
    # blank casing wall; the rule for this family is that a drawn nozzle wins.
    ("pump", "peristaltic"):      ("pumps", "Peristaltic",
                                   {"suction": ("N", 20.0), "discharge": ("N", 40.0)}),
    # Submersible (sump) pump: it stands in the liquid it pumps, so the suction
    # is the strainer plate it sits on and takes the stencil's own S anchor. The
    # discharge is the elbow drawn out of the casing at y = 31.5, and the port
    # is on the open end of that pipe at x = 96.77, not on the box edge 6.8
    # further out, so the line meets the pipe instead of stopping short of it.
    ("pump", "submersible"):      ("pumps", "Submersible Pump",
                                   {"suction": "S", "discharge": ("AT", 96.77, 31.5)}),
    ("compressor", "rotary"):      ("compressors", "Rotary Compressor", {"suction": "W", "discharge": "N"}),
    ("compressor", "liquid_ring"): ("compressors", "Liquid Ring Compressor", {"suction": "W", "discharge": "N"}),
    # Vessel / tank styles.
    # Brackets widen the bounding box past the shell, so box-edge ports float
    # outside the vessel; pin them to the shell walls at x = 10 and x = 50.
    #
    # Six of the ten vessels below are one 40-wide dished shell dressed
    # differently, and their heads are all the same ellipse: rx 20, ry 7.69,
    # about (cx, 7.69) on top and (cx, 87.69) underneath. So the relief is the
    # same point on all six, shifted with the shell: x = cx - 12 is 0.6 of a
    # radius off the crown, at y = 7.69 - 7.69*0.8 = 1.5. The drain is the
    # bottom head's own crown at (cx, 95.38). Stating the arithmetic once here
    # is what keeps the six from drifting apart one variant at a time, which is
    # the same reason ``insulated`` takes ``jacketed``'s map to the decimal.
    ("vessel", "dished"): ("vessels", "Vessel (Dished Ends, Brackets)",
                           {"inlet": ("AT", 10.0, 47.0), "outlet": ("AT", 50.0, 47.0),
                            "vent": ("N", 30.0),
                            "relief": ("AT", 18.0, 1.5), "drain": ("S", 30.0)}),
    # the vent rides the raised manway dome on top, apex near x = 62.7
    #
    # The dome is the one vessel lying down in this group: a 95.4 x 55 body with
    # its top wall drawn as a line at y = 14.95 and its bottom at y = 54.95, the
    # manway riding above the first. So the relief goes on the body's top wall
    # rather than on the manway, which the vent already has, and the drain on
    # the bottom wall at the body's midpoint. Both are 15 or so inboard of the
    # box edge the face is read against, which is what a dome and a manway cost
    # in bounding box; both still resolve N and S, since the box is nearly twice
    # as wide as it is tall.
    ("vessel", "dome"):   ("vessels", "Vessel (Dome)",
                           {"inlet": ("W", 27), "outlet": ("E", 27), "vent": ("N", 62.7),
                            "relief": ("AT", 30.0, 15.0), "drain": ("S", 47.7)}),
    # Jacketed: the same dished vessel inside a heating/cooling jacket, drawn as
    # a panel down each side out to the box edge. The process nozzles go on the
    # jacket's outer wall rather than on the shell at x = 6 and 46, so the line
    # stops where it meets the equipment instead of being drawn across the
    # jacket. Both are at the straight shell's mid-height, and the vent is on
    # the top head's crown, as on "dished".
    ("vessel", "jacketed"): ("vessels", "Vessel (Dished Ends, Heating-Cooling Jacket)",
                             {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                              "vent": ("N", 26.0),
                              # Shell at x 6..46, so cx = 26 and the heads'
                              # arithmetic above gives 26 - 12 = 14 and 95.38.
                              # The relief and the drain go on the SHELL's heads
                              # and not on the jacket, which the two process
                              # nozzles are moved out onto: a jacket is a
                              # utility annulus, and a nozzle drawn on it would
                              # be relieving the heating medium.
                              "relief": ("AT", 14.0, 1.5), "drain": ("S", 26.0)}),
    # Insulated: the same vessel again, lagged rather than jacketed, and the
    # closest thing in the set to a pure change of artwork. The insulation is
    # drawn as a line down each side at x = 0 and x = 52 with the hatch ticks
    # between it and the shell, which is exactly where the jacket's outer panel
    # walls are: same 52 x 95.38 box, same shell at x 6..46, same heads. So it
    # takes ``jacketed``'s port map to the decimal, and a sheet swapping one for
    # the other does not move a run. Both process nozzles are on that outer
    # line, which spans y 12.69..82.69 and so is under them at any box the unit
    # is drawn at, and the vent is on the top head's crown at (26, 0).
    ("vessel", "insulated"): ("vessels", "Vessel (Dished Ends, Thermal Insulation)",
                              {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                               "vent": ("N", 26.0),
                               "relief": ("AT", 14.0, 1.5), "drain": ("S", 26.0)}),
    # Electrically heated: the 40-wide shell "skirted" and "legs" are drawn
    # from, at x 0..40 between heads that reach y = 0 and y = 95.38, with the
    # resistor element hung on the OUTSIDE of the east wall at x 44..50. That
    # element is the only thing widening the box to 50, and it is why this is
    # the one vessel in the family whose nozzles are not its siblings' to the
    # decimal.
    #
    # The inlet still is. Nothing is drawn on the west side, so the shell wall
    # IS the box's west face there and the inlet keeps the family's 47.7.
    #
    # The outlet cannot. The element and its two leads occupy y 27.69..67.69 out
    # to the box edge, so a nozzle at 47.7 has its run drawn straight through
    # the heater; it drops to 77.7, on the clear shell below, which is a low
    # draw-off and how a vessel with a heating element in its side wall is piped
    # anyway. It is pinned to the shell at x = 40 rather than taken from the
    # box's east face, on ``dished``'s reason: the ink out at x = 50 is the
    # heater's own casing, and a process nozzle does not belong on it.
    ("vessel", "electrical_heating"): (
        "vessels", "Vessel (Dished Ends, Electrical Heating)",
        {"inlet": ("W", 47.7), "outlet": ("AT", 40.0, 77.7), "vent": ("N", 20.0),
         # Shell at x 0..40, so cx = 20 and the heads give 8 and 95.38. The
         # element hangs off the east wall between y 27.69 and 67.69 and the
         # drain is below all of it, so unlike the outlet above it needs no
         # dodging: it is the family's bottom crown, unmoved.
         "relief": ("AT", 8.0, 1.5), "drain": ("S", 20.0)}),
    # Skirted: the same 40-wide shell as "dished", standing on a skirt instead
    # of brackets. Nothing widens the box here, so the shell walls ARE the box's
    # west and east faces and the two process nozzles take them directly.
    #
    # The drain is the one nozzle here that cannot take the box's south face.
    # ``skirted`` and ``legs`` are 122.69 tall over a vessel that ends at 95.38,
    # and there is no ink at all across the bottom of the box -- the skirt is
    # two lines with a foot turned off each, the legs two rects, and between
    # them 24 units of nothing. So the drain goes on the bottom head's crown at
    # (20, 95.38), which is the vessel's low point and is what the pipe would
    # actually leave from, and comes out of the west face at this box's own
    # aspect. The block at ``vessel/default`` argues why that is the right way
    # round to be wrong.
    ("vessel", "skirted"): ("vessels", "Vessel (Dished Ends, Skirts)",
                            {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                             "vent": ("N", 20.0),
                             "relief": ("AT", 8.0, 1.5),
                             "drain": ("AT", 20.0, 95.4)}),
    # Legs: "skirted"'s vessel on a pair of legs. The two stencils draw the same
    # shell and the same heads from the same path -- x 0..40, straight between
    # y 7.69 and 87.69, heads out to y = 0 and 95.38 -- in the same 40 x 122.69
    # box, and differ only in what stands under y = 87.69: two rects at x 0..8
    # and 32..40 here, a pair of skirt lines there. Nothing a nozzle sits on
    # moves, so this takes ``skirted``'s port map verbatim, which is what a
    # change of variant is supposed to cost.
    ("vessel", "legs"): ("vessels", "Vessel (Dished Ends, Legs)",
                         {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                          "vent": ("N", 20.0),
                          "relief": ("AT", 8.0, 1.5),
                          "drain": ("AT", 20.0, 95.4)}),
    # Swaged: one vessel in two diameters, the narrow section on top of the wide
    # one with a cone between them at y 40..50. It comes out at 50 x 97.5, in
    # among ``jacketed``'s 52 x 95.38 and ``dished``'s 60 x 95.38 rather than
    # standing out beside them.
    #
    # Both process nozzles go on the WIDE section, which is the one whose walls
    # are the box's own west and east faces (x = 0 from y 50.25 to 85, x = 50
    # from y 50 to 85); the narrow shell's walls are at x = 10 and x = 40,
    # inboard of the box, and a pair placed up there would be the only nozzles
    # in the family not on the box edge for no gain. 67 is that wide section's
    # mid-height, so the two are level, as they are on every sibling.
    #
    # The vent is the top head's crown, at (25, 0). That head is a true
    # semicircle rather than the family's flattened one: the stencil asks for
    # r = 10 over a 30-wide chord, which SVG scales up to the r = 15 the chord
    # needs, so the arc springs from y = 15 and its crown lands exactly on the
    # box's top edge rather than a fraction under it.
    #
    # The relief goes on that same true semicircle, r = 15 about (25, 15), so
    # x = 16 puts it at y = 15 - sqrt(15^2 - 9^2) = 3 -- the 3-4-5 triangle, not
    # the flattened family's 0.6-of-a-radius rule, because this head is not that
    # head. The drain is the bottom ellipse's crown at (25, 97.5), on the WIDE
    # section, which is where a two-diameter vessel holds its liquid.
    ("vessel", "swaged"): ("vessels", "Vessel (Different Diameters)",
                           {"inlet": ("W", 67.0), "outlet": ("E", 67.0),
                            "vent": ("N", 25.0),
                            "relief": ("AT", 16.0, 3.0), "drain": ("S", 25.0)}),
    # The third roof that rises inside its bounding box: the shell is open
    # between x = 5 and x = 95 at y = 0 (that gap is what the roof floats in),
    # so anything on the box's top edge is drawn in mid-air 5 units above the
    # roof plate. The plate spans x 5..95 at y = 5, and the vent and the relief
    # go on it, 15 either side of its middle. A floating roof has no vapour
    # space to conserve and is not what a conservation vent is for; the nozzles
    # are still here because a declared nozzle is offered rather than asserted,
    # which is the argument in ``units.Tank``, and because a rim vent and a roof
    # bleeder are connections a floating roof does have.
    #
    # THE FILL HAS NO ROOF PLACEMENT AT ALL, and this is the one variant where
    # that is not a default but a fact about the drawing (#226). A floating roof
    # rides on the liquid: there is no fixed roof to weld a nozzle to, and the
    # plate the reader sees at y = 5 is the deck, drawn at whatever level the
    # tank happens to be at. A fill line landing on it is a pipe joined to a
    # moving deck. So the shell wall is the whole menu -- west or east at y =
    # 60, ten above the floor -- and ``nozzle("inlet", "N")`` raises rather than
    # drawing something the plant cannot have. ``examples/14``'s TK-601 was
    # taking its motor spirit onto the deck.
    ("tank", "floating_roof"): ("vessels", "Tank (Floating Roof)",
                                {"inlet": [("W", 60), ("E", 60)],
                                 "outlet": ("S", 50),
                                 "vent": ("AT", 15.0, 5.0),
                                 "relief": ("AT", 45.0, 5.0),
                                 "drain": ("S", 20)}),
    # ...and the third: the sphere rides on a support skirt inside its box, so
    # its crown is at (40, 5) and the box's top and bottom edges are the skirt,
    # not the vessel.
    #
    # THIS IS THE ONE STENCIL IN THE LIBRARY THAT DRAWS ITS NOZZLES AS NOZZLES
    # (all 157 registered symbols were swept for a second; there is none -- see
    # ``tests/test_symbol_invariants.py``'s drawn-nozzle check). Three 12 x 12
    # rectangles, each with a flange line ruled across its free face: two on the
    # crown at x 18..30 and 50..62, faces at y = 0, and one under the belly at
    # x 34..46, face at y = 90. A rectangle drawn on a vessel is a statement
    # that a connection exists *there*, so a port anywhere else on this drawing
    # is the drawing disagreeing with itself. That is issue #225, and the whole
    # of what it costs is that three nozzles have to carry five duties.
    #
    # WHICH THREE DUTIES GET THE NOZZLES. Two of the five are fixed by
    # something other than preference and both are on top. CHEE4001 p.7 puts the
    # protective device there -- "The PSV should be placed, whenever possible,
    # directly on the system to be protected, vertically, upward, and at the top
    # of the container" -- so ``relief`` takes a crown rectangle. ``vent`` is
    # the vapour connection and a vapour space is at the top of a vessel by
    # definition, so it takes the other. Which rectangle is which is arbitrary;
    # they are one drawing twice. That leaves the belly nozzle for one of the
    # three liquid duties, and ``outlet`` has it: the draw is what the vessel is
    # piped for on every day of its life, and on this sheet it is the whole
    # reason the sphere is drawn at all (``examples/14``'s butane leaves under
    # its own pressure and needs no pump). It also had the more visible half of
    # the defect -- the outlet sat at (40, 100), on the base rail of the support
    # skirt, so the sheet drew product leaving the *structure* 10 units below
    # the nozzle the stencil drew for it.
    #
    # WHERE THE OTHER TWO GO. ``inlet`` and ``drain`` are both liquid and both
    # therefore belong low, which is also the research issue #226 recorded for
    # this vessel: an LPG sphere takes liquid in and out at the lowest part of
    # the shell and reserves the crown for relief and vapour. They go on the
    # shell either side of the belly nozzle, which is the ordinary convention
    # and what every other stencil in the library does with every nozzle it has
    # -- 156 of 157 draw no nozzle at all and let the line stop at the wall.
    # They are NOT stacked on the belly rectangle with the outlet: two ports on
    # one placement draw two streams on one point, which
    # ``Symbol.coincident_ports`` refuses and is right to.
    #
    # All three sit on the ellipse (cx 40, cy 45, r 40), so each coordinate is
    # the circle solved for the height wanted:
    #
    #   inlet, the fill, at y = 75:   x = 40 -+ 40*sqrt(1 - (30/40)^2) = 13.5 / 66.5
    #   drain, the water draw-off, at y = 82.1: x = 40 + 40*sqrt(1 - (37.1/40)^2) = 54.9
    #
    # The fill is the one port here with a face to choose, so it is the one with
    # a menu: west by default and east on request, since a sphere is filled from
    # whichever side the header runs down. 75 rather than 82.1 is what buys it
    # those faces -- at 82.1 the point is nearer the box floor than either wall
    # and ``outward_dir`` reads it as south, and a fill drawn arriving from
    # underneath is a line the reader has to follow around the vessel to
    # believe. The drain keeps south, which is the face its role asks for
    # (``tests/test_symbol_invariants.py``) and where a low-point draw-off goes.
    #
    # The crown is deliberately left with no fill placement on it. A pressure
    # sphere's two top connections are spoken for, and offering ``inlet`` an
    # "N" it would have to share with the relief or the vent is offering a
    # nozzle the drawing cannot honour.
    ("tank", "sphere"):        ("vessels", "Storage Sphere",
                                {"inlet": [("AT", 13.5, 75.0), ("AT", 66.5, 75.0)],
                                 "outlet": ("AT", 40.0, 90.0),
                                 "vent": ("AT", 24.0, 0.0),
                                 "relief": ("AT", 56.0, 0.0),
                                 "drain": ("AT", 54.9, 82.1)}),
    # Tanks that drain to a cone rather than to a floor. The four above vary the
    # roof and all of them stand on a flat bottom; a hopper is what anything
    # holding solids, a slurry or a settled phase is actually drawn with, and
    # the family had none.
    #
    # ALL THREE KEEP THE CROWN AS THEIR DEFAULT FILL, where the flat-floored
    # four moved theirs to the shell (#226, argued at ``tank/default``). The
    # reason a flammable liquid is filled low is the static a splash fill
    # generates in a vapour space, and a hopper is the drawing for solids, a
    # slurry or a settled phase, filled over the top the way a silo is. The low
    # shell nozzle is offered on both walls all the same, since the shape is
    # also what a liquid tank with a drain cone is drawn as, and #226's
    # complaint was that the library permitted only one arrangement.
    #
    # The outlet goes on the cone's APEX, which is the same rule the roofs above
    # follow at the other end: a cone touches the box's bottom edge at one point
    # and curves away from it either side, so a nozzle anywhere else on that
    # edge hangs in the air beside the drawing. It is the cheaper of the two to
    # say, though, because that one point is the middle of the south face, so
    # ("S", 50) lands on it and no ("AT", ...) is needed -- where a dished roof's
    # crown is inboard of the top edge and has to be named outright.
    #
    # Flat roof, conical bottom: 100 x 100, on the family's 100-unit width. The
    # roof is a plain line across y = 0 from x 0 to 100, so the inlet takes the
    # north face directly, and the cone runs from y = 70 down to its apex at
    # (50, 100).
    #
    # The roof is flat, so the vent and the relief take the north face directly
    # at x = 35 and 65, as the inlet does. The drain cannot take the south face:
    # a cone touches the box's bottom edge at one point and the outlet is on it.
    # It goes half way down the cone's west slope, from (0, 70) to the apex at
    # (50, 100), which is (35, 91) -- still south-facing, since 9 units of
    # bottom clearance beat 35 of side.
    # The shell walls run from y = 0 to y = 70 where the cone springs, so the
    # two alternate fills take them at y = 60.
    ("tank", "conical_bottom"): ("vessels", "Tank (Conical Bottom)",
                                 {"inlet": [("N", 50), ("W", 60), ("E", 60)],
                                  "outlet": ("S", 50),
                                  "vent": ("N", 35), "relief": ("N", 65),
                                  "drain": ("AT", 35.0, 91.0)}),
    # A cone at each end: the silo or bin a tank holding solids is drawn as.
    # Called ``conical_ends`` and not ``conical_roof_bottom`` for the reason
    # ``vessel/dished`` is called that after "Vessel (Dished Ends, Brackets)":
    # naming the pair of ends is how this file says both, and the alternative
    # reads as easily as "the bottom of a conical roof" -- which is a different
    # place on the drawing. ``conical`` already means the roof alone, so the
    # three names line up: one cone on top, one underneath, or one at each end.
    #
    # 101 x 150, and the tallest thing in the family by half again. That is the
    # shape and not the scale: it is 101 wide, which is the 100 every other tank
    # here is drawn at, and the extra height is the two 30-unit cones over and
    # under a shell that is itself only 20 taller than ``conical``'s. Squashing
    # it to the family's height would draw shallower cones than the stencil
    # author drew, and the cone angle is what the variant is about.
    #
    # Both nozzles sit at x = 51 rather than 50 because the drawing does: the
    # stencil puts its shell walls at x = 1 and x = 101 in a box 101 wide, so
    # the two apexes are on the SHELL's centreline, half a unit right of the
    # box's, and a nozzle at 50 would be half a unit off the point of the cone.
    #
    # Both cones are half as steep as they are wide -- 30 of rise over 50 of
    # run -- so the midpoint of each slope is 25 across and 15 down from its
    # apex: (26, 15) and (76, 15) on the roof, (26, 135) on the floor. All three
    # keep the shell's x = 1..101, so the pair on the roof are as far either
    # side of the fill as ``default``'s are, scaled to a taller drawing.
    # The alternate fills take the shell walls at y = 110, ten above the cone.
    # The west one is named outright: the wall is at x = 1 rather than at the
    # box edge, for the same half-unit reason the two apexes are at x = 51.
    ("tank", "conical_ends"): ("vessels", "Tank (Conical Roof and Bottom)",
                               {"inlet": [("N", 51), ("AT", 1.0, 110.0), ("E", 110)],
                                "outlet": ("S", 51),
                                "vent": ("AT", 26.0, 15.0),
                                "relief": ("AT", 76.0, 15.0),
                                "drain": ("AT", 26.0, 135.0)}),
    # Dished roof over a conical bottom: ``default``'s tank with the floor
    # opened out into a cone, and it takes ``default``'s port map verbatim,
    # character for character. The roof is the same arc drawn over the same
    # 100-wide chord, so its crown is the same (50, 6.4) -- the stencil asks for
    # r = 75 over a chord of 100, so the arc rises 75 - sqrt(75^2 - 50^2) = 19.1
    # above the springing line at y = 25.46 and stops at 6.4, leaving the top
    # 6.4 units of the box empty. The outlet's ("S", 50) resolves to
    # the cone apex at (50, 125.46) where on ``default`` it resolved to the flat
    # floor: same spec, same face, different ink, which is what a variant is.
    # The roof nozzles are ``default``'s too, at (35, 7.9) and (65, 7.9), for
    # the same arc, and the shell walls are ``default``'s as well -- y 25.46 to
    # 95.46 -- so the alternate fills take them at the same y = 85. Only the
    # drain differs, and for ``conical_bottom``'s reason: the apex is the
    # outlet's, so the drain takes the west slope's midpoint, from (0, 95.46) to
    # (50, 125.46), which is (35, 116.5). The fill's *default* differs too, for
    # the reason given at ``conical_bottom``: this one stands on a hopper, so
    # the crown keeps it.
    ("tank", "dished_roof_conical_bottom"): (
        "vessels", "Tank (Dished Roof, Conical Bottom)",
        {"inlet": [("AT", 50.0, 6.4), ("W", 85), ("E", 85)], "outlet": ("S", 50),
         "vent": ("AT", 35.0, 7.9), "relief": ("AT", 65.0, 7.9),
         "drain": ("AT", 35.0, 116.5)}),
    # Two more shapes in vessels.xml were weighed with those and left out, and
    # both for the same reason: a nozzle a class has no name for is a nozzle
    # that cannot be drawn.
    #
    #   "Tank (Boot)", and the covered and floating-roof tanks drawn with one --
    #   the sump welded under one end that a settled water phase is drawn off
    #   separately from the product. The boot IS the variant: a tank with one
    #   drawn and piped like a tank without one says nothing the plain tank does
    #   not, and Tank.PORTS was inlet/outlet, so there was no third draw to put
    #   on it. That half of the objection is now spent -- issue #222 gave Tank
    #   the ``drain`` a settled phase leaves by, which is exactly the boot's
    #   draw -- and the shapes are still out, because the change that lets them
    #   in is a vendoring with its own measurements and its own place in the
    #   variants table, not a line added to a port map.
    #
    #   "Vessel (Full-Tube Heating-Cooling Coil)" and its semi-tube sibling --
    #   a 120 x 70 box holding a bare 100 x 70 rect, with the coil's four cut
    #   tube ends drawn as circles beside it at (5, 25), (5, 55), (115, 15) and
    #   (115, 45). Those four are
    #   the only nozzles the shape draws and all four are the coil's, which
    #   Vessel has no port for; inlet and outlet would land on plain casing
    #   wall, which is what ``pump/peristaltic`` refuses on this same principle
    #   (a drawn nozzle wins). There is nothing else to weigh against it either:
    #   no head, no crown and no drawn level, so the vessel family's own reason
    #   for not turning would have to be invented for it as well.
    # Reactor / separator styles. The straight wall spans y 7.69..87.69.
    ("reactor", "plain"):     ("vessels", "Reactor",
                               {"feed": ("SERIES", "W", 30, 14, 0.4),
                                "outlet": ("S", 20), "duty": ("E", 47),
                                "vent": ("AT", 30.0, 7.69)}),
    # Horizontal vessel: reflux drum, accumulator, knock-out pot. A lying
    # cylinder with dished ends: the shape a vertical vessel does NOT become
    # when rotated, since its saddles and shell bands would turn with it.
    # Inlet on either head or from above, liquid out of the bottom, vent off the
    # top; the top and bottom faces span x 5.77..85.77.
    #
    # The outlet takes no alternate: liquid draws off the bottom, and the right
    # head is already the inlet's alternate. Giving both an "E" option would
    # land two nozzles on the same point.
    #
    # A lying drum has no crown and no bottom head: the whole top wall is the
    # top of the vessel and the whole bottom wall its low point, so the relief
    # and the drain take the two faces directly rather than being measured onto
    # a curve. 30 and 25 keep both clear of the three placements the inlet may
    # take and of the outlet at 68.
    ("vessel", "horizontal"): ("vessels", "Drum or Condenser",
                               {"inlet": [("W", 15), ("N", 20.0), ("E", 15)],
                                "outlet": ("S", 68.0),
                                "vent": ("N", 55.0),
                                "relief": ("N", 30.0), "drain": ("S", 25.0)}),
    # The same shape as a horizontal phase separator, where naming the vapour
    # and liquid products is the point. Neither product takes an alternate face:
    # vapour always disengages off the top, liquid draws off the bottom.
    ("separator", "horizontal"): ("vessels", "Drum or Condenser",
                                  {"feed": [("W", 15), ("N", 20.0), ("E", 15)],
                                   "vapor": ("N", 30.0),
                                   "liquid": ("S", 68.0)}),
    ("separator", "cyclone"): ("separators", "Separator (Cyclone)", {"feed": "W", "vapor": "N", "liquid": "S"}),
    # Gas-cleaning vessels: hopper-bottomed box, gas across the top and the
    # collected phase out of the apex at (40, 120). The scrubber's wash-liquid
    # header is drawn on the centreline, so the clean gas leaves sideways rather
    # than through the top face.
    ("separator", "scrubber"): ("separators", "Separator (Wet Scrubber)",
                                {"feed": "W", "vapor": "E", "liquid": "S"}),
    # ``gravity``, ``electrostatic`` and ``electromagnetic`` are deliberately NOT
    # vendored. All three are this same hopper-bottomed body carrying one ISO
    # 10628-2 group-29 characteristic -- items 8.3 X8031, 8.6 X8125 and 8.8
    # X8126 -- and the standard composes them itself, so pandid composes them
    # too: ``SymbolRegistry._register_composed`` builds each from
    # ``symbols._SEPARATING_VESSEL`` and the mark in ``render/iso_parts.py``.
    #
    # Vendoring a stencil for them as well would put a second drawing of each in
    # the library with nothing to say which is the live one, which is the fault
    # ``column/default`` already had (report 04, finding F-0).
    #
    # The five that stay vendored stay because ISO gives each a distinct
    # registered symbol and group 29 has nothing to build them out of: no
    # vortex, no baffle, no spray and no permanent magnet anywhere in it.
    # The mechanical separators, which sort by size, inertia or magnetism rather
    # than into phases. All four are the same body as the two above, anchor for
    # anchor: 80 x 120, W (0, 12) and E (80, 12) on the two side walls (which
    # span y 0..80, so both are on ink at any box the unit is drawn at), and S
    # on the hopper apex at (40, 120). Only the internals tell them apart: the
    # sifter's screen deck, the impact separator's baffle down the centreline,
    # and the magnet's coil or block low in the body.
    #
    # The port map follows from that and from nothing else. A high draw and a
    # low draw is all the artwork commits to, so ``overflow`` and ``underflow``
    # name the two positions and leave which of them is the product to the
    # service, exactly as ``shell``/``tube`` leaves which side is the hot one to
    # the operating case. Naming either for its contents would be guessing: the
    # same drawing is a scalping screen and a sizing screen.
    ("separator", "sifter"): ("separators", "Separator, Sifter",
                              {"feed": "W", "overflow": "E", "underflow": "S"}),
    ("separator", "impact"): ("separators", "Impact Separator",
                              {"feed": "W", "overflow": "E", "underflow": "S"}),
    ("separator", "permanent_magnet"): ("separators", "Separator (Permanent Magnet)",
                                        {"feed": "W", "overflow": "E", "underflow": "S"}),
    # Filter styles. Press Filter's own W/E anchors sit on opposite *corners* of
    # the box, so both faces are placed on the plate pack's mid-height instead.
    ("filter", "gas"):    ("filters", "Gas Filter (Bag, Candle, Cartridge)",
                           {"inlet": "W", "outlet": "E"}),
    ("filter", "press"):  ("filters", "Press Filter",
                           {"inlet": ("W", 25.0), "outlet": ("E", 25.0)}),
    ("filter", "rotary"): ("filters", "Liquid Filter (Rotary, Drum or Disc)",
                           {"inlet": ("W", 50.0), "outlet": "E"}),
    # The same drum with the knife that lifts the cake off it. That knife is the
    # whole of what tells the two drawings apart, and the drum is set 7 units
    # left to make room for its arm.
    #
    # The arm reaches out to x = 55 while the casing stays the 50 the rest of
    # the family is drawn at, so the bounding box is 5 units wider than the
    # equipment -- exactly what ``vessel/dished``'s brackets do, and it gets
    # ``vessel/dished``'s answer. A nozzle on the box's east face would be drawn
    # in the air beside the casing, so the outlet is pinned to the casing wall
    # instead. draw.io's own "E" is at 0.91 x 55 = 50.05, which is that same
    # wall rounded to two places; naming 50 outright says so, rather than
    # leaving a nozzle a twentieth of a unit outside the equipment for the next
    # reader to measure. Nothing widens the west side, so the inlet keeps the
    # box's own face there.
    ("filter", "rotary_scraper"): ("filters", "Liquid Filter (Rotary, Drum or Disc, Scraper)",
                                   {"inlet": ("W", 50.0), "outlet": ("AT", 50.0, 50.0)}),
    # Ion exchanger: the resin bed between its two retention screens, the water
    # treatment vessel every demineraliser train is drawn with. The stencil
    # names only N and S, but the whole 50 x 100 casing is stroked, so the side
    # walls carry the same W/E faces the rest of the filters use: a change of
    # variant is a change of artwork, not of piping.
    ("filter", "ion_exchange"): ("filters", "Liquid Filter (Ion Exchanger)",
                                 {"inlet": ("W", 50.0), "outlet": ("E", 50.0)}),
    # Two more media, each drawn twice by the stencil set: once in a liquid
    # casing and once in a gas one. The gas half of a pair adds the hopper below
    # the medium and changes nothing else, and that hopper is the reason both
    # halves ship: it is where what the medium sheds lands, so it is also what
    # fixes the gas two the right way up and leaves the liquid two free to turn
    # (see GRAVITY_FIXED).
    #
    # All four are piped straight across on the casing's side walls at
    # mid-height, which is ``ion_exchange``'s placement and its reason: draw.io
    # names a different subset of the compass points on each of these four
    # (``fixed_bed`` has N and S alone, and the two ``belt`` shapes have three
    # each, but not the same three), while the casing rect is stroked all the
    # way round, so both walls carry a face whether the stencil named it or not.
    # Choosing between these variants is a statement about the medium, so they
    # are piped alike and a sheet can swap one for another without moving a run.
    #
    # Fixed bed: granular medium -- sand, anthracite, activated carbon -- held
    # between the two retention screens the X is drawn between.
    ("filter", "fixed_bed"):     ("filters", "Liquid Filter (Fixed Bed)",
                                  {"inlet": ("W", 50.0), "outlet": ("E", 50.0)}),
    ("filter", "gas_fixed_bed"): ("filters", "Gas Filter (Fixed Bed)",
                                  {"inlet": "W", "outlet": ("E", 50.0)}),
    # Belt / roll: the medium is a cloth running between two rollers, drawn low
    # in the casing at y 59..71, so nozzles at mid-height clear it rather than
    # being piped into the roll.
    ("filter", "belt"):          ("filters", "Liquid Filter (Belt, Roll)",
                                  {"inlet": ("W", 50.0), "outlet": "E"}),
    ("filter", "gas_belt"):      ("filters", "Gas Filter (Belt, Roll)",
                                  {"inlet": "W", "outlet": ("E", 50.0)}),
    # Drier styles. A spray drier is fed through the atomiser in its roof and
    # drops powder out of the floor, so it is piped top-to-bottom, not across.
    ("dryer", "fluidized_bed"): ("driers", "Drier (Fluidized Bed)",
                                 {"feed": "W", "product": "E"}),
    ("dryer", "spray"): ("driers", "Spray Drier",
                         {"feed": ("N", 50.0), "product": ("S", 50.0)}),

    # --- New classes (genuinely different port signature / function) ---
    # The process coil is drawn entering at (0, 54.5) and leaving at (80, 79.5);
    # the W/E anchors sit on blank casing wall at mid-height instead, which also
    # destroys the high-in / low-out reading of the coil.
    ("furnace", "default"): ("vessels", "Furnace",
                             {"inlet": ("W", 54.5), "outlet": ("E", 79.5), "fuel": "S"}),
    ("turbine", "default"): ("pumps", "Turbine", {"inlet": "W", "outlet": "E"}),
    ("filter", "default"):  ("filters", "Liquid Filter (Bag, Candle, Cartridge)", {"inlet": "W", "outlet": "E"}),
    ("dryer", "default"):   ("driers", "Rotary Drum Drier, Tumbling Drier", {"feed": "W", "product": "E"}),
    # Steam/gas ejector: motive fluid into the steam chest, entrained fluid up
    # through its floor, mixture out of the diffuser cone. The stencil's own "S"
    # anchor lands on the chest's bottom-*right* corner, where the cone starts,
    # so the suction nozzle is placed mid-face instead.
    ("ejector", "default"): ("fittings", "Injector",
                             {"motive": "W", "suction": ("S", 20.0), "discharge": "E"}),
    # Open ends. Each is a stem with something on top of it, so the single pipe
    # connection is the free end of that stem, at the bottom of the box.
    ("vent", "default"):   ("fittings", "Vent", {"inlet": ("S", 40.0)}),
    ("funnel", "default"): ("fittings", "Funnel", {"outlet": ("S", 40.0)}),
    # Two more open ends, from piping.xml. Both discharge to atmosphere and are
    # piped from below, so each has the one connection a Vent declares, on the
    # point of the body the riser meets. draw.io names W and E on the exhaust
    # head, which is its generic box anchors rather than a flow path: nothing
    # passes through an open discharge.
    #
    # Exhaust head: the silencing/separating hood on a steam or relief vent.
    # The riser meets the apex of the cone at (25, 40).
    ("vent", "exhaust_head"): ("piping", "Exhaust Head", {"inlet": ("S", 25.0)}),
    # Breather: the tank conservation vent, drawn as a box on a stem. The stem's
    # free end at (25, 30) is the tank connection.
    ("vent", "breather"):     ("piping", "Breather", {"inlet": ("S", 25.0)}),
}


# Devices the stencil set draws twice: once open, once closed.
#
# These are not two shapes a user picks between. They are one device in two
# positions, and the position is a property of the unit
# (``Fitting(normal_position="closed")``), exactly as it is on a Valve. The
# generator emits the second shape as a second Symbol, registered under the same
# (kind, variant) through ``SymbolRegistry.register_closed``, so the name a user
# writes stays the name of the device.
#
# Both shapes go through the same port map and the same SCALE, and render()
# refuses to emit a pair whose boxes, nozzles or aspect disagree: two positions
# of one device must differ in ink and in nothing else, or declaring the
# position would move a line already drawn.
#
# Only the figure-8 pair is mapped. fittings.xml carries two more:
#
#   Open Disc / Blind Disc -- a single disc on a 100-long handle in a 40 x 140
#   box, so 71% of the shape is bare stalk. Scaled until the disc reads, the
#   stalk is most of a centimetre of plain line hanging off the run, which on a
#   P&ID is how a branch is drawn. It also carries no <connections> at all,
#   which is the stencil author saying overlay rather than device -- the same
#   thing that keeps fittings.xml's "Orifice Plate" out of the table above.
#
#   Interchangeable Disc (Open Disc In Function) / (Blind Disc) -- the same
#   drawing as the figure-8 pair: two tangent discs on a handle, one of them
#   filled, at 40 x 140 instead of 20 x 80 (1:3.5 against 1:4). Two mappings a
#   reader cannot tell apart are one mapping and a trap, so this ships once.
#
# (kind, variant) -> the shape drawn when the device is declared normally closed
CLOSED_SHAPES = {
    ("fitting", "blind"): "Closed Figure 8 Blind",
}


# Corrections to the vendored stencils themselves.
#
# vendor_data/drawio/*.xml is a mirror of jgraph/drawio and stays byte-for-byte
# what was vendored, so re-vendoring is a file copy and nothing else. Where a
# shape is *wrong* (not merely a style this library does not use), the
# correction lives here instead: an mxGraph fragment appended to the shape's
# <foreground>, written in the stencil's own drawing language and converted by
# the same converter as the rest of the shape. Provenance therefore stays in
# this file beside KIND_MAP, and a re-vendor cannot quietly drop the fix,
# because a shape a patch cannot find stops the generator (see render()).
#
# This is not a way to draw something the stencil set lacks. A symbol nothing
# upstream draws is a hand-drawn primitive and belongs in symbols.py, under the
# rules in CONTRIBUTING section 1.
#
# (stencil, shape) -> (what is wrong upstream, mxGraph fragment)
STENCIL_PATCHES = {
    # draw.io's "Globe Valve" is a byte-for-byte copy of its "Ball Valve":
    # strip the name and the two shapes' XML is identical, down to the
    # <connections>. Both draw the bowtie whose waist is pinched around an OPEN
    # circle, which is the ball valve (ISO 10628-2 X8071). The globe valve
    # (X8068) is that same seat drawn SOLID, and the contrast between the two is
    # the whole of what tells a reader which valve is in the line, so shipping
    # them identical is not a plain drawing, it is the wrong one.
    #
    # The patch fills the seat, and nothing else: the four arcs below are the
    # stencil's own, quoted from its background and foreground paths in the
    # order that walks the circle once, so the filled region is exactly the seat
    # already drawn rather than a circle re-derived from it. The two triangles
    # that make up the BODY keep their white interiors, which is what keeps this
    # clear of the fully-darkened body that means "normally closed"
    # (PIP PIC001 4.2.2.7).
    ("valves", "Globe Valve"): (
        "identical to Ball Valve upstream; ISO 10628-2 X8068 fills the seat",
        '<fillcolor color="#000000"/>'
        '<path>'
        '<move x="31.9" y="19.7"/>'
        '<arc rx="20" ry="20" x-axis-rotation="0" large-arc-flag="0" sweep-flag="1"'
        ' x="66.2" y="19.7"/>'
        '<arc rx="20" ry="20" x-axis-rotation="0" large-arc-flag="0" sweep-flag="1"'
        ' x="66.2" y="40.5"/>'
        '<arc rx="20" ry="20" x-axis-rotation="0" large-arc-flag="0" sweep-flag="1"'
        ' x="31.9" y="40.5"/>'
        '<arc rx="20" ry="20" x-axis-rotation="0" large-arc-flag="0" sweep-flag="1"'
        ' x="31.9" y="19.7"/>'
        '<close/>'
        '</path>'
        '<fillstroke/>'
    ),
}


def patch_shape(stencil, name, el):
    """Apply :data:`STENCIL_PATCHES` to one parsed <shape>, if it has one.

    The fragment is appended to the shape's <foreground>, so it paints over
    what the stencil already drew, exactly as a stencil author would have
    written it in the first place.
    """
    entry = STENCIL_PATCHES.get((stencil, name))
    if entry is None:
        return el
    _why, fragment = entry
    foreground = el.find("foreground")
    if foreground is None:
        foreground = ET.SubElement(el, "foreground")
    for op in ET.fromstring(f"<foreground>{fragment}</foreground>"):
        foreground.append(op)
    return el


# Stencil-derived symbols this generator cannot emit, and where they live
# instead. It emits one fixed-size Symbol per shape, and a fixed drawing placed
# in a box of a different aspect ratio is scaled unevenly, so a shape that has
# to stretch along one axis only cannot come out of here. Recorded so the
# provenance is in the mapping table with everything else, and so nobody
# "restores" one of these by adding it to KIND_MAP above: doing that would draw
# it at one fixed size and undo the reason it was written by hand.
#
# (kind, variant) -> (stencil, shape_name, where it lives, what was changed)
ADAPTED_ELSEWHERE = {
    ("conveyor", "default"): (
        "driers", "Drier (Roller Conveyor Belt)",
        "pandid.render.symbols.conveyor_symbol",
        "drier housing dropped; roller spacing made a parameter, roller r=10 kept",
    ),
}


# Symbols that must not be turned, as ``Symbol.gravity_fixed``.
#
# ISO 15519-1 §11.4.2, *Orientation of graphical symbols*, permits turning and
# mirroring "in order to fit into the actual layout of the diagram", and then:
#
#     Exceptions for turning are symbols representing components or devices
#     where gravity is a functionality, for example symbol 2061: Open tank or
#     symbol X 2618: Cyclone separator; see Figure 22 b). Such symbols must not
#     be turned.
#
# Figure 22 b) draws those two: an open-topped U, and a body whose conical apex
# points down with the vortex spiralling into it. Both are devices whose *job* is
# done by gravity, and both say something the plant cannot do once turned.
#
# The test applied here is that one, not "stands on the ground": every piece of
# plant does. A symbol is listed when the separation, containment or holdup it
# depicts is performed by gravity **and the artwork draws it**: a free liquid
# surface, an open top, a settling or classifying body with a low-point draw, a
# falling-solids path. A device whose function is pressure, rotation, heat
# transfer or throttling is not listed even when a nozzle happens to sit low,
# because it is installed in whatever attitude the run wants and turning its
# symbol states nothing false.
#
# What that leaves out, and why:
#
# * ``hex/kettle`` -- its bottoms draw is at the weir end and low, but an
#   exchanger's function is heat transfer and the artwork draws no level. The
#   rest of the shell-and-tube family is freely turnable and this one shares it.
# * ``valve/bleed`` -- inlet N / outlet S encodes a *piping arrangement* (the
#   stencil draws the tap running down into the bowtie), and varying a piping
#   arrangement is what ``pin()`` and ``nozzle()`` are for. A bleeder tapped off
#   the top of a line is the same device.
# * ``conveyor`` -- its artwork is two rollers and a bar, symmetric top to
#   bottom, so a turn makes nothing in the drawing false; the gravity fact about
#   a belt lives in its port alternates (feed from above, discharge from
#   underneath), which the symbol already fixes. ISO cites the conveyor in
#   §13.1 as the case for a *horizontal-view* layout, which is about the sheet
#   rather than about the symbol.
# * ``dryer/default`` -- a rotary drum drawn as a circle in a box; nothing in it
#   is up or down. Contrast ``dryer/spray`` and ``dryer/fluidized_bed`` below.
# * ``fitting/*`` and every LIQUID ``filter`` -- plate packs, cartridges, resin
#   and media beds, and a cloth on its rollers, all drawn as bands in a box and
#   all driven by pressure drop across the medium. A bed rests on its support
#   the way every piece of plant rests on the ground; nothing in the artwork is
#   a level, a hopper or a fall. The gas ones are listed below, and they are
#   listed for the hopper drawn under the medium rather than for the medium.
#
# (kind, variant) -> what in the artwork only means one thing one way up
GRAVITY_FIXED = {
    # ISO's own example, X 2618: the vortex drops the heavy phase out of the
    # apex. The six siblings separate by density the same way (one of them is
    # called ``gravity``), and the three hopper-bottomed ones collect out of an
    # apex exactly as the cyclone does.
    #
    # ``default`` no longer draws the demister its reason used to name, so the
    # reason is now the disengagement itself, in the same words ``horizontal``
    # already uses: the two are one stencil family in two attitudes and the
    # fact that fixes them is the same fact.
    ("separator", "default"):       "vapour disengages off the top, liquid draws off the bottom",
    ("separator", "cyclone"):       "ISO 15519-1 symbol X 2618; apex points down",
    ("separator", "horizontal"):    "vapour disengages off the top, liquid draws off the bottom",
    ("separator", "knockout"):      "demister on top, vapour up and liquid down",
    ("separator", "scrubber"):      "hopper bottom under a wash-liquid header",
    # The four mechanical separators, listed for the reason ``electrostatic``
    # already is rather than for what does the separating. A precipitator sorts
    # by charge and a magnet by magnetism, and neither is gravity; what fixes
    # the attitude in both is the hopper the artwork draws under them, and the
    # fall into it. Turned, the hopper is a roof and nothing collects.
    ("separator", "sifter"):           "screen deck over a hopper; the undersize falls through it",
    ("separator", "impact"):           "hopper bottom under the baffle, collected phase out of the apex",
    ("separator", "permanent_magnet"): "hopper bottom, separated fraction out of the apex",
    # ISO's other example, 2061: Open tank. Every variant holds a liquid with a
    # free surface, fills at the roof and drains at the low point; the floating
    # roof is drawn floating on that surface. On the three hopper-bottomed ones
    # that low point is a cone, which is the same fall the hopper-bottomed
    # separators above are listed for: turned, the cone is a roof and the tank
    # holds nothing and drains nowhere.
    ("tank", "default"):        "dished roof over a free surface, draw at the floor",
    ("tank", "conical"):        "conical roof over a free surface, draw at the floor",
    ("tank", "floating_roof"):  "the roof floats on the liquid",
    ("tank", "sphere"):         "stands on a skirt; relief and vapour on the crown, liquid below",
    ("tank", "conical_bottom"): "flat roof over a free surface, drains to the cone apex",
    ("tank", "conical_ends"):   "conical roof over a free surface, drains to the cone apex",
    ("tank", "dished_roof_conical_bottom"):
        "dished roof over a free surface, drains to the cone apex",
    # Holdup with a vapour space: every variant carries its vent on the top head
    # and drains from the shell, and four of them draw the skirt, brackets, legs
    # or saddles they stand on. ``Vessel``'s own docstring already says this in
    # prose, "the outlet still has to drain from the bottom whichever way the
    # artwork is spun", and ``horizontal`` is the variant that sentence points
    # at, which is ISO's recommended escape hatch: a new symbol drawn to the
    # actual orientation, not the upright one turned.
    ("vessel", "default"):    "vent on the top head, free surface below it",
    ("vessel", "dished"):     "vent on the top head; stands on brackets",
    ("vessel", "dome"):       "the manway dome is on top",
    ("vessel", "horizontal"): "vent off the top, liquid out of the bottom",
    ("vessel", "jacketed"):   "vent on the top head, free surface below it",
    ("vessel", "skirted"):    "vent on the top head; stands on a skirt",
    ("vessel", "legs"):       "vent on the top head; stands on legs",
    ("vessel", "insulated"):  "vent on the top head, free surface below it",
    ("vessel", "electrical_heating"): "vent on the top head, low draw-off from the shell",
    # The swage is a second fact on top of the family's. A vessel drawn wide at
    # the bottom and narrow at the top holds its inventory in the larger
    # diameter and its vapour in the smaller one; turned, the two diameters are
    # side by side and the drawing says nothing about either.
    ("vessel", "swaged"):     "vent on the top head, and the larger diameter is the one below it",
    # A tower works because liquid runs down over the trays and vapour rises
    # through them: distillate leaves the top head, bottoms the bottom one, and
    # the packed variant draws the beds resting on their support grids.
    ("column", "default"): "distillate off the top, bottoms off the floor",
    ("column", "packed"):  "packed beds rest on their support grids",
    # A charge vessel: the agitator hangs into it from above and the contents
    # drain out of the dished bottom, with the off-gas taken from the top.
    ("reactor", "default"):  "top-entering agitator over a dished bottom",
    ("reactor", "mixing"):   "top-entering agitator over a conical bottom",
    ("reactor", "jacketed"): "top-entering agitator over a dished bottom, inside its jacket",
    ("reactor", "plain"):    "vent on the top head, outlet in the floor",
    # Open ends. What leaves a vent rises, and what would otherwise fall into it
    # is what the weather cap and the exhaust head's V-bottom drain are for; a
    # funnel is charged by pouring into it. Turned, each of these is drawn as
    # something else: an open end pointing down is a drain, not a vent.
    ("vent", "default"):      "weather cap on top of the stack",
    ("vent", "breather"):     "the tank conservation vent sits on the roof",
    ("vent", "exhaust_head"): "the V-bottom catches and drains condensate",
    ("funnel", "default"):    "open cone above a stem that drains down",
    # Solids that fall. The spray drier atomises into its roof and drops powder
    # out of the floor; the fluidised bed is a layer held down by gravity and
    # lifted by the gas through its distributor, and the artwork draws it as a
    # horizontal band of particles on that plate.
    ("dryer", "spray"):         "atomiser in the roof, powder out of the floor",
    ("dryer", "fluidized_bed"): "the bed is a layer on its distributor plate",
    # The three filters drawn with a dust hopper. It is the whole difference
    # between each gas casing and the liquid one beside it, and what it draws is
    # a fall: the dislodged cake drops off the medium and is collected out of
    # the apex, exactly as the hopper-bottomed separators above collect. Turned,
    # the hopper is a roof and the dust falls out of the filter.
    ("filter", "gas"):           "dust hopper under the bags",
    ("filter", "gas_fixed_bed"): "dust hopper under the bed",
    ("filter", "gas_belt"):      "dust hopper under the belt",
}

# Symbols whose artwork states a *direction of flow* that an axis flip would
# reverse -- either mirror, and the half turn that is the two of them composed.
# See ``Symbol.directional``: the placement still moves the nozzles, and the
# renderer holds the drawing still under it rather than drawing the statement
# backwards. A quarter turn is carried rather than reversed and is left alone.
#
# One family, drawn from two stencils that differ in nothing else. "Heater" and
# "Condenser" are the same circle and the same zigzag on the same diagonal, and
# which of the two a reader is looking at is *only* which end of that diagonal
# carries the arrowhead. Flip either and the head lands at the far end, which is
# where the other one draws it, so the sheet says heat is added where it is
# removed. Nothing else vendored here has a mark of that kind: every other
# arrowhead in the set (a separator's falling solids, a conveyor's belt) points
# the way gravity or the run does, and those symbols are held one way up by
# ``GRAVITY_FIXED`` or are built to their run instead.
#
# The reason is carried into the generated file, since that is where a reader
# meets the keyword.
DIRECTIONAL = {
    ("heater", "default"): "the arrowhead on the diagonal is the whole of what "
                           "makes this a heater and not a cooler",
    ("cooler", "default"): "the arrowhead on the diagonal is the whole of what "
                           "makes this a cooler and not a heater",
    ("hex", "condenser"):  "the same drawing as cooler/default, and the same "
                           "arrowhead carrying the same statement",
}


# draw.io draws inline devices oversized; scale them to read as small devices
# (the converter is handed a matching heavier stroke, so the line still lands at
# 2px once the transform has been applied).
#
# A key is a kind, or one (kind, variant) where a single variant is drawn at a
# different size from the rest of its class. A value is one factor, or a pair
# (sx, sy) for the cases where a symbol has to be *reproportioned* rather than
# merely resized: the vessel, the flash drum and the column are all cut from one
# stencil, and the first two are the short ones.
#
# An uneven pair is the one case where that compensation cannot be exact, since
# it strokes the artwork with an elliptical pen (see ``drawing``). It divides by
# sqrt(sx*sy), so nothing under such a pair lands ON 2px: a vertical stroke
# comes out sqrt(sx/sy) heavy and a horizontal one the same factor light, about
# a pen whose area is the sheet's. It used to divide by sx alone, which put the
# vertical strokes exactly on 2px and left the horizontal ones at sy/sx of it --
# a fifth light on the vessel and the flash drum, and under half on the packed
# tower, where the bed grids read as a different sheet's ink from the shell they
# sit in. Nothing here chooses which axis is the true one any more, because
# there is no reading of a drawing on which one of them is.
#
# 0.25 is the inline family's factor, and it is measured rather than chosen. A
# drawing unit is the CSS pixel, so an A3 sheet is 420 mm x 96/25.4 = 1587 units
# wide and 1 mm is 3.78 of them. An issued A3 P&ID draws its gate valves 17.0 pt
# long and 8.5 pt across (6.0 mm x 3.0 mm), the same 17.0 pt its instrument
# balloons and its interlock squares are drawn at, the whole sheet being cut to
# one 6 mm module. The valve stencil is 98 x 60, so 0.25 puts it at 24.5 x 15.0
# units, 6.5 mm x 4.0 mm: within 8% of the reference along the flow axis, which
# is the axis that decides how many valves fit on a run. At the 0.5 this
# replaces, the same valve was 49 units (13 mm, over twice the reference), which
# is why a station with isolation valves either side of a control valve took the
# width five valves and a flow element occupy on a real sheet.
#
# It stays a single factor rather than an (sx, sy) pair even though the
# reference's bowtie is 2:1 against the stencil's 98:60. Squashing the family to
# match would draw the globe and ball seats as ovals and the check valve's
# arrowhead askew, and an uneven pair strokes with an elliptical pen no single
# stroke-width can round out, so the diagonals would land off 2px whatever the
# compensation divides by. A valve one third taller than the reference's is a
# smaller error than a valve whose internals are wrong.
#
# Everything that shares a pipe with a valve takes the same factor, because they
# share a line size: a strainer, an orifice plate or a sight glass left at the
# old scale would be drawn half again longer than the valve beside it.
# ``reducer`` is the exception in this family and has its own entry below: it is
# a piping.xml shape drawn on a 20-unit module, so 0.25 would put it at 5 units
# long, a fifth of the valve it sits beside.
#
# flow_sensors.xml and piping.xml are the exception, and for a reason that is
# about the stencils rather than about the drawing: they lay their in-line
# devices out on a 50-unit module where valves.xml and fittings.xml use a ~100
# one. Halving those would draw a venturi 12.5 units long beside a 24.5-unit
# valve, so they take 0.5 and land on the same 25 x ~20 box the flame arrestors
# and the static mixer already occupy. Same sheet size, different stencil scale.
HALF_SCALE_FITTINGS = (
    # flow_sensors.xml: the primary elements
    "venturi", "flow_nozzle", "coriolis", "vortex", "ultrasonic",
    "turbine_meter", "positive_displacement", "v_cone", "wedge", "target",
    "pitot", "averaging_pitot",
    # piping.xml: the in-line devices
    "strainer_y", "strainer_basket", "strainer_duplex",
    "bellows", "damper", "spool",
    # ...and the spectacle blind, which is on that file's module like the rest
    # of them and takes its factor for the same reason. It happens to be the
    # right size for its own reason too: 0.5 draws each disc 10 units across, so
    # the figure-8 is 20, the 5.3 mm that lands on the reference sheet's 6 mm
    # module, and enough for the open disc's 8-unit bore to read as a hole
    # rather than as a thick dot. The whole symbol is that one distinction, so
    # it was checked at 1:1 and at print before this factor was settled; 0.375
    # closes the bore to 5.5 units and the two states start to converge.
    "blind",
)

# Three shapes in valves.xml are not on that file's ~98-unit module, so the
# kind's 0.25 draws them undersized: Safety PSV 1 is 55.5 x 94.5, Relief PRV
# 40 x 59 and Pneumatic Operated Butterfly Valve 60 x 80, coming out at 13.9,
# 10.0 and 15.0 units of length against everyone else's 24.5. Each therefore
# takes its own factor below.
#
# What "the same size as the rest of the family" means is NOT the box, because
# these are upright devices and the box holds whatever rides above the body: a
# spring bonnet, a diaphragm dome, an operator. Forcing them into a gate valve's
# landscape 24.5 x 15.0 would shrink the part that carries the flow to make room
# for the part that does not.
#
# It is the SEAT. Every valve body in valves.xml is the same pair of triangles,
# 60 units across the run with a 49-unit apex, and 0.25 draws that pair 15.0
# across and 12.25 along wherever it appears. Gate Valve sets them base to base
# and comes out 24.5 x 15.0; Angle folds them into an L (its own path is
# (0,79)-(30,30)-(79,0)-(79,60)-(30,30)-(60,79), which is that triangle twice)
# and comes out 19.8 x 19.8 at the very same 0.25. So an upright valve is sized
# by drawing ITS seat at 15.0 across the run, and the bonnet above it is extra
# height rather than a reason to shrink the seat.
#
# Safety PSV 1 draws exactly that pair, at 0.7 of the size: the inlet leg is
# (0,94.5)-(21,60)-(42,94.5), a 42-wide base under a 34.5 apex, and the outlet
# leg is the same triangle turned a quarter. 15.0 / 42 restores it, putting the
# base on the family's 15.0 and the apex on 12.3 against the family's 12.25. It
# comes out 19.8 x 33.8, whose lower 19.8 x 19.8 is valve/angle's box to the
# decimal -- the same quarter-turn body, with 14 units of spring bonnet on top.
# One factor and not a pair: the three spring strokes and both seat faces are
# diagonals, which a non-uniform factor would tilt, and would stroke with a pen
# no compensation can hold round, so they would also land off 2px. That is the
# reason the valve family takes a single factor at all (see the paragraph
# above).
#
# Relief PRV has no seat to measure: it is a 40-wide semicircular bonnet on a
# stem, piped S to N, so across-the-run is that bonnet and 15.0 / 40 is the same
# statement. It comes out 15.0 x 22.1 -- a gate valve's 15.0 across the run,
# and 22.1 along it where a gate valve is 24.5, the difference being that this
# one spends its length on a stem rather than on a bowtie. Uniform again,
# because the bonnet is a true semicircle and a pair would draw it as a half
# ellipse. The check that a bonnet is a bonnet across the three: this shape and
# the butterfly draw the identical 40 x 20 semicircle, and come out 15.0 x 7.5
# and 16.3 x 7.5.
#
# Pneumatic Operated Butterfly Valve is the one that does need the pair. Its
# body is a plain rect, x 0..60 and y 40..80, at 3:2 where the family's bowtie
# is 98:60, so a single factor cannot put the body on 24.5 x 15.0 and the run on
# the family's height at once. (24.5/60, 15.0/40) does both: a 24.5 x 15.0 body
# in a 24.5 x 30.0 box, with the W/E anchors at y = 0.75 landing 7.5 above the
# bottom, which is where every other straight-through valve carries the line.
# Uniform at 24.5/60 would leave the run 8.2 up and still off the family's run.
SCALE = {"valve": 0.25, "fitting": 0.25,
         "vent": 0.25, "funnel": 0.25,
         ("valve", "psv"): 15.0 / 42, ("valve", "relief"): 15.0 / 40,
         ("valve", "butterfly_pneumatic"): (24.5 / 60, 15.0 / 40),
         **{("fitting", variant): 0.5 for variant in HALF_SCALE_FITTINGS},
         # ...and the two open ends taken from the same 50-unit file.
         ("vent", "exhaust_head"): 0.5, ("vent", "breather"): 0.5,
         # Every reducer body is drawn 12.5 units tall. A reducer's drawn height
         # is the line it sits in, so two of them in one run (the reduction into
         # a control valve and the expansion out of it) have to agree about it,
         # and so must the three variants, since switching one for another is a
         # change of artwork and not of line size. The length follows from each
         # stencil's own proportions: the concentric body is drawn square, the
         # eccentric one longer than it is tall. The kind's entry covers
         # ``default``, which is the same shape as ``concentric``.
         "reducer": 12.5 / 20, ("reducer", "eccentric"): 12.5 / 15,
         # 62 x 100, at 1:1.6 against the column's 1:2: a drum is short because
         # it holds inventory, a tower is slender because it holds trays, and
         # two shapes cut to the same proportions read as one piece of equipment
         # drawn at two sizes. It lands in the same family as vessel/dished
         # (60 x 95), the knock-out drum (51 x 95) and the reactor (50 x 96).
         #
         # It is also the box the barrel occupied, to the unit: the nozzles keep
         # the heights every pinned sheet was drawn to, so this changes what a
         # vessel looks like without moving a single run.
         ("vessel", "default"): (0.62, 0.5),
         # The flash drum takes vessel/default's reproportioning, for
         # vessel/default's reason, and this entry is required rather than
         # cosmetic: separator/default is cut from the same "Pressurized Vessel"
         # stencil as the column, so left at 1.0 it comes out in the tower's
         # 100 x 200 box and its artwork is pixel-identical to a column's on a
         # sheet carrying both. 62 x 100 puts it in the box vessel/default
         # already occupies, which is the point: a flash drum and a surge drum
         # are the same size of equipment, and the tower beside them is the
         # slender one.
         ("separator", "default"): (0.62, 0.5),
         # The stirred tank takes the same reproportioning for the same reason: it
         # is the same "Pressurized Vessel" stencil, and a reactor, a surge drum and
         # a flash drum are one size of equipment with the tower beside them the
         # slender one. 62 x 100 is also within four units of the box the "Mixing
         # Reactor" stencil occupied (50 x 96,4), so the change is to what a reactor
         # looks like and not to how much room it takes.
         ("reactor", "default"): (0.62, 0.5),
         # 62 x 200. The packed tower is drawn 14 x 97, at 1:6.9, which is far
         # slenderer than anything else on the sheet and would come out 14px
         # wide. The height is the column's own 200, so every nozzle keeps the
         # height it has on column/default and no pinned sheet moves vertically.
         #
         # The width is the drum's, not the column's, and that is the smaller of
         # two evils. Stretching to 100 would take the dished heads to 14:1
         # (flat lips rather than domes) and would draw the bed grids and the
         # packing at under a third of the shell's line weight -- the ratio
         # between a horizontal stroke and a vertical one is sy/sx whatever the
         # compensation divides by, so widening the box widens that gap. At 62
         # the heads are 8.6:1, which is where vessel/default's already are, and
         # the internals are within about half the shell weight.
         ("column", "packed"): (62 / 14, 200 / 97)}


def scale_for(kind, variant):
    """The (sx, sy) a symbol's artwork is drawn at, from :data:`SCALE`.

    A (kind, variant) entry beats the kind's own, so one variant can be resized
    without dragging its siblings with it.
    """
    s = SCALE.get((kind, variant), SCALE.get(kind, 1.0))
    return (float(s), float(s)) if isinstance(s, (int, float)) else (float(s[0]), float(s[1]))


def drawio_shape_key(namespace, shape_name):
    """The key draw.io's own stencil registry files one shape under.

    mxGraph builds it out of the two names the stencil file already carries:
    ``mxStencilRegistry.parseStencilSet`` takes the package off the root
    element, the shape's own name off the ``<shape>``, replaces the spaces in
    the shape's name with underscores and lowercases the pair. So
    ``mxGraph.pid.valves`` and ``Gate Valve`` make
    ``mxgraph.pid.valves.gate_valve``, which is what a ``shape=`` in a draw.io
    style has to say to reach the very drawing this generator converted.

    Reproducing the rule is the whole point: a guessed key is not merely wrong,
    it fails *quietly*. draw.io answers an unresolvable ``shape=`` with its
    default rectangle, so the file still opens, the equipment is still all
    there, and every symbol on the sheet has become a box. Deriving the key from
    the same two strings the artwork was converted from is what makes the export
    wrong loudly or not at all.

    Only spaces become underscores; the punctuation upstream puts in a shape
    name survives ("Tank (Dished Roof)", "Y-Type Strainer", "Rotary Drum Drier,
    Tumbling Drier"), and it has to, since draw.io does an exact dictionary
    lookup on the key it built by the same rule. A **dot** is the one character
    that cannot survive, and is refused rather than passed through: draw.io
    finds the *file* to load by splitting the key on dots and treating all but
    the last part as a path (``mxStencilRegistry.getBasenameForStencil``), so a
    dot inside the shape's own name moves that boundary and sends draw.io
    looking for a stencil file that was never there. No shape in the vendored
    set has one today; this is here so that the day one arrives the generator
    stops instead of emitting a reference nothing can resolve.
    """
    if "." in shape_name:
        raise SystemExit(
            f"shape name {shape_name!r} in {namespace} contains a dot. draw.io "
            f"splits a shape key on dots to find the stencil file to load, so a "
            f"dot in the shape's own name would send it looking for the wrong "
            f"file and the reference would resolve to nothing."
        )
    return f"{namespace}.{shape_name.replace(' ', '_')}".lower()


def is_series(spec):
    """True for a port spec declaring a *family* rather than one nozzle."""
    return isinstance(spec, tuple) and spec[0] == "SERIES"


def resolve_port(spec, constraints, w, h):
    """Resolve a port spec to (x, y) in the shape's own units.

    ``"W"``            - a named draw.io <constraint> anchor (compass point).
    ``("E", 10.0)``    - a point on a bounding-box edge, at the given offset.
    ``("AT", x, y)``   - an absolute point, for nozzles that sit inboard of the
                         bounding box (e.g. a dome crown, or a shell wall drawn
                         inside the box because brackets widen the extent).

    A fifth form, ``("SERIES", edge, along, pitch, extent)``, is not a nozzle at
    all: it hands the port to a :class:`~pandid.render.symbols.PortSeries`, which
    places as many as the unit turns out to have, ``pitch`` apart and centred on
    ``along``. See :func:`is_series`.
    """
    if isinstance(spec, str):
        if spec not in constraints:
            raise SystemExit(f"missing constraint {spec!r}; have {list(constraints)}")
        return constraints[spec]
    if spec[0] == "AT":
        _, x, y = spec
        return (float(x), float(y))
    edge, along = spec
    return {"N": (float(along), 0.0), "S": (float(along), float(h)),
            "E": (float(w), float(along)), "W": (0.0, float(along))}[edge]


def drawing(el, kind, variant, port_map, sx, sy):
    """One shape converted, its ports resolved, both at the family's scale.

    Returns ``(inner, w, h, ports, menu, series, aspect)``: the artwork, and
    everything a :class:`~pandid.render.symbols.Symbol` is built from except its
    id. Split out so the two states of a device (see :data:`CLOSED_SHAPES`) go
    through exactly the same arithmetic, which is what lets :func:`render` insist
    afterwards that the pair differs in ink and in nothing else.
    """
    # Emit a heavier stroke on scaled symbols so it renders at 2px after the
    # scale transform (2px matches streams + hand-drawn symbols exactly).
    #
    # The divisor is the geometric mean of the two factors, which is
    # ``pandid.render.svg._pen_scale``'s answer to the same question one level
    # down, arrived at for the same reason: stroking sweeps a *circular* pen,
    # and a group that scales the axes differently sweeps an elliptical one, so
    # the rendered weight depends on the direction the line runs in and no
    # ``stroke-width`` -- one number -- can undo that. sqrt(sx*sy) holds the
    # pen's area to the circle's, splits what is left evenly either side of 2px
    # rather than piling it onto one axis, and is exact the moment the two
    # factors agree, which is every family but the four SCALE reproportions.
    inner, w, h, constraints, aspect = convert_shape(
        el, stroke_width=round(2.0 / math.sqrt(sx * sy), 3))
    # A port spec may be a LIST: the first entry is the default placement and
    # the rest are alternate faces the user can move that port to.
    #
    # An alternate is written the same two ways a home placement is. An edge
    # spec -- ``("N", 30.0)`` -- names the face it lands on outright. An
    # ``("AT", x, y)`` one does not, because it is a point *inboard* of the box:
    # a dished roof's crown sits 6,4 under the top edge, and a tank offering a
    # top fill has to put the nozzle on the roof plate rather than on the empty
    # paper above it. So the face is read off the point, by the same
    # :func:`outward_dir` that reads the home placement's, and read *after* the
    # family's scale has been applied for the same reason that one is.
    ports, alts, series = {}, {}, {}
    for p, spec in port_map.items():
        if is_series(spec):
            _, edge, along, pitch, extent = spec
            series[p] = (edge, float(along), float(pitch), float(extent))
            continue
        choices = spec if isinstance(spec, list) else [spec]
        ports[p] = resolve_port(choices[0], constraints, w, h)
        for extra in choices[1:]:
            if not isinstance(extra, tuple) or extra[0] not in ("N", "S", "E", "W", "AT"):
                raise SystemExit(
                    f"{kind}/{variant} port {p!r}: an alternate face must be an "
                    f'edge spec like ("N", 30.0) or a point like ("AT", 50.0, '
                    f"6.4), got {extra!r}")
            face = None if extra[0] == "AT" else extra[0]
            alts.setdefault(p, []).append((face, resolve_port(extra, constraints, w, h)))

    if (sx, sy) != (1.0, 1.0):
        factors = f"{sx}" if sx == sy else f"{sx}, {sy}"
        inner = f'<g transform="scale({factors})">{inner}</g>'
        w, h = w * sx, h * sy
        ports = {p: (x * sx, y * sy) for p, (x, y) in ports.items()}
        alts = {p: [(f, (x * sx, y * sy)) for f, (x, y) in v] for p, v in alts.items()}
        # A series runs along one face, so it is the along-axis that scales it.
        series = {p: (e, at * (sy if e in ("W", "E") else sx),
                      pitch * (sy if e in ("W", "E") else sx), ext)
                  for p, (e, at, pitch, ext) in series.items()}
    w, h = round(w, 1), round(h, 1)
    ports = {p: tuple(round(v, 1) for v in xy) for p, xy in ports.items()}
    alts = {p: [(f, tuple(round(v, 1) for v in xy)) for f, xy in v]
            for p, v in alts.items()}
    # Emit the whole menu, home first: Symbol keeps exactly one enumeration
    # of a port's placements, so a symbol with alternates must declare the
    # default among them rather than leave it to be merged in later.
    menu = {}
    for p, entries in alts.items():
        faces = {outward_dir(*ports[p], w, h): ports[p]}
        for face, xy in entries:
            faces[face or outward_dir(*xy, w, h)] = xy
        menu[p] = faces
    return inner, w, h, ports, menu, series, aspect


def render() -> str:
    """The whole generated module, as a string, writing nothing.

    Separate from :func:`main` so a test can regenerate the library in memory and
    compare it against the committed ``_vendored_symbols.py``. That file is
    regenerated wholesale, so a hand edit to it is lost the next time anyone runs
    the generator and the drawing silently reverts; nothing but that comparison
    notices, since a stale generated file still imports and still draws.
    """
    # Index every shape once, correcting the ones STENCIL_PATCHES names, and
    # note the package each file declares, which is what its shapes are filed
    # under at the draw.io end. See :func:`drawio_shape_key`.
    index = {}
    namespaces = {}
    for stencil in {m[0] for m in KIND_MAP.values()}:
        namespaces[stencil] = stencil_namespace(STENCILS / f"{stencil}.xml")
        for name, el in shapes_in(STENCILS / f"{stencil}.xml"):
            index[(stencil, name)] = patch_shape(stencil, name, el)
    # A patch that matches nothing is a fix that has silently stopped being
    # applied -- an upstream rename, or a stencil this generator no longer
    # reads. Either way the drawing quietly reverts, so say so instead.
    missing = sorted(key for key in STENCIL_PATCHES if key not in index)
    if missing:
        raise SystemExit(
            "STENCIL_PATCHES names shapes the generator did not load: "
            + ", ".join(f"{stencil}:{shape}" for stencil, shape in missing)
        )
    # A closed state for a device nothing draws is a position with no symbol
    # behind it, which is exactly the silence the pairing exists to prevent.
    orphans = sorted(key for key in CLOSED_SHAPES if key not in KIND_MAP)
    if orphans:
        raise SystemExit(
            "CLOSED_SHAPES names symbols KIND_MAP does not draw: "
            + ", ".join(f"{kind}/{variant}" for kind, variant in orphans)
        )
    # ...and a turning rule for a symbol nothing draws is a rule that never
    # fires, which reads on the page as a symbol that has been cleared to turn.
    orphans = sorted(key for key in GRAVITY_FIXED if key not in KIND_MAP)
    if orphans:
        raise SystemExit(
            "GRAVITY_FIXED names symbols KIND_MAP does not draw: "
            + ", ".join(f"{kind}/{variant}" for kind, variant in orphans)
        )
    # ...and the same again for the arrow that must not be flipped: a rule for a
    # symbol nothing draws is a rule that never fires, which reads on the page
    # as an arrow that has been cleared to reverse.
    orphans = sorted(key for key in DIRECTIONAL if key not in KIND_MAP)
    if orphans:
        raise SystemExit(
            "DIRECTIONAL names symbols KIND_MAP does not draw: "
            + ", ".join(f"{kind}/{variant}" for kind, variant in orphans)
        )

    imports = "PortSeries, Symbol" if any(
        is_series(spec) for _, _, port_map in KIND_MAP.values() for spec in port_map.values()
    ) else "Symbol"
    lines = [
        '"""draw.io-derived equipment symbols (Apache-2.0). GENERATED by',
        'scripts/vendor_symbols.py. Do not edit by hand. See NOTICE for attribution."""',
        "",
        "",
        "def register_vendored(registry):",
        '    """Register the vendored draw.io symbols, overriding hand-drawn',
        '    defaults of the same (kind, variant)."""',
        f"    from pandid.render.symbols import {imports}",
        "",
    ]
    for (kind, variant), (stencil, shape, port_map) in KIND_MAP.items():
        sx, sy = scale_for(kind, variant)
        # The open drawing, then the closed one where the stencil set has one.
        states = [("register", "", shape)]
        if (kind, variant) in CLOSED_SHAPES:
            states.append(("register_closed", "_closed", CLOSED_SHAPES[(kind, variant)]))
        drawn = {}
        for _, suffix, shape_name in states:
            el = index.get((stencil, shape_name))
            if el is None:
                raise SystemExit(f"shape {shape_name!r} not in {stencil}.xml")
            drawn[suffix] = drawing(el, kind, variant, port_map, sx, sy)
        if "_closed" in drawn:
            opened, closed = drawn[""], drawn["_closed"]
            # Same device, two positions. A pair whose boxes or nozzles differ
            # would move a line already drawn the moment the position was
            # declared; a pair whose artwork does not differ would draw the two
            # positions identically and say nothing at all.
            if opened[1:] != closed[1:]:
                raise SystemExit(
                    f"{kind}/{variant}: {shape!r} and "
                    f"{CLOSED_SHAPES[(kind, variant)]!r} are two positions of one "
                    f"device, so their boxes, nozzles and aspect must agree"
                )
            if opened[0] == closed[0]:
                raise SystemExit(
                    f"{kind}/{variant}: {shape!r} and "
                    f"{CLOSED_SHAPES[(kind, variant)]!r} draw the same thing, so "
                    f"declaring the position would draw nothing"
                )
        for method, suffix, shape_name in states:
            inner, w, h, ports, menu, series, aspect = drawn[suffix]
            sid = kind if variant == "default" else f"{kind}_{variant}"
            svg = f'<g id="sym_{sid}{suffix}">{inner}</g>'
            lines += [
                f"    # draw.io {stencil}:{shape_name} (aspect={aspect}) -> {kind}/{variant}"
                + (" [normally closed]" if suffix else ""),
                f"    registry.{method}({kind!r}, Symbol(",
                f"        svg={svg!r},",
                f"        width={w}, height={h},",
                f"        ports={ports!r},",
                # The stencil this drawing came from, named the way draw.io's
                # own registry names it, so an export can hand the reader back
                # the shape rather than a tracing of it. Emitted for every
                # symbol here and for none of the hand-drawn ones, which is
                # exactly the distinction: a symbol that carries this has a
                # draw.io shape behind it and one that does not, does not.
                f"        drawio_shape="
                f"{drawio_shape_key(namespaces[stencil], shape_name)!r},",
            ]
            if suffix:
                # A second drawing of one (kind, variant) needs a <defs> entry of
                # its own, which is what the suffix on the id buys.
                lines.append(f"        id_suffix={suffix!r},")
            # Only the shapes that refuse to be reshaped say so: stretchable is
            # the default on Symbol, exactly as "variable" is in a stencil.
            if aspect == "fixed":
                lines.append("        stretchable=False,")
            # ISO 15519-1 11.4.2: gravity is a functionality here, so the symbol
            # must not be turned. The reason is carried into the generated file,
            # since that is where a reader meets the keyword.
            if (kind, variant) in GRAVITY_FIXED:
                lines.append(f"        # must not be turned: {GRAVITY_FIXED[(kind, variant)]}")
                lines.append("        gravity_fixed=True,")
            # The artwork says which way something goes, and an axis flip says
            # the reverse of it. The reason travels with the keyword for the
            # same reason the turning one does.
            if (kind, variant) in DIRECTIONAL:
                # The renderer holds the *whole* drawing still under a flip, so
                # a glyph inside one would be counter-transformed twice over.
                # Caught here rather than in the renderer, which has no way to
                # report it by the time it is drawing.
                if "<text" in inner:
                    raise SystemExit(
                        f"{kind}/{variant} is DIRECTIONAL and carries lettering; "
                        f"the renderer holds a directional drawing still as a whole "
                        f"and cannot also counter-transform a glyph inside it"
                    )
                lines.append(f"        # must not be flipped: {DIRECTIONAL[(kind, variant)]}")
                lines.append("        directional=True,")
            if menu:
                lines.append(f"        port_faces={menu!r},")
            # A family is named after the port it replaces: one member keeps
            # that name, and only a second one numbers them.
            if series:
                declared = ", ".join(
                    f"PortSeries({p + '_'!r}, {edge!r}, pitch={round(pitch, 1)}, "
                    f"extent={extent}, at={round(at, 1)}, singular={p!r})"
                    for p, (edge, at, pitch, extent) in series.items()
                )
                lines.append(f"        port_series=({declared},),")
            lines += [
                f"    ), {variant!r})",
                "",
            ]
    # "\n" and not os.linesep: this is the string the test compares against the
    # committed file, which it reads back in text mode. Both ends therefore speak
    # LF whatever the checkout does with line endings on the way to disk.
    return "\n".join(lines)


def main():
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT} ({len(KIND_MAP)} symbols, "
          f"{len(CLOSED_SHAPES)} of them in two positions)")


if __name__ == "__main__":
    main()

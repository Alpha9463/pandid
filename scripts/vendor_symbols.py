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
emit — the parametric ones — and where they are written instead.

``STENCIL_PATCHES`` records the corrections applied to the vendored stencils on
the way through, for the shapes draw.io draws wrongly. The vendored XML stays
exactly as vendored; the correction is written in the stencil's own language
here, so the deviation from upstream is in this file rather than hidden in a
mirrored data file.

Run:  python scripts/vendor_symbols.py
"""
import pathlib
import xml.etree.ElementTree as ET

import sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from mxgraph_to_svg import shapes_in, convert_shape  # noqa: E402
from pandid.portgeom import outward_dir  # noqa: E402  (the one place a face is derived)

STENCILS = HERE / "vendor_data" / "drawio"
OUT = HERE.parent / "pandid" / "render" / "_vendored_symbols.py"

# (kind, variant) -> (stencil, shape_name, {port_name: "constraint" | (edge, along)})
KIND_MAP = {
    # Valves — inline family (inlet W / outlet E).
    #
    # ``actuator`` is where a controller's output lands. It is a signal terminal
    # and not a nozzle: nothing flows through it, so the line stops at the valve
    # rather than reaching into it, and the port belongs on the edge of the
    # symbol's own extent, at the point the operator would be mounted on. A
    # coordinate inboard of that edge draws the signal ending inside the body,
    # since the router steers to the edge and the renderer draws to the
    # coordinate. Coordinates are in the stencil's own space, which
    # SCALE["valve"] = 0.25 then quarters.
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
    ("valve", "control"):   ("valves", "Diaphragm",         {"inlet": "W", "outlet": "E",
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
    # Spring-loaded angle safety valve — the PSV a real sheet draws, with the
    # spring bonnet on top of the inlet leg. The stem runs to y = 0.
    ("valve", "psv"):       ("valves", "Safety PSV 1",      {"inlet": "S", "outlet": "E",
                             "actuator": ("AT", 21.0, 0.0)}),
    # Bleeder: the small drain valve tapped off a header. The stencil draws it
    # vertical — the tap runs down from (12.5, 0) into a bowtie whose open
    # bottom bar at y = 75 discharges — so it is piped from above and down, not
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
    # the valve, so ``actuator`` lands on its crown — the top of the motor/
    # solenoid/hydraulic box, or the apex of a diaphragm dome — which is where a
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
    # Diaphragm actuator drawn as a dome *above* the body (the "control" variant
    # above uses the Diaphragm stencil, which draws a diaphragm inside the body
    # instead — a Saunders body, not an operator).
    ("valve", "pneumatic"): ("valves", "Pneumatic Operated",
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
    # Heat exchangers (horizontal shell & tube: cold through tubes W->E, hot shell N/S).
    ("hex", "default"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                         {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
    # Kettle reboiler. The stencil draws a channel head at x 0..16.5 separated
    # from the shell by a tubesheet (the rect at x 16.5..19.5), so the left stub
    # is the TUBE side — the heating medium — not a process connection. The
    # process boils in the shell: liquid in at the bottom, vapour off the top.
    # Mapping cold_in to that left stub, as the plain W anchor does, pipes the
    # column bottoms straight into the steam side.
    #
    # Only one tube-side opening is drawn, so hot_out has to take the shell's
    # far dished head; treat it as the heating-medium return.
    #
    # ``bottoms`` is the draw at the weir end: what does not boil overflows the
    # plate at x = 86.5 and leaves the bottom of the shell, which is how a
    # tower's bottoms product actually gets off the sheet.
    ("hex", "kettle"):  ("heat_exchangers", "Reboiler",
                         {"cold_in": ("AT", 45.8, 30.0), "cold_out": ("N", 64.0),
                          "hot_in": ("W", 22.5), "hot_out": ("E", 15.0),
                          "bottoms": ("AT", 85.0, 30.0)}),
    # Heater and cooler are one stencil pair: the same circle and zigzag, with
    # the diagonal arrow pointing in (heat added) or out (heat removed). Taking
    # the cooler from anywhere else breaks the pairing: "Heat Exchanger
    # (Spiral)" is a different piece of equipment entirely and, at 100x100,
    # draws a utility cooler larger than the reactor upstream of it. draw.io
    # files the heat-removed one under "Condenser".
    ("heater", "default"): ("heat_exchangers", "Heater",
                            {"inlet": "W", "outlet": "E", "duty": "S"}),
    ("cooler", "default"): ("heat_exchangers", "Condenser",
                            {"inlet": "W", "outlet": "E", "duty": "N"}),
    # A real exchanger style in its own right, just not what a Cooler is drawn as.
    ("hex", "spiral"):     ("heat_exchangers", "Heat Exchanger (Spiral)",
                            {"cold_in": "W", "cold_out": "E",
                             "hot_in": "N", "hot_out": "S"}),
    # Vessels / columns / reactors / separators / tanks.
    #
    # The generic ISO 10628 vessel: a vertical cylinder with dished heads, the
    # same stencil the column is drawn from. "Barrel, Drum" is a 44-gallon
    # shipping barrel — hoop bands and all — which is a container rather than a
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
    ("vessel", "default"): ("vessels", "Pressurized Vessel",
                            {"inlet": ("W", 100.0), "outlet": ("E", 100.0),
                             "vent": ("N", 50.0)}),
    # Feed enters on the left; the returns come back on the RIGHT, which is the
    # side the overhead and reboiler systems are drawn on. reflux_in sits high
    # and boilup_in low on the straight shell wall (which spans y 15..185), with
    # the two duty arrows spaced between them.
    #
    # The feeds are a family: an extractive tower takes its solvent above the
    # feed tray. They stay on the west wall, between the two duty arrows'
    # heights, so however many there are none can reach the returns opposite.
    ("column", "default"): ("vessels", "Pressurized Vessel",
                            {"feed": ("SERIES", "W", 130, 35, 0.5),
                             "distillate": ("N", 50), "bottoms": ("S", 50),
                             "reflux_in": ("E", 35), "boilup_in": ("E", 175),
                             "condenser_duty": ("E", 65), "reboiler_duty": ("E", 145)}),
    # The packed tower: the same shell, with two beds of packing between their
    # support grids. This is the one column stencil that draws an internal, so
    # an absorber or a stripper stops coming out as a bare drum.
    #
    # Every nozzle is the default column's, restated in the tower's own 97-unit
    # shell: SCALE puts the shape in a 62 x 200 box, so 16.975 lands on 35,
    # 31.525 on 65, 70.325 on 145, 84.875 on 175 and the feed family on 130 at a
    # 35 pitch — the heights every column sheet is already drawn to. The two
    # products take the head crowns at (7, 0) and (7, 97); everything else is on
    # the straight shell, which spans y 3.5..93.5 on both walls.
    ("column", "packed"): ("vessels", "Tower With Packing",
                           {"feed": ("SERIES", "W", 63.05, 16.975, 0.5),
                            "distillate": ("N", 7), "bottoms": ("S", 7),
                            "reflux_in": ("E", 16.975), "boilup_in": ("E", 84.875),
                            "condenser_duty": ("E", 31.525),
                            "reboiler_duty": ("E", 70.325)}),
    # vent sits on the vessel's top edge, clear of the agitator shaft at x 24..26.
    # The charge nozzles spread along the straight west wall, which spans
    # y 32.4..77.4 — the vessel is dished below that and open above it.
    ("reactor", "default"): ("vessels", "Mixing Reactor",
                             {"feed": ("SERIES", "W", 48.2, 14, 0.32),
                              "outlet": "S", "duty": "E",
                              "vent": ("AT", 40.0, 32.4)}),
    ("separator", "default"): ("vessels", "Knock-out Drum",
                               {"feed": ("W", 55), "vapor": ("N", 25), "liquid": ("S", 25)}),
    # Both roofs rise inside the bounding box, so an inlet on the box's top edge
    # floats above the drawn ink. Put it on the roof itself: the dome crown, and
    # the cone apex.
    ("tank", "default"):  ("vessels", "Tank (Dished Roof)",
                           {"inlet": ("AT", 50.0, 6.4), "outlet": ("S", 50)}),
    ("tank", "conical"):  ("vessels", "Tank (Conical Roof)",
                           {"inlet": ("N", 50), "outlet": ("S", 50)}),
    # Fittings.
    ("reducer", "default"): ("fittings", "Reducer", {"inlet": "W", "outlet": "E"}),
    # piping.xml draws the reducer the way a piping drawing does: a trapezoid
    # between a large face and a small one. (fittings.xml's, above, is a
    # triangle — a cone tapering to a point, so the outlet nozzle is on the
    # apex and the line it reduces to has no width at all.)
    #
    # Both new bodies are drawn to the same 12.5 the default reducer is, since
    # a reducer's drawn height is the pipe it sits in and two of them in one
    # run have to agree about that; see SCALE.
    ("reducer", "concentric"): ("piping", "Concentric Reducer",
                                {"inlet": "W", "outlet": "E"}),
    # Eccentric: flat on top, so the small end's centreline is *below* the large
    # end's — which is the whole point of it on a pump suction, where a
    # concentric reducer would trap vapour against the roof of the line. The
    # stencil's own E anchor is on that lowered centreline (y = 4.5 of 15) and
    # not at mid-height, so it is taken as named rather than placed.
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
    # the two anchors sit — one on each arc's extremum.
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
    # inboard of the box (x = 10 and 40) — on the pipe ends the clamp grips.
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
    # Fitting is, so they are variants of it rather than a class of their own —
    # nothing about the flowsheet changes because the thing in the run measures
    # rather than strains. (A ``FlowElement`` class would read better on an
    # equipment list, and is worth its own change; it is not this one.)
    #
    # Every shape here names W and E on its own outline and every one of them is
    # stroked — the meter bodies are a plain rectangle, and the two profiling
    # elements close their bodies with a straight face at each end — so all of
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
                            {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
    ("hex", "u_tube"):     ("heat_exchangers", "U-Tube Heat Exchanger",
                            {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
    # Horizontal shell-and-tube in elevation — the exchanger a real sheet draws
    # for an overhead condenser or a feed cooler. (The "shell_tube" variant above
    # is the ISO circle-and-zigzag; despite the name it is not this shape.)
    # Tube side runs through the heads at x 0..15 and 85..100; the shell nozzles
    # sit between the tubesheets, which is where draw.io's NE/SW anchors land.
    ("hex", "straight_tubes"): ("heat_exchangers", "Heat Exchanger (Straight Tubes)",
                                {"cold_in": ("W", 15), "cold_out": ("E", 15),
                                 "hot_in": ("N", 75), "hot_out": ("S", 25)}),
    ("hex", "condenser"):  ("heat_exchangers", "Condenser",
                            {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
    ("hex", "plate"):      ("heat_exchangers", "Heat Exchanger (Plate)",
                            {"cold_in": "SW", "cold_out": "SE", "hot_in": "NW", "hot_out": "NE"}),
    # Finned tubes: the same casing as "straight_tubes", with a finned tube in
    # place of the bundle, so it takes that variant's nozzles exactly and is a
    # drop-in change of artwork. draw.io's own N/S anchors are at x = 7 and 93,
    # which is over the channel heads rather than between the tubesheets at
    # x = 15 and 85 — a shell nozzle cannot be on the tube side.
    ("hex", "finned"):     ("heat_exchangers", "Heat Exchanger (Finned Tubes)",
                            {"cold_in": "W", "cold_out": "E",
                             "hot_in": ("N", 75), "hot_out": ("S", 25)}),
    # Air cooler (fin-fan). The only piped side is the tube bundle, drawn across
    # the bottom at y = 80 where the stencil's own W/E anchors sit, so that is
    # the PROCESS side and it is named hot: an air cooler is what cools a
    # stream, the way the kettle above is named for the side that boils. Air is
    # the cold stream, and it is not piped — an induced-draft bay pulls it in
    # under the bundle and discharges it through the fan on top, so cold_in and
    # cold_out sit on the plenum's own bottom and top faces on the fan's
    # centreline.
    ("hex", "air_cooled"): ("heat_exchangers", "Heat Exchanger (Finned Tubes, Fan)",
                            {"hot_in": ("W", 80), "hot_out": ("E", 80),
                             "cold_in": ("S", 50), "cold_out": ("N", 50)}),
    # Double pipe, drawn as a hairpin: the inner pipe is stubbed up at (10, 0)
    # and down at (10, 50), and the annulus opens on the west face at y = 10 and
    # y = 40. Both fluids therefore enter at the same end and turn round at the
    # far one, which is why the annulus has no east nozzle to give hot_out.
    # Counter-current: the annulus enters low where the tube leaves.
    ("hex", "double_pipe"): ("heat_exchangers", "Double Pipe Heat Exchanger",
                             {"cold_in": "N", "cold_out": "S",
                              "hot_in": "SW", "hot_out": "NW"}),
    # Hairpin: a U-tube in a shell, with no <connections> at all. The tube ends
    # are the two flared openings on the west face (y 7..10 and y 20..23); the
    # shell draws four stubs, and the pair taken is the diagonal one, far end
    # top and near end bottom, matching "straight_tubes". Like the double pipe
    # above, the tube returns to the end it came in at, so both tube nozzles are
    # on the west face.
    ("hex", "hairpin"):    ("heat_exchangers", "Hairpin Exchanger",
                            {"cold_in": ("W", 8.5), "cold_out": ("W", 21.5),
                             "hot_in": ("N", 72.5), "hot_out": ("S", 17.5)}),
    # Thin-film (wiped-film) evaporator — the one evaporator in the set. The
    # process runs top to bottom: feed onto the wiper at the shell's top face,
    # which is drawn at y = 10 rather than on the box edge, and concentrate out
    # of the cone apex at (40, 120). The port is offset to x = 20 to keep the
    # inlet line off the rotor shaft the stencil draws down the centre.
    # The jacket is the hot side, and the stencil opens it on both walls at
    # y = 30, so that is where the heating medium goes in and comes out.
    ("hex", "thin_film"):  ("heat_exchangers", "Thin-Film Evaporator",
                            {"cold_in": ("AT", 20.0, 10.0), "cold_out": ("S", 40),
                             "hot_in": ("W", 30), "hot_out": ("E", 30)}),
    # Pump / compressor styles.
    ("pump", "vacuum"):           ("pumps", "Vacuum Pump",
                                   {"suction": ("W", 25.0), "discharge": ("E", 25.0)}),
    # Peristaltic (hose) pump: the tube runs over the rollers and leaves the top
    # of the head, so the only connections the stencil draws are the two stubs
    # at (20, 0) and (40, 0). The casing circle would take a W/E pair and keep
    # this in line with the rest of the pumps, but it would put both nozzles on
    # blank casing wall — the rule for this family is that a drawn nozzle wins.
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
    ("vessel", "dished"): ("vessels", "Vessel (Dished Ends, Brackets)",
                           {"inlet": ("AT", 10.0, 47.0), "outlet": ("AT", 50.0, 47.0),
                            "vent": ("N", 30.0)}),
    # the vent rides the raised manway dome on top, apex near x = 62.7
    ("vessel", "dome"):   ("vessels", "Vessel (Dome)",
                           {"inlet": ("W", 27), "outlet": ("E", 27), "vent": ("N", 62.7)}),
    # Jacketed: the same dished vessel inside a heating/cooling jacket, drawn as
    # a panel down each side out to the box edge. The process nozzles go on the
    # jacket's outer wall rather than on the shell at x = 6 and 46, so the line
    # stops where it meets the equipment instead of being drawn across the
    # jacket. Both are at the straight shell's mid-height, and the vent is on
    # the top head's crown, as on "dished".
    ("vessel", "jacketed"): ("vessels", "Vessel (Dished Ends, Heating-Cooling Jacket)",
                             {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                              "vent": ("N", 26.0)}),
    # Skirted: the same 40-wide shell as "dished", standing on a skirt instead
    # of brackets. Nothing widens the box here, so the shell walls ARE the box's
    # west and east faces and the two process nozzles take them directly.
    ("vessel", "skirted"): ("vessels", "Vessel (Dished Ends, Skirts)",
                            {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                             "vent": ("N", 20.0)}),
    # The third roof that rises inside its bounding box, and the same treatment
    # the dished and conical ones get above: the shell is open between x = 5 and
    # x = 95 at y = 0 — that gap is what the roof floats in — so an inlet on the
    # box's top edge is drawn in mid-air 5 units above the roof plate. Put it on
    # the plate, which spans x 5..95 at y = 5. (Nothing showed while the tank was
    # painted as a solid block; with the block gone the nozzle is in the open.)
    ("tank", "floating_roof"): ("vessels", "Tank (Floating Roof)",
                                {"inlet": ("AT", 30.0, 5.0), "outlet": ("S", 50)}),
    # ...and the third: the sphere rides on legs inside its box, so its crown is
    # at (40, 5) and the box's top edge carries only the two short lines the
    # legs are drawn against, at x 15..33 and x 47..65. An inlet at x = 40 falls
    # in the gap between them. Put it on the crown, as on the dished roof.
    ("tank", "sphere"):        ("vessels", "Storage Sphere",
                                {"inlet": ("AT", 40.0, 5.0), "outlet": ("S", 40)}),
    # Reactor / separator styles. The straight wall spans y 7.69..87.69.
    ("reactor", "plain"):     ("vessels", "Reactor",
                               {"feed": ("SERIES", "W", 30, 14, 0.4),
                                "outlet": ("S", 20), "duty": ("E", 47),
                                "vent": ("AT", 30.0, 7.69)}),
    # Horizontal vessel: reflux drum, accumulator, knock-out pot. A lying
    # cylinder with dished ends — the shape a vertical vessel does NOT become
    # when rotated, since its saddles and shell bands would turn with it.
    # Inlet on either head or from above, liquid out of the bottom, vent off the
    # top; the top and bottom faces span x 5.77..85.77.
    #
    # The outlet takes no alternate: liquid draws off the bottom, and the right
    # head is already the inlet's alternate — giving both an "E" option would
    # land two nozzles on the same point.
    ("vessel", "horizontal"): ("vessels", "Drum or Condenser",
                               {"inlet": [("W", 15), ("N", 20.0), ("E", 15)],
                                "outlet": ("S", 68.0),
                                "vent": ("N", 55.0)}),
    # The same shape as a horizontal phase separator, where naming the vapour
    # and liquid products is the point. Neither product takes an alternate face:
    # vapour always disengages off the top, liquid draws off the bottom.
    ("separator", "horizontal"): ("vessels", "Drum or Condenser",
                                  {"feed": [("W", 15), ("N", 20.0), ("E", 15)],
                                   "vapor": ("N", 30.0),
                                   "liquid": ("S", 68.0)}),
    ("separator", "cyclone"): ("separators", "Separator (Cyclone)", {"feed": "W", "vapor": "N", "liquid": "S"}),
    ("separator", "gravity"): ("separators", "Gravity Separator, Settling Chamber",
                               {"feed": "W", "vapor": "E", "liquid": "S"}),
    # Gas-cleaning vessels: hopper-bottomed box, gas across the top and the
    # collected phase out of the apex at (40, 120). The scrubber's wash-liquid
    # header is drawn on the centreline, so the clean gas leaves sideways rather
    # than through the top face.
    ("separator", "scrubber"): ("separators", "Separator (Wet Scrubber)",
                                {"feed": "W", "vapor": "E", "liquid": "S"}),
    ("separator", "electrostatic"): ("separators", "Separator (Electrostatic Precipitator)",
                                     {"feed": "W", "vapor": "E", "liquid": "S"}),
    # Filter styles. Press Filter's own W/E anchors sit on opposite *corners* of
    # the box, so both faces are placed on the plate pack's mid-height instead.
    ("filter", "gas"):    ("filters", "Gas Filter (Bag, Candle, Cartridge)",
                           {"inlet": "W", "outlet": "E"}),
    ("filter", "press"):  ("filters", "Press Filter",
                           {"inlet": ("W", 25.0), "outlet": ("E", 25.0)}),
    ("filter", "rotary"): ("filters", "Liquid Filter (Rotary, Drum or Disc)",
                           {"inlet": ("W", 50.0), "outlet": "E"}),
    # Ion exchanger: the resin bed between its two retention screens, the water
    # treatment vessel every demineraliser train is drawn with. The stencil
    # names only N and S, but the whole 50 x 100 casing is stroked, so the side
    # walls carry the same W/E faces the rest of the filters use — a change of
    # variant is a change of artwork, not of piping.
    ("filter", "ion_exchange"): ("filters", "Liquid Filter (Ion Exchanger)",
                                 {"inlet": ("W", 50.0), "outlet": ("E", 50.0)}),
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
# Both shapes go through the same port map and the same SCALE, and build()
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
# shape is *wrong* — not merely a style this library does not use — the
# correction lives here instead: an mxGraph fragment appended to the shape's
# <foreground>, written in the stencil's own drawing language and converted by
# the same converter as the rest of the shape. Provenance therefore stays in
# this file beside KIND_MAP, and a re-vendor cannot quietly drop the fix,
# because a shape a patch cannot find stops the generator (see build()).
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
    # the whole of what tells a reader which valve is in the line — so shipping
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
# in a box of a different aspect ratio is scaled unevenly — so a shape that has
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


# draw.io draws inline devices oversized; scale them to read as small devices
# (the converter is handed a matching heavier stroke, so the line still lands at
# 2px once the transform has been applied).
#
# A key is a kind, or one (kind, variant) where a single variant is drawn at a
# different size from the rest of its class. A value is one factor, or a pair
# (sx, sy) for the one case where a symbol has to be *reproportioned* rather
# than merely resized: the vessel and the column are the same stencil, and the
# vessel is the short one. That stroke compensation is taken from sx, so the
# shell walls — the long strokes, and the ones a reader takes the line weight
# from — are the pair that lands exactly on 2px.
#
# 0.25 is the inline family's factor, and it is measured rather than chosen. A
# drawing unit is the CSS pixel, so an A3 sheet is 420 mm x 96/25.4 = 1587 units
# wide and 1 mm is 3.78 of them. An issued A3 P&ID draws its gate valves 17.0 pt
# long and 8.5 pt across — 6.0 mm x 3.0 mm, the same 17.0 pt its instrument
# balloons and its interlock squares are drawn at, the whole sheet being cut to
# one 6 mm module. The valve stencil is 98 x 60, so 0.25 puts it at 24.5 x 15.0
# units, 6.5 mm x 4.0 mm: within 8% of the reference along the flow axis, which
# is the axis that decides how many valves fit on a run. At the 0.5 this
# replaces, the same valve was 49 units — 13 mm, over twice the reference, which
# is why a station with isolation valves either side of a control valve took the
# width five valves and a flow element occupy on a real sheet.
#
# It stays a single factor rather than an (sx, sy) pair even though the
# reference's bowtie is 2:1 against the stencil's 98:60. Squashing the family to
# match would draw the globe and ball seats as ovals and the check valve's
# arrowhead askew, and the stroke compensation comes from sx alone, so the
# diagonals would land off 2px. A valve one third taller than the reference's is
# a smaller error than a valve whose internals are wrong.
#
# Everything that shares a pipe with a valve takes the same factor, because they
# share a line size: a strainer, an orifice plate or a sight glass left at the
# old scale would be drawn half again longer than the valve beside it. That
# includes ``reducer``, which is the fittings.xml stencil like the rest of them
# and only had a kind of its own; at 1.0 it was 70 x 50, nearly three times the
# new valve.
#
# flow_sensors.xml and piping.xml are the exception, and for a reason that is
# about the stencils rather than about the drawing: they lay their in-line
# devices out on a 50-unit module where valves.xml and fittings.xml use a ~100
# one. Halving those would draw a venturi 12.5 units long beside a 24.5-unit
# valve, so they take 0.5 and land on the same 25 x ~20 box the flame arrestors
# and the static mixer already occupy. Same sheet size, different stencil scale.
HALF_SCALE_FITTINGS = (
    # flow_sensors.xml — the primary elements
    "venturi", "flow_nozzle", "coriolis", "vortex", "ultrasonic",
    "turbine_meter", "positive_displacement", "v_cone", "wedge", "target",
    "pitot", "averaging_pitot",
    # piping.xml — the in-line devices
    "strainer_y", "strainer_basket", "strainer_duplex",
    "bellows", "damper", "spool",
    # ...and the spectacle blind, which is on that file's module like the rest
    # of them and takes its factor for the same reason. It happens to be the
    # right size for its own reason too: 0.5 draws each disc 10 units across, so
    # the figure-8 is 20 — the 5.3 mm that lands on the reference sheet's 6 mm
    # module, and enough for the open disc's 8-unit bore to read as a hole
    # rather than as a thick dot. The whole symbol is that one distinction, so
    # it was checked at 1:1 and at print before this factor was settled; 0.375
    # closes the bore to 5.5 units and the two states start to converge.
    "blind",
)

SCALE = {"valve": 0.25, "fitting": 0.25, "reducer": 0.25,
         "vent": 0.25, "funnel": 0.25,
         **{("fitting", variant): 0.5 for variant in HALF_SCALE_FITTINGS},
         # ...and the two open ends taken from the same 50-unit file.
         ("vent", "exhaust_head"): 0.5, ("vent", "breather"): 0.5,
         # Both piping.xml reducers are drawn 12.5 units tall, which is the
         # height reducer/default already comes out at. A reducer's drawn height
         # is the line it sits in, so two of them in one run have to agree about
         # it; the length follows from each stencil's own proportions (the
         # eccentric body is drawn longer than it is tall, the concentric one
         # square).
         ("reducer", "concentric"): 12.5 / 20, ("reducer", "eccentric"): 12.5 / 15,
         # 62 x 100, at 1:1.6 against the column's 1:2 — a drum is short because
         # it holds inventory, a tower is slender because it holds trays, and
         # two shapes cut to the same proportions read as one piece of equipment
         # drawn at two sizes. It lands in the same family as vessel/dished
         # (60 x 95), the knock-out drum (51 x 95) and the reactor (50 x 96).
         #
         # It is also the box the barrel occupied, to the unit: the nozzles keep
         # the heights every pinned sheet was drawn to, so this changes what a
         # vessel looks like without moving a single run.
         ("vessel", "default"): (0.62, 0.5),
         # 62 x 200. The packed tower is drawn 14 x 97, at 1:6.9, which is far
         # slenderer than anything else on the sheet and would come out 14px
         # wide. The height is the column's own 200, so every nozzle keeps the
         # height it has on column/default and no pinned sheet moves vertically.
         #
         # The width is the drum's, not the column's, and that is the smaller of
         # two evils. Stretching to 100 would take the dished heads to 14:1 —
         # flat lips rather than domes — and, since the stroke compensation
         # comes from sx, would draw the bed grids and the packing at under a
         # third of the shell's line weight. At 62 the heads are 8.6:1, which is
         # where vessel/default's already are, and the internals are within
         # about half the shell weight.
         ("column", "packed"): (62 / 14, 200 / 97)}


def scale_for(kind, variant):
    """The (sx, sy) a symbol's artwork is drawn at, from :data:`SCALE`.

    A (kind, variant) entry beats the kind's own, so one variant can be resized
    without dragging its siblings with it.
    """
    s = SCALE.get((kind, variant), SCALE.get(kind, 1.0))
    return (float(s), float(s)) if isinstance(s, (int, float)) else (float(s[0]), float(s[1]))


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
    through exactly the same arithmetic, which is what lets :func:`build` insist
    afterwards that the pair differs in ink and in nothing else.
    """
    # Emit a heavier stroke on scaled symbols so it renders at 2px after the
    # scale transform (2px matches streams + hand-drawn symbols exactly).
    inner, w, h, constraints, aspect = convert_shape(el, stroke_width=round(2.0 / sx, 3))
    # A port spec may be a LIST: the first entry is the default placement and
    # the rest are alternate faces the user can move that port to, keyed by
    # the edge each one names.
    ports, alts, series = {}, {}, {}
    for p, spec in port_map.items():
        if is_series(spec):
            _, edge, along, pitch, extent = spec
            series[p] = (edge, float(along), float(pitch), float(extent))
            continue
        choices = spec if isinstance(spec, list) else [spec]
        ports[p] = resolve_port(choices[0], constraints, w, h)
        for extra in choices[1:]:
            if not isinstance(extra, tuple) or extra[0] not in ("N", "S", "E", "W"):
                raise SystemExit(
                    f"{kind}/{variant} port {p!r}: an alternate face must be an "
                    f'edge spec like ("N", 30.0), got {extra!r}')
            alts.setdefault(p, {})[extra[0]] = resolve_port(extra, constraints, w, h)

    if (sx, sy) != (1.0, 1.0):
        factors = f"{sx}" if sx == sy else f"{sx}, {sy}"
        inner = f'<g transform="scale({factors})">{inner}</g>'
        w, h = w * sx, h * sy
        ports = {p: (x * sx, y * sy) for p, (x, y) in ports.items()}
        alts = {p: {f: (x * sx, y * sy) for f, (x, y) in d.items()} for p, d in alts.items()}
        # A series runs along one face, so it is the along-axis that scales it.
        series = {p: (e, at * (sy if e in ("W", "E") else sx),
                      pitch * (sy if e in ("W", "E") else sx), ext)
                  for p, (e, at, pitch, ext) in series.items()}
    w, h = round(w, 1), round(h, 1)
    ports = {p: tuple(round(v, 1) for v in xy) for p, xy in ports.items()}
    alts = {p: {f: tuple(round(v, 1) for v in xy) for f, xy in d.items()}
            for p, d in alts.items()}
    # Emit the whole menu, home first: Symbol keeps exactly one enumeration
    # of a port's placements, so a symbol with alternates must declare the
    # default among them rather than leave it to be merged in later.
    menu = {p: {outward_dir(*ports[p], w, h): ports[p], **d} for p, d in alts.items()}
    return inner, w, h, ports, menu, series, aspect


def build():
    # Index every shape once, correcting the ones STENCIL_PATCHES names.
    index = {}
    for stencil in {m[0] for m in KIND_MAP.values()}:
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

    imports = "PortSeries, Symbol" if any(
        is_series(spec) for _, _, port_map in KIND_MAP.values() for spec in port_map.values()
    ) else "Symbol"
    lines = [
        '"""draw.io-derived equipment symbols (Apache-2.0). GENERATED by',
        'scripts/vendor_symbols.py — do not edit by hand. See NOTICE for attribution."""',
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
            ]
            if suffix:
                # A second drawing of one (kind, variant) needs a <defs> entry of
                # its own, which is what the suffix on the id buys.
                lines.append(f"        id_suffix={suffix!r},")
            # Only the shapes that refuse to be reshaped say so: stretchable is
            # the default on Symbol, exactly as "variable" is in a stencil.
            if aspect == "fixed":
                lines.append("        stretchable=False,")
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
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(KIND_MAP)} symbols, "
          f"{len(CLOSED_SHAPES)} of them in two positions)")


if __name__ == "__main__":
    build()

#!/usr/bin/env python3
"""Generate pandid/render/_vendored_symbols.py from draw.io (jgraph/drawio) P&ID
stencils (Apache-2.0). See NOTICE for attribution.

Each mapped symbol is converted from mxGraph stencil XML to plain SVG by
scripts/mxgraph_to_svg.py, and its ports are resolved either from the stencil's
named <constraint> anchors ("W"/"E"/"N"/"S"/...) or placed explicitly on a
bounding-box edge as ``(edge, along)`` for shapes that lack a needed anchor.

The shape's ``aspect`` becomes ``Symbol.stretchable``; only a ``fixed`` shape
carries the keyword.

``STENCIL_PATCHES`` corrects the shapes draw.io draws wrongly; the vendored XML
stays as vendored.

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
from pandid.render.symbols import CENTRED, FROM_START  # noqa: E402

#: How each alignment is spelled in the generated file.
_ALIGN_NAMES = {CENTRED: "CENTRED", FROM_START: "FROM_START"}

STENCILS = HERE / "vendor_data" / "drawio"
OUT = HERE.parent / "pandid" / "render" / "_vendored_symbols.py"

# (kind, variant) -> (stencil, shape_name, {port_name: "constraint" | (edge, along)})
KIND_MAP = {
    # Valves: inline family (inlet W / outlet E). ``actuator`` is a signal terminal on
    # the symbol's edge where the operator mounts, in stencil units before SCALE.
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
    # Saunders (weir diaphragm) body: no operator drawn.
    ("valve", "saunders"):  ("valves", "Diaphragm",         {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "needle"):    ("valves", "Needle",            {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    # The branch is the stencil's own "S" constraint, bottom centre.
    ("valve", "three_way"): ("valves", "Three-Way Valve",   {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0), "branch": "S"}),
    # A PSV's centreline is taken by its own inlet and outlet; the pilot/solenoid
    # connection goes on the side of the spring bonnet instead.
    ("valve", "relief"):    ("valves", "Relief PRV",        {"inlet": "S", "outlet": "N",
                             "actuator": ("AT", 40.0, 24.0)}),
    # Angle body: piped from below and out to the side; the stem rises at x = 30.
    ("valve", "angle"):     ("valves", "Angle",             {"inlet": "S", "outlet": "E",
                             "actuator": ("N", 30.0)}),
    # Spring-loaded angle safety valve: the PSV a real sheet draws, with the
    # spring bonnet on top of the inlet leg. The stem runs to y = 0.
    ("valve", "psv"):       ("valves", "Safety PSV 1",      {"inlet": "S", "outlet": "E",
                             "actuator": ("AT", 21.0, 0.0)}),
    # Bleeder: drawn vertical and tapped from above; the actuator is set over to
    # x = 24, off the tap's centreline.
    ("valve", "bleed"):     ("valves", "Bleeder Valve 1",   {"inlet": "N", "outlet": "S",
                             "actuator": ("N", 24.0)}),
    # Their "N" constraint sits on inboard ink, so the actuator goes on the edge.
    ("valve", "plug"):      ("valves", "Plug",              {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),
    ("valve", "pinch"):     ("valves", "Pinch Valve",       {"inlet": "W", "outlet": "E",
                             "actuator": ("N", 49.0)}),

    # --- Valves that draw their operator: ``actuator`` on its crown ---
    # "Solenoid Valve Closed" is draw.io's name; the drawing states no position.
    ("valve", "motor"):     ("valves", "Motor Operated Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "solenoid"):  ("valves", "Solenoid Valve Closed",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "hydraulic"): ("valves", "Hydraulic Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    # Control valve: a diaphragm actuator drawn above the body.
    ("valve", "control"):   ("valves", "Pneumatic Operated",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    ("valve", "manual"):    ("valves", "Manual Operated Valve",
                             {"inlet": "W", "outlet": "E", "actuator": ("AT", 49.0, 0.0)}),
    # Knife gate: rising stem through a handwheel bar spanning x 30..70 at y = 0.
    ("valve", "knife"):     ("valves", "Knife Valve",
                             {"inlet": "W", "outlet": "E", "actuator": "N"}),
    ("valve", "butterfly_pneumatic"): ("valves", "Pneumatic Operated Butterfly Valve",
                                       {"inlet": "W", "outlet": "E", "actuator": "N"}),
    # Self-acting regulator: ``actuator`` is the external pilot connection at the top.
    ("valve", "regulator"): ("valves", "Back Pressure Regulator 1",
                             {"inlet": "W", "outlet": "E", "actuator": ("N", 49.0)}),
    # Rotating equipment. Where the stencil draws a nozzle, the port goes on its
    # mouth rather than on draw.io's compass anchor.
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
    # Heat exchangers: nozzles are named for the side (shell or tube), not the duty.
    # The ISO circle-and-zigzag: the tube runs W to E, the shell takes N and S.
    ("hex", "default"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                         {"tube_in": "W", "tube_out": "E", "shell_in": "N", "shell_out": "S"}),
    # Kettle reboiler: the left stub is the channel head (tube side), and the process
    # boils in the shell. ``tube_out`` takes the far head; ``bottoms`` is the weir-end draw.
    ("hex", "kettle"):  ("heat_exchangers", "Reboiler",
                         {"shell_in": ("AT", 45.8, 30.0), "shell_out": ("N", 64.0),
                          "tube_in": ("W", 22.5), "tube_out": ("E", 15.0),
                          "bottoms": ("AT", 85.0, 30.0)}),
    # Heater and cooler are one stencil pair, the arrow in or out; draw.io files the
    # cooler as "Condenser". The third connection is the utility one.
    ("heater", "default"): ("heat_exchangers", "Heater",
                            {"inlet": "W", "outlet": "E", "utility_in": "S"}),
    ("cooler", "default"): ("heat_exchangers", "Condenser",
                            {"inlet": "W", "outlet": "E", "utility_out": "N"}),
    # Spiral: the sides are lettered; side B's axial connections take the casing's N and S.
    ("hex", "spiral"):     ("heat_exchangers", "Heat Exchanger (Spiral)",
                            {"side_a_in": "W", "side_a_out": "E",
                             "side_b_in": "N", "side_b_out": "S"}),
    # Vessels / columns / reactors / separators / tanks.
    #
    # The vessel shares the column's stencil, which SCALE reproportions. Process
    # nozzles sit at mid-height on the straight shell. ``relief`` goes on the crown
    # beside the vent, on the head's ink; ``drain`` on the vessel's lowest drawn point.
    ("vessel", "default"): ("vessels", "Pressurized Vessel",
                            {"inlet": ("W", 100.0), "outlet": ("E", 100.0),
                             "vent": ("N", 50.0),
                             # Unscaled; (25, 2) is on the top head's ellipse,
                             # half a radius off the crown.
                             "relief": ("AT", 25.0, 2.0),
                             "drain": ("S", 50.0)}),
    # The feed and draw families sit on opposite walls inside 65..145, the band the
    # duty arrows bound: two 35 pitches fit, so extent = 70 / 200 = 0.35.
    ("column", "default"): ("vessels", "Pressurized Vessel",
                            {"feed": ("SERIES", "W", 105, 35, 0.35),
                             "draw": ("SERIES", "E", 105, 35, 0.35),
                             "distillate": ("N", 50), "bottoms": ("S", 50),
                             "reflux_in": ("E", 35), "boilup_in": ("E", 175),
                             "condenser_duty": ("E", 65), "reboiler_duty": ("E", 145)}),
    # Packed tower: the default column's nozzles restated in the tower's 97-unit
    # shell, which SCALE draws 200 tall; ``extent`` is a fraction, so it stays 0.35.
    ("column", "packed"): ("vessels", "Tower With Packing",
                           {"feed": ("SERIES", "W", 50.925, 16.975, 0.35),
                            "draw": ("SERIES", "E", 50.925, 16.975, 0.35),
                            "distillate": ("N", 7), "bottoms": ("S", 7),
                            "reflux_in": ("E", 16.975), "boilup_in": ("E", 84.875),
                            "condenser_duty": ("E", 31.525),
                            "reboiler_duty": ("E", 70.325)}),
    # Stirred tank (ISO item 1.27): the drum's body and box; ``Reactor`` composes the
    # agitator. The vent sits on the east wall below the head, since the crown carries
    # the shaft. The outlet also offers E and W at y = 165.
    ("reactor", "default"): ("vessels", "Pressurized Vessel",
                             {"feed": ("SERIES", "W", 100.0, 28.0, 0.32),
                              "outlet": [("S", 50.0), ("E", 165.0), ("W", 165.0)],
                              "duty": ("E", 100.0),
                              "vent": ("AT", 100.0, 20.0)}),
    # Jacketed stirred tank: ``vessel/jacketed``'s stencil. The jacket, y 12.69..82.69,
    # takes its supply low and its return high, each 10 off its end on the east face;
    # the vent takes the shell wall above it.
    ("reactor", "jacketed"): ("vessels", "Vessel (Dished Ends, Heating-Cooling Jacket)",
                              {"feed": ("SERIES", "W", 47.7, 14, 0.32),
                               "outlet": ("S", 26.0),
                               "jacket_in": ("E", 72.7), "jacket_out": ("E", 22.7),
                               "vent": ("AT", 46.0, 10.0)}),
    # The flash drum: the vessel's stencil, nozzle places and box, with the phases
    # named. The feed family is centred on y = 100 at a 40 pitch, so two feeds sit
    # 20 apart as drawn.
    ("separator", "default"): ("vessels", "Pressurized Vessel",
                               {"feed": ("SERIES", "W", 100.0, 40.0, 0.5),
                                "vapor": ("N", 50.0), "liquid": ("S", 50.0)}),
    # Knock-out drum, with its mesh pad and level gauge. The feed band, 0.52 of the
    # body, stays below the pad (y 27.69) and above the dished bottom.
    ("separator", "knockout"): ("vessels", "Knock-out Drum",
                                {"feed": ("SERIES", "W", 55, 20, 0.52),
                                 "vapor": ("N", 25), "liquid": ("S", 25)}),
    # Roof nozzles go on the roof's own ink, which rises inside the box; ``vent`` and
    # ``relief`` flank the crown. The fill enters the shell low on W or E, with the
    # crown as an alternate. The dished roof is r = 75 about (50, 81.36), so x = 35
    # and 65 meet it at y = 7.9.
    ("tank", "default"):  ("vessels", "Tank (Dished Roof)",
                           {"inlet": [("W", 85), ("E", 85), ("AT", 50.0, 6.4)],
                            "outlet": ("S", 50),
                            "vent": ("AT", 35.0, 7.9),
                            "relief": ("AT", 65.0, 7.9),
                            "drain": ("S", 20)}),
    # The conical roof's slopes put the vent and relief at (25, 10) and (75, 10); the
    # fill takes the walls at y = 80.
    ("tank", "conical"):  ("vessels", "Tank (Conical Roof)",
                           {"inlet": [("W", 80), ("E", 80), ("N", 50)],
                            "outlet": ("S", 50),
                            "vent": ("AT", 25.0, 10.0),
                            "relief": ("AT", 75.0, 10.0),
                            "drain": ("S", 20)}),
    # Fittings.
    #
    # The default reducer is piping.xml's concentric one; fittings.xml's "Reducer"
    # draws a closed cone. Both bodies are drawn 12.5 tall; see SCALE.
    ("reducer", "default"): ("piping", "Concentric Reducer",
                             {"inlet": "W", "outlet": "E"}),
    ("reducer", "concentric"): ("piping", "Concentric Reducer",
                                {"inlet": "W", "outlet": "E"}),
    # Eccentric: flat on top; the stencil's E anchor is on the raised centreline.
    # ``pin(mirrored="y")`` draws it flat on the bottom.
    ("reducer", "eccentric"): ("piping", "Eccentric Reducer",
                               {"inlet": "W", "outlet": "E"}),
    # In-line devices: a pair of faces on a line, taking the shapes' own W/E anchors.
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
    # Each arrestor body is a distinct certification, so each is its own variant.
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
    # Restriction orifice, from valves.xml; fittings.xml's "Orifice Plate" has no flow path.
    ("fitting", "orifice"):        ("valves", "Orifice", {"inlet": "W", "outlet": "E"}),
    ("fitting", "rotameter"):      ("valves", "Rotameter", {"inlet": "W", "outlet": "E"}),
    ("fitting", "static_mixer"):   ("mixers", "In-Line Static Mixer",
                                    {"inlet": "W", "outlet": "E"}),

    # --- Primary flow elements (flow_sensors.xml) ---
    # On a 50-unit module, so SCALE halves them; each takes its own W/E anchors.
    # The venturi's N anchor is on the throat and goes unused.
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
    # draw.io spells the averaging probe "Averging"; the shape name keeps the typo.
    ("fitting", "pitot"):          ("flow_sensors", "Pitot Tube",
                                    {"inlet": "W", "outlet": "E"}),
    ("fitting", "averaging_pitot"): ("flow_sensors", "Averging Pitot Tube",
                                     {"inlet": "W", "outlet": "E"}),

    # --- In-line piping devices (piping.xml), on the flow elements' module ---
    # These strainers lie in the run; "strainer" and "strainer_cone" stand across it.
    ("fitting", "strainer_y"):      ("piping", "Y-Type Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer_basket"): ("piping", "Basket Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    ("fitting", "strainer_duplex"): ("piping", "Duplex Strainer",
                                     {"inlet": "W", "outlet": "E"}),
    # Bellows: piping.xml's expansion joint; "expansion_joint" is the plain lens.
    ("fitting", "bellows"):        ("piping", "Expansion Joint",
                                    {"inlet": "W", "outlet": "E"}),
    # Blade on a pivot between two flanges.
    ("fitting", "damper"):         ("piping", "Damper", {"inlet": "W", "outlet": "E"}),
    # Removable spool: the length of pipe taken out to break a line for
    # maintenance, drawn as a pipe between two flanges.
    ("fitting", "spool"):          ("piping", "Removable Spool",
                                    {"inlet": "W", "outlet": "E"}),
    # Spectacle blind, the one in-line device drawn in two states (see CLOSED_SHAPES).
    # The run passes through the lower disc at y = 30, the one that blanks the line;
    # the tie hangs below.
    ("fitting", "blind"):          ("piping", "Open Figure 8 Blind",
                                    {"inlet": ("W", 30.0), "outlet": ("E", 30.0)}),

    # --- Variants (style choices within a class; same ports) ---
    # Heat exchanger styles.
    ("hex", "shell_tube"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": "N", "shell_out": "S"}),
    # U-tube: both tube connections on the channel head, one per chamber either side
    # of the pass partition at y = 15; the shell keeps N and S.
    ("hex", "u_tube"):     ("heat_exchangers", "U-Tube Heat Exchanger",
                            {"tube_in": ("W", 7.5), "tube_out": ("W", 22.5),
                             "shell_in": "N", "shell_out": "S"}),
    # Horizontal shell-and-tube in elevation: the tube side through the heads, the
    # shell nozzles between the tubesheets.
    ("hex", "straight_tubes"): ("heat_exchangers", "Heat Exchanger (Straight Tubes)",
                                {"tube_in": ("W", 15), "tube_out": ("E", 15),
                                 "shell_in": ("N", 75), "shell_out": ("S", 25)}),
    # The circle-and-zigzag with the heat-removed arrow: tube W to E, shell N and S.
    ("hex", "condenser"):  ("heat_exchangers", "Condenser",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": "N", "shell_out": "S"}),
    # Plate: the circuits are lettered and follow the drawn diagonals, NW-SE and SW-NE.
    ("hex", "plate"):      ("heat_exchangers", "Heat Exchanger (Plate)",
                            {"side_a_in": "NW", "side_a_out": "SE",
                             "side_b_in": "SW", "side_b_out": "NE"}),
    # Finned tubes: the "straight_tubes" casing and nozzles; the shell pair sits
    # between the tubesheets, not on draw.io's N/S over the channel heads.
    ("hex", "finned"):     ("heat_exchangers", "Heat Exchanger (Finned Tubes)",
                            {"tube_in": "W", "tube_out": "E",
                             "shell_in": ("N", 75), "shell_out": ("S", 25)}),
    # Air cooler: the tube bundle at y = 80 is the only piped side; the air enters
    # under the bundle and leaves through the fan, on the fan's centreline.
    ("hex", "air_cooled"): ("heat_exchangers", "Heat Exchanger (Finned Tubes, Fan)",
                            {"tube_in": ("W", 80), "tube_out": ("E", 80),
                             "air_in": ("S", 50), "air_out": ("N", 50)}),
    # Double pipe as a hairpin: the annulus is stubbed N and S and the inner pipe
    # enters the west face; both fluids turn at the far end, counter-current.
    ("hex", "double_pipe"): ("heat_exchangers", "Double Pipe Heat Exchanger",
                             {"shell_in": "N", "shell_out": "S",
                              "tube_in": "SW", "tube_out": "NW"}),
    # Hairpin: the tube ends are the two west openings; the shell takes the diagonal
    # stub pair.
    ("hex", "hairpin"):    ("heat_exchangers", "Hairpin Exchanger",
                            {"tube_in": ("W", 8.5), "tube_out": ("W", 21.5),
                             "shell_in": ("N", 72.5), "shell_out": ("S", 17.5)}),
    # Thin-film evaporator: product top to bottom, the feed set over to x = 20 off
    # the rotor shaft; the jacket opens on both walls at y = 30.
    ("hex", "thin_film"):  ("heat_exchangers", "Thin-Film Evaporator",
                            {"product_in": ("AT", 20.0, 10.0), "product_out": ("S", 40),
                             "jacket_in": ("W", 30), "jacket_out": ("E", 30)}),
    # Pump / compressor styles.
    ("pump", "vacuum"):           ("pumps", "Vacuum Pump",
                                   {"suction": ("W", 25.0), "discharge": ("E", 25.0)}),
    # Peristaltic: the only drawn connections are the two stubs on top.
    ("pump", "peristaltic"):      ("pumps", "Peristaltic",
                                   {"suction": ("N", 20.0), "discharge": ("N", 40.0)}),
    # Submersible: the suction is the strainer plate (S); the discharge is the open
    # end of the drawn elbow, inboard of the box edge.
    ("pump", "submersible"):      ("pumps", "Submersible Pump",
                                   {"suction": "S", "discharge": ("AT", 96.77, 31.5)}),
    ("compressor", "rotary"):      ("compressors", "Rotary Compressor", {"suction": "W", "discharge": "N"}),
    ("compressor", "liquid_ring"): ("compressors", "Liquid Ring Compressor", {"suction": "W", "discharge": "N"}),
    # Vessel / tank styles.
    # Brackets widen the box past the shell, so the process ports sit on the shell walls.
    # The 40-wide dished shells share one head: relief at (cx - 12, 1.5), drain at
    # (cx, 95.38).
    ("vessel", "dished"): ("vessels", "Vessel (Dished Ends, Brackets)",
                           {"inlet": ("AT", 10.0, 47.0), "outlet": ("AT", 50.0, 47.0),
                            "vent": ("N", 30.0),
                            "relief": ("AT", 18.0, 1.5), "drain": ("S", 30.0)}),
    # Dome: the vent rides the manway apex near x = 62.7; the relief and drain sit on
    # the body's top and bottom walls, inboard of the box.
    ("vessel", "dome"):   ("vessels", "Vessel (Dome)",
                           {"inlet": ("W", 27), "outlet": ("E", 27), "vent": ("N", 62.7),
                            "relief": ("AT", 30.0, 15.0), "drain": ("S", 47.7)}),
    # Jacketed: the process nozzles on the jacket's outer wall at mid-height; the vent
    # on the crown.
    ("vessel", "jacketed"): ("vessels", "Vessel (Dished Ends, Heating-Cooling Jacket)",
                             {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                              "vent": ("N", 26.0),
                              # Relief and drain on the shell's heads (cx = 26), not on the jacket.
                              "relief": ("AT", 14.0, 1.5), "drain": ("S", 26.0)}),
    # Insulated: the same box, shell and heads as ``jacketed``, so the same port map.
    ("vessel", "insulated"): ("vessels", "Vessel (Dished Ends, Thermal Insulation)",
                              {"inlet": ("W", 47.7), "outlet": ("E", 47.7),
                               "vent": ("N", 26.0),
                               "relief": ("AT", 14.0, 1.5), "drain": ("S", 26.0)}),
    # Electrically heated: the element on the east wall widens the box, so the
    # outlet drops to y = 77.7 below it, on the shell at x = 40.
    ("vessel", "electrical_heating"): (
        "vessels", "Vessel (Dished Ends, Electrical Heating)",
        {"inlet": ("W", 47.7), "outlet": ("AT", 40.0, 77.7), "vent": ("N", 20.0),
         # Shell at x 0..40, so cx = 20 and the heads give 8 and 95.38.
         "relief": ("AT", 8.0, 1.5), "drain": ("S", 20.0)}),
    # Swaged: the process nozzles on the wide section at mid-height, y = 67. The top
    # head is a true semicircle, r = 15 about (25, 15), so x = 16 puts the relief at y = 3.
    ("vessel", "swaged"): ("vessels", "Vessel (Different Diameters)",
                           {"inlet": ("W", 67.0), "outlet": ("E", 67.0),
                            "vent": ("N", 25.0),
                            "relief": ("AT", 16.0, 3.0), "drain": ("S", 25.0)}),
    # Floating roof: the vent and relief on the deck plate at y = 5. The fill has no
    # roof placement, since the deck moves; it enters the shell at y = 60.
    ("tank", "floating_roof"): ("vessels", "Tank (Floating Roof)",
                                {"inlet": [("W", 60), ("E", 60)],
                                 "outlet": ("S", 50),
                                 "vent": ("AT", 15.0, 5.0),
                                 "relief": ("AT", 45.0, 5.0),
                                 "drain": ("S", 20)}),
    # Sphere: the stencil draws three nozzles, two on the crown (vent, relief) and
    # one under the belly (outlet). The inlet and drain sit low on the shell circle
    # (cx 40, cy 45, r 40); the inlet at y = 75 keeps a W or E face.
    ("tank", "sphere"):        ("vessels", "Storage Sphere",
                                {"inlet": [("AT", 13.5, 75.0), ("AT", 66.5, 75.0)],
                                 "outlet": ("AT", 40.0, 90.0),
                                 "vent": ("AT", 24.0, 0.0),
                                 "relief": ("AT", 56.0, 0.0),
                                 "drain": ("AT", 54.9, 82.1)}),
    # Hopper-bottomed tanks keep the crown as their default fill and offer the shell
    # walls; the outlet takes the cone apex. Conical bottom: the flat roof takes the
    # vent and relief at x = 35 and 65, the drain sits halfway down the west slope at
    # (35, 91), and the fills take the walls at y = 60.
    ("tank", "conical_bottom"): ("vessels", "Tank (Conical Bottom)",
                                 {"inlet": [("N", 50), ("W", 60), ("E", 60)],
                                  "outlet": ("S", 50),
                                  "vent": ("N", 35), "relief": ("N", 65),
                                  "drain": ("AT", 35.0, 91.0)}),
    # Cone at each end: the shell walls are at x = 1 and 101, so the apexes are at
    # x = 51. Each cone rises 30 over 50, so the slope midpoints are (26, 15),
    # (76, 15) and (26, 135).
    ("tank", "conical_ends"): ("vessels", "Tank (Conical Roof and Bottom)",
                               {"inlet": [("N", 51), ("AT", 1.0, 110.0), ("E", 110)],
                                "outlet": ("S", 51),
                                "vent": ("AT", 26.0, 15.0),
                                "relief": ("AT", 76.0, 15.0),
                                "drain": ("AT", 26.0, 135.0)}),
    # ``default``'s dished roof and port map over a cone; the drain takes the west
    # slope's midpoint, (35, 116.5), since the apex is the outlet's.
    ("tank", "dished_roof_conical_bottom"): (
        "vessels", "Tank (Dished Roof, Conical Bottom)",
        {"inlet": [("AT", 50.0, 6.4), ("W", 85), ("E", 85)], "outlet": ("S", 50),
         "vent": ("AT", 35.0, 7.9), "relief": ("AT", 65.0, 7.9),
         "drain": ("AT", 35.0, 116.5)}),
    # Gas holder: the gas connections are on the seal tank walls at y = 45, not on
    # the moving bell; the vent and relief on the dome at x = 35 -+ 18; the drain on
    # the floor.
    ("tank", "gas_holder"): ("vessels", "Gas Holder",
                             {"inlet": ("W", 45.0), "outlet": ("E", 45.0),
                              "vent": ("AT", 17.0, 3.0),
                              "relief": ("AT", 53.0, 3.0),
                              "drain": ("S", 20.0)}),
    # Thickener: open at the top, so the feed and overflow take the walls at y = 8 and
    # the underflow the apex.
    ("thickener", "default"): ("vessels", "Settling Tank",
                               {"feed": ("W", 8.0), "overflow": ("E", 8.0),
                                "underflow": ("S", 50.0)}),
    # Horizontal vessel: inlet on either head or from above, liquid out of the bottom.
    # The whole top and bottom walls are its high and low points, so the relief and
    # drain take those faces directly.
    ("vessel", "horizontal"): ("vessels", "Drum or Condenser",
                               {"inlet": [("W", 15), ("N", 20.0), ("E", 15)],
                                "outlet": ("S", 68.0),
                                "vent": ("N", 55.0),
                                "relief": ("N", 30.0), "drain": ("S", 25.0)}),
    # Horizontal separator: the feed offers three faces, so it is a menu rather than
    # a family; ``Separator`` refuses ``n_feeds`` above one here.
    ("separator", "horizontal"): ("vessels", "Drum or Condenser",
                                  {"feed": [("W", 15), ("N", 20.0), ("E", 15)],
                                   "vapor": ("N", 30.0),
                                   "liquid": ("S", 68.0)}),
    # Hopper-bottomed bodies share one feed family on the 80 x 120 box, run down from
    # y = 12 (``FROM_START``) so that adding a feed leaves the first in place.
    ("separator", "cyclone"): ("separators", "Separator (Cyclone)",
                               {"feed": ("SERIES", "W", 12, 20, 0.5, FROM_START),
                                "vapor": "N", "liquid": "S"}),
    # Gas-cleaning vessels: gas across the top, the collected phase out of the apex.
    # The scrubber's wash header is on the centreline, so the clean gas leaves east.
    ("separator", "scrubber"): ("separators", "Separator (Wet Scrubber)",
                                {"feed": ("SERIES", "W", 12, 20, 0.5, FROM_START),
                                 "vapor": "E", "liquid": "S"}),
    # Venturi scrubber (ISO 8.11 X8034): ``scrubber``'s body and nozzles, so the two
    # swap without moving a run; draw.io's W/E anchors sit level with the throat, unused.
    ("separator", "venturi_scrubber"): ("separators", "Separator (Venturi Scrubber)",
                                        {"feed": ("SERIES", "W", 12.0, 20, 0.5, FROM_START),
                                         "vapor": ("E", 12.0), "liquid": "S"}),
    # The mechanical separators share the hopper body's anchors; ``overflow`` and
    # ``underflow`` name the high and low draws, not their contents.
    ("separator", "sifter"): ("separators", "Separator, Sifter",
                              {"feed": ("SERIES", "W", 12, 20, 0.5, FROM_START),
                               "overflow": "E", "underflow": "S"}),
    ("separator", "impact"): ("separators", "Impact Separator",
                              {"feed": ("SERIES", "W", 12, 20, 0.5, FROM_START),
                               "overflow": "E", "underflow": "S"}),
    ("separator", "permanent_magnet"): ("separators", "Separator (Permanent Magnet)",
                                        {"feed": ("SERIES", "W", 12, 20, 0.5, FROM_START),
                                         "overflow": "E", "underflow": "S"}),
    # Filter styles. Press Filter's W/E anchors sit on opposite corners, so both
    # faces are placed at the plate pack's mid-height. On a cake-forming filter the
    # wash comes in from above (N) and the cake falls out of the floor (S).
    ("filter", "gas"):    ("filters", "Gas Filter (Bag, Candle, Cartridge)",
                           {"inlet": "W", "outlet": "E"}),
    # The plate pack lies down; the wash and cake ports sit between the plate lines.
    ("filter", "press"):  ("filters", "Press Filter",
                           {"inlet": ("W", 25.0), "wash_in": ("N", 25.0),
                            "outlet": ("E", 25.0), "cake": ("S", 50.0)}),
    # The wash lands on top of the drum at (25, 0); the cake falls through the floor.
    ("filter", "rotary"): ("filters", "Liquid Filter (Rotary, Drum or Disc)",
                           {"inlet": ("W", 50.0), "wash_in": ("N", 25.0),
                            "outlet": "E", "cake": ("S", 25.0)}),
    # The same drum with its scraper; the arm widens the box east, so the outlet is
    # pinned to the casing wall at x = 50. The wash and cake match ``rotary``.
    ("filter", "rotary_scraper"): ("filters", "Liquid Filter (Rotary, Drum or Disc, Scraper)",
                                   {"inlet": ("W", 50.0), "wash_in": ("N", 25.0),
                                    "outlet": ("AT", 50.0, 50.0),
                                    "cake": ("S", 25.0)}),
    # Ion exchanger: piped across like the other filters; the regenerant enters
    # above the bed and the spent regenerant leaves through the underdrain.
    ("filter", "ion_exchange"): ("filters", "Liquid Filter (Ion Exchanger)",
                                 {"inlet": ("W", 50.0), "regenerant_in": ("N", 25.0),
                                  "outlet": ("E", 50.0),
                                  "spent_regenerant": ("S", 25.0)}),
    # Liquid and gas pairs of one medium; the gas half adds a hopper (see
    # GRAVITY_FIXED). All four are piped across at mid-height on the side walls.
    # Fixed bed: a granular medium between two retention screens.
    ("filter", "fixed_bed"):     ("filters", "Liquid Filter (Fixed Bed)",
                                  {"inlet": ("W", 50.0), "outlet": ("E", 50.0)}),
    ("filter", "gas_fixed_bed"): ("filters", "Gas Filter (Fixed Bed)",
                                  {"inlet": "W", "outlet": ("E", 50.0)}),
    # Belt / roll: the cloth runs low, so mid-height nozzles clear it. The liquid
    # one forms a cake and takes the N/S wash and cake pair.
    ("filter", "belt"):          ("filters", "Liquid Filter (Belt, Roll)",
                                  {"inlet": ("W", 50.0), "wash_in": ("N", 25.0),
                                   "outlet": "E", "cake": ("S", 25.0)}),
    ("filter", "gas_belt"):      ("filters", "Gas Filter (Belt, Roll)",
                                  {"inlet": "W", "outlet": ("E", 50.0)}),
    # Drier styles. A spray drier is piped top to bottom, so its gas nozzles go on
    # the side walls; the others take the gas at the floor and roof. ``heating_in``
    # and ``vent`` are pandid's own; see ``pandid.units.Dryer``.
    ("dryer", "fluidized_bed"): ("driers", "Drier (Fluidized Bed)",
                                 {"feed": "W", "product": "E",
                                  "heating_in": ("S", 50.0), "vent": ("N", 50.0)}),
    ("dryer", "spray"): ("driers", "Spray Drier",
                         {"feed": ("N", 50.0), "product": ("S", 50.0),
                          "heating_in": ("W", 50.0), "vent": ("E", 50.0)}),

    # --- New classes (genuinely different port signature / function) ---
    # The process coil enters at (0, 54.5) and leaves at (80, 79.5).
    ("furnace", "default"): ("vessels", "Furnace",
                             {"inlet": ("W", 54.5), "outlet": ("E", 79.5), "fuel": "S"}),
    ("turbine", "default"): ("pumps", "Turbine", {"inlet": "W", "outlet": "E"}),
    # Cooling tower: the nozzles are named for the side (water, air), as on ``hex``;
    # ``makeup`` and ``blowdown`` flank ``water_out`` on the basin floor, and both
    # drawings offer the same six. Induced draft: the air leaves the stack top and
    # enters the east louvre; ``water_in`` is on the west slope at y = 20.
    ("cooling_tower", "default"): ("vessels", "Induced-Draft Cooling Tower",
                                   {"water_in": ("AT", 4.8, 20.0), "water_out": "S",
                                    "air_in": "E", "air_out": "N",
                                    "makeup": ("S", 28.0), "blowdown": ("S", 70.0)}),
    ("cooling_tower", "induced_draft"): ("vessels", "Induced-Draft Cooling Tower",
                                         {"water_in": ("AT", 4.8, 20.0), "water_out": "S",
                                          "air_in": "E", "air_out": "N",
                                          "makeup": ("S", 28.0), "blowdown": ("S", 70.0)}),
    # Forced draft: ``air_in`` on the fan housing's outer wall at (89.5, 77); the
    # rest restates the induced-draft tower in this drawing's dimensions.
    ("cooling_tower", "forced_draft"): ("vessels", "Forced-Draft Cooling Tower",
                                        {"water_in": ("AT", 19.5, 25.0), "water_out": "S",
                                         "air_in": ("AT", 89.5, 77.0), "air_out": "N",
                                         "makeup": ("S", 25.0), "blowdown": ("S", 75.0)}),
    ("filter", "default"):  ("filters", "Liquid Filter (Bag, Candle, Cartridge)", {"inlet": "W", "outlet": "E"}),
    ("dryer", "default"):   ("driers", "Rotary Drum Drier, Tumbling Drier",
                             {"feed": "W", "product": "E",
                              "heating_in": ("S", 50.0), "vent": ("N", 50.0)}),
    # Ejector: the stencil's "S" sits on the chest's corner, so the suction is
    # placed mid-face.
    ("ejector", "default"): ("fittings", "Injector",
                             {"motive": "W", "suction": ("S", 20.0), "discharge": "E"}),
    # Open ends. Each is a stem with something on top of it, so the single pipe
    # connection is the free end of that stem, at the bottom of the box.
    ("vent", "default"):   ("fittings", "Vent", {"inlet": ("S", 40.0)}),
    ("funnel", "default"): ("fittings", "Funnel", {"outlet": ("S", 40.0)}),
    # Two open ends from piping.xml, piped from below like a Vent.
    # Exhaust head: the riser meets the cone apex at (25, 40).
    ("vent", "exhaust_head"): ("piping", "Exhaust Head", {"inlet": ("S", 25.0)}),
    # Breather: the tank conservation vent, drawn as a box on a stem. The stem's
    # free end at (25, 30) is the tank connection.
    ("vent", "breather"):     ("piping", "Breather", {"inlet": ("S", 25.0)}),
}


# Devices drawn open and closed: the closed shape, registered through
# ``SymbolRegistry.register_closed`` under the same (kind, variant). render()
# refuses a pair whose boxes, nozzles or aspect differ.
# (kind, variant) -> the shape drawn when the device is declared normally closed
CLOSED_SHAPES = {
    ("fitting", "blind"): "Closed Figure 8 Blind",
}

# Kinds ISO 10628-1 §5.3.1 c) draws at half the equipment line weight: valves,
# fittings and piping accessories, chosen by pandid kind, not by stencil file.
TRIM_KINDS = frozenset({"valve", "fitting", "reducer", "vent", "funnel", "ejector"})


# Corrections to shapes draw.io draws wrongly, appended to the shape's
# <foreground> in its own drawing language; the vendored XML stays as vendored.
# (stencil, shape) -> (what is wrong upstream, mxGraph fragment)
STENCIL_PATCHES = {
    # Upstream's "Globe Valve" is a copy of "Ball Valve"; fill the seat with the
    # stencil's own four arcs, leaving the body white.
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
    """Apply the :data:`STENCIL_PATCHES` entry for one parsed shape.

    The fragment is appended to the shape's ``<foreground>``, so it paints
    over what the stencil drew.

    Parameters
    ----------
    stencil : str
        Stencil file stem.
    name : str
        Shape name within the stencil.
    el : xml.etree.ElementTree.Element
        Parsed ``<shape>`` element.

    Returns
    -------
    xml.etree.ElementTree.Element
        The same element, patched in place when an entry exists.
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


# Symbols that must not be turned, as ``Symbol.gravity_fixed`` (ISO 15519-1
# §11.4.2): those whose artwork draws a separation, containment or holdup done by
# gravity.
# (kind, variant) -> what in the artwork only means one thing one way up
GRAVITY_FIXED = {
    # ISO's own example, X 2618, and the separators that drop a phase the same way.
    ("separator", "default"):       "vapour disengages off the top, liquid draws off the bottom",
    ("separator", "cyclone"):       "ISO 14617 symbol X 2618; apex points down",
    ("separator", "horizontal"):    "vapour disengages off the top, liquid draws off the bottom",
    ("separator", "knockout"):      "demister on top, vapour up and liquid down",
    ("separator", "scrubber"):      "hopper bottom under a wash-liquid header",
    # The venturi throat runs down into the hopper.
    ("separator", "venturi_scrubber"):
        "wash spray on the crown, throat running down into the hopper",
    # The mechanical separators, held by the hopper drawn under them.
    ("separator", "sifter"):           "screen deck over a hopper; the undersize falls through it",
    ("separator", "impact"):           "hopper bottom under the baffle, collected phase out of the apex",
    ("separator", "permanent_magnet"): "hopper bottom, separated fraction out of the apex",
    # ISO's other example, 2061: a free surface, filled at the roof, drained low.
    ("tank", "default"):        "dished roof over a free surface, draw at the floor",
    ("tank", "conical"):        "conical roof over a free surface, draw at the floor",
    ("tank", "floating_roof"):  "the roof floats on the liquid",
    ("tank", "sphere"):         "stands on a skirt; relief and vapour on the crown, liquid below",
    ("tank", "conical_bottom"): "flat roof over a free surface, drains to the cone apex",
    ("tank", "conical_ends"):   "conical roof over a free surface, drains to the cone apex",
    ("tank", "dished_roof_conical_bottom"):
        "dished roof over a free surface, drains to the cone apex",
    # The bell rests on the water seal.
    ("tank", "gas_holder"):     "the bell floats on the water seal",
    # Holdup with a vapour space: vent on top, drain from the shell.
    ("vessel", "default"):    "vent on the top head, free surface below it",
    ("vessel", "dished"):     "vent on the top head; stands on brackets",
    ("vessel", "dome"):       "the manway dome is on top",
    ("vessel", "horizontal"): "vent off the top, liquid out of the bottom",
    ("vessel", "jacketed"):   "vent on the top head, free surface below it",
    ("vessel", "insulated"):  "vent on the top head, free surface below it",
    ("vessel", "electrical_heating"): "vent on the top head, low draw-off from the shell",
    # The larger diameter, below, holds the inventory.
    ("vessel", "swaged"):     "vent on the top head, and the larger diameter is the one below it",
    # Liquid runs down a tower and vapour rises through it.
    ("column", "default"): "distillate off the top, bottoms off the floor",
    ("column", "packed"):  "packed beds rest on their support grids",
    # A charge vessel: the agitator hangs into it from above and the contents
    # drain out of the dished bottom, with the off-gas taken from the top.
    ("reactor", "default"):  "top-entering agitator over a dished bottom",
    ("reactor", "jacketed"): "top-entering agitator over a dished bottom, inside its jacket",
    # Open ends: pointing down, an open end is a drain, not a vent.
    ("vent", "default"):      "weather cap on top of the stack",
    ("vent", "breather"):     "the tank conservation vent sits on the roof",
    ("vent", "exhaust_head"): "the V-bottom catches and drains condensate",
    ("funnel", "default"):    "open cone above a stem that drains down",
    # Water falls through the fill into the basin, whatever the fan arrangement.
    ("cooling_tower", "default"):        "the water falls through the fill into the basin",
    ("cooling_tower", "induced_draft"):  "the water falls through the fill into the basin",
    ("cooling_tower", "forced_draft"):   "the water falls through the fill into the basin",
    # Solids that fall: powder out of the spray drier's floor, a fluidised bed on its plate.
    ("dryer", "spray"):         "atomiser in the roof, powder out of the floor",
    ("dryer", "fluidized_bed"): "the bed is a layer on its distributor plate",
    # The gas filters' dust hopper.
    ("filter", "gas"):           "dust hopper under the bags",
    ("filter", "gas_fixed_bed"): "dust hopper under the bed",
    ("filter", "gas_belt"):      "dust hopper under the belt",
    # A thickener settles solids into a raked cone under an open rim.
    ("thickener", "default"): "open rim over a raked cone; the solids settle into it",
}

# Symbols whose arrowhead states a direction of flow that a mirror would reverse,
# as ``Symbol.directional``.
DIRECTIONAL = {
    ("heater", "default"): "the arrowhead on the diagonal is the whole of what "
                           "makes this a heater and not a cooler",
    ("cooler", "default"): "the arrowhead on the diagonal is the whole of what "
                           "makes this a cooler and not a heater",
    ("hex", "condenser"):  "the same drawing as cooler/default, and the same "
                           "arrowhead carrying the same statement",
}


# Where a family may put a nozzle on a face, as ``{face: (lo, hi)}`` along that
# face in finished coordinates; emitted as ``Symbol.bands``. A band is the
# straight wall held 10 off each end, or the drawn nozzle's own clearance; a
# curved head, apex or crown offers one point, ``(t, t)``.
BANDS = {
    # Shell y 25.46..95.46; N is the dome crown, S the floor.
    ("tank", "default"): {"W": (36.0, 85.0), "E": (36.0, 85.0), "S": (10.0, 90.0),
                          "N": (50.0, 50.0)},
    # Shell y 20..90 under the conical roof; the fill at 80 is ten above the
    # floor. N is the cone apex; S is the flat floor.
    ("tank", "conical"): {"W": (30.0, 80.0), "E": (30.0, 80.0), "S": (10.0, 90.0),
                          "N": (50.0, 50.0)},
    # Shell y 0..70 over the cone; the roof is flat; S is the cone apex.
    ("tank", "conical_bottom"): {"N": (10.0, 90.0), "W": (10.0, 60.0), "E": (10.0, 60.0),
                                 "S": (50.0, 50.0)},
    # Shell y 30..120 between the two cones; the fill at 110 is ten above the
    # lower knuckle. Both N and S are cone apexes.
    ("tank", "conical_ends"): {"W": (40.0, 110.0), "E": (40.0, 110.0),
                               "N": (51.0, 51.0), "S": (51.0, 51.0)},
    # tank/default's shell; N is the dome crown, S the cone apex.
    ("tank", "dished_roof_conical_bottom"): {"W": (36.0, 85.0), "E": (36.0, 85.0),
                                             "N": (50.0, 50.0), "S": (50.0, 50.0)},
    # Shell y 0..70, roof and floor both flat; the fill at 60 is ten above the
    # floor.
    ("tank", "floating_roof"): {"W": (10.0, 60.0), "E": (10.0, 60.0), "S": (10.0, 90.0)},
    # The seal tank's wall, y 30..95; the bell carries no connection.
    ("tank", "gas_holder"): {"W": (45.0, 80.0), "E": (45.0, 80.0)},
    # The sphere meets W and E at y = 75 only; S is the draw-off boss.
    ("tank", "sphere"): {"W": (75.0, 75.0), "E": (75.0, 75.0), "S": (40.0, 40.0)},
    # The barrel, y 7.5..92.5 as drawn, held 10 off each end.
    ("vessel", "default"): {"W": (17.5, 82.5), "E": (17.5, 82.5)},
    ("vessel", "dished"): {"W": (17.7, 77.7), "E": (17.7, 77.7)},
    # Drawn on its side: the W and E faces are the two dished heads, and a head
    # meets the box at its apex alone.
    ("vessel", "dome"): {"W": (27.0, 27.0), "E": (27.0, 27.0)},
    # The same 7,7..87,7 barrel. The outlet is drawn at 77,7, which is where the
    # 10 clearance already puts the band's lower end, so it does not move.
    ("vessel", "electrical_heating"): {"W": (17.7, 77.7), "E": (17.7, 77.7)},
    # The lagging lines, y 12.69..82.69, are the W and E faces.
    ("vessel", "insulated"): {"W": (22.7, 72.7), "E": (22.7, 72.7)},
    # The jacket, for insulated's reason: the outer faces are the jacket boxes,
    # y 12,69..82,69.
    ("vessel", "jacketed"): {"W": (22.7, 72.7), "E": (22.7, 72.7)},
    # Only the lower, larger barrel meets the W and E faces.
    ("vessel", "swaged"): {"W": (60.3, 75.0), "E": (60.0, 75.0)},
    # Roof and floor between the heads; W and E are the heads' apexes at y = 15.
    ("vessel", "horizontal"): {"N": (15.8, 75.8), "S": (15.8, 75.8),
                               "W": (15.0, 15.0), "E": (15.0, 15.0)},
}


# ISO 10628-2 registration numbers for vendored drawings checked against
# Table 2 (see ``Symbol.iso_reg``).
ISO_REG = {
    # Item 12.2 X2673; see ``pandid.render.symbols._register_mixers``.
    ("fitting", "static_mixer"): "X2673",
}


# Scale factors by kind, or by (kind, variant) for one variant. A value is one
# factor, or an (sx, sy) pair that reproportions the shape. The inline family
# takes 0.25, which draws a gate valve 24.5 x 15.0; flow_sensors.xml and
# piping.xml shapes are on a 50-unit module and take 0.5.
HALF_SCALE_FITTINGS = (
    # flow_sensors.xml: the primary elements
    "venturi", "flow_nozzle", "coriolis", "vortex", "ultrasonic",
    "turbine_meter", "positive_displacement", "v_cone", "wedge", "target",
    "pitot", "averaging_pitot",
    # piping.xml: the in-line devices
    "strainer_y", "strainer_basket", "strainer_duplex",
    "bellows", "damper", "spool",
    # ...and the spectacle blind, on the same module.
    "blind",
)

# Three valves.xml shapes are off that file's module, so each takes its own
# factor: the PSV and the relief valve scale their seat or bonnet to 15.0 across
# the run, and the pneumatic butterfly takes a pair that draws its body 24.5 x 15.0.
SCALE = {"valve": 0.25, "fitting": 0.25,
         "vent": 0.25, "funnel": 0.25,
         ("valve", "psv"): 15.0 / 42, ("valve", "relief"): 15.0 / 40,
         ("valve", "butterfly_pneumatic"): (24.5 / 60, 15.0 / 40),
         **{("fitting", variant): 0.5 for variant in HALF_SCALE_FITTINGS},
         # ...and the two open ends taken from the same 50-unit file.
         ("vent", "exhaust_head"): 0.5, ("vent", "breather"): 0.5,
         # Every reducer is drawn 12.5 tall, the line it sits in.
         "reducer": 12.5 / 20, ("reducer", "eccentric"): 12.5 / 15,
         # A drum is short and a tower slender: 62 x 100 against the column's 100 x 200.
         ("vessel", "default"): (0.62, 0.5),
         # The flash drum shares the column's stencil and takes the drum's box.
         ("separator", "default"): (0.62, 0.5),
         # The stirred tank shares the same stencil and box.
         ("reactor", "default"): (0.62, 0.5),
         # 62 x 200: the column's height, so no nozzle moves vertically, at the drum's width.
         ("column", "packed"): (62 / 14, 200 / 97)}


def scale_for(kind, variant):
    """Return the scale a symbol's artwork is drawn at.

    A ``(kind, variant)`` entry in :data:`SCALE` takes precedence over the
    entry for the kind.

    Parameters
    ----------
    kind : str
        Unit kind.
    variant : str
        Symbol variant.

    Returns
    -------
    tuple[float, float]
        Horizontal and vertical scale factors.
    """
    s = SCALE.get((kind, variant), SCALE.get(kind, 1.0))
    return (float(s), float(s)) if isinstance(s, (int, float)) else (float(s[0]), float(s[1]))


def drawio_shape_key(namespace, shape_name):
    """Return the key draw.io's stencil registry gives a shape.

    draw.io joins the stencil package and the shape name, replaces spaces
    with underscores, and lowercases the result. It draws a plain rectangle
    for an unknown key, so the key is derived by the same rule. draw.io
    splits the key on dots to find the stencil file, so a dot in the shape
    name is rejected.

    Parameters
    ----------
    namespace : str
        Package declared by the stencil file, for example
        ``mxGraph.pid.valves``.
    shape_name : str
        Shape name as written in the stencil.

    Returns
    -------
    str
        Registry key, for example ``mxgraph.pid.valves.gate_valve``.

    Raises
    ------
    SystemExit
        If the shape name contains a dot.
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
    """Return whether a port spec declares a nozzle family.

    Parameters
    ----------
    spec : object
        Port specification from :data:`KIND_MAP`.

    Returns
    -------
    bool
        Whether the spec is a ``("SERIES", ...)`` tuple.
    """
    return isinstance(spec, tuple) and spec[0] == "SERIES"


def resolve_port(spec, constraints, w, h):
    """Resolve a single-nozzle port spec to a point in the shape's units.

    A spec is a named draw.io constraint such as ``"W"``, an edge offset
    such as ``("E", 10.0)``, or an absolute point such as ``("AT", x, y)``
    for a nozzle inboard of the bounding box. A ``("SERIES", ...)`` spec is
    handled by :func:`drawing`, not here.

    Parameters
    ----------
    spec : str or tuple
        Port specification.
    constraints : dict[str, tuple[float, float]]
        Named anchors read from the stencil.
    w, h : float
        Shape width and height.

    Returns
    -------
    tuple[float, float]
        Port coordinates.

    Raises
    ------
    SystemExit
        If a named constraint is missing from the stencil.
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
    """Convert one shape and resolve its ports at the family's scale.

    A port spec given as a list declares alternate faces after its home
    placement.

    Parameters
    ----------
    el : xml.etree.ElementTree.Element
        Parsed ``<shape>`` element.
    kind : str
        Unit kind.
    variant : str
        Symbol variant.
    port_map : dict[str, object]
        Port specifications keyed by port name.
    sx, sy : float
        Horizontal and vertical scale factors.

    Returns
    -------
    tuple
        ``(inner, w, h, ports, menu, series, aspect)``: the SVG artwork, its
        size, single-nozzle points, face menus, nozzle families, and the
        stencil's aspect setting.

    Raises
    ------
    SystemExit
        If an alternate face is not an edge or point spec.
    """
    # Stroke heavier so it renders at 2px after the scale; for uneven factors the
    # geometric mean holds the elliptical pen's area to the circle's.
    inner, w, h, constraints, aspect = convert_shape(
        el, stroke_width=round(2.0 / math.sqrt(sx * sy), 3))
    # A list spec is the home placement, then alternate faces; an ``AT`` alternate's
    # face is read off the scaled point by ``outward_dir``.
    ports, alts, series = {}, {}, {}
    for p, spec in port_map.items():
        if is_series(spec):
            _, edge, along, pitch, extent, *rest = spec
            series[p] = (edge, float(along), float(pitch), float(extent),
                         rest[0] if rest else CENTRED)
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
                      pitch * (sy if e in ("W", "E") else sx), ext, align)
                  for p, (e, at, pitch, ext, align) in series.items()}
    w, h = round(w, 1), round(h, 1)
    ports = {p: tuple(round(v, 1) for v in xy) for p, xy in ports.items()}
    alts = {p: [(f, tuple(round(v, 1) for v in xy)) for f, xy in v]
            for p, v in alts.items()}
    # Emit the whole menu, home first.
    menu = {}
    for p, entries in alts.items():
        faces = {outward_dir(*ports[p], w, h): ports[p]}
        for face, xy in entries:
            faces[face or outward_dir(*xy, w, h)] = xy
        menu[p] = faces
    return inner, w, h, ports, menu, series, aspect


def render() -> str:
    """Return the text of the generated module without writing it.

    A test compares this text with the committed ``_vendored_symbols.py``.

    Returns
    -------
    str
        Python source with LF line endings.

    Raises
    ------
    SystemExit
        If a table names a shape or symbol the generator does not draw, or
        the two states of a device differ in more than their artwork.
    """
    # Index every shape once, applying STENCIL_PATCHES, and note each file's package.
    index = {}
    namespaces = {}
    for stencil in {m[0] for m in KIND_MAP.values()}:
        namespaces[stencil] = stencil_namespace(STENCILS / f"{stencil}.xml")
        for name, el in shapes_in(STENCILS / f"{stencil}.xml"):
            index[(stencil, name)] = patch_shape(stencil, name, el)
    # Refuse a patch that matches nothing.
    missing = sorted(key for key in STENCIL_PATCHES if key not in index)
    if missing:
        raise SystemExit(
            "STENCIL_PATCHES names shapes the generator did not load: "
            + ", ".join(f"{stencil}:{shape}" for stencil, shape in missing)
        )
    # Refuse a table entry for a symbol KIND_MAP does not draw.
    tables = {"CLOSED_SHAPES": CLOSED_SHAPES, "GRAVITY_FIXED": GRAVITY_FIXED,
              "DIRECTIONAL": DIRECTIONAL, "BANDS": BANDS}
    for table_name, table in tables.items():
        orphans = sorted(key for key in table if key not in KIND_MAP)
        if orphans:
            raise SystemExit(
                f"{table_name} names symbols KIND_MAP does not draw: "
                + ", ".join(f"{kind}/{variant}" for kind, variant in orphans)
            )

    specs = [spec for _, _, port_map in KIND_MAP.values() for spec in port_map.values()]
    names = ["Symbol"]
    if any(is_series(spec) for spec in specs):
        names.append("PortSeries")
    # Import FROM_START only when a series uses it.
    if any(is_series(spec) and len(spec) > 5 and spec[5] == FROM_START for spec in specs):
        names.append("FROM_START")
    imports = ", ".join(sorted(names))
    lines = [
        '"""Equipment symbols adapted from draw.io stencils (Apache-2.0).',
        "",
        'Generated by scripts/vendor_symbols.py; do not edit. See NOTICE.',
        '"""',
        "",
        "",
        "def register_vendored(registry):",
        '    """Register the vendored symbols.',
        "",
        '    Parameters',
        '    ----------',
        '    registry : SymbolRegistry',
        '        Registry to register the symbols on.',
        '    """',
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
            # The two positions must share box and nozzles and differ in ink.
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
                f"    registry.{method}({kind!r}, Symbol(",
                f"        svg={svg!r},",
                f"        width={w}, height={h},",
                f"        ports={ports!r},",
                # The draw.io registry key, so an export can name the stencil shape.
                f"        drawio_shape="
                f"{drawio_shape_key(namespaces[stencil], shape_name)!r},",
            ]
            # A registration number only for a drawing checked against Table 2; see ISO_REG.
            if not suffix and (kind, variant) in ISO_REG:
                lines.append(f"        iso_reg={ISO_REG[(kind, variant)]!r},")
            # ISO 10628-1 §5.3.1 c), by kind; see TRIM_KINDS.
            if kind in TRIM_KINDS:
                lines.append("        trim=True,")
            if suffix:
                # A second drawing of one (kind, variant) needs a <defs> entry of
                # its own, which is what the suffix on the id buys.
                lines.append(f"        id_suffix={suffix!r},")
            # Only the shapes that refuse to be reshaped say so: stretchable is
            # the default on Symbol, exactly as "variable" is in a stencil.
            if aspect == "fixed":
                lines.append("        stretchable=False,")
            # ISO 15519-1 11.4.2: gravity is a functionality here, so the symbol
            # must not be turned.
            if (kind, variant) in GRAVITY_FIXED:
                lines.append("        gravity_fixed=True,")
            if (kind, variant) in DIRECTIONAL:
                if "<text" in inner:
                    raise SystemExit(
                        f"{kind}/{variant} is DIRECTIONAL and carries lettering; "
                        f"the renderer holds a directional drawing still as a whole "
                        f"and cannot also counter-transform a glyph inside it"
                    )
                lines.append("        directional=True,")
            if menu:
                lines.append(f"        port_faces={menu!r},")
            # See BANDS; the closed drawing shares the open one's body.
            if (kind, variant) in BANDS:
                lines.append(f"        bands={BANDS[(kind, variant)]!r},")
            # A family is named after the port it replaces: one member keeps
            # that name, and only a second one numbers them.
            if series:
                declared = ", ".join(
                    f"PortSeries({p + '_'!r}, {edge!r}, pitch={round(pitch, 1)}, "
                    f"extent={extent}, at={round(at, 1)}, singular={p!r}"
                    + (f", align={_ALIGN_NAMES[align]})" if align != CENTRED else ")")
                    for p, (edge, at, pitch, extent, align) in series.items()
                )
                lines.append(f"        port_series=({declared},),")
            lines += [
                f"    ), {variant!r})",
                "",
            ]
    # LF, to match the committed file read back in text mode.
    return "\n".join(lines)


def main():
    """Write the generated module and print a summary."""
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT} ({len(KIND_MAP)} symbols, "
          f"{len(CLOSED_SHAPES)} of them in two positions)")


if __name__ == "__main__":
    main()

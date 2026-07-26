#!/usr/bin/env python3
"""Generate pfd/render/_vendored_symbols.py from draw.io (jgraph/drawio) P&ID
stencils (Apache-2.0). See NOTICE for attribution.

Each mapped symbol is converted from mxGraph stencil XML to plain SVG by
scripts/mxgraph_to_svg.py, and its ports are resolved either from the stencil's
named <constraint> anchors ("W"/"E"/"N"/"S"/...) or placed explicitly on a
bounding-box edge as ``(edge, along)`` for shapes that lack a needed anchor.

Run:  python scripts/vendor_symbols.py
"""
import pathlib

import sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from mxgraph_to_svg import shapes_in, convert_shape  # noqa: E402
from pfd.portgeom import outward_dir  # noqa: E402  (the one place a face is derived)

STENCILS = HERE / "vendor_data" / "drawio"
OUT = HERE.parent / "pfd" / "render" / "_vendored_symbols.py"

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
    # SCALE["valve"] = 0.5 then halves.
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
    ("vessel", "default"): ("vessels", "Barrel, Drum",
                            {"inlet": "W", "outlet": "E", "vent": ("N", 31.0)}),
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
    # Pump / compressor styles.
    ("pump", "vacuum"):           ("pumps", "Vacuum Pump",
                                   {"suction": ("W", 25.0), "discharge": ("E", 25.0)}),
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
    ("tank", "floating_roof"): ("vessels", "Tank (Floating Roof)", {"inlet": ("N", 30), "outlet": ("S", 50)}),
    ("tank", "sphere"):        ("vessels", "Storage Sphere", {"inlet": ("N", 40), "outlet": ("S", 40)}),
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
}


# draw.io draws inline devices oversized; scale them to read as small devices
# (lines stay 2px thanks to non-scaling-stroke).
SCALE = {"valve": 0.5, "fitting": 0.5, "vent": 0.5, "funnel": 0.5}


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
    all: it hands the port to a :class:`~pfd.render.symbols.PortSeries`, which
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


def build():
    # Index every shape once.
    index = {}
    for stencil in {m[0] for m in KIND_MAP.values()}:
        for name, el in shapes_in(STENCILS / f"{stencil}.xml"):
            index[(stencil, name)] = el

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
        f"    from pfd.render.symbols import {imports}",
        "",
    ]
    for (kind, variant), (stencil, shape, port_map) in KIND_MAP.items():
        el = index.get((stencil, shape))
        if el is None:
            raise SystemExit(f"shape {shape!r} not in {stencil}.xml")
        s = SCALE.get(kind, 1.0)
        # Emit a heavier stroke on scaled symbols so it renders at 2px after the
        # scale transform (2px matches streams + hand-drawn symbols exactly).
        inner, w, h, constraints = convert_shape(el, stroke_width=round(2.0 / s, 3))
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

        if s != 1.0:
            inner = f'<g transform="scale({s})">{inner}</g>'
            w, h = w * s, h * s
            ports = {p: (x * s, y * s) for p, (x, y) in ports.items()}
            alts = {p: {f: (x * s, y * s) for f, (x, y) in d.items()} for p, d in alts.items()}
            series = {p: (e, at * s, pitch * s, ext) for p, (e, at, pitch, ext) in series.items()}
        w, h = round(w, 1), round(h, 1)
        ports = {p: tuple(round(v, 1) for v in xy) for p, xy in ports.items()}
        alts = {p: {f: tuple(round(v, 1) for v in xy) for f, xy in d.items()}
                for p, d in alts.items()}
        # Emit the whole menu, home first: Symbol keeps exactly one enumeration
        # of a port's placements, so a symbol with alternates must declare the
        # default among them rather than leave it to be merged in later.
        menu = {p: {outward_dir(*ports[p], w, h): ports[p], **d} for p, d in alts.items()}
        sid = kind if variant == "default" else f"{kind}_{variant}"
        svg = f'<g id="sym_{sid}">{inner}</g>'
        lines += [
            f"    # draw.io {stencil}:{shape} -> {kind}/{variant}",
            f"    registry.register({kind!r}, Symbol(",
            f"        svg={svg!r},",
            f"        width={w}, height={h},",
            f"        ports={ports!r},",
        ]
        if menu:
            lines.append(f"        port_faces={menu!r},")
        # A family is named after the port it replaces: one member keeps that
        # name, and only a second one numbers them.
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
    print(f"wrote {OUT} ({len(KIND_MAP)} symbols)")


if __name__ == "__main__":
    build()

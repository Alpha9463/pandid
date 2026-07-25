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
from mxgraph_to_svg import shapes_in, convert_shape  # noqa: E402

STENCILS = HERE / "vendor_data" / "drawio"
OUT = HERE.parent / "pfd" / "render" / "_vendored_symbols.py"

# (kind, variant) -> (stencil, shape_name, {port_name: "constraint" | (edge, along)})
KIND_MAP = {
    # Valves — inline family (inlet W / outlet E).
    ("valve", "default"):   ("valves", "Gate Valve",        {"inlet": "W", "outlet": "E"}),
    ("valve", "gate"):      ("valves", "Gate Valve",        {"inlet": "W", "outlet": "E"}),
    ("valve", "globe"):     ("valves", "Globe Valve",       {"inlet": "W", "outlet": "E"}),
    ("valve", "ball"):      ("valves", "Ball Valve",        {"inlet": "W", "outlet": "E"}),
    ("valve", "butterfly"): ("valves", "Butterfly Valve 1", {"inlet": "W", "outlet": "E"}),
    ("valve", "check"):     ("valves", "Check Valve 1",     {"inlet": "W", "outlet": "E"}),
    ("valve", "control"):   ("valves", "Diaphragm",         {"inlet": "W", "outlet": "E"}),
    ("valve", "needle"):    ("valves", "Needle",            {"inlet": "W", "outlet": "E"}),
    ("valve", "three_way"): ("valves", "Three-Way Valve",   {"inlet": "W", "outlet": "E"}),
    ("valve", "relief"):    ("valves", "Relief PRV",        {"inlet": "S", "outlet": "N"}),
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
    # hot_in: the raw "N" anchor lands on the cone vertex where three segments
    # meet; put it mid-span of the flat shell top over the vapour space.
    ("hex", "kettle"):  ("heat_exchangers", "Reboiler",
                         {"cold_in": "W", "cold_out": "E",
                          "hot_in": ("N", 64.0), "hot_out": "S"}),
    ("heater", "default"): ("heat_exchangers", "Heater",
                            {"inlet": "W", "outlet": "E", "duty": "S"}),
    ("cooler", "default"): ("heat_exchangers", "Heat Exchanger (Spiral)",
                            {"inlet": "W", "outlet": "E", "duty": "N"}),
    # Vessels / columns / reactors / separators / tanks.
    ("vessel", "default"): ("vessels", "Barrel, Drum", {"inlet": "W", "outlet": "E"}),
    # reflux_in / boilup_in ride the same straight shell wall as the feed (the
    # shell spans y 15..185), reflux high and boilup low, matching where those
    # streams physically re-enter the tower.
    ("column", "default"): ("vessels", "Pressurized Vessel",
                            {"feed": ("W", 130), "distillate": ("N", 50), "bottoms": ("S", 50),
                             "reflux_in": ("W", 40), "boilup_in": ("W", 175),
                             "reboiler_duty": ("E", 170), "condenser_duty": ("E", 40)}),
    # vent sits on the vessel's top edge, clear of the agitator shaft at x 24..26.
    ("reactor", "default"): ("vessels", "Mixing Reactor",
                             {"feed": "W", "outlet": "S", "duty": "E",
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

    # --- Variants (style choices within a class; same ports) ---
    # Heat exchanger styles.
    ("hex", "shell_tube"): ("heat_exchangers", "Shell and Tube Heat Exchanger 1",
                            {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
    ("hex", "u_tube"):     ("heat_exchangers", "U-Tube Heat Exchanger",
                            {"cold_in": "W", "cold_out": "E", "hot_in": "N", "hot_out": "S"}),
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
                           {"inlet": ("AT", 10.0, 47.0), "outlet": ("AT", 50.0, 47.0)}),
    ("vessel", "dome"):   ("vessels", "Vessel (Dome)", {"inlet": ("W", 27), "outlet": ("E", 27)}),
    ("tank", "floating_roof"): ("vessels", "Tank (Floating Roof)", {"inlet": ("N", 30), "outlet": ("S", 50)}),
    ("tank", "sphere"):        ("vessels", "Storage Sphere", {"inlet": ("N", 40), "outlet": ("S", 40)}),
    # Reactor / separator styles.
    ("reactor", "plain"):     ("vessels", "Reactor",
                               {"feed": ("W", 30), "outlet": ("S", 20), "duty": ("E", 47),
                                "vent": ("AT", 30.0, 7.69)}),
    ("separator", "cyclone"): ("separators", "Separator (Cyclone)", {"feed": "W", "vapor": "N", "liquid": "S"}),
    ("separator", "gravity"): ("separators", "Gravity Separator, Settling Chamber",
                               {"feed": "W", "vapor": "E", "liquid": "S"}),

    # --- New classes (genuinely different port signature / function) ---
    # The process coil is drawn entering at (0, 54.5) and leaving at (80, 79.5);
    # the W/E anchors sit on blank casing wall at mid-height instead, which also
    # destroys the high-in / low-out reading of the coil.
    ("furnace", "default"): ("vessels", "Furnace",
                             {"inlet": ("W", 54.5), "outlet": ("E", 79.5), "fuel": "S"}),
    ("turbine", "default"): ("pumps", "Turbine", {"inlet": "W", "outlet": "E"}),
    ("filter", "default"):  ("filters", "Liquid Filter (Bag, Candle, Cartridge)", {"inlet": "W", "outlet": "E"}),
    ("dryer", "default"):   ("driers", "Rotary Drum Drier, Tumbling Drier", {"feed": "W", "product": "E"}),
}


# draw.io draws inline valves oversized; scale them to read as small devices
# (lines stay 2px thanks to non-scaling-stroke).
SCALE = {"valve": 0.5}


def resolve_port(spec, constraints, w, h):
    """Resolve a port spec to (x, y) in the shape's own units.

    ``"W"``            - a named draw.io <constraint> anchor (compass point).
    ``("E", 10.0)``    - a point on a bounding-box edge, at the given offset.
    ``("AT", x, y)``   - an absolute point, for nozzles that sit inboard of the
                         bounding box (e.g. a dome crown, or a shell wall drawn
                         inside the box because brackets widen the extent).
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

    lines = [
        '"""draw.io-derived equipment symbols (Apache-2.0). GENERATED by',
        'scripts/vendor_symbols.py — do not edit by hand. See NOTICE for attribution."""',
        "",
        "",
        "def register_vendored(registry):",
        '    """Register the vendored draw.io symbols, overriding hand-drawn',
        '    defaults of the same (kind, variant)."""',
        "    from pfd.render.symbols import Symbol",
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
        ports = {p: resolve_port(spec, constraints, w, h) for p, spec in port_map.items()}
        if s != 1.0:
            inner = f'<g transform="scale({s})">{inner}</g>'
            w, h = w * s, h * s
            ports = {p: (x * s, y * s) for p, (x, y) in ports.items()}
        w, h = round(w, 1), round(h, 1)
        ports = {p: tuple(round(v, 1) for v in xy) for p, xy in ports.items()}
        sid = kind if variant == "default" else f"{kind}_{variant}"
        svg = f'<g id="sym_{sid}">{inner}</g>'
        lines += [
            f"    # draw.io {stencil}:{shape} -> {kind}/{variant}",
            f"    registry.register({kind!r}, Symbol(",
            f"        svg={svg!r},",
            f"        width={w}, height={h},",
            f"        ports={ports!r},",
            f"    ), {variant!r})",
            "",
        ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(KIND_MAP)} symbols)")


if __name__ == "__main__":
    build()

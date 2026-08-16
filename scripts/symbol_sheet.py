#!/usr/bin/env python3
"""Render every registered symbol in a labelled grid, with port anchors marked.

A dev tool for reviewing the icon library visually:

    python scripts/symbol_sheet.py [out.svg]
    python scripts/symbol_sheet.py --parts [out.svg]

Each cell shows one (kind, variant) symbol scaled to fit, its name, and a red
dot at every named port anchor. A device drawn in two positions (a spectacle
blind) gets a cell for each, since the second drawing is a symbol of its own
and nothing else on this sheet would show it. Purely for inspection, not part
of the package.

``--parts`` draws the other half of the library instead: the ISO 10628-2
groups 26-29 supplementary symbols (``pandid/render/iso_parts.py``), which the
default sheet cannot show because a part is not a symbol and is not in the
registry a symbol lookup reads. Each cell names the Table 2 item and
registration number it claims to be, so a reader with the standard can check
the drawing against the row. Below the parts, a strip of worked compositions
shows a handful of them on real bodies -- built by this script, not registered,
since nothing in the library composes yet.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pandid.render.symbols import Overlay, compose, default_registry as R  # noqa: E402

CELL_W, CELL_H = 200, 200
FIT = 110.0          # target max symbol dimension inside a cell
COLS = 5

PART_CELL_W, PART_CELL_H = 220, 190
PART_FIT = 100.0
PART_COLS = 5


def inner(svg: str) -> str:
    """Strip the outer <g ...> wrapper, returning just the drawing content."""
    i = svg.find(">")
    j = svg.rfind("</g>")
    return svg[i + 1:j] if svg.startswith("<g") and j != -1 else svg


def main():
    args = sys.argv[1:]
    parts = "--parts" in args
    rest = [a for a in args if not a.startswith("--")]
    if parts:
        out = pathlib.Path(rest[0]) if rest else pathlib.Path("part_sheet.svg")
        return part_sheet(out)
    out = pathlib.Path(rest[0]) if rest else pathlib.Path("symbol_sheet.svg")
    items = []
    for (kind, variant), sym in sorted(R._symbols.items()):
        items.append(((kind, variant), "", sym))
        shut = R.closed_symbol(kind, variant)
        if shut is not None:
            items.append(((kind, variant), " (closed)", shut))
    rows = (len(items) + COLS - 1) // COLS
    W, H = COLS * CELL_W, rows * CELL_H + 60

    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         f'<text x="20" y="36" font-family="sans-serif" font-size="22" '
         f'font-weight="bold">pandid symbol library: {len(items)} symbols</text>']

    for idx, ((kind, variant), position, sym) in enumerate(items):
        r, c = divmod(idx, COLS)
        ox, oy = c * CELL_W, r * CELL_H + 60
        L.append(f'<rect x="{ox}" y="{oy}" width="{CELL_W}" height="{CELL_H}" '
                 f'fill="none" stroke="#e2e2e2"/>')
        s = FIT / max(sym.width, sym.height)
        sw, sh = sym.width * s, sym.height * s
        gx = ox + (CELL_W - sw) / 2
        gy = oy + (CELL_H - sh) / 2 - 8
        L.append(f'<g transform="translate({gx:.1f},{gy:.1f}) scale({s:.3f})">{inner(sym.svg)}</g>')
        # port anchors, plus where each port *family* puts its lone member: the
        # count belongs to the unit, and a symbol sheet has no unit in hand.
        anchors = list(sym.ports.values())
        anchors += [series.placement(0, 1, sym.width, sym.height)
                    for series in sym.port_series]
        for px, py in anchors:
            ax, ay = gx + px * s, gy + py * s
            L.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.2" fill="#d1495b"/>')
        name = (kind if variant == "default" else f"{kind}/{variant}") + position
        L.append(f'<text x="{ox + CELL_W/2}" y="{oy + CELL_H - 14}" font-family="sans-serif" '
                 f'font-size="13" text-anchor="middle" font-weight="bold">{name}</text>')
        L.append(f'<text x="{ox + CELL_W/2}" y="{oy + CELL_H - 30}" font-family="sans-serif" '
                 f'font-size="9" fill="#777" text-anchor="middle">{int(sym.width)}×{int(sym.height)} · '
                 f'{len(anchors)} ports</text>')

    L.append("</svg>")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out} ({len(items)} symbols)")


# --- the parts sheet ---------------------------------------------------------

#: Compositions drawn under the parts, to show what a part looks like on the
#: body it was drawn for rather than alone in a box. Nothing here is
#: registered: these are built by this script and thrown away, because no unit
#: in the library composes yet.
DEMOS = [
    ("vessel/dished + turbine", "vessel", "dished",
     [Overlay(28, "turbine", 0.30, 0.05, 0.40, 0.75)]),
    ("vessel/dished + anchor", "vessel", "dished",
     [Overlay(28, "anchor", 0.28, 0.05, 0.44, 0.80)]),
    ("column + 6 bubble caps", "column", "default",
     [Overlay(27, "bubble_cap_tray", 0.12, 0.18 + 0.11 * i, 0.76, 0.09)
      for i in range(6)]),
    ("column + 8 sieve trays", "column", "default",
     [Overlay(27, "sieve_tray", 0.12, 0.16 + 0.085 * i, 0.76, 0.07)
      for i in range(8)]),
    ("column + packing", "column", "default",
     [Overlay(27, "packing", 0.12, 0.20, 0.76, 0.55)]),
    ("separator + gravity", "separator", "gravity",
     [Overlay(29, "gravity", 0.40, 0.15, 0.20, 0.45)]),
    ("vessel + 2 legs", "vessel", "default",
     [Overlay(26, "leg", 0.18, 0.95, 0.06, 0.22),
      Overlay(26, "leg", 0.76, 0.95, 0.06, 0.22)]),
    ("vessel + skirt", "vessel", "default",
     [Overlay(26, "skirt", 0.20, 0.92, 0.60, 0.22)]),
]


def part_sheet(out: pathlib.Path):
    parts = R.parts()
    rows = (len(parts) + PART_COLS - 1) // PART_COLS
    demo_top = rows * PART_CELL_H + 130
    W = max(PART_COLS * PART_CELL_W, len(DEMOS) * 190)
    H = demo_top + 300

    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         '<text x="20" y="34" font-family="sans-serif" font-size="20" '
         f'font-weight="bold">ISO 10628-2 Table 2 groups 26-29: {len(parts)} parts</text>',
         '<text x="20" y="52" font-family="sans-serif" font-size="11" fill="#777">'
         'original artwork built to the standard&#8217;s construction; '
         'grid ticks are one 2,5 mm module apart</text>']

    for idx, part in enumerate(parts):
        r, c = divmod(idx, PART_COLS)
        ox, oy = c * PART_CELL_W, r * PART_CELL_H + 70
        L.append(f'<rect x="{ox}" y="{oy}" width="{PART_CELL_W}" height="{PART_CELL_H}" '
                 f'fill="none" stroke="#e2e2e2"/>')
        s = PART_FIT / max(part.width, part.height)
        gx = ox + (PART_CELL_W - part.width * s) / 2
        gy = oy + (PART_CELL_H - part.height * s) / 2 - 14
        # The module grid the artwork was drawn on, so a reader can count
        # modules off the cell the way Table 2 is counted off its dotted grid.
        L.append(f'<g transform="translate({gx:.2f},{gy:.2f}) scale({s:.4f})">')
        step = 10.0
        L.append(''.join(
            f'<circle cx="{x * step:g}" cy="{y * step:g}" r="{0.7 / s:.2f}" fill="#cfcfcf"/>'
            for x in range(int(part.width / step) + 1)
            for y in range(int(part.height / step) + 1)))
        L.append(f'{inner(part.svg)}</g>')
        for px, py in part.ports.values():
            L.append(f'<circle cx="{gx + px * s:.1f}" cy="{gy + py * s:.1f}" '
                     f'r="3.2" fill="#d1495b"/>')
        cx = ox + PART_CELL_W / 2
        L.append(f'<text x="{cx}" y="{oy + PART_CELL_H - 34}" font-family="sans-serif" '
                 f'font-size="13" text-anchor="middle" font-weight="bold">'
                 f'{part.iso.group}/{part.name}</text>')
        L.append(f'<text x="{cx}" y="{oy + PART_CELL_H - 20}" font-family="sans-serif" '
                 f'font-size="10" fill="#444" text-anchor="middle">'
                 f'{part.iso.item} · {part.iso.reg} · {part.iso.name}</text>')
        flags = " · ".join(
            [f'{part.width / 10:g}×{part.height / 10:g} M']
            + ([] if part.stretchable else ["fixed aspect"])
            + (["gravity"] if part.gravity_fixed else [])
            + ([f'port {n}' for n in part.ports]))
        L.append(f'<text x="{cx}" y="{oy + PART_CELL_H - 7}" font-family="sans-serif" '
                 f'font-size="9" fill="#888" text-anchor="middle">{flags}</text>')

    L.append(f'<text x="20" y="{demo_top - 12}" font-family="sans-serif" font-size="15" '
             f'font-weight="bold">composed onto a body (built here, not registered)</text>')
    for idx, (label, kind, variant, overlays) in enumerate(DEMOS):
        ox = idx * 190 + 10
        sym = compose(R.get(kind, variant),
                      [(o, R.part(o.group, o.name)) for o in overlays])
        s = 200.0 / max(sym.width, sym.height)
        gx = ox + (180 - sym.width * s) / 2
        L.append(f'<g transform="translate({gx:.1f},{demo_top:.1f}) scale({s:.3f})">'
                 f'{inner(sym.svg)}</g>')
        for name, (px, py) in sym.ports.items():
            L.append(f'<circle cx="{gx + px * s:.1f}" cy="{demo_top + py * s:.1f}" '
                     f'r="3" fill="#d1495b"/>')
        L.append(f'<text x="{ox + 90}" y="{demo_top + 275}" font-family="sans-serif" '
                 f'font-size="11" text-anchor="middle">{label}</text>')

    L.append("</svg>")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out} ({len(parts)} parts, {len(DEMOS)} compositions)")


if __name__ == "__main__":
    main()

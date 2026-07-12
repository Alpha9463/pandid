#!/usr/bin/env python3
"""Render every registered symbol in a labelled grid, with port anchors marked.

A dev tool for reviewing the icon library visually:

    python scripts/symbol_sheet.py [out.svg]

Each cell shows one (kind, variant) symbol scaled to fit, its name, and a red
dot at every named port anchor. Purely for inspection — not part of the package.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pfd.render.symbols import default_registry as R  # noqa: E402

CELL_W, CELL_H = 200, 200
FIT = 110.0          # target max symbol dimension inside a cell
COLS = 5


def inner(svg: str) -> str:
    """Strip the outer <g ...> wrapper, returning just the drawing content."""
    i = svg.find(">")
    j = svg.rfind("</g>")
    return svg[i + 1:j] if svg.startswith("<g") and j != -1 else svg


def main():
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("symbol_sheet.svg")
    items = sorted(R._symbols.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    rows = (len(items) + COLS - 1) // COLS
    W, H = COLS * CELL_W, rows * CELL_H + 60

    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         f'<text x="20" y="36" font-family="sans-serif" font-size="22" '
         f'font-weight="bold">pfd symbol library — {len(items)} symbols</text>']

    for idx, ((kind, variant), sym) in enumerate(items):
        r, c = divmod(idx, COLS)
        ox, oy = c * CELL_W, r * CELL_H + 60
        L.append(f'<rect x="{ox}" y="{oy}" width="{CELL_W}" height="{CELL_H}" '
                 f'fill="none" stroke="#e2e2e2"/>')
        s = FIT / max(sym.width, sym.height)
        sw, sh = sym.width * s, sym.height * s
        gx = ox + (CELL_W - sw) / 2
        gy = oy + (CELL_H - sh) / 2 - 8
        L.append(f'<g transform="translate({gx:.1f},{gy:.1f}) scale({s:.3f})">{inner(sym.svg)}</g>')
        # port anchors
        for pname, (px, py) in sym.ports.items():
            ax, ay = gx + px * s, gy + py * s
            L.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.2" fill="#d1495b"/>')
        name = kind if variant == "default" else f"{kind}/{variant}"
        L.append(f'<text x="{ox + CELL_W/2}" y="{oy + CELL_H - 14}" font-family="sans-serif" '
                 f'font-size="13" text-anchor="middle" font-weight="bold">{name}</text>')
        L.append(f'<text x="{ox + CELL_W/2}" y="{oy + CELL_H - 30}" font-family="sans-serif" '
                 f'font-size="9" fill="#777" text-anchor="middle">{int(sym.width)}×{int(sym.height)} · '
                 f'{len(sym.ports)} ports</text>')

    L.append("</svg>")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out} ({len(items)} symbols)")


if __name__ == "__main__":
    main()

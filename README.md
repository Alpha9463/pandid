# pfd — Process Flow Diagram engine

`pfd` is a zero-dependency, pure-Python engine that turns a topological
flowsheet definition into a publication-quality, orthogonal **PFD / P&ID** as
SVG. You describe *what connects to what*; the engine lays out the equipment,
routes every stream, and draws industry-standard symbols.

## Features

- **Topology-first API** — declare typed units (pumps, columns, reactors,
  heat exchangers, …) and connect their named ports; streams are created for you.
- **Industry-standard symbol library** — 49+ ISO 10628-2 / ISA-5.1 symbols with
  style **variants** (e.g. a heat exchanger can be shell-&-tube, plate, kettle,
  U-tube…), derived from the Apache-2.0 draw.io P&ID stencils (see `NOTICE`).
- **Automatic layout** — Sugiyama-style layering, crossing reduction, and a
  center-aligned flow spine; recycles are detected and routed around the sheet.
- **Orthogonal A\* routing** — clean right-angle streams with crossing jump-gaps
  and parallel-segment separation. Never emits a disconnected stream.
- **Pixel-perfect overrides** — `pin()` equipment to exact coordinates and
  `.via()` a stream through explicit waypoints; the engine honors them and
  auto-routes the rest.
- **Instrumentation (ISA-5.1)** — instrument balloons with tags drawn inside,
  location variants, and typed signal lines (electric / pneumatic / data).
- **Engineering sheet framing** — a zone-ruled drawing border (ASME-style
  letter/number grid), a full-width title strip (integrated revision history,
  company/logo cell, status / drawing-number / two-line title / date / rev),
  and generic titled boxes docked to the corners (auto **equipment list**,
  **notes**, **legend**, or any `Annotation` / `TableBox`), plus a sectioned
  stream-property table. Off-page connectors carry a drawing reference.
- **Validation** — `fs.validate()` flags overlapping pins, off-sheet
  coordinates (errors) and routes crossing equipment or big detours (warnings).
- **Zero runtime dependencies** — the package uses only the Python standard
  library. (SVG symbols are pre-converted and inlined; `cairosvg` is optional,
  only for PDF/PNG export.)

## Installation

Requires Python 3.10+.

```bash
pip install .
# optional PDF/PNG export backend:
pip install '.[pdf]'
```
Tests run with `pytest`.

## Quick start

```python
from pfd import Flowsheet, units as U

fs = Flowsheet("Ammonia Loop")

feed     = fs.add(U.Feed("Natural Gas"))
mixer    = fs.add(U.Mixer("M-101"))
reformer = fs.add(U.Reactor("R-101"))
hx       = fs.add(U.HeatExchanger("E-101"))
sep      = fs.add(U.Separator("V-101"))
comp     = fs.add(U.Compressor("K-101"))
prod     = fs.add(U.Product("Ammonia"))

fs.connect(feed.outlet,     mixer.in_1)
fs.connect(mixer.outlet,    reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out,      sep.feed)
fs.connect(sep.vapor,       comp.suction)
fs.connect(comp.discharge,  mixer.in_2)   # detected as the recycle
fs.connect(sep.liquid,      prod.inlet)

fs.render("ammonia_loop.svg")             # layout + routing run automatically
```

`render()` infers the format from the extension (`.svg`, or `.pdf`/`.png` with
the optional backend). `fs.to_svg()` returns the SVG string; `fs.show()` opens
it in a browser; a flowsheet also renders inline in Jupyter.

## Equipment & variants

A **class** is a functional equipment type (defined by its ports); a **variant**
is a visual style within it. Pick a variant with the `variant=` argument:

```python
fs.add(U.HeatExchanger("E-1", variant="plate"))   # or shell_tube, kettle, u_tube, condenser
fs.add(U.Valve("FV-1", variant="control"))         # gate, globe, ball, butterfly, check, needle, three_way, relief
fs.add(U.Pump("P-1", variant="gear"))              # centrifugal, gear, screw, vacuum
fs.add(U.Tank("TK-1", variant="floating_roof"))    # dished, conical, floating_roof, sphere
fs.add(U.Separator("V-2", variant="cyclone"))      # knock-out, cyclone, gravity
```

Classes include: `Feed`, `Product`, `Pump`, `Compressor`, `Blower`, `Valve`,
`Vessel`, `Tank`, `HeatExchanger`, `Heater`, `Cooler`, `Reactor`, `Separator`,
`Column`, `Mixer`, `Splitter`, `Reducer`, `Furnace`, `Turbine`, `Filter`,
`Dryer`, and `Instrument`.

## Manual layout

```python
# Pin equipment to exact SVG coordinates (top-left corner):
hx = fs.add(U.HeatExchanger("E-1")).pin(x=100, y=50)
# ...or to a grid cell, mirrored:
fv = fs.add(U.Valve("FV-1")).pin(col=2, row=1, mirrored=True)

# Force a stream through explicit orthogonal waypoints:
fs.connect(feed.outlet, hx.cold_in).via([(130, 65), (130, 110)])
```

Pinned and auto-placed units mix freely — the engine resolves each unit's frame
from your intent and auto-routes anything you didn't pin.

## Instrumentation & signals

```python
ft  = fs.add(U.Instrument("FT-101"))                       # field flow transmitter
fic = fs.add(U.Instrument("FIC-101", variant="panel"))     # panel-mounted controller
fy  = fs.add(U.Instrument("FY-101", variant="computer"))   # computing relay
# variants: field (default), panel, aux, shared (DCS square), computer (hexagon)

fs.connect(ft.sig_out, fic.sig_in, kind="electric")        # dashed
fs.connect(fic.sig_out, fy.sig_in, kind="pneumatic")       # slash-ticks
```

The instrument's `name` is its tag, drawn inside the balloon (functional letters
over loop number). Signal `kind`s: `electric`, `pneumatic`, `data`/`software`,
`capillary` — rendered with the right line style, no arrowheads, and no stream
numbers.

Inline fittings (valves, reducers) carry the stream number **through** them; set
`unit.significant = True` to break the number at an important valve.

## Engineering title block & sheet furniture

Under `styling="pid"` the sheet gets a zone-ruled border and a full-width
engineering title strip. `title`/`subtitle` are the two title lines; `company`
fills the logo cell and `status` the issue-status cell. Each `Revision` carries
its own `by`/`checked`/`approved` initials (the block-level
`drawn_by`/`checked_by`/`approved_by` backfill the newest row).

```python
from pfd.document import TitleBlock, Revision

fs.title_block = TitleBlock(
    title="Aromatics Recovery A100", subtitle="Process Flow Diagram 1",
    drawing_number="PFD-1001", company="THE UNIVERSITY OF QUEENSLAND",
    status="ISSUED FOR REVIEW", sheet="1", of_sheets="3",
    revisions=[
        Revision("B", "2026-07-01", "Issued for design", "AA", "JS", "RL"),
        Revision("C", "2026-07-12", "Added recycle loop", "AA", "JS", "RL"),
    ],
)
```

**Generic titled boxes** dock **flush to the sheet frame** — like a real
drawing, not floating in the whitespace. `align=` is a nine-point grid
(`top-left`/`top`/`top-right`/`left`/`center`/`right`/`bottom-left`/`bottom`/
`bottom-right`); the box's matching corner/edge is pinned to the frame's, inset
by an optional `margin=`. For hand-placed furniture, `position=(x, y)` pins the
box's **top-left corner** at absolute sheet coordinates instead. Equipment
lists, notes, and legends are thin wrappers over `Annotation`; `TableBox` is a
bordered grid for anything else. Add them with `fs.add_annotation(...)`.

```python
from pfd.document import equipment_list, notes, legend, Annotation, TableBox

fs.add(U.Column("T-101", description="Beer Column"))   # feeds the equipment list
fs.add_annotation(equipment_list(fs, align="top-right"))
fs.add_annotation(notes(["Sampling point on every product line."], align="top"))
fs.add_annotation(legend({"SS": "Stainless Steel 316L"}, align="top-left"))
fs.add_annotation(Annotation(title="HOLD", rows=["Awaiting vendor data"],
                             position=(1200, 90)))          # absolute placement
```

(`anchor=` is still accepted as a deprecated alias for `align=`.)

**Off-page connectors** — a boundary flag's `reference` is drawn as its second
line (the drawing the stream comes from / goes to):

```python
fs.add(U.Feed("Fermentation Broth", reference="PFD-201"))
```

**Stream table** — property rows render in first-seen key order (values carry
their own units); inject section headers with `stream_table_sections`:

```python
fs.stream_table_sections = [("Ethanol", "Mass Fraction")]   # header before "Ethanol"
fs.render("sheet.svg", styling="pid", show_stream_table=True)
```

## Examples

Runnable scripts in `examples/`:

- `01_ammonia_loop.py` — fully automatic layout, layering, recycle detection.
- `02_manual_layout.py` — `pin()` + `.via()` overrides.
- `03_distillation_train.py` — two-column train, recycle, stream table, P&ID
  title block with revision history.
- `04_control_loop.py` — ISA instrument balloons and signal-line types.

## Architecture

1. **Topology** (`pfd/flowsheet.py`, `pfd/units.py`, `pfd/ports.py`,
   `pfd/streams.py`) — units, ports, and stream connectivity.
2. **Geometry** — `pfd/layout/` (Sugiyama layering → ordering → coordinates,
   emitting each unit's resolved `Frame`), `pfd/portgeom.py` (single source of
   truth for port geometry), `pfd/routing/` (visibility graph + A\*).
3. **Render** (`pfd/render/`) — SVG output, the symbol registry, and
   `pfd/validate.py` / `pfd/document.py`.

Geometry separates *intent* (`Pin`, from `pin()`) from *result* (`Frame`,
computed by the layout engine), so layout is idempotent.

The symbol library is generated by `scripts/vendor_symbols.py`
(mxGraph stencil XML → SVG via `scripts/mxgraph_to_svg.py`) into
`pfd/render/_vendored_symbols.py`; `scripts/symbol_sheet.py` renders a catalogue.

## License & attribution

Apache-2.0. Equipment symbols derive from the draw.io / diagrams.net P&ID
stencils (Apache-2.0) — see `NOTICE`.

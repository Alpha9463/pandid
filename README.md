# pandid — P&ID and process flow diagram engine

`pfd` is a zero-dependency, pure-Python engine that turns a topological
flowsheet definition into a publication-quality, orthogonal **PFD / P&ID** as
SVG. You describe *what connects to what*; the engine lays out the equipment,
routes every stream, and draws industry-standard symbols.

The distribution is **`pandid`** — how "P&ID" is said out loud — and it imports
as **`pfd`**.

[![Distillation train](https://raw.githubusercontent.com/Alpha9463/py-chemengg/main/docs/gallery/03_distillation_train.png)](https://github.com/Alpha9463/py-chemengg/blob/main/docs/gallery/README.md)

<sub>[`examples/03_distillation_train.py`](https://github.com/Alpha9463/py-chemengg/blob/main/examples/03_distillation_train.py) — see the [gallery](https://github.com/Alpha9463/py-chemengg/blob/main/docs/gallery/README.md) for all nine.</sub>

## Install

Requires Python 3.10+. No runtime dependencies. Fully type-hinted and marked
[PEP 561](https://peps.python.org/pep-0561/), so `mypy` and `pyright` read the
annotations straight out of the wheel.

```bash
pip install pandid
pip install 'pandid[pdf]'    # optional PDF/PNG export backend (cairosvg)
pip install 'pandid[yaml]'   # optional YAML spec reader (Flowsheet.from_yaml)
```

From a checkout:

```bash
pip install -e .
pip install -e '.[dev]'       # pytest, ruff, mypy
```

## Quick start

```python
from pfd import Flowsheet, units

fs = Flowsheet("Flash Separation")
feed   = fs.add(units.Feed("Crude"))
heater = fs.add(units.Heater("E-101"))
drum   = fs.add(units.Separator("V-101"))
gas    = fs.add(units.Product("Off-Gas"))
liquid = fs.add(units.Product("Condensate"))

fs.connect(feed.outlet,   heater.inlet)
fs.connect(heater.outlet, drum.feed)
fs.connect(drum.vapor,    gas.inlet)
fs.connect(drum.liquid,   liquid.inlet)

fs.render("flash.svg")        # layout + routing run automatically
```

No coordinates anywhere: `render()` runs layout and routing for you. It infers
the format from the extension (`.svg`, or `.pdf`/`.png` with the optional
backend). `fs.to_svg()` returns the SVG string, `fs.show()` opens it in a
browser, and a flowsheet renders inline in Jupyter.

## What it does

- **Topology-first API** — declare typed units (pumps, columns, reactors,
  heat exchangers, …) and connect their named ports; streams are created for you.
- **Automatic layout** — Sugiyama-style layering, crossing reduction, and a
  center-aligned flow spine; recycles are detected and routed around the sheet.
  Ports that a symbol authors on more than one face are put on the face the
  peer is actually on, so a drum under its condenser is fed from the top.
- **Orthogonal A\* routing** — clean right-angle streams with crossing jump-gaps
  and parallel-segment separation. Never emits a disconnected stream.
- **Industry-standard symbol library** — 95+ ISO 10628-2 / ISA-5.1 symbols with
  style **variants** (a heat exchanger can be shell-&-tube, plate, kettle,
  U-tube…), derived from the Apache-2.0 draw.io P&ID stencils (see `NOTICE`).
- **Pixel-perfect overrides** — `pin()` equipment to exact coordinates and
  `.via()` a stream through explicit waypoints; the engine honors them and
  auto-routes the rest.
- **Line numbers** — a line is labelled the way the line list has it
  (`6"-P-1001-A1A`: size, service, sequence, spec), not `S1`. The sequence is
  filled automatically, the number carries through in-line fittings and breaks
  at a spec break, and the convention is a format string you can replace.
- **Instrumentation (ISA-5.1)** — instrument balloons anchored to the line or
  the equipment they read (with impulse lines), tags drawn inside, location
  variants, alarms and interlock squares, typed signal lines (electric /
  pneumatic / data), and controller outputs landing on a valve's actuator.
- **Engineering sheet framing** — a zone-ruled drawing border (ASME-style
  letter/number grid), a full-width title strip (integrated revision history,
  company/logo cell, status / drawing-number / two-line title / date / rev),
  and generic titled boxes docked to the corners (auto **equipment list**,
  **notes**, **legend**, or any `Annotation` / `TableBox`), plus a sectioned
  stream-property table. Off-page connectors carry a drawing reference.
- **Declare it as data** — a round-trippable spec format (`dict`, JSON, or
  YAML) covering everything above, so an equipment list and a stream table go
  straight to a drawing without anyone writing Python. Validated, not
  interpreted: a typo names the entry and lists what would have worked.
- **Validation** — `fs.validate()` flags overlapping pins, off-sheet
  coordinates (errors) and routes crossing equipment or big detours (warnings).
- **Zero runtime dependencies** — the package uses only the Python standard
  library. (SVG symbols are pre-converted and inlined; `cairosvg` is optional,
  only for PDF/PNG export, and `PyYAML` only for reading a YAML spec.)

**It does not do mass or energy balances.** Stream properties are strings you
supply; nothing is calculated from them. This is a drawing engine.

## Documentation

| Where | What |
|---|---|
| [Example gallery](https://github.com/Alpha9463/py-chemengg/blob/main/docs/gallery/README.md) | all nine examples rendered, with what each one demonstrates |
| [API reference](https://github.com/Alpha9463/py-chemengg/blob/main/docs/api.md) | every public class, port and option, verified against the source |
| [Contributing](https://github.com/Alpha9463/py-chemengg/blob/main/CONTRIBUTING.md) | setup, the four gates, and the conventions that are easy to get wrong |
| [Changelog](https://github.com/Alpha9463/py-chemengg/blob/main/CHANGELOG.md) | what is in this release |

---

## Equipment & variants

A **class** is a functional equipment type (defined by its ports); a **variant**
is a visual style within it. Pick a variant with the `variant=` argument; the
`"default"` variant is listed first with the shape it draws — those brackets are
descriptions, not names. A name no symbol answers to raises `ValueError` listing
the ones that kind does have.

```python
fs.add(units.HeatExchanger("E-1", variant="plate"))    # default, shell_tube, straight_tubes, plate, kettle, u_tube, condenser, spiral
fs.add(units.Valve("FV-1", variant="control"))         # default (gate), gate, globe, ball, butterfly, check, needle, three_way, control, relief
fs.add(units.Pump("P-1", variant="gear"))              # default (centrifugal), gear, screw, vacuum
fs.add(units.Tank("TK-1", variant="floating_roof"))    # default (dished roof), conical, floating_roof, sphere
fs.add(units.Separator("V-2", variant="cyclone"))      # default (knock-out drum), horizontal, cyclone, gravity, scrubber, electrostatic
fs.add(units.Fitting("ST-1", variant="strainer"))      # see "In-line fittings" below
```

Classes include: `Feed`, `Product`, `Pump`, `Compressor`, `Blower`, `Valve`,
`Vessel`, `Tank`, `HeatExchanger`, `Heater`, `Cooler`, `Reactor`, `Separator`,
`Column`, `Mixer`, `Splitter`, `Reducer`, `Fitting`, `Ejector`, `Vent`,
`Funnel`, `Furnace`, `Turbine`, `Filter`, `Dryer`, and `Instrument`. The
[API reference](https://github.com/Alpha9463/py-chemengg/blob/main/docs/api.md#units-and-ports) lists every class's ports and every
registered variant.

**Valve operators.** Most valve variants draw the body only; these draw the
operator too, and their `actuator` port sits on its crown rather than on the
body, so a controller output or interlock lands where the signal really goes:

```python
fs.add(units.Valve("XV-1", variant="solenoid"))    # motor, solenoid, hydraulic (lettered boxes)
fs.add(units.Valve("PV-1", variant="pneumatic"))   # diaphragm actuator dome
fs.add(units.Valve("HV-1", variant="manual"))      # manual, knife (handwheel), butterfly_pneumatic
fs.add(units.Valve("PCV-1", variant="regulator"))  # self-acting, with its external sense line
```

Bodies without an operator: `plug`, `pinch`, `angle` (piped from below, out to
the side) and `psv` (spring-loaded angle safety valve).

**In-line fittings.** `Fitting` is one class because to the flowsheet every
in-line device is the same thing — a pair of faces on a line — and they differ
only in what is drawn between them. The variant picks the device: `strainer`,
`strainer_cone`, `orifice`, `rotameter`, `rupture_disc`, `sight_glass`,
`sight_glass_lit`, `silencer`, `expansion_joint`, `static_mixer`, `hose`,
`coupling`, `clamped_coupling`, `flange` (the default), and the flame arrestors
(`flame_arrestor` plus `_explosion_proof` / `_detonation_proof` /
`_fire_resistant`).

`Ejector` is separate because it has three connections (`motive`, `suction`,
`discharge`), and `Vent` / `Funnel` because each has only one: `Vent` is a stack
open to atmosphere that a PSV tailpipe or a tank breather terminates on, and
`Funnel` is a manual charging point feeding the line.

## Automatic layout and recycles

Given only the topology, the engine layers the units, orders them to reduce
crossings, aligns the main process line onto one axis, and detects feedback
loops itself — you never declare a stream to be a recycle:

```python
from pfd import Flowsheet, units

fs = Flowsheet("Ammonia Loop")

feed     = fs.add(units.Feed("Natural Gas"))
mixer    = fs.add(units.Mixer("M-101"))
reformer = fs.add(units.Reactor("R-101"))
hx       = fs.add(units.HeatExchanger("E-101"))
sep      = fs.add(units.Separator("V-101"))
comp     = fs.add(units.Compressor("K-101"))
prod     = fs.add(units.Product("Ammonia"))

fs.connect(feed.outlet,     mixer.in_1)
fs.connect(mixer.outlet,    reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out,      sep.feed)
fs.connect(sep.vapor,       comp.suction)
fs.connect(comp.discharge,  mixer.in_2)   # detected as the recycle
fs.connect(sep.liquid,      prod.inlet)

fs.render("ammonia_loop.svg")
```

## Manual layout

```python
# Pin equipment to exact SVG coordinates (top-left corner):
hx = fs.add(units.HeatExchanger("E-1")).pin(x=100, y=50)
# ...or to a grid cell, mirrored:
fv = fs.add(units.Valve("FV-1")).pin(col=2, row=1, mirrored=True)

# Force a stream through explicit orthogonal waypoints:
fs.connect(feed.outlet, hx.cold_in).via([(130, 65), (130, 110)])
```

**Orientation and mirroring.** `orientation` is a clockwise quarter turn in
degrees (`0`/`90`/`180`/`270`) and swaps the unit's width and height; `mirrored`
flips it — `True` or `"x"` left↔right (swapping the E and W faces), `"y"`
top↔bottom (swapping N and S), `"xy"` both. Ports follow the placement, so a
stream never detaches from its nozzle:

```python
fs.add(units.Pump("P-1")).pin(x=200, y=100, orientation=90)      # discharge now faces S
fs.add(units.Pump("P-2")).pin(x=400, y=100, mirrored="y")        # flipped top-to-bottom
```

**Choosing a port's face.** Many vessels can be piped from more than one side,
and the engine picks which one: it scores every face the symbol authored against
where the unit at the other end of the stream actually landed, and takes the
shortest run. A reflux drum sitting under its condenser is fed from the top
without being told. Nozzles fixed by physics (a column's bottoms, a drum's
liquid draw-off) offer one face and are never moved.

`nozzle()` overrides the choice where the sheet wants a particular convention,
naming the compass point **as drawn** so mirroring cannot invert it;
`Flowsheet(..., auto_faces=False)` turns the whole thing off:

```python
drum = fs.add(units.Separator("V-1", variant="horizontal"))
drum.nozzle("feed", "N")        # always from above, however the header is laid in
```

Pinned and auto-placed units mix freely — the engine resolves each unit's frame
from your intent and auto-routes anything you didn't pin. A port sits at a fixed
*fraction* of its symbol's box, so lining two items up means matching those
fractions rather than their corners; see [example 06](https://github.com/Alpha9463/py-chemengg/blob/main/docs/gallery/README.md#06--column-reflux-and-reboiler).

## Instrumentation & signals

```python
ft  = fs.add_instrument("FT", 101)                             # field flow transmitter
fic = fs.add_instrument("FIC", 101, variant="panel")           # panel-mounted controller
fy  = fs.add_instrument("FY", 101, variant="computer")         # computing relay
# variants: default (field balloon), panel, aux, shared (DCS square),
#           computer (hexagon), logic (interlock square)

fs.connect(ft.sig_out, fic.sig_in, kind="electric")        # dashed
fs.connect(fic.sig_out, fy.sig_in, kind="pneumatic")       # slash-ticks
```

`type` and `number` make the tag: `unit.name` is `"FT-101"` for equipment lists
and cross-references, while the balloon draws the letters over the **bare**
number, as a real sheet does. (`units.Instrument("FT-101")` is still accepted
and split.) Signal `kind`s: `electric`, `pneumatic`, `data`/`software`,
`capillary` — rendered with the right line style, no arrowheads, and no stream
numbers.

**Attaching a balloon.** A bubble measures something, so anchor it to that
thing with `on=` rather than letting the ranker float it in its own row:

```python
s   = fs.connect(feed.outlet, fv.inlet)
fs.add_instrument("FE", 101, on=s, at=0.4, offset=0)             # element sits ON the line
ft  = fs.add_instrument("FT", 101, on=s, at=0.4, offset=60)      # transmitter above the tap
lic = fs.add_instrument("LIC", 101, on=drum, at="E", variant="panel")   # mounted on the drum
fs.add_instrument("LAH", 101, on=lic, at="N", offset=48)         # alarm, same loop number
fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")   # interlock square
```

- `on=` a **stream** taps the line, or a **unit** mounts on equipment.
- `at=` is a fraction `0..1` along the host stream's routed path, or a face
  (`"N"`/`"S"`/`"E"`/`"W"`) of a host unit's box.
- `offset=` is the distance from the tap to the balloon centre; `offset=0`
  leaves an in-line primary element sitting on the line.
- `angle=` is the branch direction in degrees from the **flow direction at the
  tap**, counter-clockwise positive (default `90`, i.e. perpendicular) — so a
  tap keeps its orientation when the line is re-routed.

An impulse line is drawn from the tap to the balloon: a fine solid line to a
process host, dashed where a balloon hangs off another balloon. Attached
balloons take no part in the layout ranking, and are drawn over the lines so
neither an in-line element nor a stream number is lost underneath one.

**Final control element.** `Valve.actuator` is the signal connection on top of
the valve, so a controller output terminates on real equipment:

```python
fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
```

A relief valve is an ordinary `Valve` with `variant="relief"`; its tag is drawn
as plain text beside the symbol (`PSV-308`), not in a balloon.

Inline fittings (valves, reducers, `Fitting`s) carry the stream number
**through** them; set `unit.significant = True` to break the number at an
important valve. `connect()` hands back the number that gets drawn, so
`s.name` is safe to quote in a report or a stream table of your own.

## Line numbers

A P&ID identifies a line the way the line list does — size, service, sequence,
spec — because that is what ties the drawing to the stress calculation and the
isometric. Give `connect()` the components and the line is named that way
instead of `S1`:

```python
s = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
s.name        # '6"-P-1001-A1A'
s.sequence    # '1001' — filled by auto-numbering, from line_number_start
```

You supply `size`, `service`, `spec` and `insulation`; auto-numbering fills
`sequence`, unless you set it to tie into a line that already exists. The number
carries **through** an in-line valve or strainer and breaks at a unit marked
`significant` — which is exactly where the spec breaks. A component left unset
drops out, so a line with no spec issued yet reads `6"-P-1001`.

The convention is a format string (or a callable), so a site that spells it
differently says so once:

```python
fs = Flowsheet("U100", line_numbering_scheme="{service}-{size}-{sequence:0>6}-{insulation}",
               line_number_start=1)
```

Under `show_stream_table=True` each column is headed by its line number, so a
column ties to a line without a second lookup. A stream with no components set
is numbered exactly as before.

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

fs.add(units.Column("T-101", description="Beer Column"))   # feeds the equipment list
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
fs.add(units.Feed("Fermentation Broth", reference="PFD-201"))
```

**Stream table** — property rows render in first-seen key order (values are the
strings you supply and carry their own units); inject section headers with
`stream_table_sections`:

```python
fs.stream_table_sections = [("Ethanol", "Mass Fraction")]   # header before "Ethanol"
fs.render("sheet.svg", styling="pid", show_stream_table=True)
```

## Building a flowsheet from data

An equipment list and a stream table are data, and they usually already exist —
in a spreadsheet, a YAML file, or a simulator export. The same flowsheet can be
declared as a plain mapping and handed to the engine, so nobody has to retype a
schedule as Python:

```python
from pfd import Flowsheet

fs   = Flowsheet.from_dict(spec)         # a plain dict, from anywhere
fs   = Flowsheet.from_json("bfw.json")   # standard library only
fs   = Flowsheet.from_yaml("bfw.yaml")   # pip install 'pandid[yaml]'
spec = fs.to_dict()                      # writes the same spec back out

fs.render("bfw.svg", styling="pid", show_stream_table=True)
```

`to_dict()` **round-trips**: `Flowsheet.from_dict(fs.to_dict())` rebuilds an
equivalent flowsheet — same equipment, same nozzles, same placement, same
drawing. Only intent is written, never the engine's results (resolved frames,
routed paths, computed stream numbers), so the file stays short and re-lays out
cleanly. YAML is the one optional extra; `from_dict` and `from_json` need
nothing, and asking for YAML without PyYAML installed says exactly that.

A complete sheet:

```yaml
name: Feed Metering Skid          # the only required field
stream_naming_scheme: "S{n}"
line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
line_number_start: 1001
components: [Water, {name: Ethanol, formula: C2H6O}]

units:
  - {kind: Feed, name: Raw Feed, reference: PFD-100, pin: {x: 60, y: 275}}
  - {kind: Fitting, name: ST-101, variant: strainer, description: Suction Strainer}
  - {kind: Mixer, name: M-101, n_inlets: 3, description: Suction Header}
  - {kind: Pump, name: P-101, description: Feed Pump}
  - {kind: Splitter, name: SP-101, n_outlets: 2, description: Minimum-Flow Tee}
  - {kind: Valve, name: FV-101, variant: control, significant: true,
     description: Spillback Valve}
  - {kind: Vessel, name: V-101, variant: horizontal, width: 130, height: 42,
     description: Surge Drum, port_faces: {inlet: N}}
  - {kind: Product, name: To Unit 200, reference: PFD-200}

instruments:
  - {type: LIC, number: 101, variant: panel, on: V-101, at: S, offset: 110,
     port_faces: {sig_out: W}}

streams:
  - {from: [Raw Feed, outlet], to: [ST-101, inlet]}
  - {from: [ST-101, outlet], to: [M-101, in_1]}
  - {from: [M-101, outlet], to: [P-101, suction]}
  - from: [P-101, discharge]
    to:   [SP-101, inlet]
    size: '6"'
    service: P
    spec: A1A
    properties: {Temperature: 25 C, Pressure: 4.0 barg, Ethanol: "0.92"}
  - {from: [SP-101, out_1], to: [V-101, inlet]}
  - {from: [SP-101, out_2], to: [FV-101, inlet]}
  - {from: [FV-101, outlet], to: [M-101, in_3], tear_hint: true}
  - {from: [V-101, outlet], to: [To Unit 200, inlet]}
  - {from: [LIC-101, sig_out], to: [FV-101, actuator], kind: electric}

stream_table_sections: [[Ethanol, Mass Fraction]]

title_block:
  title: Utilities U200
  subtitle: Process Flow Diagram 1
  drawing_number: PFD-2001
  company: THE UNIVERSITY OF QUEENSLAND
  status: ISSUED FOR REVIEW
  sheet: "1"
  of_sheets: "2"
  revisions:
    - {rev: A, date: 2026-05-18, description: Issued for review, by: AA}
    - {rev: B, date: 2026-07-02, description: Added spillback, by: AA,
       checked: JS, approved: RL}

annotations:
  - {type: equipment_list, align: top-right}
  - {type: notes, align: top, items: [Sampling point on every product line.]}
  - {type: legend, align: top-left, margin: 6, entries: {SS: Stainless Steel 316L}}
  - {type: annotation, title: HOLD, rows: [Awaiting vendor data], position: [1200, 90]}
  - {type: table, title: TIE-INS, headers: [Tag, Line], rows: [[TI-1, 6-P-101]]}
```

**`units`** — `kind` (required) is the equipment class from the list above, in
any spelling you would reasonably write: `HeatExchanger`, `heat_exchanger` or
`hex`. `name` (required) is the tag. Then `variant`, `description` (feeds the
equipment list), `reference` (a boundary flag's off-page drawing), explicit
`width`/`height`, `label_pos`, `significant` (break the stream or line number at
this inline item), and `n_inlets` / `n_outlets` for `Mixer` / `Splitter`.

**`pin` / `port_faces`** — `pin` mirrors `pin()`: `x`/`y` (absolute), `col`/`row`
(grid), `orientation` (`0`/`90`/`180`/`270`) and `mirrored` (`x`/`y`/`xy`).
`port_faces` maps a port to the face it leaves from **as drawn**, so a
mirrored or turned unit takes the face the reader sees. It is an override —
without it the engine picks the face itself, and the top-level `auto_faces:
false` is how you stop it.

**`instruments`** — `type` (required) and `number` make the tag, so `{type: LIC,
number: 101}` is referred to elsewhere as `LIC-101`. `on` names the host: a unit,
a named stream, or `[unit, port]` for the line leaving that nozzle — which is how
`to_dict()` writes it, since auto-numbered stream names are rewritten at render
time. `at` / `offset` / `angle` / `variant` / `port_faces` behave as in
`add_instrument()`. An instrument with no `on` is laid out like any other unit.

**`streams`** — `from` and `to` are `[unit, port]` pairs (or
`{unit: ..., port: ...}`). `kind` makes a signal line (`electric`, `pneumatic`,
`data`, …), `name` overrides the auto number, `tear_hint` nominates the recycle
to cut, `via` forces waypoints, and `properties` is that line's stream-table
column. `size` / `service` / `spec` / `insulation` are the line-number
components, and `sequence` overrides the one auto-numbering would assign —
which is why `to_dict()` writes the components but never the computed
sequence.

**Sheet furniture** — `title_block` takes the `TitleBlock` fields plus
`revisions`; each `annotations` entry is one box, typed `equipment_list`,
`notes`, `legend`, `annotation` or `table`, and placed with `align` /
`position` / `margin` exactly as above.

**Errors name the entry and what would have worked** — the format is validated,
not interpreted, so a typo cannot silently drop a nozzle off the drawing:

```
units[3] 'P-101': unknown key 'varient' (did you mean 'variant'?); allowed keys:
['description', 'height', 'kind', 'label_pos', 'name', 'pin', 'port_faces', ...]

streams[6].from: Pump 'P-101' has no port 'dischrge' (did you mean 'discharge'?);
available ports: ['discharge', 'suction']
```

Every failure raises `pfd.SpecError`, a `ValueError`.

## Examples

Runnable scripts in `examples/`, each usable from the repo root or from
`examples/` itself. All nine are rendered in the
[gallery](https://github.com/Alpha9463/py-chemengg/blob/main/docs/gallery/README.md).

| Script | Demonstrates |
|---|---|
| `01_ammonia_loop.py` | fully automatic layout, layering, recycle detection |
| `02_manual_layout.py` | `pin()` + `.via()` overrides |
| `03_distillation_train.py` | two-column train, recycle, stream table, P&ID title block with revision history, equipment list / notes / legend |
| `04_control_loop.py` | ISA balloons attached to the line and to equipment, alarms, an interlock, a PSV, and both loops closing on a valve actuator |
| `05_reactor_recycle.py` | automatic recycle + purge split, straightened process spine |
| `06_column_reflux.py` | fractionation sheet: overhead condenser, reflux drum, kettle reboiler, both loops closing on the column's return nozzles |
| `07_metering_skid.py` | in-line fittings and actuated valves on one spine, PSV to flare, level controller on the valve operator |
| `08_from_data.py` | the whole flowsheet declared as data and built with `Flowsheet.from_dict()` |
| `09_line_numbers.py` | full line numbers (`8"-P-1001-A1A`) carried through in-line fittings and broken at two spec breaks, with the stream table headed by them |

## Architecture

1. **Topology** (`pfd/flowsheet.py`, `pfd/units.py`, `pfd/ports.py`,
   `pfd/streams.py`) — units, ports, and stream connectivity.
2. **Geometry** — `pfd/layout/` (Sugiyama layering → ordering → coordinates,
   emitting each unit's resolved `Frame`, then port-face selection and label
   placement), `pfd/portgeom.py` (single source of truth for port geometry),
   `pfd/routing/` (visibility graph + A\*).
3. **Render** (`pfd/render/`) — SVG output, the symbol registry, and
   `pfd/validate.py` / `pfd/document.py`.

Geometry separates *intent* (`Pin`, from `pin()`) from *result* (`Frame`,
computed by the layout engine), so layout is idempotent.

The symbol library is generated by `scripts/vendor_symbols.py`
(mxGraph stencil XML → SVG via `scripts/mxgraph_to_svg.py`) into
`pfd/render/_vendored_symbols.py`; `scripts/symbol_sheet.py` renders a catalogue.

## Contributing

See [CONTRIBUTING.md](https://github.com/Alpha9463/py-chemengg/blob/main/CONTRIBUTING.md). The gates are `pytest`, `ruff check .`,
`ruff format --check tests` and `mypy pfd`.

## Licence & attribution

`pandid` is **free for individuals, for research and teaching, and for small
companies**, under the [PolyForm Small Business License 1.0.0](https://polyformproject.org/licenses/small-business/1.0.0).

You may use it at no cost if your company has **fewer than 100 people** and
**under 1,000,000 USD** (2019, inflation adjusted) of revenue in its prior tax
year. Students, academics, hobbyists and small consultancies are covered.

A company above either threshold needs a commercial licence. Contact
`<add your contact address>`.

This is a source-available licence, not an OSI-approved open-source one — worth
knowing if your organisation screens dependencies by licence.

**Equipment symbols are Apache-2.0 and stay that way.** They derive from the
draw.io / diagrams.net P&ID stencils, so `pfd/render/_vendored_symbols.py` and
`scripts/vendor_data/drawio/` carry the original licence rather than the one
above. [`NOTICE`](https://github.com/Alpha9463/py-chemengg/blob/main/NOTICE)
says exactly which files are which; the full texts are in
[`LICENSE`](https://github.com/Alpha9463/py-chemengg/blob/main/LICENSE) and
[`LICENSE-APACHE`](https://github.com/Alpha9463/py-chemengg/blob/main/LICENSE-APACHE).

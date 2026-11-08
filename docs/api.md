# API reference

Pandid builds a drawing from equipment and connections. It does not calculate
mass or energy balances. This page covers the main public calls; the example
[gallery](gallery/README.md) shows complete sheets.

Most classes and returned handles are importable from `pandid`. Equipment is also
available through `pandid.units` and `pandid.devices`.

## `Flowsheet`

```python
from pandid import Feed, Flowsheet, Product, Pump

fs = Flowsheet("Transfer")
feed = fs.add(Feed("Feed"))
pump = fs.add(Pump("P-101"))
product = fs.add(Product("Product"))
fs.connect(feed.outlet, pump.suction)
fs.connect(pump.discharge, product.inlet)
fs.render("transfer.svg")
```

`Flowsheet(name, *, stream_naming_scheme="S{n}", stream_number_start=1,
line_numbering_scheme="{size}-{service}-{sequence}-{spec}",
line_number_start=1001, loop_number_start=101,
valve_station_tag_scheme="{letters}-{number}{suffix}", auto_faces=True)`
sets numbering and automatic port-face selection. Numbering schemes can be
format strings or callables; a stream naming scheme that cannot format the
number `{n}` raises `ValueError` when set. The three number starts are integers;
a float, even `1.0`, raises `TypeError`. Sizes, `pin()` coordinates and `via()`
waypoints take any finite real number (`int`, `float` or numpy); a `Decimal`
raises `TypeError`, and NaN or infinity raises `ValueError`. Loop and
instrument numbers are integers or text; a float raises `TypeError`. Drawn
text such as a description, reference or table cell may be given as a number;
it is drawn as text and round-trips through a spec; names and settings must be
text.

| Method | Purpose |
|---|---|
| `add(unit, *, on=None, at=None)` | Register and return a `Unit`. Tags must be unique, apart from repeatable logic symbols and utility headers. `on=` puts a valve, reducer or fitting in a line. |
| `connect(source, dest, **options)` | Join ports and return a `Stream`. Process connections go from outlet to inlet. |
| `package(name, units, *, description="", reference="")` | Draw units as one package unit and return a `Package`; see [Package units](#package-units). |
| `layout()` / `route()` | Resolve equipment coordinates and stream paths. `render()` calls both. |
| `render(path, **options)` | Write SVG, draw.io, PDF or PNG according to the extension. |
| `to_svg(**options)` / `show(**options)` | Return SVG text or open a browser preview. |
| `validate(*, diagram=None, show_stream_table=None)` | Return `list[Issue]`; errors and warnings have a severity, code and message. |
| `to_dict()` / `from_dict(spec)` | Serialize intent and the drawn layout, or build an equivalent sheet. |
| `from_json(path)` / `from_yaml(path)` | Read a spec file; YAML needs `pandid[yaml]`. |
| `line_list()` / `equipment_list()` / `instrument_index()` | Return a schedule as rows; see [Schedules](#schedules). |

The main collections are `fs.units`, `fs.streams`, `fs.components`,
`fs.loops` and `fs.packages`. `fs.warnings` contains findings from the last render. The sheet
also carries `title_block`, `annotations`, `stream_table`, `stream_labels` and
`stream_table_sections`.

| Handle | Meaning |
|---|---|
| `Port` | A named connection on a unit. |
| `Stream` | A connection returned by `connect()`. |
| `Pin` | A unit's declared placement. |
| `Frame` | A unit's resolved drawing box. |
| `Route` | A stream's resolved path. |

### Rendering options

`render()`, `to_svg()` and `show()` accept the same drawing options:

| Option | Values | Effect |
|---|---|---|
| `diagram` | `"pfd"` (default), `"p&id"`, `"bfd"` | Drawing conventions and validation context. |
| `show_stream_table` | `False` (default), `True`, `"sheet"` | Omit the table, draw it on the sheet, or give it its own sheet. |
| `border` | `"none"` (default), `"zone"` | Add a zone border. |
| `page_size` | `None` (default), `"A4"` to `"A0"` | Fit the sheet to the drawing, or set the physical sheet size. |
| `connections` | `"none"` (default), `"flanged"`, `"flanged-at-nozzles"` | Default joint style for streams; a stream's `ends` overrides it. |
| `jump_direction` | `"vertical"` (default), `"horizontal"` | Which crossing line carries the mark. |
| `crossing_style` | `"gap"` (default), `"arc"`, `"plain"` | Crossing mark. |
| `debug` | `False` (default), `True`, or grid spacing | Draw the coordinate overlay. |
| `check` | `True` (default), `False` | Raise on validation errors during rendering when true. |

PDF and PNG require `pandid[pdf]`. `.drawio` writes an editable diagrams.net
file. SVG output has no optional dependencies.

## Units and ports

A `Unit` has a tag, a symbol `variant`, optional `width` and `height`,
`label_pos`, `description` for the equipment list, and `reference` for boundary
flags; pass these five by keyword. Use `unit.ports["name"]`,
`unit.port("name")`, or a named attribute such as `pump.suction`. Some classes
add `n_feeds`, `n_inlets`, `n_outlets` or `n_draws` to create numbered ports.

A class names equipment; `variant=` selects how its base kind is drawn. For
example, `Cyclone("S-101")` is a `Separator` with the cyclone drawing. A drawing
without its own class is available as `units.Separator("S-101", variant="sifter")`.

### Common ports

Ports are available by attribute (`pump.suction`) or through `unit.ports`.
The names depend on the class and variant. Common patterns are:

- `Feed.outlet` connects to a unit's inlet; `Product.inlet` receives its output.
- Pumps, compressors and fans use `suction` and `discharge`; valves use
  `inlet`, `outlet` and a signal `actuator`. A valve's `variant=` is its body
  and `actuator=` what strokes it: `"diaphragm"`, `"piston"`, `"motor"`,
  `"solenoid"`, `"hydraulic"` or `"handwheel"`, drawn on the body's stem, as in
  `Valve("XV-101", variant="ball", actuator="piston")`. `ControlValve`,
  `SolenoidValve` and `MotorOperatedValve` draw their own actuator on the body
  `variant=` names.
- A machine that takes a driver has a `drive`: pumps, compressors, fans,
  conveyors, crushers, mills and feeders. A `Motor` (`variant="ac"` or `"dc"`
  for ISO items 20.7 and 20.8) turns it through its `shaft`:
  `fs.connect(motor.shaft, pump.drive)`. The motor is drawn beside the
  machine, on the side its `drive` faces, joined by a short straight shaft.
- Other drivers turn a machine the same way: a `Turbine` and a `DieselEngine`
  through their `shaft`, and a `Gearbox` between a driver and its machine,
  taking the driver at its `drive` and turning the machine with its `shaft`.
  A `Generator` (`variant="ac"` or `"dc"`) is driven at its `drive`:
  `fs.connect(turbine.shaft, generator.drive)`. A unit whose only lines are
  shafts is drawn beside its partner; two piped machines on one shaft, such as
  a turbine and the compressor it drives, are stacked where their shaft ends
  face each other, and the shaft is drawn straight wherever they do.
- Separators expose `feed` and either `vapor`/`liquid` or
  `overflow`/`underflow`.
- A `Crystallizer` uses `feed`, `vapor`, `overflow` and `product`; `agitator=`
  names the stirrer in its draft tube, or `None` for none.
- A `FlotationCell` uses `feed`, `concentrate`, `tailings` and `air`;
  `agitator=` names the rotor on its shaft, or `None` for none.
- A `Furnace` heats `inlet` to `outlet` with `fuel`. A `CombustionChamber`
  takes combustion air at `inlet` and sends hot gas out of `outlet`.
- A `Silo` uses `feed`, `vent` and `discharge`; a `Bunker` has no `vent`.
- A tumbling mill, `BallMill`, `RodMill`, `SAGMill` or `AGMill`
  (`Mill("ML-101", variant="ball")` and so on), takes `feed` through its west
  trunnion and gives `discharge` through its east one. A `Stockpile` is
  stacked at `feed`, on top, and reclaimed at `reclaim`, under it. Both are
  built to the `width` and `height` they are given: a longer mill carries more
  balls, and a wider pile has a flat top.
- A `MembraneModule` takes `feed` and gives `concentrate` and `permeate`;
  `variant="ro"`, `"nf"`, `"uf"` or `"mf"` letters its grade. A
  `PigLauncher` sends the pig out of `main`, driven in at `kicker`; a
  `PigReceiver` takes it in at `main` and lets the line out at `kicker`. Both
  have `closure`, `vent`, `relief` and `drain`.
- A `BootedDrum` (`Separator(variant="boot")`) or `ThreePhaseSeparator`
  (`variant="three_phase"`) takes one `feed` and gives `vapor`, `liquid` and
  `water`: the water from the boot, or from ahead of the weir.
- A `MixerSettler` uses `light_in`, `heavy_in`, `light_out` and `heavy_out`;
  `agitator=` names the stirrer in its mixer. An `ExtractionColumn` takes the
  heavy phase at `feed_1` on its top stage and the light phase at `feed_2` on
  its bottom one.
- A `Deaerator` uses `feed`, `vent`, `steam` and `outlet`.
- Columns use `feed`, `overhead` and `bottoms`; distillation columns also have
  reflux, boilup and duty ports.
- Reactors use `feed`, `outlet`, `vent` and `duty`. A `JacketedReactor` has
  `jacket_in` low on the jacket and `jacket_out` high on it in place of `duty`.
- Tanks and vessels use `inlet`, `outlet`, `vent`, `relief` and `drain`; an
  open-top tank, `Tank(variant="open_top")`, has no `vent` or `relief`.
  `agitator=` hangs a stirrer from the roof with its motor above it, which
  carries `drive`, and moves the vent and relief to the top of the east and
  west walls: `Tank("TK-101", variant="flat_roof", agitator="turbine")`.
- Multi-feed equipment exposes `feed_1`, `feed_2`, and so on when configured.

### Equipment classes

Import a named equipment class directly from `pandid`, such as `GearPump`,
`GravitySeparator`, `DistillationColumn` or `ControlValve`. Each inherits the
ports and behavior of its base class. Inspect `unit.ports` for the exact
connections a chosen class provides.

### Variants

Use `variant=` on a base class for a drawing without its own equipment class:
`units.Valve("HV-101", variant="gate")`. Run `pandid symbols` to list the
current registry, or `pandid symbols --kind valve` to narrow it. The installed
registry is the source of available variant names.

### Manholes and sockets

`Vessel` and `Evaporator` take `manholes=` and `sockets=`, each a list of
`(face, fraction)` pairs: the wall, and how far along it from its top or left
end, 0 to 1. A manhole (ISO 10628-2 26.5) is drawn on the wall and has no port.
A socket (26.6) is an outlet, `socket_1`, `socket_2`, and so on in the order
given. A face with no straight wall, or a fraction off the wall, is refused.

```python
from pandid import Flowsheet, Product, Vessel

fs = Flowsheet("Drum")
d101 = fs.add(Vessel("D-101", manholes=[("E", 0.3)], sockets=[("W", 0.7)]))
sample = fs.add(Product("Sample"))
fs.connect(d101.socket_1, sample.inlet)
fs.render("drum.svg")
```

### `Block`: the block flow diagram

`Block(name, inputs=1, outputs=1)` draws a plant section. Counts create
`in_1`... and `out_1`... ports on the west and east faces, which the layout
may move to face their peers; face sequences such as `inputs=["W", "N"]`
set each port's side. `block.ports_on("N")` lists a face's ports,
`block.order_on("N", ports)` sets their order, and `block.face("in_1")`
returns the declared face. An unpinned block sizes itself for its ports and name.

## Placement

Unpinned units follow the flow and the faces their nozzles are drawn on. Pin
only the coordinates or nozzles that need manual control.

| Call | Effect |
|---|---|
| `unit.pin(x=..., y=...)` | Fix either or both coordinates. `col=` puts the unit in a flow column, counted west to east; `row=` orders units down their column. |
| `unit.pin(port="feed", x=..., y=...)` | Place a specified port at a coordinate. |
| `unit.pin(orientation=..., mirrored=...)` | Turn or mirror the symbol. |
| `unit.nozzle("feed", "W")` | Require a port on a compass face. |
| `stream.via([(x1, y1), (x2, y2)])` | Route through explicit pixel waypoints. |

### Devices on a line

```python
from pandid import Feed, Flowsheet, Product, Pump, Reducer, Valve

fs = Flowsheet("Inline devices")
feed = fs.add(Feed("Feed"))
pump = fs.add(Pump("P-101"))
product = fs.add(Product("Product"))
line = fs.connect(feed.outlet, pump.suction)
fs.connect(pump.discharge, product.inlet)
fs.add(Valve("HV-101"), on=line)
fs.add_valve_station("CV-101", on=line)
fs.add(Reducer("RD-101"), on=line, at=0.9)
```

`on=` puts a valve, reducer or fitting, or a valve station, in a line returned
by `connect()`. The handle still names the whole line. Devices sit in the
order they are added; `at=`, a fraction strictly between 0 and 1, gives a
rough position, and a device with `at=` goes before any with a larger `at`.
The line's resolved path determines where they are drawn. Pin a device with
`pin()`, and a station with `x=` and `y=`.

### Automatic face selection

`auto_faces=True` lets the engine choose among a symbol's movable port faces.
It passes over a face blocked by another unit. Use `nozzle()` to force a face
when the piping convention matters. The choice is made on the rendered sheet; a
`Block`'s declared faces turn with the block.

The default `Reactor` offers `outlet` on `"S"`, `"E"` or `"W"`. `"S"` is used unless a side face gives a more direct run.

A count such as `inputs=2` leaves the faces of a `Block`'s, `Tank`'s or
`Vessel`'s connections to the engine; a list such as `inputs=["W", "N"]`
states each one. The engine moves a counted connection to another face only
where the family's lines need fewer bends, the box has room, and no two lines
on that face cross or crowd. `route()` keeps the move only where the drawn
sheet has fewer bends or crossings and no new finding. The faces on offer:

| Unit | Inlets | Outlets |
|---|---|---|
| `Block` | `"W"`, `"E"`, `"N"`, `"S"` | `"W"`, `"E"`, `"N"`, `"S"` |
| `Tank` | `"W"`, `"E"`, `"N"`; `"floating_roof"`, `"open_top"` and `"sphere"`: `"W"`, `"E"`; `"gas_holder"`: `"W"`, `"E"` | `"S"`; `"default"`, `"conical"`, `"flat_roof"`, `"floating_roof"` and `"open_top"` also `"W"`, `"E"` low on the wall; `"gas_holder"`: `"E"`, `"W"` |
| `Vessel` | `"W"`, `"E"`, `"N"` (the top head); `"dome"`: `"W"`, `"E"`; `"electrical_heating"`: `"W"`, `"N"`; `"horizontal"`: `"W"`, `"N"`, `"E"` | `"E"`, `"W"`; `"horizontal"`: `"S"` |

With an `agitator=`, a `Tank` or `Vessel` offers its inlets no `"N"`: the roof
carries the motor.

An inlet and an outlet on one wall are spread apart along it, the inlet
above. A head, roof or cone drawn to a point takes one connection. Fix a face with a
list, with `unit.nozzle("in_2", "N")`, or by pinning the nozzle with
`unit.pin(port="in_2", x=..., y=...)`. A list and the tables give the faces of
the unit upright, which turn with it. On a `Tank` or `Vessel`, `nozzle()` names
the face as drawn, so a turned or mirrored unit takes the face the reader sees;
on a `Block` it names the box's own side.

A reactor's, column's or separator's feeds and draws move the same way:

| Unit | Feeds | Draws |
|---|---|---|
| `Reactor` | `"W"`; `"default"` and `"jacketed"` also `"N"`, one feed on the top head beside the drive | |
| `Column` | `"W"`, `"E"` | `"E"`, `"W"` |
| `Separator` | `"W"`; `"default"` and `"knockout"` also `"E"` | |

A feed or draw on the opposite wall keeps its stage height, which must lie
between the condenser and reboiler duty nozzles. Fix one with
`column.nozzle("feed_2", "E")`, which names the face as drawn.

Symbols whose function depends on gravity should keep their upright orientation.
Validation reports `gravity-turned` when one is rotated away from it.

## Streams

`connect()` requires both endpoints to be on the sheet. Process streams join an
outlet to an inlet. Signal connections may use ports or bare instrument/valve
units. `kind` may be `material`, `energy`, `electric`, `pneumatic`,
`hydraulic`, `wireless`, `data`, `software`, `capillary` or `mechanical`. A
hydraulic line carries a footed stroke at each mark (ISO 15519-2 A.1.08) and a
wireless line is drawn as a wave. When omitted, a signal line to a valve with a
diaphragm or piston actuator, or with none drawn, is pneumatic and any other
signal line is electric; two energy/utility ports make an energy stream; a driver's `shaft` to a
machine's `drive` makes a mechanical one, drawn without a number; other process
ports make a material stream. `add_control_loop()` infers its output line the same way
unless `output_kind=` is given. On a PFD, `validate()` reports
`energy-carrier-missing` until the label drawn on an energy line names its
carrier: `fs.connect(cooler.utility_out, heater.utility_in, service="LP steam")`.

`connect()` also accepts `name`, `draw_as_recycle`, `ends` and line-number fields
`size`, `schedule`, `service`, `sequence`, `spec` and `insulation`. The first
stream is `S1` by default. Inline fittings carry the same number through;
`unit.new_line_number = True` starts a new one. Assigning line-number fields
produces names such as `6"-P-1001-A1A` instead of `S1`.

`line.mark(kind, at=...)` marks a point of a line, `at` being a fraction of its
drawn length strictly between 0 and 1:

- `line.mark("battery limit", at=0.5, before="ISBL", after="OSBL")` and
  `line.mark("limit of supply", at=0.5, before="VENDOR", after="OWNER")` draw
  a dashed boundary across the line with a diamond on top (ISO 10628-1 5.6,
  Figure 7), the parties either side of the diamond; both texts are optional.
- `line.mark("tie-in", at=0.5, number="TI-101")` draws the number in a hexagon
  on the line.
- `line.mark("spec break", at=0.5, before="A1A", after="B2B")` draws a bar
  across the line with the piping classes either side.

`before` is the upstream side. On a split line's handle, `at` runs along the
whole run. Tags and line numbers keep off the markers, and `validate()` reports
`line-marker-crowded` for one drawn over a unit, another line or another
marker. Signal lines take none.

`connect()` also draws a pipe's treatment along it: `tracing="steam"` (or
`"electric"`, or any medium) for a traced line (ISO 10628-2 25.6),
`insulated=True` for an insulated one (25.9; 25.8 when traced too) and
`jacketed=True` for a jacketed one (25.7). `insulation=` is only the line
number's code and draws nothing. A line carries its marks once, together on
its longest straight run with room for them clear of every unit, other line,
marker and note; its own segments come first, then its valve stations' pipework. Tags and
line numbers keep off the marks. Where no run has room the marks are not drawn,
and `validate()` reports `line-mark-crowded`. Set on a split line's handle, a
treatment applies to the whole run; signal lines take none.

A returned `Stream` exposes `source`, `dest`, `kind`, `name`, `route`,
`properties`, `color`, `dasharray`, `ends`, `tracing`, `insulated`, `jacketed`
and `markers`. `properties` supplies text or
numbers for the stream table; no balances are calculated. `draw_as_recycle`
hints which edge a cycle should break. `via()` overrides its automatic route.

### Line numbers

Set the line-number fields in `connect()` or on the returned stream. The
`line_numbering_scheme` format string supports `{size}`, `{schedule}`,
`{service}`, `{sequence}`, `{spec}` and `{insulation}`; a callable can replace
it. `line_number_start` controls the automatic sequence. This is separate from
`stream_number_start`, which controls `S1`, `S2`, and so on.
`validate()` reports `line-field-undrawn` for a field set on a line that its
label does not draw: a `name=` replaces the line number, the scheme leaves the
field out, or the field is stated past a valve or tee that carries another
segment's number on. Set `new_line_number = True` on that valve or tee to start
a new number there.

### Stream properties and the table

Set `stream.properties = {"Temperature": "25 C", "Pressure": "4 barg"}`
on a returned stream, then call `fs.render("sheet.svg", show_stream_table=True)`.

`show_stream_table="sheet"` puts the table on its own sheet. Use
`fs.stream_table` (`pandid.document.StreamTableOptions`) for sizing and the
sheet title; `fs.stream_table_sections` adds section headers. Set
`fs.stream_labels` (`pandid.document.StreamLabelOptions`) for label enclosure.

## Instrumentation

`fs.add_instrument("FT", 101, sensing=stream)` adds an instrument with the tag
`FT-101`. Use `near=`, `offset=` and `angle=` to anchor a balloon to a stream
or unit: `at=` how far along a line, `face=` which side of a unit. `display=`
selects field, central or subsidiary presentation, drawn as no bar, one bar or
two across every symbol; `variant=` selects the symbol: `"default"`,
`"shared"`, `"computer"`, `"sis"`, `"logic"` or `"interlock"`.
`fs.add_balloon(element)` gives a primary fitting its balloon.
`function=` draws a function block touching the balloon at a clear corner,
upper right first: `fs.add_instrument("FY", 101, acting_on=fv, function="I/P")`.
It takes a symbol of ISO 15519-2 A.6 or ISA-5.1, typed as drawn or as a word:
`"sum"` (Σ), `"average"` (Σ/n), `"difference"` (Δ), `"multiply"` (×),
`"divide"` (÷), `"sqrt"` (√), `"derivative"` (dx/dt), `"integral"` (∫),
`"characterize"` (f(x)), `"bias"` (±), `"gain"` (K), `"lag"` (Pt1),
`"high select"` (>), `"low select"` (<), `"max"`, `"min"`, or a signal
conversion such as `"I/P"` or `"E/P"`.

A level gauge, an external cage or a DP level transmitter takes two process
taps on the face it senses, as fractions along it from its top or left end, and
draws an impulse line from each:
`fs.add_instrument("LG", 101, sensing=drum, face="E", taps=(0.3, 0.7))`.
`element=` draws the primary element at the tap end (ISO 15519-2 A.4):
`"thermowell"` (A.4.10), `"radar"` or `"ultrasonic"` (A.4.21),
`"vibrating fork"` (A.4.22) or `"electrode"` (A.4.23):
`fs.add_instrument("TT", 101, sensing=line, element="thermowell")`.

### Control loops

`fs.add_loop("F", 101)` returns a `Loop` that supplies member tags with
`loop.element("FE")` and `loop.tag("CV")`. `fs.add_control_loop(variable,
measuring=..., acting_on=...)` creates the transmitter, controller and signal
streams around an existing final control element, returning a `ControlLoop`.
Signal streams connect instrument terminals to a valve's `actuator`.

### Valve stations

`fs.add_valve_station("CV-101", isolation=True, reducers=True, bypass=True,
drains=2)` builds a station and returns a `ValveStation` with `inlet`, `outlet`,
`control` and `members`. Its control valve is a diaphragm valve on the body
`variant=` names; `actuator=` gives it another. Pass `on=` to put one in an
existing line, as for a device. The station's tag scheme can be set on the flowsheet or for one
station.

## Package units

```python
skid = fs.package("PK-301", [p301a, p301b, f301],
                  description="Dosing Package", reference="VENDOR DWG 4711")
```

`fs.package()` draws bought-in equipment, such as a vendor skid, as one package
unit and returns a `Package` with `name`, `units`, `description` and
`reference`. A package has no ports and no place of its own: it is drawn as a
boundary frame round its units (ISO 15519-1 7.3), a dash-dot line at the
detail weight, with its tag outside the upper-left corner and `reference=`
inside the lower-left corner. The units keep their own tags. A unit belongs to
one package, and a package tag may not repeat a unit's.

Automatic layout keeps a package's units together and other units, valves on
its lines included, out of its frame; lines that do not serve a package are
routed round it. Whatever is drawn inside the frame is in the package, so list
the valves and instruments drawn there too. `validate()` reports
`package-encloses`, an error, for a unit drawn inside the frame of a package it
is not in.

## Sheet furniture

Assign a `TitleBlock` to `fs.title_block`; `Revision` entries carry its issue
history. `Annotation` and `TableBox` add notes and tables with
`fs.add_annotation()`. The `pandid.document` helpers `equipment_table()`,
`notes()` and `legend()` create common boxes. A date left blank in a title block
is filled at render time; set it for reproducible output.

```python
from pandid import Revision, TitleBlock

fs.title_block = TitleBlock(
    title="Transfer", drawing_number="PFD-1001",
    revisions=[Revision("A", "2026-09-29", "Issued for review")],
)
```

## Schedules

`fs.line_list()`, `fs.equipment_list()` and `fs.instrument_index()` return the
sheet's schedules as a `list[dict]`: one dict per row, with the same keys in
every row of a list. `csv.DictWriter` and `pandas.DataFrame` take them as they
are.

```python
import csv
import sys

from pandid import Feed, Flowsheet, Product, Pump

fs = Flowsheet("Transfer")
feed = fs.add(Feed("Feed"))
pump = fs.add(Pump("P-101"))
product = fs.add(Product("Product"))
line = fs.connect(feed.outlet, pump.suction, size='4"', service="P", spec="A1A")
fs.connect(pump.discharge, product.inlet)
line.properties = {"Flow (kg/h)": 1200}

rows = fs.line_list()
writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
writer.writeheader()
writer.writerows(rows)
```

| Schedule | One row per | Keys |
|---|---|---|
| `line_list()` | Line, grouped as the stream table groups it | `line`, `kind`, `size`, `schedule`, `service`, `spec`, `insulation`, `from_unit`, `from_nozzle`, `to_unit`, `to_nozzle`, then one per stream property |
| `equipment_list()` | Unit that `equipment_table()` lists by default, and package; a package's row comes before its units' | `tag`, `description`, `class`, `variant` (`None` for a package) |
| `instrument_index()` | Instrument balloon | `tag`, `loop`, `measured_variable`, `function_letters`, `location`, `on`, `relation` |

A field or property the sheet does not state is `None`.

## Validation

`fs.validate()` returns `Issue` objects with `severity`, `code` and `message`.
Errors include unit overlap, invalid pins and coincident ports. Warnings include
routes through unrelated units, large detours, crowded nozzles and undrawn
labels. `fs.render(..., check=True)` raises on errors; warnings from the last
render are in `fs.warnings`. The `diagram` argument selects the drawing
conventions used by validation.

### A set of sheets

```python
from pandid import Document, Feed, Flowsheet, Product, Pump, TitleBlock

crude = Flowsheet("Crude unit")
crude.title_block = TitleBlock(drawing_number="PFD-001")
feed = crude.add(Feed("Crude Oil"))
pump = crude.add(Pump("P-101"))
to_residue = crude.add(Product("Crude", reference="PFD-002"))
crude.connect(feed.outlet, pump.suction)
crude.connect(pump.discharge, to_residue.inlet)

residue = Flowsheet("Residue unit")
residue.title_block = TitleBlock(drawing_number="PFD-002")
from_crude = residue.add(Feed("Crude", reference="PFD-001"))
product = residue.add(Product("Residue"))
residue.connect(from_crude.outlet, product.inlet)

print(Document([crude, residue]).validate())  # []
```

`Document(sheets).validate()` checks sheets against each other and returns
`Issue` objects, errors first. A sheet's drawing number is its
`title_block.drawing_number`. A `Feed` or `Product` with `reference=` is an
off-page connector. Its partner is the flag of the other direction on the
referenced sheet whose `reference=` names this sheet and that has the same tag,
or else the same line number. Errors are a connector without a partner,
partners whose lines differ in line number, service or size, one tag on
different kinds of equipment, a drawing number on two sheets, and a sheet
without a number that another sheet has to point back at. A reference to a
drawing outside the set is a warning. Each sheet's own findings still come
from `fs.validate()`.

## Declaring a flowsheet as data

`Flowsheet.from_dict()`, `from_json()` and `from_yaml()` load a spec.
`to_dict()` writes author intent and, once the sheet is drawn, a `layout:`
section with where each unit, balloon and line is drawn, and `route_state`, the
state `route()` holds for its next call, compressed and tagged with the engine
version that wrote it. `from_dict()` starts from that layout, so the sheet
draws as it was drawn, lines frozen with `via()` included, and an edit after
reading it back draws as on the sheet that wrote it. Read by another engine
version, the sheet still draws as saved and is laid out afresh once edited. The layout is not a pin: it records a checksum of the rest of the
spec, and a spec edited since, or one without a `layout:`, is laid out afresh.
YAML input requires the `yaml` extra. Invalid specs raise `SpecError` naming
the entry. A minimal YAML sheet is:

```yaml
name: Transfer
units:
  - {kind: Feed, name: Feed}
  - {kind: Pump, name: P-101}
  - {kind: Product, name: Product}
streams:
  - {from: [Feed, outlet], to: [P-101, suction]}
  - {from: [P-101, discharge], to: [Product, inlet]}
```

A spec can also define the numbering schemes and starts, components, loops,
instruments, line properties, `pin`, `port_faces`, packages
(`packages: [{name: PK-301, units: [P-301A, F-301], reference: VENDOR DWG 4711}]`),
a title block, annotations and stream-table options. YAML reads only plain decimals as numbers, so
`0101` and `1:30` stay text. A key written twice in one mapping raises
`SpecError`.
Custom `Unit` subclasses are Python-only and cannot round-trip through the
built-in spec format.

## Command line

`python -m pandid` and the installed `pandid` command are equivalent.

```text
pandid draw SPEC [-o OUT] [--diagram {pfd,p&id,bfd}] [--page-size SIZE]
                   [--border {none,zone}] [--stream-table [sheet]]
pandid validate SPEC [--diagram {pfd,p&id,bfd}] [--stream-table [sheet]]
pandid symbols [--kind KIND]
```

`SPEC` is JSON or YAML; YAML needs `pandid[yaml]`. `draw` defaults to an SVG
beside the spec. `validate` prints findings; `symbols` lists registered
variants. Exit codes: `0` success, `1` rejected sheet, `2` invalid command,
`3` missing optional extra.

## Custom equipment

Subclass `Unit` with a unique `kind` and a `PORTS` list. Each port is
`(name, direction, role)`; directions are `inlet` or `outlet`. Roles include
`process`, `feed`, `product`, `energy`, `utility`, `vapor`, `liquid`, `signal`,
and `shaft` and `drive` for the two ends of a shaft.

```python
from pandid import Unit

class Crystalliser(Unit):
    kind = "crystalliser"
    PORTS = [
        ("feed", "inlet", "process"),
        ("mother_liquor", "outlet", "process"),
        ("crystals", "outlet", "process"),
    ]
```

Without a registered symbol, the unit draws as a generic box and emits a
warning. Register a `pandid.render.symbols.Symbol` with
`pandid.render.symbols.default_registry` for custom artwork. A custom class is
not available to the built-in JSON/YAML spec reader or automatic equipment
list unless explicitly included.

## Extension points

Pass an object implementing `layout(fs)` to `fs.layout(engine=...)` or one
implementing `route(fs)` to `fs.route(router=...)`. Symbol registration lives in
`pandid.render.symbols.default_registry`. The built-in engines remain the
defaults.

## Standards

Pandid uses selected conventions from ISO 10628-1/2 and ISO 15519-1/2 for
process drawings, and ANSI/ISA-5.1 for instrument tags, balloons and signal
lines. ISA instrumentation differs from the ISO 15519-2 scheme. Sheet sizes use
the ISO 216 A series, and title-block fields draw on ISO 7200. These are design
references, not a claim of conformance or certification. Record any project
conventions and deviations in the drawing legend.

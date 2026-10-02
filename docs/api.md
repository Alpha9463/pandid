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
format strings or callables. The three number starts are integers; a float,
even `1.0`, raises `TypeError`. Sizes, `pin()` coordinates and `via()`
waypoints take any real number (`int`, `float` or numpy); a `Decimal` raises
`TypeError`.

| Method | Purpose |
|---|---|
| `add(unit)` | Register and return a `Unit`. Tags must be unique, apart from repeatable logic symbols and utility headers. |
| `connect(source, dest, **options)` | Join ports and return a `Stream`. Process connections go from outlet to inlet. |
| `place_on(stream, device, *, at=0.5)` | Put an inline device on an existing material stream. |
| `place_valve_station_on(stream, tag, *, at=0.5, **options)` | Put a complete `ValveStation` on a stream. |
| `layout()` / `route()` | Resolve equipment coordinates and stream paths. `render()` calls both. |
| `render(path, **options)` | Write SVG, draw.io, PDF or PNG according to the extension. |
| `to_svg(**options)` / `show(**options)` | Return SVG text or open a browser preview. |
| `validate(*, diagram=None)` | Return `list[Issue]`; errors and warnings have a severity, code and message. |
| `to_dict()` / `from_dict(spec)` | Serialize intent or build an equivalent sheet. |
| `from_json(path)` / `from_yaml(path)` | Read a spec file; YAML needs `pandid[yaml]`. |

The main collections are `fs.units`, `fs.streams`, `fs.components` and
`fs.loops`. `fs.warnings` contains findings from the last render. The sheet
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
flags. Use `unit.ports["name"]`, `unit.port("name")`, or a named attribute such
as `pump.suction`. Some classes add `n_feeds`, `n_inlets`, `n_outlets` or
`n_draws` to create numbered ports.

A class names equipment; `variant=` selects how its base kind is drawn. For
example, `Cyclone("S-101")` is a `Separator` with the cyclone drawing. A drawing
without its own class is available as `units.Separator("S-101", variant="sifter")`.

### Common ports

Ports are available by attribute (`pump.suction`) or through `unit.ports`.
The names depend on the class and variant. Common patterns are:

- `Feed.outlet` connects to a unit's inlet; `Product.inlet` receives its output.
- Pumps use `suction` and `discharge`; valves use `inlet`, `outlet` and a signal
  `actuator`.
- Separators expose `feed` and either `vapor`/`liquid` or
  `overflow`/`underflow`.
- Columns use `feed`, `overhead` and `bottoms`; distillation columns also have
  reflux, boilup and duty ports.
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

### `Block`: the block flow diagram

`Block(name, inputs=1, outputs=1)` draws a plant section. Counts create
`in_1`... and `out_1`... ports; face sequences such as `inputs=["W", "N"]`
set each port's side. `block.ports_on("N")` lists a face's ports,
`block.order_on("N", ports)` sets their order, and `block.face("in_1")`
returns the declared face. An unpinned block sizes itself for its ports and name.

## Placement

Unpinned units follow topology and port-face claims. Pin only the coordinates
or nozzles that need manual control.

| Call | Effect |
|---|---|
| `unit.pin(x=..., y=...)` | Fix either or both coordinates. `col=` and `row=` are grid alternatives. |
| `unit.pin(port="feed", x=..., y=...)` | Place a specified port at a coordinate. |
| `unit.pin(orientation=..., mirrored=...)` | Turn or mirror the symbol. |
| `unit.nozzle("feed", "W")` | Require a port on a compass face. |
| `stream.via([(x1, y1), (x2, y2)])` | Route through explicit pixel waypoints. |

### Stream-relative attachments

```python
from pandid import Feed, Flowsheet, Product, Pump, Valve

fs = Flowsheet("Inline devices")
feed = fs.add(Feed("Feed"))
pump = fs.add(Pump("P-101"))
product = fs.add(Product("Product"))
run = fs.connect(feed.outlet, pump.suction)
fs.connect(pump.discharge, product.inlet)
fs.place_on(run, Valve("HV-101"))
fs.place_valve_station_on(run, "CV-101", at=0.25)
```

`at` is a fraction strictly between 0 and 1, and defaults to 0.5.
Inline devices and valve stations do not make independent
placement claims; the stream's resolved path determines their location. Keep
the original stream handle to attach more than one device at distinct fractions.

### Automatic face selection

`auto_faces=True` lets the engine choose among a symbol's movable port faces.
It passes over a face blocked by another unit. Use `nozzle()` to force a face
when the piping convention matters. The choice is made on the rendered sheet; a
`Block`'s declared faces turn with the block.

`Reactor` variants `default` and `plain` offer `outlet` on `"S"`, `"E"` or
`"W"`. `"S"` is used unless a side face gives a more direct run.

Symbols whose function depends on gravity should keep their upright orientation.
Validation reports `gravity-turned` when one is rotated away from it.

## Streams

`connect()` requires both endpoints to be on the sheet. Process streams join an
outlet to an inlet. Signal connections may use ports or bare instrument/valve
units. `kind` may be `material`, `energy`, `electric`, `pneumatic`, `data`,
`software` or `capillary`. When omitted, two energy/utility ports make an energy
stream; other process ports make a material stream.

`connect()` also accepts `name`, `draw_as_recycle`, `ends` and line-number fields
`size`, `schedule`, `service`, `sequence`, `spec` and `insulation`. The first
stream is `S1` by default. Inline fittings carry the same number through;
`unit.new_line_number = True` starts a new one. Assigning line-number fields
produces names such as `6"-P-1001-A1A` instead of `S1`.

A returned `Stream` exposes `source`, `dest`, `kind`, `name`, `route`,
`properties`, `color`, `dasharray` and `ends`. `properties` supplies text or
numbers for the stream table; no balances are calculated. `draw_as_recycle`
hints which edge a cycle should break. `via()` overrides its automatic route.

### Line numbers

Set the line-number fields in `connect()` or on the returned stream. The
`line_numbering_scheme` format string supports `{size}`, `{schedule}`,
`{service}`, `{sequence}`, `{spec}` and `{insulation}`; a callable can replace
it. `line_number_start` controls the automatic sequence. This is separate from
`stream_number_start`, which controls `S1`, `S2`, and so on.

### Stream properties and the table

Set `stream.properties = {"Temperature": "25 C", "Pressure": "4 barg"}`
on a returned stream, then call `fs.render("sheet.svg", show_stream_table=True)`.

`show_stream_table="sheet"` puts the table on its own sheet. Use
`fs.stream_table` (`pandid.document.StreamTableOptions`) for sizing and the
sheet title; `fs.stream_table_sections` adds section headers. Set
`fs.stream_labels` (`pandid.document.StreamLabelOptions`) for label enclosure.

## Instrumentation

`fs.add_instrument("FT", 101, sensing=stream)` adds an instrument with the tag
`FT-101`. Use `near=`, `at=`, `offset=` and `angle=` to anchor a balloon to a
stream or unit. `display=` selects field, central or subsidiary presentation;
`variant=` selects the symbol. `fs.add_balloon(element)` gives a primary
fitting its balloon.

### Control loops

`fs.add_loop("F", 101)` returns a `Loop` that supplies member tags with
`loop.element("FE")` and `loop.tag("CV")`. `fs.add_control_loop(variable,
measuring=..., acting_on=...)` creates the transmitter, controller and signal
streams around an existing final control element, returning a `ControlLoop`.
Signal streams connect instrument terminals to a valve's `actuator`.

### Valve stations

`fs.add_valve_station("CV-101", isolation=True, reducers=True, bypass=True,
drains=2)` builds a station and returns a `ValveStation` with `inlet`, `outlet`,
`control` and `members`. Use `place_valve_station_on()` to attach one to an
existing stream; it defaults to the stream midpoint. The station's tag scheme
can be set on the flowsheet or for one station.

## Sheet furniture

Assign a `TitleBlock` to `fs.title_block`; `Revision` entries carry its issue
history. `Annotation` and `TableBox` add notes and tables with
`fs.add_annotation()`. The `pandid.document` helpers `equipment_list()`,
`notes()` and `legend()` create common boxes. A date left blank in a title block
is filled at render time; set it for reproducible output.

```python
from pandid import Revision, TitleBlock

fs.title_block = TitleBlock(
    title="Transfer", drawing_number="PFD-1001",
    revisions=[Revision("A", "2026-09-29", "Issued for review")],
)
```

## Validation

`fs.validate()` returns `Issue` objects with `severity`, `code` and `message`.
Errors include unit overlap, invalid pins and coincident ports. Warnings include
routes through unrelated units, large detours, crowded nozzles and undrawn
labels. `fs.render(..., check=True)` raises on errors; warnings from the last
render are in `fs.warnings`. The `diagram` argument selects the drawing
conventions used by validation.

## Declaring a flowsheet as data

`Flowsheet.from_dict()`, `from_json()` and `from_yaml()` load a spec.
`to_dict()` writes only author intent, not computed routes or coordinates.
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

A spec can also define components, loops, instruments, line properties,
`pin`, `port_faces`, a title block, annotations and stream-table options.
Custom `Unit` subclasses are Python-only and cannot round-trip through the
built-in spec format.

## Command line

`python -m pandid` and the installed `pandid` command are equivalent.

```text
pandid draw SPEC [-o OUT] [--diagram {pfd,p&id,bfd}] [--page-size SIZE]
                   [--border {none,zone}] [--stream-table [sheet]]
pandid validate SPEC [--diagram {pfd,p&id,bfd}]
pandid symbols [--kind KIND]
```

`SPEC` is JSON or YAML; YAML needs `pandid[yaml]`. `draw` defaults to an SVG
beside the spec. `validate` prints findings; `symbols` lists registered
variants. Exit codes: `0` success, `1` rejected sheet, `2` invalid command,
`3` missing optional extra.

## Custom equipment

Subclass `Unit` with a unique `kind` and a `PORTS` list. Each port is
`(name, direction, role)`; directions are `inlet` or `outlet`. Roles include
`process`, `feed`, `product`, `energy`, `utility`, `vapor`, `liquid` and `signal`.

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

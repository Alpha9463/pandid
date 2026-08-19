# API reference

Everything a process engineer touches, verified against the source. Anything not
listed here is either internal or not part of the supported surface.

> **Scope.** `pandid` draws diagrams. There is **no mass or energy balance engine**:
> stream properties are strings you supply, and nothing is computed from them.
> `pandid.state.State` and the `state` slots on `Port`/`Stream` are reserved for a
> future backend and are never written by this library.

```python
from pandid import Flowsheet, Component, Pump, Separator, Cyclone
import pandid
pandid.__version__          # the installed version, e.g. "0.0.1"
```

Every unit and equipment class is on the package. `pandid.units` and
`pandid.devices` are the same classes under a qualified name, and importing
either namespace still works.

---

## `Flowsheet`

```text
Flowsheet(name: str, *,
          stream_naming_scheme: str | Callable[[int], str] = "S{n}",
          stream_number_start: int = 1,
          line_numbering_scheme: str | Callable[[Stream], str]
              = "{size}-{service}-{sequence}-{spec}",
          line_number_start: int = 1001,
          loop_number_start: int = 101,
          valve_station_tag_scheme: str | Callable[[str, str], str]
              = "{letters}-{number}{suffix}",
          auto_faces: bool = True)
```

The container and the single source of truth for connectivity.

- `stream_naming_scheme` is either a format string taking `{n}` (default
  `"S{n}"` → `S1`, `S2`, …) or a callable `int -> str`. Keyword-only.
- `stream_number_start` sets the `{n}` the first stream gets (default `1`, so
  the first stream is `S1`; `100` gives `S100`, `S101`, …). Keyword-only.
- `line_numbering_scheme` is either a format string taking the line-number
  components (`{size}`, `{schedule}`, `{service}`, `{sequence}`, `{spec}`,
  `{insulation}`) or a callable `Stream -> str`, for a site whose convention is
  spelled some other way. Keyword-only. See [Line numbers](#line-numbers).
- `line_number_start` sets where the automatic sequence begins (default `1001`,
  so the first line is `…-1001-…`). Keyword-only.
- `loop_number_start` sets the number the first `add_loop()` with no number of
  its own takes (default `101`, so the first loop is `F-101`). Keyword-only. See
  [Control loops](#control-loops).

`stream_number_start` and `line_number_start` are two different numbers on two
different labels. `stream_number_start` moves the whole stream number, the `S1`
a PFD draws in a flag and a stream table keys its columns on.
`line_number_start` moves the `sequence` **component** of a line number, the
`1001` inside `6"-P-1001-A1A`. A sheet may want one and not the other, so
neither stands in for the other.
- `valve_station_tag_scheme` spells a valve station's members out of its control
  valve's tag: a format string taking `{letters}`, `{number}`, `{suffix}`,
  `{role}` and `{control}`, or a callable `(role, control_tag) -> str`.
  Keyword-only. See [Valve stations](#valve-stations).
- `auto_faces` lets the engine choose which face each movable port is piped
  from. See [automatic face selection](#automatic-face-selection). Keyword-only.

### Attributes

| Attribute | Type | Notes |
|---|---|---|
| `units` | `list[Unit]` | in insertion order |
| `streams` | `list[Stream]` | in creation order |
| `components` | `list[Component]` | |
| `loops` | `list[Loop]` | declared control loops, in declaration order; never in `units` |
| `auto_faces` | `bool` | engine picks movable ports' faces; default `True` |
| `warnings` | `list[Issue]` | soft findings from the last render, and only from it: emptied at the start of every render |
| `title_block` | `TitleBlock \| None` | drawn whenever it is set |
| `annotations` | `list` | sheet furniture boxes, drawn whenever they are added |
| `stream_table_sections` | `list[tuple[str, str]]` | `(before_key, header_label)` |

### Building the topology

```text
add(unit: Unit) -> Unit
```
Registers a unit and returns it, so it chains with `.pin()`. Raises `ValueError`
if the unit is already on a flowsheet, or if the tag is already taken: a tag
names one item, so two pumps called `P-101` are a mistake in the drawing.

Two symbols stand for one thing shown in several places and are the exceptions.
A **trip square** (`Instrument(variant="sis")`, its `"logic"` spelling, or
`variant="interlock"`) is a logic function rather than a device and is drawn at
every place it acts; a **utility header flag** (`Feed`/`Product` with
`header=True`, see [Off-page connectors](#off-page-connectors)) is one service
drawn at every place it is tapped. Both carry the same tag each time. A repeat
is accepted and given a name of its own, so a stream endpoint, a spec entry or
an equipment-list row still means exactly one of them:

```python
squares = [fs.add_instrument("I", 1, variant="logic") for _ in range(4)]
[s.tag for s in squares]     # ['I-1', 'I-1', 'I-1', 'I-1']   drawn four times
[s.name for s in squares]    # ['I-1', 'I-1 (2)', 'I-1 (3)', 'I-1 (4)']
```

A [`Tee`](#units-and-ports) repeats for the opposite reason: it draws no tag at
all, so two of them are not two things a reader could confuse. `Tee()` defaults
to the name `TEE` and the second one becomes `TEE (2)`. It may still not take a
name that already means something else, because that name is what a stream and a
spec entry reach it by.

Nothing else repeats, and both drawings have to be of the same thing. A second
`LT-101` balloon is one loop number used twice, a square sharing its tag with a
balloon is two ISA-5.1 symbols claiming to be the same thing, and a `Feed` and a
`Product` under one label are two services pointing opposite ways; all of them
raise.

```text
connect(src: Port | Unit, dst: Port | Unit, *,
        kind: str = "material",
        name: str | None = None,
        draw_as_recycle: bool = False,
        size=None, schedule=None, service=None, sequence=None, spec=None,
        insulation=None,
        ends: str | tuple[str, str] | None = None) -> Stream
```
Creates the stream. Both units must already be on this flowsheet, and neither
port may already carry a stream. Each of those raises `ValueError`.

On a **process** connection `src` must be an outlet and `dst` an inlet; fluid
enters a nozzle or leaves it. A **signal** connection has no such rule — the
same alarm terminal is fed on one sheet and trips from it on another — so either
of an instrument's connections takes either end, and which end it took is
`stream.source` / `stream.dest`.

On a signal line either end may be the **unit** instead of one of its
connections, and this picks: an instrument mints a connection and a control
valve offers its stem.

```python
fs.connect(ft305, fic305, kind="electric")     # same as ft305.sig_out -> fic305.sig_in
```

Process piping always names its nozzle, since which nozzle a pipe runs to is the
whole question; a `"material"` kind with a bare unit at either end raises.

`kind` is one of `"material"`, `"energy"`, `"electric"`, `"pneumatic"`,
`"data"`, `"software"` or `"capillary"`. Anything else raises. A `"material"`
connection between two energy/utility-role ports is silently promoted to
`"energy"`.

`kind` also has to agree with what the two ports are. A **signal connection**
(role `signal`: `Valve.actuator` and an instrument's `pv`, `sig_in`, `sig_out`)
is a terminal for a measurement or a command, so nothing flows through it: it
joins another signal connection and takes one of the four signal kinds. Every
other port is a nozzle and takes `"material"` or `"energy"`. Both mismatches
raise, naming the two ports:

```python
fs.connect(feed.outlet, fv.actuator)                       # ValueError: FV-101.actuator
                                                           # is a signal connection and
                                                           # Feed.outlet is a process one
fs.connect(pump_a.discharge, pump_b.suction, kind="pneumatic")   # ValueError: process
                                                                 # piping
```

`name` overrides the auto-generated stream number. `draw_as_recycle=True`
is advisory, nudging the cycle breaker toward tearing *this* edge when a recycle
loop is ambiguous.

`size` / `schedule` / `service` / `spec` / `insulation` are the line-number
components, given as text or a number. Supplying any of them identifies the line
by its line number instead of a stream number. `sequence` is filled by
auto-numbering unless it is given here. See [Line numbers](#line-numbers).

`ends` says how this line's joints are made up and overrides the sheet's
`connections` for this run alone. See
[Flanged connections](#flanged-connections).

```text
add_component(component: Component) -> Component
```
Registers a chemical species. `Component(name: str, formula: str | None = None)`
carries no thermophysical data.

```text
add_annotation(annotation) -> annotation
```
Registers an `Annotation` or `TableBox` (see [Sheet furniture](#sheet-furniture)).

```text
add_instrument(type, number="", *, sensing=None, acting_on=None, near=None,
               at=None, offset=45.0, angle=90.0, variant="default",
               display=None, **kwargs) -> Instrument
add_balloon(element, *, at=None, offset=46.0, angle=90.0, **kwargs) -> Instrument
add_loop(variable: str, number: str | int | None = None) -> Loop
add_valve_station(tag: str, **kwargs) -> ValveStation
```
See [Instrumentation](#instrumentation),
[A primary element's balloon](#a-primary-elements-balloon),
[Control loops](#control-loops) and [Valve stations](#valve-stations).

### Geometry and output

```text
layout(engine=None) -> None      # run auto-layout; resolves a Frame per unit
route(router=None) -> None       # run the orthogonal router; layouts first if needed
renumber_streams() -> None       # assign stream numbers (called by connect and to_svg)
validate() -> list[Issue]        # errors first, then warnings
to_dict() -> dict                # JSON-safe topology
```

```text
to_svg(*, show_stream_table: bool = False,
       border: str | None = None,
       diagram: str | None = None,
       page_size: str | None = None,
       jump_direction: str = "vertical",
       debug: bool | float = False,
       check: bool = True) -> str
```
Returns the SVG string, running `layout()` and `route()` first if they have not
run, or if the sheet changed since they did. With `check=True`, validation
errors raise `ValueError` and warnings land on `fs.warnings`. The checks that
read the model alone run *before* the layout and the routing; see
[When the checks run](#when-the-checks-run).

```text
to_drawio(*, diagram: str | None = None,
          page_size: str | None = None,
          border: str | None = None,
          jump_direction: str = "vertical",
          show_stream_table: bool = False,
          check: bool = True) -> str
```
Returns a draw.io / diagrams.net document, on the same terms. See
[Editing the sheet by hand](#editing-the-sheet-by-hand).

```text
render(path: str | Path, *, show_stream_table=False, border=None,
       diagram=None, page_size=None,
       jump_direction="vertical", debug=False, check=True) -> None
```
Writes the drawing. The format comes from the extension: `.svg` (or no
extension) is pure Python; `.pdf` and `.png` need the optional `pdf` extra
(`pip install 'pandid[pdf]'`) and raise `ImportError` naming the missing package
without it; `.drawio` writes the editable draw.io document. Any other extension
raises `ValueError`. The PDF is vector, drawn at the sheet's physical size, and
the PNG is rasterised from that same PDF.

```text
show() -> None                   # render to a temp file and open a browser
_repr_svg_() -> str              # Jupyter renders a flowsheet inline
```

### Rendering options

| Option | Values | Effect |
|---|---|---|
| `border` | `"none"`, `"zone"` | `"zone"` rules the sheet with the zone-lettered drawing frame (A.. top down, 1.. left to right, so A1 is the top-left corner). Anything else raises `ValueError` |
| `diagram` | `"pfd"` (the default), `"p&id"` | which drawing this is. A P&ID draws its process lines without arrowheads |
| `connections` | `"none"` (the default), `"flanged"`, `"flanged-at-nozzles"` | `"flanged"` marks the double tick at every equipment nozzle *and* both sides of every valve and in-line fitting; `"flanged-at-nozzles"` marks the nozzles alone. A P&ID only; a PFD draws none whatever this says. See [Flanged connections](#flanged-connections) |
| `show_stream_table` | `bool` | draws the stream property table (one column per stream that has properties, plus every feed and product); see [Stream properties and the table](#stream-properties-and-the-table) |
| `check` | `bool` | validate; errors raise, warnings collect. The model-only checks run before the sheet is laid out, the geometric ones after — see [When the checks run](#when-the-checks-run) |
| `page_size` | `None`, `"A4"`, `"A3"`, `"A2"`, `"A1"`, `"A0"` | `None` (the default) sizes the sheet to the drawing; a name draws a sheet of exactly that size |
| `jump_direction` | `"vertical"`, `"horizontal"` | which of two crossing lines gets the semicircle hop |
| `debug` | `False` (the default), `True`, a number | draws the [coordinate overlay](#the-coordinate-overlay). `True` uses a 50-unit grid; a number sets the spacing |

### The coordinate overlay

`debug=True` draws the coordinate system on the sheet, so the numbers
[`pin()`](#pin) takes can be read off the drawing instead of worked out:

```python
fs.render("draft.svg", debug=True)   # or debug=100 to set the grid spacing
```

It draws four things, all in red and blue and all *under* the diagram, so
nothing on the sheet is obscured:

- a faded dashed grid, with the coordinate written along the top and left edges;
- a red cross on the point `pin(x=, y=)` sets — the unit's **top-left corner**,
  or a flag's **nozzle** — labelled with the tag and that pair of numbers;
- a blue dot on every **port**, labelled with the name `pin(port=…)` and
  `connect()` take and the coordinate it is at;
- a faint outline of each unit's drawn box.

Red for corners and blue for ports, because [confusing the two](#pinport) is the
mistake the overlay exists to catch.

The numbers are drawing coordinates on any sheet, including one with a fixed
`page_size` — that is what makes them safe to type back into `pin()`. The
lettering is sized to the paper, so it stays readable when a page fits the
drawing down. `.svg`, `.pdf` and `.png` all carry it.

It is scaffolding for whoever is writing the placement, not part of the drawing.
Off by default; leave it off on anything issued.
`examples/02_manual_layout.py` is drawn with it on.

### Which drawing this is

```python
fs.render("sheet.svg", page_size="A3", border="zone", diagram="p&id")
```

**A P&ID draws no arrowhead on a process line**, because flow direction on one
is read off the equipment and the line list rather than off an arrow on every
run; the arrowhead at the end of each line is a PFD convention, where showing
where the material goes is the whole job of the line. Nothing else about the
sheet changes, and signal lines never carried one on either drawing.

On a PFD, which keeps them, the head marks where a line *arrives* somewhere, so
a line ending at a [`Tee`](#units-and-ports) is drawn without one. A junction is
not somewhere: it is a point on a line where the line divides, drawn as bare pipe
with the run carrying straight on past it, and a filled triangle there reads as
flow stopping in the middle of an unbroken run. A line *leaving* a junction is
untouched and takes its head at its own destination. Every in-line device that
draws a body of its own, a valve or a reducer or a fitting, gives the head
something to land against and keeps it; the rule is
[`Symbol.bare_run`](#the-symbol), so it is the artwork that answers rather than
the class.

### Flanged connections

**A P&ID can mark its joints.** `connections` draws the double tick where the
drawing says a joint is bolted rather than welded:

```python
fs.render("sheet.svg", diagram="p&id")                                    # nothing said
fs.render("sheet.svg", diagram="p&id", connections="flanged")             # bolted throughout
fs.render("sheet.svg", diagram="p&id", connections="flanged-at-nozzles")  # nozzles only
```

The default is `"none"`, and it is the honest one: an unmarked joint is what a
sheet has always drawn, and marking every joint flanged would be a claim about
the piping that nobody made. `"none"` is not `"welded"` — it is the drawing
declining to say.

The other two differ in one thing, and it is the thing you are choosing between:
whether the **bodies standing in the run** are bolted in or welded in.

| | equipment nozzles | valves, in-line fittings | reducers, tees | flags, instruments, signals |
|---|---|---|---|---|
| `"flanged"` | marked | marked both sides | — | — |
| `"flanged-at-nozzles"` | marked | — | — | — |

`"flanged"` takes the plain word because that is what the plain word means: all
of them. A valve in flanged service is flanged both sides — that is how it is
got out of the line. Reducers and tees are butt-welded fittings, as much *pipe*
as the pipe either side, so neither setting marks them. A `Feed` or a `Product`
is a reference to another drawing and has no flange faces; an instrument
terminates a tap or a signal, not a pipe; neither is ever marked.

`"flanged-at-nozzles"` is what `professional_examples/P&ID_301.pdf` draws, where
every piped branch off a shell carries the mark and the gate valves either side
of `CV-305` carry none.

**Which of the two you want is a drafting choice, not a compliance question.**
The word *flange* appears nowhere in either ISO 15519-1:2010 or
ISO 15519-2:2015. §12.4 *Joints* in Part 1 sounds relevant and is not: it governs
the joining of connecting *lines* on the paper — the dot at a T-junction — and
not pipe. §6.3.1 of Part 2 hands symbols to the ISO 14617 series, which
registers symbols rather than placing them. No clause requires a flange at a
valve and none forbids one, so this library offers both and settles neither.

**Only a P&ID marks them**, and *that* clause is quotable. ISO 15519-2:2015
Table 5 (p. 19) lists *connections* among the specific graphical symbols a P&ID
carries as basic information, where Table 4 (p. 17) gives the PFD only general
symbols for them, so any value of `connections` on a PFD draws nothing.

One line can say the opposite of its sheet, in either direction:

```python
fs.connect(t301.bottom, p301.suction, ends="flanged")            # on a plain sheet
fs.connect(t301.bottom, p301.suction, ends="none")               # on a flanged one
fs.connect(t301.bottom, p301.suction, ends=("flanged", "none"))  # one end only
```

A pair states the two ends apart, in the order they were just connected. `ends`
takes any of the three values, so one run can be marked at its nozzles alone on
a sheet that flanges its valves. Left unset, the line follows the sheet.
`examples/11_ethanol_pid.py` draws the whole sheet flanged.

`border` and `diagram` are independent, and both spellings of each are accepted
case-insensitively (`"P&ID"`, `"p&id"`, `"pid"`). A PFD carries the zone frame
as readily as a P&ID does, as `examples/10_ethanol_pfd.py` does, so
`border="zone"` says nothing about which drawing is on the sheet, and
`diagram="p&id"` says nothing about the paper. A P&ID on the engineering frame
asks for both, `border="zone", diagram="p&id"`, and either alone is the half of
it that was asked for.

### Sheet size

Without `page_size` the canvas is the union of the drawing and its furniture, so
the sheet fits the drawing. Naming a size inverts that: the sheet is fixed, the
border and title strip rule to its edges, and the drawing is fitted into what
they leave.

```python
fs.render("sheet.svg", page_size="A3", border="zone")
```

Fix the sheet when the zone grid has to be stable. It is then a property of the
page, so a note reading "valve in D-4" still points at D-4 after the next
revision adds an exchanger. A fitted sheet renumbers its zones whenever it
grows.

Sizes are the ISO 216 landscape sheets, in mm: A4 297x210, A3 420x297,
A2 594x420, A1 841x594, A0 1189x841.

The grid itself runs `A` downward from the top and `1` rightward from the left,
which is ISO 5457 §4.4's direction, so zone `A1` is the top-left corner and a
`location_reference` composed from it names the region a reader would look at.

The *ruling* is not ISO 5457's. §4.4 fixes a 50 mm pitch and the field counts of
its Table 2, and §4.2, §4.3 and §4.5 add a 20 mm filing margin and centring and
trimming marks. `pandid` matches none of those: the interval and the field count
are chosen to suit the sheet. ISO 15519-1 §5.1.2, which is the clause that
applies to a diagram, asks for the centring marks only on a document prepared
for microfilming.

A named sheet declares that physical size on the `<svg>` element, so it prints
and exports to PDF at exactly its ISO size rather than at whatever the reader
takes a user unit to be worth:

```python
fs.render("sheet.pdf", page_size="A3", border="zone")   # a 420x297 mm PDF page
```

A sheet fitted to its drawing has no physical size to declare and stays in user
units.

A drawing too big for the page is scaled down uniformly to fit, never clipped,
and never enlarged when it is already smaller. A page too small for the
furniture itself (a wide stream table on A4, say) raises `ValueError` naming the
size it needed and the widest piece of furniture that needed it.

### Editing the sheet by hand

`.drawio` writes the drawing as an editable draw.io / diagrams.net model rather
than a picture of one: every unit is a shape and every stream an edge between two
of its connection points, so blocks and lines can be moved by hand. draw.io
exports `.vsdx`, so this is also the way to Visio.

```python
fs.render("sheet.drawio")          # or: text = fs.to_drawio()
```

The equipment symbols *are* draw.io's own P&ID stencils (see `NOTICE`), so the
file references them and what opens is a native, editable shape. The fifteen
symbols `pandid` draws itself have no draw.io stencil behind them and are
approximated with draw.io's built-in shapes:

| Drawn here | Exported as | What it loses |
|---|---|---|
| instrument balloon | a circle | nothing |
| panel / auxiliary balloon | a circle | the bar across it, which is what puts the instrument in a panel |
| shared-display balloon | a circle | the square around it |
| computer balloon | a hexagon | nothing |
| SIS / logic balloon | a diamond | the square around it |
| interlock balloon | a diamond | nothing |
| mixer | a triangle | nothing |
| splitter | a mirrored triangle | nothing |
| pipe tee | a line | the branch stub |
| feed / product flag | a rectangle | the arrow point; the tag and the off-page reference are kept |
| conveyor | a rectangle | the belt and its rollers |
| block | a rectangle | nothing |

Every row of that table with something in the last column is **reported**, as a
`drawio-approximated` warning on `fs.warnings` naming the unit and what its
stand-in lost. The rows that lose nothing say nothing. A title-block cell the
strip had to abbreviate is reported too, in the same words the rendered sheet
uses — an issued `.drawio` file carrying a shortened drawing number now says
which field it shortened:

```python
fs.to_drawio(page_size="A3")
for w in fs.warnings:
    print(w)
# [warning] drawio-approximated: CV-101 has no draw.io stencil and is exported
#     as a stand-in, which loses the belt and its two rollers
```

The sheet's own drawing conventions survive the export: the semicircle a
crossing line hops with, the cross-hatching on a pneumatic signal line, the fine
tap line from a process line to the balloon reading it, the letter codes
[`annotate()`](#letter-codes-outside-the-symbol) writes outside a balloon, each in
the quadrant the sheet put it in, and the stream numbers where the sheet
searched for clear paper to write them, leaders and all. Sheet
furniture docks where the sheet docks it, and anything ruled — an equipment
list, a legend, a note list, a `TableBox`, the stream table — comes out as a
real draw.io table with rows and cells rather than as one block of text.

`debug` is the one render option a `.drawio` path refuses. The coordinate
overlay is scaffolding for whoever is placing equipment rather than part of the
drawing, so `render()` raises `ValueError` naming it rather than accepting and
ignoring it.

---

## Units and ports

Import a unit type from the package and build it:

```python
from pandid import Flowsheet, Pump, Separator

pump = Pump("P-101")
drum = Separator("V-101")
```

Every class below, and every [equipment class](#equipment-classes) over them, is
importable that way. `units.Pump` and `devices.Cyclone` are the same classes
qualified by their namespace, which is worth importing for one thing:

```python
from pandid import units

sifter = units.Separator("SC-101", variant="sifter")
```

`units.Kind(variant=…)` is the escape hatch. 131 of the 219 registered drawings
get no class of their own, and this is how you reach them; see
[Variants](#variants) for the list. Where a class exists, name it.

Ports are exposed both as `unit.ports["name"]` and as attributes
(`pump.suction`). An unknown attribute raises `AttributeError` listing the real
ports, and `unit.port("name")` raises `KeyError` the same way. A type of your own
is [Custom equipment](#custom-equipment).

```text
Unit(name, variant="default", width=None, height=None,
     label_pos=None, description="", reference="")
```

- `name` is the equipment tag. It must be non-empty, and unique on the flowsheet
  save for the two symbols that repeat (see
  [Building the topology](#building-the-topology)).
- `variant` is the visual style within the class (see below). A name that kind
  has no symbol for raises `ValueError` listing the ones it does, at the first
  layout or render. A class that names its own `VARIANTS` refuses at
  construction instead; no class in the port table does, so every
  `Kind(variant=…)` in this page is checked when the sheet is drawn, while every
  [equipment class](#equipment-classes) is checked on the line that builds it.
  See [Narrowing a class to its variants](#narrowing-a-class-to-its-variants).
- `width` / `height` override the symbol's intrinsic size. They are taken as the
  *final* box, so a rotated unit gets exactly what you asked for.
- `label_pos` is `"top"`, `"bottom"`, `"left"`, `"right"` or `"center"`. Left
  unset, the engine picks the first free face in top → bottom → right → left
  order, so a nozzle's stream does not run through the tag.
- `description` is free text, and feeds the auto equipment list.
- `reference` is the off-page drawing reference, drawn as a boundary flag's
  second line. Only `Feed` and `Product` have that line, so giving it to
  anything else raises `ValueError`.

`Feed` and `Product` take one argument of their own, `header=False`, which marks
the flag a utility header and is what lets it be added once per tap. See
[Off-page connectors](#off-page-connectors).

### Port table

Each entry is `port` *(direction / role)*.

| Class | `kind` | Ports |
|---|---|---|
| `Feed` | `feed` | `outlet` *(outlet/feed)* |
| `Product` | `product` | `inlet` *(inlet/product)* |
| `Pump` | `pump` | `suction` *(in)*, `discharge` *(out)* |
| `Compressor` | `compressor` | `suction` *(in)*, `discharge` *(out)* |
| `Blower` | `blower` | `suction` *(in)*, `discharge` *(out)* |
| `Turbine` | `turbine` | `inlet` *(in)*, `outlet` *(out)* |
| `Valve` | `valve` | `inlet` *(in)*, `outlet` *(out)*, `actuator` *(in/signal)* |
| `Vessel` | `vessel` | `inlet` *(in)*, `outlet` *(out)*, `vent` *(out/vapor)*, `relief` *(out)*, `drain` *(out/liquid)* |
| `Tank` | `tank` | the same five as `Vessel` |
| `Separator` | `separator` | `feed` *(in)*, `vapor` *(out/vapor)*, `liquid` *(out/liquid)* on the four variants whose draws really are phases — the drum (`default`, `horizontal`, `knockout`) and the wet `scrubber`. The other seven sort or collect rather than separating into phases, and name the two draws their artwork has: `feed` *(in/feed)*, `overflow` *(out)*, `underflow` *(out)*; see [Variants](#variants) |
| `Column` | `column` | `feed` *(in/feed)*, or `feed_1` … `feed_n`, `distillate` *(out/vapor)*, `bottoms` *(out/liquid)*, `reflux_in` *(in/liquid)*, `boilup_in` *(in/vapor)*, `reboiler_duty` *(in/energy)*, `condenser_duty` *(out/energy)*; the feeds are [`feeds`](#the-family-as-a-sequence) |
| `Reactor` | `reactor` | `feed` *(in/feed)*, or `feed_1` … `feed_n`, `outlet` *(out)*, `vent` *(out/vapor)*, `duty` *(in/energy)*, and `drive` *(in/energy)* where it has an [`agitator=`](#what-a-body-carries) to be driven; `variant="tubular"` is a PFR and has no vapour space, so it has no `vent`. The feeds are [`feeds`](#the-family-as-a-sequence) |
| `HeatExchanger` | `hex` | `shell_in`, `shell_out`, `tube_in`, `tube_out`; `kettle` adds `bottoms` *(out/liquid)*. Four variants name their sides differently; see [Variants](#variants) |
| `Heater` | `heater` | `inlet` *(in)*, `outlet` *(out)*, `utility_in` *(in/energy)* |
| `Cooler` | `cooler` | `inlet` *(in)*, `outlet` *(out)*, `utility_out` *(out/energy)* |
| `CoolingTower` | `cooling_tower` | `water_in` *(in)*, `water_out` *(out)*, `air_in` *(in)*, `air_out` *(out)*, `makeup` *(in/utility)*, `blowdown` *(out/liquid)*. Named for the side of the equipment, as an exchanger's are; `makeup` and `blowdown` are on the basin |
| `Furnace` | `furnace` | `inlet` *(in)*, `outlet` *(out)*, `fuel` *(in/feed)* |
| `Filter` | `filter` | `inlet` *(in)*, `outlet` *(out)* on the five that clarify — the medium keeps the solids and is cleaned offline (`default`, `fixed_bed`, `gas`, `gas_fixed_bed`, `gas_belt`). The four that form a cake add `wash_in` *(in/utility)* and `cake` *(out)*: `press`, `belt`, `rotary`, `rotary_scraper`. `ion_exchange` takes a regenerant rather than a wash, and names it: `regenerant_in` *(in/utility)*, `spent_regenerant` *(out)*; see [Variants](#variants) |
| `Centrifuge` | `centrifuge` | `feed` *(in/feed)*, `overflow` *(out)*, `underflow` *(out)*; named for where Table 2 draws them, not for which is the product — see [Variants](#variants) |
| `Dryer` | `dryer` | `feed` *(in/feed)*, `product` *(out)* |
| `CrushingMachine` | `crushing_machine` | `feed` *(in/feed)*, `discharge` *(out)* |
| `Crusher` | `crusher` | `feed` *(in/feed)*, `discharge` *(out)* |
| `Mill` | `mill` | `feed` *(in/feed)*, `discharge` *(out)* |
| `Conveyor` | `conveyor` | `feed` *(in/feed)*, `discharge` *(out)*; the belt anchors them at its two ends and the `screw` casing on its top and underside |
| `Elevator` | `elevator` | `feed` *(in/feed)* at the boot, `discharge` *(out)* at the head |
| `Feeder` | `feeder` | `feed` *(in/feed)*, `discharge` *(out)* |
| `SprayNozzle` | `spray_nozzle` | `inlet` *(in)*, offered on the west face and the east alike — the header runs through it rather than dead-ending on it |
| `ScreeningDevice` | `screening_device` | `feed` *(in/feed)*, `oversize` *(out)*, `undersize` *(out)*; named for where Table 2 draws them, not for which is the product — see [Variants](#variants) |
| `Kneader` | `kneader` | `inlet` *(in)*, `outlet` *(out)* |
| `Reducer` | `reducer` | `inlet` *(in)*, `outlet` *(out)* |
| `Tee` | `tee` | `inlet` *(in)*, `outlet` *(out)*, `branch` *(out, or in with `branch="inlet"`)* |
| `Fitting` | `fitting` | `inlet` *(in)*, `outlet` *(out)* |
| `Ejector` | `ejector` | `motive` *(in/utility)*, `suction` *(in)*, `discharge` *(out)* |
| `Vent` | `vent` | `inlet` *(in/vapor)* |
| `Funnel` | `funnel` | `outlet` *(out/feed)* |
| `Instrument` | `instrument` | `pv` *(in/signal)*, `sig_in` … `sig_in_n`, `sig_out` … `sig_out_n` *(signal)*; the two are [pools](#several-signal-lines-on-one-balloon) |
| `Mixer` | `mixer` | `in_1` … `in_n` *(in)*, `outlet` *(out)*; the family is [`inlets`](#the-family-as-a-sequence) |
| `Splitter` | `splitter` | `inlet` *(in)*, `out_1` … `out_n` *(out)*; the family is [`outlets`](#the-family-as-a-sequence) |
| `Block` | `block` | `in_1` … `in_n` *(in)*, `out_1` … `out_m` *(out)*; the families are [`inlets`/`outlets`](#the-family-as-a-sequence) |

`Vessel` and `Tank` carry the same five nozzles, because a tank and a vessel are
one shell at two design pressures. Three of them are not what enters and what
leaves:

| nozzle | where it is drawn | what it is |
|---|---|---|
| `vent` | the crown | the vapour connection. On a fixed-roof tank, the conservation vent it breathes through as it fills, empties and warms |
| `relief` | the crown | the connection a PSV or a rupture disc is mounted on. Separate from `vent` because a relief passes nothing until the design case, and its path must not run through a valve someone can close |
| `drain` | the vessel's low point | the liquid draw-off: settled water, a clean-out, the liquid a vapour drum knocks out |

```python
tank = fs.add(units.Tank("TK-602", description="Denatured Ethanol Storage"))
fs.connect(tank.vent, arrestor.inlet)      # breather, with the arrestor under it
fs.connect(sphere.relief, flare.inlet)     # PSV takeoff on the crown
fs.connect(drum.drain, sump.inlet)
```

Each is drawn where its duty puts it, not where a count would: a relief is on
the crown because CHEE4001 p.7 puts it there — upright, discharging upward, at
the top of the container — and a drain at the low point because that is what a
drain is. Every tank and vessel variant has all five, and piping none of them
draws the sheet you drew before — a declared nozzle is offered, and leaving one
open is a drawing decision that nothing reports. See
[Nozzles nothing is piped to](#nozzles-nothing-is-piped-to).

Two variants read their drain's face differently: `vessel/legs` and
`vessel/skirted` are drawn much taller than wide, so at their own proportions
the drain leaves sideways rather than downwards. Give the unit a `height` less
than about 2.2 × its `width` and it comes out of the bottom.

Variable-port constructors take their count first:

```text
units.Mixer(name, n_inlets=2, variant="default", width=None, height=None,
            description="")
units.Splitter(name, n_outlets=2, variant="default", width=None, height=None,
               description="")
units.Column(name, n_feeds=1, variant="default", internals=None, trays=8,
             feed_stages=None, width=None, height=None, label_pos=None,
             description="")
units.Reactor(name, n_feeds=1, variant="default", agitator="agitator",
              internals=None, width=None, height=None, label_pos=None,
              description="")
```

(`Mixer` and `Splitter` do not accept `label_pos`, unlike the fixed-port
classes.)

`Tee` is the pipe tee, the junction where a line branches: a bypass leg, a
drain, a vent, a sample point, a PSV takeoff. It is drawn as bare pipe (the run
straight through and the branch off it, nothing at the junction) and carries no
tag, so it never reaches the equipment list. Nothing at the junction includes the
[arrowhead](#which-drawing-this-is): a line ending at a tee has arrived nowhere,
so it is drawn without one even on a PFD.

```text
units.Tee(name="", branch="outlet", variant="default", width=None, height=None,
          description="")
```

`branch="outlet"` takes flow off the run and `branch="inlet"` returns it. The
branch leaves the **south** face as drawn, so the side is the tee's placement:
nothing for south, `pin(mirrored="y")` for north, `pin(orientation=90)` for a
run standing on end with the branch west, `270` for east.

`name` may be left out. A tee has no tag to be told apart by, so
`Tee.repeats()` lets any two share a name and `Flowsheet.add()` hands out
`TEE (2)`, `TEE (3)`, by the same mechanism a repeated interlock square and a
tapped utility header use. It may still not take a name that already means
something else, since that name is what a stream and a spec entry reach it by.

The run keeps one stream or line number straight through a tee, as it does
through a valve or a reducer, and each branch takes one of its own;
`new_line_number` breaks the run's number at the junction.

That is the rule for a tee that *divides*, where both legs are the same fluid.
A `branch="inlet"` joins a second material to the run, so what leaves is not
what arrived, and carrying the number through would write a flow on the line
that the line does not have. End the number there and start another;
[`examples/13_mineral_dewatering.py`](../examples/13_mineral_dewatering.py)
does that at all five of its junctions.

Every port gets a nozzle of its own on the face its family owns, whatever the
count. They sit a fixed pitch apart, 20 px on a mixer or splitter, or are
squeezed into a band of that face once there are too many for that. The count
the symbol was drawn for lands where it always has, so raising a count on one
unit never moves any other, and a single-feed `Column` draws exactly the
tower it always did.

A second feed is what changes the spelling: `col.feed` on a one-feed tower,
`col.feed_1` … `col.feed_n` once there is more than one, drawn top to bottom in
that order. The feeds stay on the shell wall opposite the `reflux_in` and
`boilup_in` returns, so no count can put a feed on a return nozzle.

```python
tower = units.Column("T-302", n_feeds=2, description="Extractive Column")
fs.connect(solvent.outlet, tower.feed_1)   # solvent enters above...
fs.connect(feed.outlet, tower.feed_2)      # ...the feed tray
```

Where that spread lands is still arbitrary — it says nothing about *which*
stage a feed actually enters on. `Column(feed_stages=)` says so, one entry per
feed and in the same count `trays=` gives:

```python
units.Column("T-101", internals="valve_tray", trays=30,
             n_feeds=2, feed_stages=[12, 22])
```

`feed_stages=[12, None]` pins only the first feed and leaves the second on the
even spread. Naming a stage the column does not have (`feed_stages=[40]` on a
30-tray column) is refused, naming the count; naming one at all on a column
with no `internals=` is refused too, since there is no tray for a reader to
count against. `internals="packing"` counts beds rather than decks, and a
stage there lands *above* the bed it names, not through it — a packed tower's
feed enters above the packing.

### The family as a sequence

Each of those counts also has an accessor for the **whole family**, a
`tuple[Port, ...]` in declaration order:

| class | accessor | the nozzles it holds |
| --- | --- | --- |
| `Mixer` | `inlets` | `in_1` … `in_n` |
| `Splitter` | `outlets` | `out_1` … `out_n` |
| `Block` | `inlets`, `outlets` | `in_1` … `in_n`, `out_1` … `out_m` |
| `Column` | `feeds` | `feed`, or `feed_1` … `feed_n` |
| `Reactor` | `feeds` | `feed`, or `feed_1` … `feed_n` |

```python
mixer = fs.add(units.Mixer("M-101", n_inlets=len(headers)))
for header, inlet in zip(headers, mixer.inlets):
    fs.connect(header.outlet, inlet)
```

It is the ports themselves, not their names and not copies, so
`mixer.inlets[0] is mixer.in_1`. The numbered attributes, `port("in_3")` and the
`ports` dict are all unchanged.

Two things worth knowing.

**The tuple is indexed from zero while the nozzles are numbered from one**, so
`inlets[0]` is `in_1`. Nothing re-bases it — a sequence that indexed from one
would be the only one in the language, and would cost `[-1]`, slicing and every
`zip`. Where the number is what you want, `m.in_3` is the plain spelling and a
type checker resolves it (below); `m.port("in_3")` is the same nozzle where the
name is computed, and `enumerate(m.inlets, start=1)` gives the number and the
port together.

**A one-feed `Column` or `Reactor` names its lone nozzle `feed`, and `feeds` is
the one-tuple holding it.** The sequence is the general form and the singular
name stays, so code written against `feeds` reads a one-feed tower and a
three-feed tower the same way.

This is also the only shape a type checker can be told about. The count is a
runtime value and Python has no integer generic, so no annotation names `in_1` …
`in_n`; a generated class per arity would type `Mixer("M", n_inlets=3)` and miss
`Mixer("M", n_inlets=len(feeds))`, which is the call a sheet built from data
actually writes. `mixer.inlets[0]` resolves to `Port` under mypy.

`mixer.in_1` resolves to `Port` too, and so does `mixer.in_3` on a three-inlet
mixer — while `mixer.in_4` on that same mixer is an **error**. The count cannot
be named in an annotation, but it can be read off the *call*: `Mixer`,
`Splitter`, `Column` and `Reactor` overload `__new__` on a literal count and
hand back a subclass declaring exactly the nozzles that count builds.

```python
m = fs.add(units.Mixer("M-101", n_inlets=3))
m.in_3        # Port
m.in_4        # error: Cannot access attribute "in_4" for class "Mixer3"
m.outlt       # error: typo detection is not given up for this
```

The subclasses exist only under `TYPE_CHECKING`. Nothing is built at run time,
the object really is a `Mixer`, and each one is assignable to the base for
anything annotating `Mixer`.

Where the count is **computed** — `Mixer("M", n_inlets=len(feeds))` — no
overload matches, the type is the plain base class, and the numbered nozzles are
unresolvable. That is honest rather than restrictive: a checker cannot know how
many nozzles that call made. Use `m.inlets[i]` there.

`Reactor` takes the same treatment: `Reactor("R-1", n_feeds=2).feed_2` resolves
to `Port`, and `.feed_3` is an error. Its one device subclass gets its own
overloads rather than reusing `Reactor`'s, so it stays itself instead of
narrowing to a `Reactor` subclass:

```python
from pandid.devices import StirredTankReactor

s = fs.add(StirredTankReactor("R-2", n_feeds=3))
s.feed_3        # Port
reveal_type(s)  # StirredTankReactor3, not Reactor3
```

**`Block`** sits outside this. It takes a blanket `__getattr__` instead, so
`block.in_1` resolves and `block.outlt` is *not* caught: its two counts are
independent, and the form its own examples use — `inputs=["W", "W", "N"]` — is a
`list`, whose length is not in its type.

### Equipment classes

**A class is what the equipment *is*; `variant=` is how it is *drawn*.**
`pandid.devices` is one class per device the registry draws, re-exported from the
package, and each is a subclass of the `units` class that owns its kind: a
`GearPump` *is* a `Pump`.

```python
from pandid import Cyclone

sep = Cyclone("S-101")   # units.Separator(variant="cyclone"), by the name it goes by
sep.variant              # 'cyclone'
sep.underflow            # the dust draw, and a Port a type checker can resolve
```

`Kind(variant=…)` stays the low-level form, and is the only way to reach the
131 drawings that get no class of their own. A class stores the
**registry's** spelling of its variant and not its own, so `to_dict()` writes
`variant: cyclone` rather than the class-local `default`, and the file reads
back. [Variants](#variants) lists the drawings each class owns.

The last column is where a class's nozzles differ from its base's: `+` one the
base has not, `-` one it drops. The bases are in the [Port table](#port-table).

| Class | `kind` | Base | Ports that differ |
|---|---|---|---|
| `CentrifugalPump` | `pump` | `Pump` | |
| `GearPump` | `pump` | `Pump` | |
| `ScrewPump` | `pump` | `Pump` | |
| `PeristalticPump` | `pump` | `Pump` | |
| `SubmersiblePump` | `pump` | `Pump` | |
| `VacuumPump` | `pump` | `Pump` | |
| `CentrifugalCompressor` | `compressor` | `Compressor` | |
| `ReciprocatingCompressor` | `compressor` | `Compressor` | |
| `RotaryCompressor` | `compressor` | `Compressor` | |
| `LiquidRingCompressor` | `compressor` | `Compressor` | |
| `ShellAndTubeExchanger` | `hex` | `HeatExchanger` | |
| `DoublePipeExchanger` | `hex` | `HeatExchanger` | |
| `KettleReboiler` | `hex` | `HeatExchanger` | `+bottoms` |
| `Condenser` | `hex` | `HeatExchanger` | |
| `AirCooledExchanger` | `hex` | `HeatExchanger` | `+air_in` `+air_out` `-shell_in` `-shell_out` |
| `PlateExchanger` | `hex` | `HeatExchanger` | `+side_a_in` `+side_a_out` `+side_b_in` `+side_b_out` `-shell_in` `-shell_out` `-tube_in` `-tube_out` |
| `SpiralExchanger` | `hex` | `HeatExchanger` | `+side_a_in` `+side_a_out` `+side_b_in` `+side_b_out` `-shell_in` `-shell_out` `-tube_in` `-tube_out` |
| `ThinFilmEvaporator` | `hex` | `HeatExchanger` | `+jacket_in` `+jacket_out` `+product_in` `+product_out` `-shell_in` `-shell_out` `-tube_in` `-tube_out` |
| `Cyclone` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `GravitySeparator` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `ElectrostaticPrecipitator` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `Screen` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `ImpactSeparator` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `MagneticSeparator` | `separator` | `Separator` | `+overflow` `+underflow` `-vapor` `-liquid` |
| `Scrubber` | `separator` | `Separator` | |
| `VenturiScrubber` | `separator` | `Separator` | |
| `KnockoutDrum` | `separator` | `Separator` | |
| `DustCollector` | `filter` | `Filter` | |
| `RotaryDrumFilter` | `filter` | `Filter` | `+wash_in` `+cake` |
| `FilterPress` | `filter` | `Filter` | `+wash_in` `+cake` |
| `IonExchanger` | `filter` | `Filter` | `+regenerant_in` `+spent_regenerant` |
| `RotaryDryer` | `dryer` | `Dryer` | |
| `FluidizedBedDryer` | `dryer` | `Dryer` | |
| `SprayDryer` | `dryer` | `Dryer` | |
| `ShelfDryer` | `dryer` | `Dryer` | |
| `TurboDryer` | `dryer` | `Dryer` | |
| `BeltDryer` | `dryer` | `Dryer` | |
| `JawCrusher` | `crusher` | `Crusher` | |
| `ConeCrusher` | `crusher` | `Crusher` | |
| `HammerCrusher` | `crusher` | `Crusher` | |
| `ImpactCrusher` | `crusher` | `Crusher` | |
| `RollerCrusher` | `crusher` | `Crusher` | |
| `HammerMill` | `mill` | `Mill` | |
| `ImpactMill` | `mill` | `Mill` | |
| `RollerMill` | `mill` | `Mill` | |
| `VibratingMill` | `mill` | `Mill` | |
| `ScrewConveyor` | `conveyor` | `Conveyor` | |
| `RotaryValveFeeder` | `feeder` | `Feeder` | |
| `RotaryTableFeeder` | `feeder` | `Feeder` | |
| `MeteringFeeder` | `feeder` | `Feeder` | |
| `CoarseRakeScreen` | `screening_device` | `ScreeningDevice` | |
| `FineRakeScreen` | `screening_device` | `ScreeningDevice` | |
| `CoarseAndFineScreen` | `screening_device` | `ScreeningDevice` | |
| `VibratingScreen` | `screening_device` | `ScreeningDevice` | |
| `RotaryDrumScreen` | `screening_device` | `ScreeningDevice` | |
| `ReelScreen` | `screening_device` | `ScreeningDevice` | |
| `ControlValve` | `valve` | `Valve` | |
| `SolenoidValve` | `valve` | `Valve` | |
| `ReliefValve` | `valve` | `Valve` | |
| `PressureRegulator` | `valve` | `Valve` | |
| `MotorOperatedValve` | `valve` | `Valve` | |
| `CheckValve` | `valve` | `Valve` | `-actuator` |
| `SpectacleBlind` | `fitting` | `Fitting` | |
| `FlowElement` | `fitting` | `Fitting` | |
| `StirredTankReactor` | `reactor` | `Reactor` | |
| `GasHolder` | `tank` | `Tank` | |

Three of them do something the name does not say:

- `KettleReboiler` adds `bottoms`, the draw at the weir end of the shell. It is
  the only class in the library that adds a nozzle.
- `CheckValve` drops `actuator`. The flow works it, so there is no operator for
  a signal to land on.
- `Cyclone`, `GravitySeparator` and `ElectrostaticPrecipitator` collect *dust*,
  and name their draws `overflow` and `underflow` for it. So does
  `Separator(variant="cyclone")`, as of 0.1.2: it called them `vapor` and
  `liquid` up to 0.1.1, and those two names were removed in 0.1.3. One drawing,
  one vocabulary, whichever class you built.

### `Block`: the block flow diagram

A BFD sits a level above the PFD: one labelled box per plant section, the
streams between them named, and nothing inside them drawn. `Block` is the only
symbol on such a sheet.

```text
units.Block(name, inputs=1, outputs=1, variant="default", width=None,
            height=None, label_pos=None, description="")
```

`inputs` and `outputs` are **one face per connection**, in order. A plain count
is the shorthand for the common case, west in and east out:

```python
rx = fs.add(units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"]))
fs.connect(feed.outlet, rx.in_1)        # west
fs.connect(recycle.out_1, rx.in_3)      # north
fs.connect(rx.out_2, drain.inlet)       # south

units.Block("Compression", inputs=2, outputs=1)   # both inputs west, output east
```

The nozzles are `in_1` … `in_n` and `out_1` … `out_m`, numbered across the whole
family rather than per face, so moving a connection to another side does not
rename it. `nozzle()` does exactly that, and on a block it always succeeds:
every other symbol is artwork drawn in advance and only offers the faces it was
authored with, while a block's rectangle is built from its own declaration.

```python
rx.nozzle("out_2", "S")          # send one product out of the bottom
rx.face("out_2")                 # -> "S"              which side of the box
rx.ports_on("N")                 # -> (Port in_3,)     what is on that side
```

The connections and the sides they are on are two different accessors, each
named for what it returns, and each a tuple:

```python
rx.inlets                        # -> (Port in_1, Port in_2, Port in_3)
rx.input_faces                   # -> ('W', 'W', 'N')
rx.outlets, rx.output_faces      # ...and the same pair for the outputs
```

`ports_on()` returns ports too, so "connect whatever is on the north" is one
step:

```python
for port in rx.ports_on("N"):
    fs.connect(recycle.outlet, port)
```

`order_on()` is its writer. It sets the order the connections on one face are
drawn in, first to last along it, and it takes the ports `ports_on()` hands back:

```python
loop = fs.add(units.Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"]))
loop.order_on("S", [loop.out_2, loop.in_2])    # purge west, recycle east
loop.order_on("S", loop.ports_on("S")[::-1])   # ...or just turn the wall round
```

Both `in_2` and `out_2` are on the south wall, and a block draws a face's
connections in the order they were declared — inputs before outputs — which is
not always the order the sheet wants. This is the only thing that says otherwise:
`nozzle()` chooses the *side*, and re-declaring a connection onto the side it is
already on leaves it exactly where it was.

Name **every** connection on the face. The call is a statement of the drawing
rather than a nudge at it, so a list that leaves one unplaced is refused, as is
one naming a connection that is on another face — move it with `nozzle()` first.
First is the low end of the face on the box's own axes: west on a north or south
face, north on a west or east one. A mirrored block therefore draws that same
first member on the right of the sheet, exactly as the face itself follows the
box.

> **A BFD lays itself out.** A connection on the north face puts its peer in
> the row above and in the same column, and one on the south puts it below, so a
> utility in from the top and a waste stream out of the bottom each reach their
> nozzle in one turn.
> [`examples/12_block_flow_diagram.py`](../examples/12_block_flow_diagram.py) is
> pinned all the same, because a hand-placed BFD says something the ranking
> cannot: which sections the reader is meant to take in a row.

**A face names the box's own side, not the reader's.** This is the one place
`Block` departs from [`nozzle()`](#nozzle), which everywhere else takes the
compass point on the *finished sheet*. It has to: the face here is the
declaration the drawing is built from, and a declaration cannot be about a
`pin()` that has not happened yet. So a turn or a mirror moves the box and every
connection with it, and `"N"` on a block turned a quarter is drawn on the east.
`face()` answers about the box; `portgeom.port_faces()` answers about the sheet.

**The box sizes itself to what it carries.** A block flow diagram's box is
precisely the thing that gathers many streams, so the height follows the west
and east counts and the width follows the north and south ones, at a pitch of
2.5 arrowheads — the least that still reads as two lines arriving rather than
one blob. Eight inputs on one wall make a *taller block*, not eight crushed
nozzles. The width also clears the name, which a BFD letters inside the box.

`width`/`height` still win where they are given, and a box too small to draw the
connections at that pitch is refused rather than drawn crushed — wherever it is
asked for: the constructor, a later assignment, `nozzle()` and `pin()`, the last
because a quarter turn draws the box's upright faces *across* the sheet and can
put a run on the shorter axis. A refused call leaves the block as it was.

A width given also wins over the name, which then hangs out of both ends of the
box. Labels are written on an opaque halo, so an overhanging one **erases
whatever is drawn beside it**. The render says so, as a `label-overruns-symbol`
warning on `fs.warnings` naming the block and the width it needed. Leave `width`
off and it cannot happen.

A block is **not** scheduled: `equipment_list()` skips it, because a box
standing for a whole section is not a purchasable item. `include=` still takes
one by name, for a block index.

`Conveyor` takes a `length` and a `diameter` instead of a `width` and a
`height`:

```text
units.Conveyor(name, length=80, diameter=20, variant="default",
               label_pos=None, description="")
```

`length` is the run, tail end to head end. `diameter` is the machine across it:
the roller a belt runs on, or the casing bore a screw turns in. Both are
dimensions of the *machine*, and each is set on its own — a long belt on small
rollers and a short one on big rollers are both drawings.

The symbol is **built** to the pair rather than scaled into a box, so a longer
belt grows the straight run, a bigger roller grows a circle, and a longer screw
gets more turns of its flight at the same pitch. `width=` and `height=` size the
drawn box instead, which a quarter turn swaps, so a `Conveyor` refuses them and
names the keyword the number belongs on.

`diameter` defaults to the drawing's own: 20 for the belt, 30 for the screw. A
belt's minimum length is two roller diameters, below which the rollers overlap,
so it moves with the roller; a screw's is a whole turn of the flight plus the
clear casing at each end, all measured along the axis, so it is the same 40 at
every bore.

`feed` is the tail end and can also be taken from the top face, since material
is dropped onto a belt rather than piped into it; `discharge` is the head end
and can also be taken from underneath, for a chute.

`Valve.actuator` is the signal connection on the valve, not a process nozzle. It
is where a controller output or an interlock terminates, and it will not take
process fluid. It sits on the top of the symbol, so the signal stops where it
meets the valve rather than running on into the body.

`unit.new_line_number = True` on an inline unit (valve, reducer, fitting) breaks the
stream number across it (see [Stream numbering](#stream-numbering)).

### Normally closed valves

```text
units.Valve(name, variant="default", normal_position="open", fail="")
valve.normal_position = "closed"
```

This is the *normal* position. Where the valve goes when its actuating energy is
lost is [`fail`](#fail-position), a separate question with a separate answer.

`normal_position` is where the valve sits with the plant running: `"open"` (the
default) or `"closed"`. A closed one is drawn with its body **darkened solid**.

```python
fs.add(units.Valve("HV-301", variant="gate", normal_position="closed"))  # drain
fs.add(units.Valve("HV-302", variant="gate"))                            # isolation
```

The source is **PIP PIC001 clause 4.2.2.7**, which draws a normally closed
manual valve with its body darkened solid. It is **not** an ISA-5.1,
ISO 10628 or ISO 15519 convention: ISA-5.1 says nothing about valve fill and
hands manual block valve depiction to the piping group, ISO 10628 does not have
the symbol either, and **ISO 15519-1 §11.4.5** does rule on the question and
prescribes a *different answer*: letters, not fill. PIP PIC001 is the only one
of the four that fills a body, which is why the fill is cited to it and why the
legend obligation below is not optional.

The rule is one-sided. Normally open is not marked at all, so `"open"` draws
exactly what a valve constructed without the argument draws, and the fill is the
whole of what `"closed"` adds. Nothing about the symbol's box, nozzles or
alternate faces changes, so declaring a valve closed never moves a line already
drawn.

**An unmarked valve says nothing, and two clauses of ISO 15519-1 disagree about
what that silence means.** §11.4.5 makes the NC/NO marking optional, which reads
as leaving an unmarked valve unstated. §11.3.1 a), under *Symbols with movable
parts*, has a general purpose valve that says nothing about its operational
state **regarded as closed** — the
inverse of the North American default that an unmarked valve is normally open.
The standard does not reconcile them, and neither does `pandid`. Read against
§11.3.1's other sub-clauses, a) is fixing a *reference state for drawing
dependent symbols* rather than saying how the plant runs: §11.3.1 e) draws a
valve's position contacts in whatever position they take when the a) valve is
closed, which is what a) exists to define.
§11.4.5 is the clause about telling a reader the operating state. That reading
is offered, not asserted. Either way both clauses agree on the operative point:
an unmarked valve is not a reliable statement of normal position, so say it. The
`"open"` default draws nothing extra because there is nothing agreed to draw,
not because an unmarked valve means open.

**Legend.** ISA-5.1 clauses 2.8.1(b)(1), 2.8.2 and 5.2.5 make it *mandatory* to
declare on a legend or cover sheet any symbol that deviates from or extends the
standard, and a darkened valve is exactly such an extension. A sheet that draws
one owes its reader a legend entry saying what the fill means. Nothing adds it
for you; [`legend`](#convenience-constructors) builds the box:

```python
from pandid.document import legend

fs.add_annotation(legend({"Darkened valve body": "Normally closed (NC)"}))
```

**Bodies that cannot be darkened.** Filling a body leaves only its outline, so
the fill is used where the outline alone still names the device. Where the
device is named by something *inside* the outline, filling over it would draw a
darkened gate valve wearing another name, so the abbreviation **NC** is written
beside the valve instead.

The letters follow **ISO 15519-1 §11.4.5**, which is the clause that rules on
them: it allows the state to be marked with `NC` for *normal closed* or `NO` for
*normal open*, set **above the symbol and to the right**, and illustrates that
at Figure 28. The figure draws an unfilled bowtie with the letters starting at
about the valve's right-hand edge, clear above the run, and that is where
`pandid` puts them. The corner is the same whatever quarter turn the valve is
placed at, so a reader scans a sheet for one thing; where the equipment tag
already reaches into it, the abbreviation steps past the tag rather than over
it.

This is a deliberate split from PIP PIC001, whose clause 4.2.2.8 puts the
letters *below* a horizontal valve and to the right of a vertical one. Each of
the two markings is taken from the standard that rules on it: the fill from PIP,
which is the only source that fills a body, and the letters from ISO 15519-1,
which is the only source that letters one. `NO` is not written; ISO 15519-1
offers it, but the fill convention this sits inside is one-sided and marking
normally open is not implemented.

| | Valve variants |
|---|---|
| darkened body | `default`, `gate`, `globe`, `ball`, `needle`, `plug`, `pinch`, `three_way`, `angle`, `bleed`, `manual`, `motor`, `solenoid`, `hydraulic` |
| `NC` in letters | `butterfly` (PIP PIC001 4.2.2.8's own example), `butterfly_pneumatic`, `check`, `knife`, `saunders` |
| refused | `control`, `regulator`, `relief`, `psv` |

The list is `pandid.render.symbols.NC_DARKENS`, and a variant added later takes
the letters until it is put on it. That is the safe way round, since a variant
falling through both would state its position nowhere.

Darkened, a valve keeps only its outline, so a normally closed `globe` and a
normally closed `ball` are the same drawing: the seat that tells them apart is
inside the body the fill covers. That is what the convention costs, and another
reason the sheet needs its legend entry.

**Control and relief valves are refused.** Clause 4.2.2.10, which bars a control
valve and a relief valve from being shown NC, is enforced rather than warned about,
because a darkened control valve on an issued sheet reads as a block valve
someone has closed:

```python
units.Valve("FV-1", variant="control", normal_position="closed")
# ValueError: FV-1: PIP PIC001 clause 4.2.2.10 bars a control valve and a
# relief valve from being shown NC, and variant 'control' draws one. ...
```

Say where the valve fails instead ([Fail position](#fail-position)), or put the
mark on the hand valve that actually isolates the line. A control valve may still
be declared `normal_position="open"`; the prohibition is only on showing one
closed.

### Fail position

```text
units.Valve(name, variant="control", fail="")
valve.fail = "closed"
```

`fail` is where the valve goes **when its actuating energy is lost**. It is a
different property from `normal_position` and running the two together is the
single easiest mistake to make here:

| | question it answers | marked by |
|---|---|---|
| `normal_position` | where the valve sits **with the plant running** | the body darkened, or `NC` beside it |
| `fail` | where the valve goes **when the air, the hydraulic supply or the power is lost** | letters beside it: `FO`, `FC`, `FL`, `FL/DO`, `FL/DC`, `FI` |

They are independent. A valve may declare either, both or neither, and nothing
infers one from the other, because nothing can:

```python
fs.add(units.Valve("FV-303", variant="control", fail="closed"))   # FC, nothing said about normal
fs.add(units.Valve("XV-304", variant="solenoid",
                   normal_position="closed", fail="open"))        # darkened body, and FO below
```

There is **no default**. `normal_position` defaults to `"open"` because open is a
real state that the convention declines to mark; an undeclared fail position is a
sheet that has not said, so `fail` is `""` and nothing is drawn.

| `fail` | drawn | ANSI/ISA-5.1-2009 Table 5.4.4 |
|---|---|---|
| `"open"` | `FO` | fail to open position |
| `"closed"` | `FC` | fail to closed position |
| `"last"` | `FL` | fail locked in last position |
| `"drift_open"` | `FL/DO` | fail at last position, drift open |
| `"drift_closed"` | `FL/DC` | fail at last position, drift closed |
| `"indeterminate"` | `FI` | fail indeterminate (ISA-5.1-1984 §6.7) |

The names are the plant's words and the letters are the drawing's, kept apart the
way `normal_position="closed"` is not spelled `"NC"`. `FI` is not in the 2009
table, which drops it; it is kept because **PIP PIC001 4.5.3.2** still names it in
its own list of four, and because a valve whose failed position genuinely cannot
be predicted has to be able to say so rather than claim `FL`. The mapping is
`pandid.render.symbols.FAIL_POSITIONS`.

**Letters, not stem arrows, and not ISO's triangle.** Three standards draw this
one fact three ways, so a drawing cannot be silent about which it means.

- **ANSI/ISA-5.1-2009 Table 5.4.4** gives two of them itself, *Method A* as
  arrows or bars on the actuator stem and *Method B* as the letters above. Its
  note 5.3.4(1) requires the user's own standard to record which of the two it
  has picked.
- **ISO 15519-1 §11.3.1 c)** gives the third, geometrically: symbol 654's apex
  points towards the valve where the valve is closed at rest, and away from it
  where the valve is open at rest. **ISO 15519-2** Annex A.3 registers the cases as `654V1A`
  fail close, `654V2A` quick closing, `654V3A` fail open and `659A` fail freeze,
  and draws each as a small triangle on the stem between a diaphragm dome and the
  valve body.
- **PIP PIC001 clause 4.5.3.2** is the only source that chooses between the ISA
  pair, and it chooses the letters: an automated valve's fail action goes in
  text, `FC`/`FO`/`FL`/`FI` after ISA-5.1, with a comment against ISA's stem
  arrows.

`pandid` follows PIP. Two further things point the same way. The reference sheets
this package was built against draw every control valve as a plain diaphragm dome
with the controller output landing on it, carrying neither letters nor stem
arrows, so nothing on an issued drawing argued for the geometry. And the ISO
encoding needs the actuator drawn as a separate symbol on a stem clear of the
body, which is not what the vendored stencils draw: their dome sits directly on
the bowtie, and the `control` variant draws no operator at all, so there is no
stem for a triangle to sit on. The choice is recorded in the README's
[Standards](https://github.com/Alpha9463/pandid/blob/main/README.md#standards)
section, alongside the balloon set, because it is the same kind of declared
exception.

**Where the letters sit.** **PIP PIC001 clause 4.2.4.6(1)** puts the fail-action
abbreviation 0.06 inch directly below the control valve on a horizontal line,
and 0.06 inch to its right on a vertical one.
That is followed whole, so a quarter turn moves these letters
where it does not move the `NC` abbreviation. The two are the same principle
rather than a contradiction: `NC` sits in a *corner*, and a corner is free
whichever way a valve is laid, which is what lets it be fixed. These sit against a
*face*, and which face is free is exactly what the quarter turn changes, because
the face below a valve on a riser is its outlet nozzle with the line running out
of it.

Everything else around the valve is spoken for. Every valve symbol here draws its
actuator on top and the controller output or interlock lands there, so above the
body belongs to the signal line and to the default equipment tag, and the upper
right corner is `NC`'s. A valve stating both of its positions therefore states
them in two places that cannot collide; where the equipment tag is already on the
side the letters want, they step past it rather than over it.

Nothing steps past a *neighbouring* unit, so one case is placed around by hand:
`pin(mirrored="y")` turns a valve's artwork over and puts its actuator
underneath, and its signal lead then arrives through the space the letters use. A
balloon hung directly below such a valve is in the same space. Neither is a
placement the standard contemplates, since it words the rule for an actuator
drawn on top. Put the balloon on another side, or leave the valve the way up its
symbol is drawn.

**Only an actuated valve may declare one.** ISA-5.1 note 5.3.4(10) scopes the
failure symbols to "all types of control valves and actuators", and an actuator
is the test: something driven by air, hydraulic fluid or electricity supplied
from outside the valve.

| | Valve variants |
|---|---|
| may declare `fail` | `control`, `butterfly_pneumatic`, `solenoid`, `motor`, `hydraulic` |
| refused, hand-operated | `manual`, `knife` |
| refused, self-acting | `regulator`, `relief`, `psv` |
| refused, no operator drawn | `default`, `gate`, `globe`, `ball`, `butterfly`, `check`, `needle`, `saunders`, `plug`, `pinch`, `three_way`, `angle`, `bleed` |

```python
units.Valve("HV-1", variant="gate", fail="closed")
# ValueError: HV-1: variant 'gate' has no actuator, so it has no fail position.
# ANSI/ISA-5.1 note 5.3.4(10) scopes the failure symbols to control valves and
# actuators: a handwheel loses no air, and a regulator or a relief valve is
# worked by the process itself. ...
```

The list is `pandid.render.symbols.FAIL_ACTUATED`, and it is the **mirror** of
the `NC` rule rather than the same list:

| | `normal_position="closed"` | `fail=…` |
|---|---|---|
| `gate` | darkened body | refused, no actuator |
| `control` | refused (PIP 4.2.2.10) | letters |
| `solenoid` | darkened body | letters |
| `relief`, `psv` | refused (PIP 4.2.2.10) | refused, self-acting |

`control` is on the list although its stencil draws a Saunders body rather than an
operator: it is the variant this package names *the control valve*, it is the one
clause 4.2.2.10 refuses on the strength of being one, and an automated valve is
exactly what PIP PIC001 4.5.3.2 requires a fail action on.

Multi-port valves are not reachable today and must not simply be added. PIP
PIC001 4.5.3.2(2) rules them out of `FO` and `FC`: an automated multi-port valve
takes `FL` or `FI` where those fit, and the job `FO` and `FC` would do is done
instead by arrows drawing the fail-position flow
paths, and `pandid` draws no such arrows. `three_way` is a bare body with no
operator, so the question does not arise.

**One position, not two.** A valve can behave one way on loss of signal and
another on loss of air, and `fail` holds a single answer. PIP PIC001 4.5.3.2(3)
wants an explanatory note on any valve that fails one way on loss of signal and
another on loss of motive power. Declare the motive-power position here and
add the note; nothing writes it for you.

Nothing about the symbol changes, so unlike a darkened body, declaring a fail
position can never move a line already drawn.

### Spectacle blinds

```text
units.Fitting(name, variant="blind", normal_position="open")
blind.normal_position = "closed"
```

A spectacle blind (figure-8 blind) is two discs on a common tie, one bored
through and one solid, bolted between a pair of flanges. Turning it over swaps
which disc is in the line, and that is the whole of what the symbol says, so it
carries the same `normal_position` a valve does:

```python
fs.add(units.Fitting("SB-101", variant="blind"))                            # line through
fs.add(units.Fitting("SB-102", variant="blind", normal_position="closed"))  # line blanked
```

The run passes through the lower disc. `"open"` (the default) draws that disc
as a **ring**, with the solid one parked above it. `"closed"` draws it
**solid**, with the ring parked above. The tie hangs below the run as the
handle it is.

| | Drawn |
|---|---|
| `normal_position="open"` | the disc in the line is bored: the line is through |
| `normal_position="closed"` | the disc in the line is solid: the line is blanked |

Two differences from the valve's darkened body are worth naming.

- It is a change of **shape**, not a mark applied to one. Both drawings come
  from the stencil set, so the closed blind is a symbol of its own with its own
  `<defs>` entry, and the two states differ in ink alone: same box, same
  nozzles, same faces. Declaring the position never moves a line already drawn.
- It needs **no legend entry**. A solid disc blanking a line is the device's
  own long-standing convention rather than an extension of ISA-5.1, which is
  what obliges the darkened valve body to be declared.

`blind` is the only fitting variant with a position. Every other one is drawn a
single way, so declaring it closed would set an attribute nothing on the sheet
draws, and raises instead:

```python
units.Fitting("ST-1", variant="strainer", normal_position="closed")
# ValueError: ST-1: variant 'strainer' is drawn one way, so it has no normally
# closed position to state; the fittings drawn in two positions are: blind. ...
```

`normal_position` itself lives on a base shared by `Valve` and `Fitting`, so
there is one attribute with one vocabulary; only what a sheet draws for it
differs between them.

### Variants

A **variant** is how a device is drawn. Each row below is a class and the
drawings it owns; where a class spells one its own way that spelling is in
brackets — `DustCollector(variant="belt")` is `filter`'s `gas_belt` — and the
first listed is what the class draws when it is built by name alone.
`Kind(variant=…)` reaches any drawing, whether or not a class of its own owns it.

| Class | `kind` | Drawings it owns |
|---|---|---|
| `CentrifugalPump` | `pump` | `default` |
| `GearPump` | `pump` | `gear` (as `default`) |
| `ScrewPump` | `pump` | `screw` (as `default`) |
| `PeristalticPump` | `pump` | `peristaltic` (as `default`) |
| `SubmersiblePump` | `pump` | `submersible` (as `default`) |
| `VacuumPump` | `pump` | `vacuum` (as `default`) |
| `CentrifugalCompressor` | `compressor` | `default` |
| `ReciprocatingCompressor` | `compressor` | `reciprocating` (as `default`) |
| `RotaryCompressor` | `compressor` | `rotary` (as `default`) |
| `LiquidRingCompressor` | `compressor` | `liquid_ring` (as `default`) |
| `ShellAndTubeExchanger` | `hex` | `default`, `shell_tube`, `u_tube`, `straight_tubes`, `finned`, `hairpin` |
| `DoublePipeExchanger` | `hex` | `double_pipe` (as `default`) |
| `KettleReboiler` | `hex` | `kettle` (as `default`) |
| `Condenser` | `hex` | `condenser` (as `default`) |
| `AirCooledExchanger` | `hex` | `air_cooled` (as `default`) |
| `PlateExchanger` | `hex` | `plate` (as `default`) |
| `SpiralExchanger` | `hex` | `spiral` (as `default`) |
| `ThinFilmEvaporator` | `hex` | `thin_film` (as `default`) |
| `Cyclone` | `separator` | `cyclone` (as `default`) |
| `GravitySeparator` | `separator` | `gravity` (as `default`) |
| `ElectrostaticPrecipitator` | `separator` | `electrostatic` (as `default`) |
| `Screen` | `separator` | `sifter` (as `default`) |
| `ImpactSeparator` | `separator` | `impact` (as `default`) |
| `MagneticSeparator` | `separator` | `permanent_magnet` (as `default`), `electromagnetic` |
| `Scrubber` | `separator` | `scrubber` (as `default`) |
| `VenturiScrubber` | `separator` | `venturi_scrubber` (as `default`) |
| `KnockoutDrum` | `separator` | `knockout` (as `default`) |
| `Separator` | `separator` | `default` (the plain vertical drum, the shell `Vessel` and `Column` share), `horizontal` (the same drum lying down) |
| `DustCollector` | `filter` | `gas` (as `default`), `gas_fixed_bed` (as `fixed_bed`), `gas_belt` (as `belt`) |
| `RotaryDrumFilter` | `filter` | `rotary` (as `default`), `rotary_scraper` (as `scraper`) |
| `FilterPress` | `filter` | `press` (as `default`) |
| `IonExchanger` | `filter` | `ion_exchange` (as `default`) |
| `Filter` | `filter` | `default` (bag/candle/cartridge), `fixed_bed`, `belt`. `DustCollector`'s three are the gas equivalents, each drawn with the dust hopper that makes it one of the [symbols that must not be turned](#symbols-that-must-not-be-turned) |
| `Centrifuge` | `centrifuge` | `default`, `decanter` (ISO item 9.6 X8082, and what `default` draws too — group 9 tabulates no "centrifuge, general" the way item 11.1 does for a crushing machine), `high_speed` (9.1 X2619), `perforated_shell` (9.2 X2614), `solid_shell` (9.3 X8035), `disc` (9.4 X8036), `screw_perforated` (9.5 X8037), `pusher` (9.7 X8038), `skimmer` (9.8 X8039) |
| `RotaryDryer` | `dryer` | `default` |
| `FluidizedBedDryer` | `dryer` | `fluidized_bed` (as `default`) |
| `SprayDryer` | `dryer` | `spray` (as `default`) |
| `ShelfDryer` | `dryer` | `shelf` (as `default`) — ISO item 10.2 X8083 |
| `TurboDryer` | `dryer` | `turbo` (as `default`) — ISO item 10.3 X8040 |
| `BeltDryer` | `dryer` | `belt` (as `default`) — ISO item 10.6 X8043 |
| `Dryer` | `dryer` | `general` — ISO item 10.1 C0046, the bare casing with no characteristic drawn |
| `CrushingMachine` | `crushing_machine` | `default` — ISO 10628-2 item 11.1 X8084, a size-reduction machine with neither a crusher's nor a mill's mark, drawn before process design has picked between them. `Crusher` and `Mill` are both built on it |
| `JawCrusher` | `crusher` | `jaw` (as `default`) |
| `ConeCrusher` | `crusher` | `cone` (as `default`) |
| `HammerCrusher` | `crusher` | `hammer` (as `default`) |
| `ImpactCrusher` | `crusher` | `impact` (as `default`) |
| `RollerCrusher` | `crusher` | `roller` (as `default`) |
| `Crusher` | `crusher` | `default` — ISO 10628-2 item 11.2 X8085, the crusher body with no characteristic in it. The five above are that body carrying one, and each is a machine of its own rather than a style of this one |
| `HammerMill` | `mill` | `hammer` (as `default`) |
| `ImpactMill` | `mill` | `impact` (as `default`) |
| `RollerMill` | `mill` | `roller` (as `default`) |
| `VibratingMill` | `mill` | `vibration` (as `default`) |
| `Mill` | `mill` | `default` — ISO 10628-2 item 11.8 X8086, and what a ball or rod mill is drawn as: the standard tabulates neither, and this is the body its four characteristics go in |
| `ScrewConveyor` | `conveyor` | `screw` (as `default`) — ISO 10628-2 item 18.5 X8063. Built to `length=` and `diameter=` rather than scaled to a box, as the belt on `Conveyor` is |
| `Elevator` | `elevator` | `default` — the bucket elevator, ISO 10628-2 item 18.7 X8065 — and `z_form`, item 18.8 X8066, the same lift with a horizontal run at each end |
| `RotaryValveFeeder` | `feeder` | `rotary_valve` (as `default`) — ISO item 19.2 X8067 |
| `RotaryTableFeeder` | `feeder` | `rotary_table` (as `default`) — ISO item 19.3 C0074 |
| `MeteringFeeder` | `feeder` | `metering` (as `default`) — ISO item 19.4 C0035 |
| `Feeder` | `feeder` | `general` — ISO item 19.1 C2056, the bare circle with no mechanism drawn. The three above are that circle (19.1/19.2) or a body of their own (19.3/19.4) carrying a mechanism, and each is a machine of its own rather than a style of this one |
| `CoarseRakeScreen` | `screening_device` | `coarse_rake` (as `default`) — ISO item 7.2 X8026 |
| `FineRakeScreen` | `screening_device` | `fine_rake` (as `default`) — ISO item 7.3 X8027 |
| `CoarseAndFineScreen` | `screening_device` | `coarse_and_fine` (as `default`) — ISO item 7.4 X8028 |
| `VibratingScreen` | `screening_device` | `vibrating` (as `default`) — ISO item 7.5 X2605 |
| `RotaryDrumScreen` | `screening_device` | `rotating_drum` (as `default`) — ISO item 7.6 X8029 |
| `ReelScreen` | `screening_device` | `basket_reel` (as `default`) — ISO item 7.7 X8030, drawn in a taller outline to hold the reel's own rollers |
| `ScreeningDevice` | `screening_device` | `general` — ISO item 7.1 X8123, the bare outline with no mechanism drawn. Not `separator/sifter` (the `Screen` class above): measured against Table 2, that drawing is not one of ISO group 7's seven rows |
| `ControlValve` | `valve` | `control` (as `default`), `butterfly_pneumatic` |
| `SolenoidValve` | `valve` | `solenoid` (as `default`) |
| `ReliefValve` | `valve` | `relief` (as `default`), `psv` |
| `PressureRegulator` | `valve` | `regulator` (as `default`) |
| `MotorOperatedValve` | `valve` | `motor` (as `default`) |
| `CheckValve` | `valve` | `check` (as `default`) |
| `Valve` | `valve` | bodies: `default` (gate), `gate`, `globe`, `ball`, `butterfly`, `needle`, `saunders`, `three_way`, `plug`, `pinch`, `angle`, `bleed`<br>with a drawn operator: `hydraulic`, `manual`, `knife`<br>which of them take a [`normal_position`](#normally-closed-valves) and which a [`fail`](#fail-position) are two different lists |
| `SpectacleBlind` | `fitting` | `blind` (as `default`) |
| `FlowElement` | `fitting` | `venturi` (as `default`), `flow_nozzle`, `coriolis`, `vortex`, `ultrasonic`, `turbine_meter`, `positive_displacement`, `v_cone`, `wedge`, `target`, `pitot`, `averaging_pitot` |
| `Fitting` | `fitting` | `default` (flanged connection), `flange`, `strainer`, `strainer_cone`, `strainer_y`, `strainer_basket`, `strainer_duplex`, `orifice`, `rotameter`, `rupture_disc`, `sight_glass`, `sight_glass_lit`, `silencer`, `expansion_joint`, `bellows`, `damper`, `spool`, `static_mixer` (ISO item 12.2 X2673), `rotary_mixer` (item 12.1 X2672), `mixing_path` (item 12.3 X8184), `hose`, `coupling`, `clamped_coupling`, `flame_arrestor`, `flame_arrestor_explosion_proof`, `flame_arrestor_detonation_proof`, `flame_arrestor_fire_resistant` |
| `StirredTankReactor` | `reactor` | `default` |
| `Reactor` | `reactor` | bodies: `plain` (a charge vessel with a packed bed hatched into it), `mixing` (a conical-bottomed mixing vessel with the stirrer drawn on top of it), `jacketed` (the dished-end shell inside a heating/cooling jacket), `tubular` (a horizontal shell with a tube pass: a PFR)<br>what is *inside* a reactor is [`agitator=` and `internals=`](#what-a-body-carries) rather than a variant, so a packed bed and a fluidised bed are the plain stirred body with a group-27 internal in it. `plain` and `mixing` are both [deprecated](#deprecated-api) for saying what is inside with the word that chooses the body |
| `Vessel` | `vessel` | `default`, `dished`, `jacketed`, `skirted`, `legs`, `insulated`, `electrical_heating`, `swaged`, `dome`, `horizontal`<br>`dished`, `skirted` and `legs` are one shell on brackets, a skirt or a pair of legs; `jacketed` and `insulated` are that shell clad, and offer the same nozzles in the same places, so swapping one for another moves no run. `swaged` is the vessel drawn in two diameters, the wider one below |
| `Tank` | `tank` | named for the roof: `default` (dished), `conical`, `floating_roof`, plus `sphere`<br>and for the bottom where it is a cone rather than a floor: `conical_bottom` (under a flat roof), `conical_ends` (a cone at each end), `dished_roof_conical_bottom`. On those three the `outlet` is on the cone's apex, which is where the tank actually drains |
| `GasHolder` | `tank` | `gas_holder` (as `default`) |
| `CoolingTower` | `cooling_tower` | `default` (induced draft: the fan on the stack), `induced_draft`, `forced_draft` (the fan in a housing at the foot of each side)<br>and the eight ISO 10628-2 group-5 drawings: `general` (5.1, 2521, the bare outline), `dry_natural` (5.2 X8109), `dry_forced` (5.3 X8110), `dry_induced` (5.4 X8111), `wet_natural` (5.5 X8112), `wet_forced` (5.6 X8113), `wet_induced` (5.7 X8114), `wet_dry_natural` (5.8 X8115) |
| `Column` | `column` | `default` (plain shell), `packed` |
| `Reducer` | `reducer` | `default` (the concentric trapezoid), `concentric`, `eccentric`, plus `large_end`, which points the cone |
| `Vent` | `vent` | `default` (stack with a weather cap), `exhaust_head`, `breather` |
| `Boiler` | `boiler` | `default` — ISO 10628-2 item 4.1, 2532, boiler with dome |
| `Stack` | `stack` | `default` — ISO 10628-2 item 4.7, 2041. Not `Vent`: a stack is Table 2's own equipment, bought and founded like the furnace or boiler it exhausts, where a vent is bulk piping |
| `Flare` | `flare` | `default` — ISO 10628-2 item 4.8, 2591 |
| `Instrument` | `instrument` | `default` (a circle), `shared` (a circle in a square), `computer` (a hexagon), `sis` (a diamond in a square, also spelled `logic`), `interlock` (a plain diamond). Where the information is available is the separate [`display`](#where-the-information-is) axis; `panel` and `aux` are that axis in this column and are reached as `display="central"` and `display="subsidiary"` |
| `SprayNozzle` | `spray_nozzle` | `default` — ISO item 19.5 2037. A terminal fitting rather than a variant of `Fitting`: the one nozzle it has is ticked on both faces, not a pair of them |
| `Kneader` | `kneader` | `default` — ISO item 12.4 X8134 |
| `Heater`, `Cooler`, `Furnace`, `Turbine`, `Blower`, `Ejector`, `Funnel`, `Conveyor`, `Mixer`, `Splitter`, `Tee`, `Block`, `Feed`, `Product` | each its own | `default` only |

`HeatExchanger(variant="kettle")` carries a fifth nozzle, `bottoms`. It is the
draw at the weir end of the shell, where what does not boil leaves as the
tower's bottoms product. No other exchanger has a weir, so no other variant has it, and
asking a plate exchanger for `.bottoms` raises.

**An exchanger's nozzles are named for the side of the equipment they sit on,
never for the duty the stream carries.** Which fluid runs in the shell and which
in the tubes is a design decision an engineer makes deliberately: fouling
service goes tube side because tubes can be rodded out, condensing vapour goes
shell side. It is a fact about the exchanger, and the drawing records it.
Hot and cold, by contrast, invert between operating cases while the nozzle stays
exactly where it is, and they did not even land on the same face from one
variant to the next.

Most variants are a shell and a tube side, and answer to `shell_in`,
`shell_out`, `tube_in` and `tube_out`. Four have no shell or no tubes and say
what they do have instead:

| Variants | Nozzles |
|---|---|
| `default`, `shell_tube`, `straight_tubes`, `finned`, `condenser`, `u_tube`, `hairpin`, `double_pipe`, `kettle` | `shell_in` `shell_out` `tube_in` `tube_out` |
| `air_cooled` | `tube_in` `tube_out` `air_in` `air_out` |
| `plate`, `spiral` | `side_a_in` `side_a_out` `side_b_in` `side_b_out` |
| `thin_film` | `jacket_in` `jacket_out` `product_in` `product_out` |

Not all four are piped across the symbol. `u_tube`, `hairpin` and `double_pipe`
turn the tube round at the far end and bring it back, so both tube nozzles are
on the same face. `air_cooled` is a fin-fan: the bundle is the only piped side,
and the air is not piped at all, so `air_in` sits on the plenum's floor under
the bundle and `air_out` on the fan above it. `plate` and `spiral` have two
symmetric channel sets with no geometric distinction to name, so they are
lettered; on the plate exchanger each side follows one of the two diagonals the
symbol draws. `thin_film` is an evaporator standing on end, fed onto the wiper
at the top (`product_in`) and drawing concentrate off the cone at the bottom
(`product_out`), with the heating medium in the jacket.

`Heater` and `Cooler` take `utility_in` and `utility_out` on the same
principle: the nozzle names the connection the heating or cooling medium lands
on, rather than the duty crossing it.

`Column(variant="packed")` draws two beds of packing between their support
grids, which is the one column symbol with an internal. Its nozzles are the
default column's, at the same heights, so a sheet already drawn does not move
when the variant changes.

`Vessel(variant="jacketed")` puts `inlet` and `outlet` on the jacket's outer
wall rather than on the shell inside it, so the line stops where it meets the
equipment instead of being drawn across the jacket. `insulated` is the same
vessel lagged instead of jacketed and its cladding is drawn on the same two
lines, so it carries the identical nozzles; `legs` likewise carries `skirted`'s.
Swapping between any of those moves nothing on a sheet already drawn.

`electrical_heating` is the one vessel that cannot. Its resistor element hangs
on the outside of the east shell wall across the shell's mid-height, so the
`outlet` drops to the clear wall below it rather than having its run drawn
through the heater. Everything else about it is the family's: `inlet` on the
west wall at mid-height, `vent` on the top head's crown.

A primary flow element is a pair of faces on a line like any other in-line
device, so it is a `Fitting` variant rather than a class of its own. `venturi`
is the one a differential-pressure loop is usually drawn with. Its tag goes in a
balloon beside it with [`add_balloon()`](#a-primary-elements-balloon), which is
how a P&ID draws one: the fitting itself is left unlettered.

`Reducer(variant="eccentric")` is flat on top, so the two ends share a roof and
the small end's centreline is the higher of the two. That is the reducer a pump
suction is drawn with, where a concentric one would leave a pocket for vapour to
collect in against the roof of the line. Its `outlet` is on that raised
centreline and not at mid-height. Flat on the *bottom* is the same fitting
rolled over, for a line that has to drain, and it is a placement rather than a
second symbol: `pin(mirrored="y")` turns the body top-to-bottom while both
nozzles stay on the faces the run enters and leaves by.

Which way a reducer's cone points is `large_end`, which names the nozzle on the
wide face:

| `large_end` | what the fitting does |
| --- | --- |
| `"inlet"` (default) | a **reduction**: the run enters wide and leaves narrow, going into a control valve |
| `"outlet"` | an **expansion**: the run enters narrow and leaves wide, coming back out of one |

It is one fitting either way, the same casting piped round the other way, which
is why it is a property of the unit rather than a second variant or a second
class. The artwork is mirrored and the two ends trade names, so the run still
goes `inlet` to `outlet` and a station reads left to right:

```python
rd = fs.add(units.Reducer("RD-306A", variant="concentric"))
cv = fs.add(units.Valve("CV-306", variant="control"))
ex = fs.add(units.Reducer("RD-306B", variant="concentric", large_end="outlet"))
fs.connect(rd.outlet, cv.inlet)
fs.connect(cv.outlet, ex.inlet)
```

`pin(mirrored="x")` cannot say this instead: that mirror turns the drawing *and*
its nozzles over together, so the run would enter the east face and leave the
west one, drawn backwards through the fitting.

`Fitting(variant="strainer_y")`, `strainer_basket` and `strainer_duplex` lie in
the run, with the pipe axis across the top of the symbol and the pocket below
it. The older `strainer` and `strainer_cone` come from a stencil drawn upright
and stand across the run instead. All four are the same two nozzles.

The operator-bearing valve variants put `actuator` on the operator's crown, and
the bare bodies put it on the top of the symbol where an operator would be
mounted, so a controller output lands where the signal physically goes on either.
`relief` is the exception: a PSV's centreline is taken by its own inlet and
outlet, so its pilot connection is on the side of the bonnet.
`angle` and `psv` are piped from below and out to the side
(`inlet` on S, `outlet` on E). `relief` is piped `inlet` S / `outlet` N and
draws its tag as plain text beside the symbol rather than in a balloon.
`bleed` is the small drain valve tapped off a header and runs down the page,
`inlet` on N and `outlet` on S, with `actuator` set over beside the tap so it
does not stack on the inlet.

### What a body carries

ISO 10628-2 has no reactor symbol and no absorber symbol. Its Table 2 has
**vessels**, and then four groups of *supplementary symbols* — the parts you put
in a vessel — and clause 5 makes composing a symbol out of them a `shall` for
anything the standard does not tabulate itself. So what a piece of equipment
*is* is often the part inside it, and four keywords say which part:

| keyword | ISO group | on |
|---|---|---|
| `agitator=` | 28, agitators and stirrers | `Reactor` |
| `internals=` | 27, internals | `Reactor`, `Column` |
| `supports=` | 26, apparatus elements | `Vessel` |
| `characteristic=` | 29, internal characteristics | `Separator` |

```python
Reactor("R-101", agitator="turbine")                     # a stirred tank
Reactor("R-201", internals="packing")                    # a packed bed
Column("T-101", internals="valve_tray", trays=30)        # a valve-tray tower
Vessel("D-301", supports="skirt")                        # a skirted drum
Separator("V-201", characteristic="gravity")             # a settling chamber
```

`variant=` still chooses the **body** — the outline the part is drawn in. The
two answer different questions, and reaching for `variant=` to say what is
inside a vessel is what the keywords replace: `Reactor(variant="plain")` could
not also be jacketed, and a jacketed `Vessel` could not also stand on legs,
because `variant=` had already been spent.

**The names, all of them ISO's**

| keyword | names |
|---|---|
| `agitator=` | `agitator` (28.1, the general one and the default), `flat_blade`, `gate_paddle`, `cross_beam`, `anchor`, `helical`, `impeller`, `propeller`, `disc`, `turbine` |
| `internals=` | `tray` (27.1), `baffle_tray`, `bubble_cap_tray`, `valve_tray`, `sieve_tray`, `filter_insert`, `fluidised_bed`, `packing` |
| `supports=` | `leg` (26.1), `bracket` (26.2), `skirt` (26.3), `ring` (26.4) |
| `characteristic=` | `gravity` (29.1), `electrostatic` (29.2), `electromagnetic` (29.3) |

**Not stated is not the same as stated empty.** A `Reactor` left alone is a
stirred tank and gets item 28.1; one told `agitator=None` is a bare shell
somebody asked for.

A `Column` is the one class where the two spellings mean the same thing, and
that is ISO's doing: item 2.1 X8100 is the general column and it carries no
internal, while the tray tower is the separate item 2.2 X8101. So an
unfurnished tower is drawn bare, and `internals=` is what furnishes it. It has
to be — an absorber, a stripper and an adsorber all reach the sheet through
this class, and none of them has decks.

**Naming `internals=` leaves the agitator out.** A packed bed is not stirred, a
fluidised bed is mixed by its own fluidisation and a trayed vessel is not a tank
with a paddle in it, so `Reactor("R-201", internals="packing")` draws the bed
and no stirrer. Name one anyway where the vessel really has both:
`Reactor("R-203", agitator="turbine", internals="packing")` is a stirred slurry
reactor and is drawn with the stirrer in the bed.

**An agitator is drawn with the motor that turns it, and the motor brings a
nozzle.** ISO item 1.27 X8006 is a vessel, a group-28 stirrer, and item 20.6's
electric motor above the top head on the stirrer's own shaft — so
`agitator=` draws both, and there is no keyword to ask for the motor or to
leave it out. A `Reactor` with an agitator has a `drive` connection at the top
of the motor, and one without has none. Trays, supports and characteristics are
marks that no line ever reaches and bring nothing.

The motor is drawn *above* the vessel, so a stirred `Reactor`'s drawing is
about a third taller than its shell and its nozzles sit lower in the box than a
bare one's. Its `vent` is on the shell just under the top head rather than on
the crown, because the crown carries the shaft.

**`trays=` counts whatever `internals=` names** — decks for a deck, beds for a
bed. `Column("T-104", internals="packing", trays=2)` is a two-bed absorber. An
absorber, a stripper, a scrubbing tower, an adsorber and a molecular sieve are
not distinct drawings and ISO gives them no symbols: each is this shell carrying
whichever internal it really contains, told apart by its tag.

**Where composition stops.** A composition is only justified where every mark
that distinguishes the drawing is a numbered Table 2 part. Three of the eleven
separators pass that test — items 8.3 X8031, 8.6 X8125 and 8.8 X8126 — and the
rest are distinct registered symbols reached by `variant=`. The cyclone is the
clearest case: group 29 has no vortex to compose one from, and ISO 14617-1 §4.5
names X2618 by registration number as a symbol in its own right, so
`Separator(variant="cyclone")` is the way to ask for a hydrocyclone and is not
going anywhere.

The stirred vessel's motor is the one thing composed from outside those four
groups, and it is composed on the standard's own authority rather than in spite
of it: item 20.6 is a *drive*, a whole machine, and item 1.27 X8006 draws it
inside another symbol and registers the result. Nothing else in group 20
follows it — a turbine or a generator is a unit with a tag of its own.

---

## Placement

### `pin`

```text
unit.pin(*, col=None, row=None, x=None, y=None,
         orientation=unchanged, mirrored=unchanged, port=unstated) -> Unit
```

Records placement **intent** and returns the unit, so it chains off `add()`.
The layout engine reads it and resolves the final geometry. Pinned axes are
honoured exactly, and unpinned units are placed around them. Grid intent
(`col`/`row`) and absolute intent (`x`/`y`) may be mixed, and absolute wins for
whichever axis it sets. `x`/`y` are the unit's frame origin, its **top-left
corner** in SVG coordinates, not its centre and not a nozzle.

A port sits at a fixed *fraction* of its symbol's box, so lining two items up
means matching those fractions, not their corners.

`Feed` and `Product` are the exception, and `pin` means something else on them:
`x`/`y` place the flag's **nozzle**. A flag is sized to its label text and,
unmirrored, a `Feed` is drawn extending *left* from its outlet, so its corner is
a coordinate with nothing drawn at it that moves as the label grows. It has one
nozzle, which is the point worth naming. Pass `port=None` to place the corner
anyway.

```python
hx = fs.add(units.HeatExchanger("E-1")).pin(x=100, y=50)
fv = fs.add(units.Valve("FV-1")).pin(col=2, row=1, mirrored=True)
f1 = fs.add(units.Feed("F-1")).pin(x=110, y=130)   # the flag's tip lands there
```

Calling `pin()` more than once merges: only the arguments you pass are updated,
`orientation` and `mirrored` included, so a later bare `pin(x=…)` nudges the
unit along without undoing a turn or a flip. A unit that has never been pinned
starts square and unflipped. Pass `orientation=0` / `mirrored=False` to put one
back.

### `pin(port=…)`

`port` names a nozzle, and the coordinates given then locate **that nozzle**
rather than the top-left corner — what a `Feed` or a `Product` does by default.
A run is a line at one elevation and the devices on it are whatever size their
artwork is, so this is how a device is put *on* a run without writing down half
its height:

```python
valve.pin(port="inlet", x=200, y=run_y)     # the inlet lands exactly there
```

The offset comes from `portgeom.port_offset()`, which asks the symbol, so no
measured number is written down and no rescaling of the artwork can leave a
valve off its run. Only the axes the call names are read that way, so
`pin(x=…)` followed by `pin(port="inlet", y=run_y)` steps along a row by the
corner and still lands the nozzle on the line. What gets stored is still the
corner, so pinning the same nozzle to the same point twice is the same
placement twice.

The transform in the *same* call is applied first, since a mirror moves the
nozzle within the box. A grid cell has no nozzle in it, so a `port` you *name*
with `col`/`row` raises `ValueError`, and a port the unit does not have raises
`KeyError` naming the ones it does. A flag pinned to a cell is not refused: it
named no port, so there is nothing to refuse.

```text
portgeom.port_offset(unit, port_name, placed=None) -> (dx, dy)
```

Where a port sits relative to the unit's own top-left corner, under `placed` (a
`Pin` or a `Frame`) or under the unit's own placement. This is the offset alone;
to find the elevation of a nozzle to run a spine at, use the pair below.

```text
portgeom.pinned_x(unit, port_name=None) -> float
portgeom.pinned_y(unit, port_name=None) -> float
```

The absolute coordinate a **pinned** unit — or one of its nozzles — sits at.

```python
spine_y = pinned_y(column, "feed")     # the nozzle's elevation
centre_x = pinned_x(tee) + tee_w / 2   # the unit's own corner
```

These replace `unit.pin_.y + port_offset(unit, port)[1]`, which is wrong in two
ways a reader does not see. `pin_` is `None` until the unit is pinned, and
`pin_.y` is `None` when it is pinned by `col`/`row`, so it raises from inside an
arithmetic expression naming neither the unit nor the reason — and the `[1]` has
to be matched to the `.y` by hand, so a `.x` paired with a `[1]` reads fine and
silently draws a run at the wrong elevation.

They answer about the **pin**, and so about the sheet that is coming, which is
what an author placing the next unit is asking. After a layout,
`port_point(unit, unit.frame, port)` is the same question about the sheet that
exists. Both raise `ValueError` if the unit is unpinned or pinned on the other
axis only.

### `orientation`

A clockwise quarter turn in degrees: `0`, `90`, `180` or `270`. Anything else
raises `ValueError`, since a non-quarter turn would tilt the text and break the
orthogonal routing grid. A quarter turn swaps the unit's width and height, and
ports follow, so a stream never detaches from its nozzle.

### `mirrored`

| Value | Effect |
|---|---|
| `False` / `None` | none |
| `True` or `"x"` / `"h"` / `"horizontal"` | left ↔ right (swaps the E and W faces) |
| `"y"` / `"v"` / `"vertical"` | top ↔ bottom (swaps N and S) |
| `"xy"` / `"both"` | both |

Mirroring is applied in the symbol's own frame *before* the quarter turn, the
same order the renderer's SVG transform composes in.

```python
fs.add(units.Pump("P-1")).pin(x=200, y=100, orientation=90)   # discharge now faces S
fs.add(units.Pump("P-2")).pin(x=400, y=100, mirrored="y")     # flipped top-to-bottom
```

### Automatic face selection

A port that its symbol authors on more than one face is **movable**, and the
engine picks which of them the stream leaves from. It scores each declared face
by the orthogonal run to the unit at the other end of the stream, charging a
face that points away from that unit for the detour back around the box, and
takes the cheapest. A reflux drum sitting under its condenser is therefore fed
from the top without anyone saying so.

Selection is a layout phase: it runs once per `layout()`, after every drawn box
is settled and before labels, routing and rendering read a face. The choice is a
*result*, so it lives on the resolved `Frame` (`frame.port_faces`), never on the
unit. `to_dict()` therefore writes the faces you named and not the ones the
engine picked, and laying the same sheet out twice draws it the same way.

Three things it will not do:

- **Override you.** A face named with [`nozzle()`](#nozzle) always wins. That is
  the point of keeping the call: the engine removes detours, it does not
  adjudicate drawing conventions, and where a sheet wants a particular one you
  still say so.
- **Move a nozzle fixed by physics.** For a column's bottoms, a drum's liquid
  draw or a kettle's bottoms draw the symbol authors one placement, so there is
  nothing to choose between and the port is never even considered. A member of a
  port family (`in_1`, `feed_2`) is fixed the same way, because a family spreads
  *along* one face and does not offer others.
- **Land two live connections on one point.** Ports are served in declaration
  order and each takes the cheapest face still free, so the selector cannot
  create the collision `validate()` reports as `coincident-ports`.

`Flowsheet(..., auto_faces=False)` (or `fs.auto_faces = False`) turns it off:
every port then sits on its symbol's own nozzle unless `nozzle()` moved it,
which is what a sheet already tuned by hand wants. In the spec format it is the
top-level `auto_faces` key.

Ties are common, because a balloon is square and stepping a signal round to the
next face trades exactly as much horizontal run for vertical. They break towards the
face pointing most directly at the peer, then on the symbol's own order of
preference.

### `nozzle`

```text
unit.nozzle(port_name: str, face: str) -> Unit
```

Pipes a port from a named face of the unit **as drawn**, overriding whatever the
engine would have picked. `face` is the compass point on the finished sheet:
`"N"`, `"S"`, `"E"`, `"W"`, or the `top`/`bottom`/`left`/`right` spelling
`label_pos` uses. A mirrored or rotated unit therefore takes the face the reader
sees, not the one the stencil was drawn with. Raises `KeyError` for an unknown port and
`ValueError` when the symbol offers no placement on that face.

The face must be reachable under the placement the unit ends up with, and either
call order enforces that. A `pin()` that rotates or mirrors the unit re-checks
any face already chosen and raises without changing the placement, and a
`nozzle()` after a `pin()` is checked against that pin, not against whatever a
previous `layout()` resolved.

A port can only take a face the symbol has authored a coordinate for, so the
moved nozzle still lands on drawn ink. Everything else has one placement, fixed
by physics: a column's bottoms, a drum's liquid draw-off. The ports that offer a
choice are listed below, named on the **untransformed** symbol. Rotation and
mirroring move them, and `nozzle()` always takes the moved face.

| Symbol | Port | Faces |
|---|---|---|
| `Vessel(variant="horizontal")` | `inlet` | `W` (home), `N`, `E` |
| `Separator(variant="horizontal")` | `feed` | `W` (home), `N`, `E` |
| `Instrument` (`default`, `shared`, `computer`, and any `display`) | `pv`, `sig_in`, `sig_out` | `N`, `S`, `E`, `W` |

(The trip squares, `Instrument(variant="sis")`, `"logic"` and `"interlock"`,
offer no choice either.)
The home is the symbol's own nozzle. It is where the port sits with
`auto_faces` off, and the first entry of the menu the engine chooses from with
it on.

```python
# Both of these are conventions the geometry alone would not arrive at: the
# engine takes the shortest run, and a shortest run is not always the drawing.
drum = fs.add(units.Separator("V-1", variant="horizontal"))
drum.nozzle("feed", "N")      # always from above, however the header is laid in

lic = fs.add_instrument("LIC", 101, near=lt, at="S", display="central")
lic.nozzle("sig_out", "W")    # keep the loop's output on the panel side
```

`face` is always the compass point **on the finished sheet**, so a unit pinned
`mirrored="x"` takes the face the reader sees rather than the one the stencil
was drawn with. A port can only take a face its symbol authored a coordinate
for, so the moved nozzle still lands on drawn ink; one fixed by physics has a
single placement and raises. The choice is re-checked against any later `pin()`.

---

## Streams

`connect()` returns a `Stream`. Useful members:

| Member | Type | Notes |
|---|---|---|
| `name` | `str` | the stream number, or the line number where the line has one; auto-assigned unless you passed `name=` |
| `source` / `dest` | `Port` | |
| `kind` | `str` | see `connect()` |
| `size` / `schedule` / `service` / `sequence` / `spec` / `insulation` | `str \| float \| None` | line-number components; `sequence` is filled by auto-numbering |
| `has_line_number` | `bool` | **read-only**, true once a component other than `sequence` is set |
| `at_boundary` | `bool` | **read-only**, true when one end of this segment is a `Feed` or a `Product` — an ingoing or outgoing material |
| `is_recycle` | `bool` | **read-only**, computed by cycle detection during layout |
| `properties` | `dict[str, str \| float]` | free-form; rendered by the stream table verbatim |
| `color` | `str \| None` | SVG stroke colour override: a name, `#0a7`, or `rgb(0, 170, 119)`. Anything else raises |
| `dasharray` | `str \| None` | SVG `stroke-dasharray` override: lengths in drawing units (`"7,4"`), or `"none"`. Anything else raises |
| `ends` | `str \| tuple[str, str] \| None` | how this line's joints are made up, overriding the sheet's `connections`. One name for both ends or a `(source, dest)` pair; `None` inherits |
| `route` | `Route \| None` | resolved waypoints; written by the router |

```text
via(waypoints: list[tuple[float, float]]) -> Stream
```
Forces the stream through those exact orthogonal pixel waypoints, overriding the
auto-router for that one stream. Chains off `connect()`:

```python
fs.connect(feed.outlet, hx.tube_in).via([(130, 65), (130, 110)])
```

### Stream numbering

Numbering settles inside `connect()` and again inside `to_svg()`, so the number
on the stream object you hold is the number the sheet gets drawn with, and
`s.name` can go straight into a report. `connect()` names the one line it just
added rather than re-deriving the whole sheet — the result is the same, and
`renumber_streams()` re-derives all of it whenever you want it to. A stream keeps its
number as it passes through an inline valve, reducer or fitting. Set
`unit.new_line_number = True` to break the number at a unit that matters, which
renumbers the flowsheet there and then. Explicitly named streams are never
renumbered, and an explicit name on one segment names its whole group.

Process streams take the low numbers, energy streams (also drawn) follow, and
unlabelled signal lines come last. One sequence covers all three, so a counted
name is never handed out twice and an energy or signal line never consumes a
process number.

A named run takes a place in that sequence rather than skipping one, so the
fourth run you draw is the fourth number whether or not the three before it were
named by hand. Without that the counter walked over the names already in use:
on a `stream_number_start=100` sheet, `connect(..., name="S100")` followed by a
plain `connect()` numbered the second stream `S100` too.

Naming two runs the same yourself stays legal — a stream drawn in several
`connect()` calls is one stream and is meant to carry one label, which is how
`examples/10_ethanol_pfd.py` draws `S-305` over five of them. What you cannot
do is have auto-numbering choose a name that is already taken, and `validate()`
reports that as [`stream-name-reused`](#validation): the stream table is one
column per distinct name, so two runs sharing one are tabulated as one and a
column of properties goes missing.

### Line numbers

A P&ID identifies a line by its full line number of size, service, sequence and
spec, because that is the identifier the line list, the stress calculation and
the isometric all key on. Supply the components on `connect()` and the line is
named that way instead of `S1`:

```python
s = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
s.name        # '6"-P-1001-A1A'  drawn on the line, and heads its table column
s.sequence    # '1001'           filled by auto-numbering
```

The components are `size`, `schedule`, `service`, `sequence`, `spec` and
`insulation`, each text or a number:

| Component | What it says |
|---|---|
| `size` | the line's nominal bore, as the site writes it (`'6"'`, `200`) |
| `schedule` | the wall the line is bought to at that bore: `160`, `40`, or the older `STD` / `XS` / `XXS` |
| `service` | what the line carries, as a service code (`P`, `FB`, `CWS`) |
| `sequence` | the number that makes the line unique within the unit |
| `spec` | the piping class or material the line is built to (`A1A`, `SS`) |
| `insulation` | the insulation code, where the site puts one in the number |

`size` and `schedule` are two facts about the pipe and get two fields: the bore
does not imply the wall, and writing them into one field puts a second number
next to the size that reads like a second size. `spec` is neither of those. It
is what the line is made of and to what class, which is why a sheet can quote a
schedule and a material (`…-200-160-SS`) or leave the wall to the class and
quote only that (`…-6"-P-1001-A1A`).

The author supplies all but `sequence`, which auto-numbering fills from
`line_number_start` (default `1001`); set it yourself to tie into a line that
already exists on someone else's list. A component left unset drops out, and so
does the text introducing it, so a line with no spec issued yet reads
`6"-P-1001` rather than `6"-P-1001-`. `line_number_start` moves this component
only; the number a stream with no line number is drawn with is moved by
[`stream_number_start`](#flowsheet).

The list is deliberately fixed. A component the engine cannot name is a
component the line list cannot be checked against, and a site wanting a fact of
its own has the callable scheme below. The trigger to add a seventh is a second
real sheet needing one, which is what `schedule` itself came from: see issue
\#118.

A line number is assigned by `renumber_streams()`, on exactly the terms a stream
number is: it carries **through** an inline valve, reducer or fitting, and
breaks at a unit marked `new_line_number`, which is where the spec break goes. The
first segment of a group that carries components supplies them for the whole
group, so a run does not have to repeat its identity at every fitting. A stream
named explicitly with `connect(name=…)` is never reformatted, and a stream with
no components set is numbered exactly as it always was.

`line_numbering_scheme` spells the convention, as a format string over the
component names or as a callable taking the `Stream`. A format spec applies, so
a site that pads its sequence says so:

```python
Flowsheet("U100", line_numbering_scheme="{size}-{service}-{sequence:0>6}-{spec}-{insulation}")
Flowsheet("A300", line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}")
Flowsheet("U100", line_numbering_scheme=lambda s: f"{s.service}-{s.size}-{s.sequence}")
```

The default is `"{size}-{service}-{sequence}-{spec}"` and names neither
`{schedule}` nor `{insulation}`, because most sheets leave the wall to the
piping class and carry no insulation code: a site that quotes either says so in
a scheme of its own. Example 11 is the second form, which is how the issued
sheet it reproduces spells `FB-301-200-160-SS`.

A scheme naming something that is not a component raises `ValueError`, as does a
line whose components the scheme never uses, since its line number would be
empty.

With `show_stream_table=True` each column is headed by its line number, and the
corner cell reads `Line Number` when every line in the table has one.

### Where the number sits on the line

A stream number or a line number is drawn once, on the longest straight run of
the line it names, parallel to that run. It sits **on** the line, on an opaque
wipe, only where the run is long enough to leave pipe showing past the wipe at
each end; otherwise it steps **beside** the line, offset perpendicular, above a
horizontal run and to the left of a vertical one. A line number is a dozen
characters wide and most runs are not, so beside is the usual answer for one.

Beside is also what **ISO 15519-1 §7.2.5** asks for: a connection's reference
designation *should* go above a horizontal connecting line and to the left of a
vertical one, and *shall* be oriented along or beside the line it belongs to.
On the line is a
divergence from that preference, but §7.2.5 words it as a `should`, and it buys
back the sheet room that a dozen-character number costs.

That clause reaches a line number only if the line number is read as the
connection's reference designation. A `pandid` line number is a line-list
identifier, not the IEC 81346 designation §7.2 is written around, so this is a
reading rather than a claim of conformance. It is a sound one: §7.3.4 turns off
the boundary-frame principle for any diagram whose connections carry reference
designations, which is a P&ID with line numbers on it.

On a vertical run the label is turned so it reads bottom to top and never upside
down. §5.1.5 allows exactly that: text runs horizontally or vertically, read
either from the bottom edge of the document or from its right-hand edge. Its
next sentence, which keeps a reference designation horizontal whatever way its
symbol is turned, does not reach a line number. It is a rule about a symbol's own
designation, which is why it is qualified by symbol orientation, and a pipe run
has none; connections are §7.2.5's subject, and that clause asks for orientation
*along* the line. ISO 15519-1 draws it both ways in one figure: Figure 40 boxes
its symbol designations horizontally and turns the annotation on every vertical
connecting line to read bottom to top, to the left of the line.

Two other standards state a rule for text that is not this one. ISO 129-1 §4.1.1
says the same thing as §5.1.5 for the text of a dimension, but its scope is
dimensions and tolerances and a P&ID has none. ASME Y14.5 uses the opposite,
unidirectional convention.

Wherever it lands, a number is slid along its own run until it clears the
equipment, tags, balloons and other numbers already on the sheet.

### Stream properties and the table

`Stream.properties` is a plain dict you fill in. **Nothing computes it**, as
there is no balance engine. Values are drawn as given, so they carry their own
units. Rows appear in first-seen key order, and missing values render as `-`.

```python
s.properties = {"Temperature": "120 C", "Pressure": "3.5 bara", "Flow": "1000 kg/h"}
fs.stream_table_sections = [("Benzene", "Mass Fraction")]   # header row before "Benzene"
fs.render("sheet.svg", border="zone", show_stream_table=True)
```

#### Which streams get a column

A stream that states no property at all is left out. An empty column is a
heading over a rule of dashes, and ISO 10628-1:2014 §4.3.3 a) leaves the flows
between the process steps optional anyway. If nothing on the sheet states a
property there is no table to draw.

**A feed or a product keeps its column** even with nothing in it, because
§4.3.2 d) makes the flow rates or quantities of ingoing and outgoing materials
something a process flow diagram *shall* contain: dropping the column would hide
the omission rather than show it. `validate()` reports it as
[`boundary-flow-missing`](#validation), on a sheet that tabulates its other
streams.

A value present and blank keeps the column. `{"H2S": ""}` is you saying this
stream has none to report, and it draws the same `-` a missing key does — the
difference is that the column stays:

```python
s.properties = {"Flow (kg/h)": ""}   # nothing to report, and the column says so
```

Every column is ruled wide enough for everything drawn in it: the row labels,
the stream number or line number heading the column, the values under it, and
any section header spanning the table. The table's width is an output of the
layout rather than a fixed budget, so a long row label or a value carrying its
units widens the table rather than running into the cell beside it. On a fixed
`page_size` that can make the table the thing that will not fit, which raises
and says so.

---

## Instrumentation

```text
fs.add_instrument(type, number="", *, sensing=None, acting_on=None, near=None,
                  at=None, offset=45.0, angle=90.0, variant="default",
                  display=None, **kwargs) -> Instrument
```

Constructs an `Instrument`, adds it, and anchors it to whatever `sensing`,
`acting_on` or `near` named. Extra `**kwargs` go to the `Instrument`
constructor (`width`, `height`, `label_pos`, `description`).

`type` is the functional letter string and `number` the loop number.
`instrument.tag` is the full tag (`"FT-101"`) for equipment lists and
cross-references, while the balloon draws the letters over the **bare** number,
as a real sheet does. `units.Instrument("FT-101")` is also accepted and split.
`unit.name` is the same tag, except on a repeated interlock square where it is
what tells one square from another (see
[Building the topology](#building-the-topology)).

```python
ft  = fs.add_instrument("FT", 101)                        # field transmitter
fic = fs.add_instrument("FIC", 101, display="central")    # control-room controller
fy  = fs.add_instrument("FY", 101, variant="computer")    # computing relay
```

#### Where the information is

`display` is ISO 15519-2 **Table 1**'s additional graphic, a horizontal bar
across the symbol, and its three values are that table's three rows:

| `display` | drawn | Table 1 |
|---|---|---|
| `"field"` (default) | no bar | reading at a field-mounted instrument or display |
| `"central"` | one bar | reading in the central control system |
| `"subsidiary"` | two bars | reading in a subsidiary control system |

It is a separate question from `variant`, which is what the instrument *does*.
**§5.1.1**, same page: where the information is available, or where it comes
from, is shown by an additional graphic inside the PCI symbol, tabulated at
Table 1.

Not every pair has a drawing registered. `variant="shared"` is the only shape
carrying a bar today and it carries `"central"` without being asked, a shared
display being the control room by definition; a shape and a display with no
artwork between them raises and names the pairs that are drawn.

`variant="panel"` and `variant="aux"` were this axis wearing `variant`'s name.
They were removed in 0.1.3 and raise; write `display="central"` and
`display="subsidiary"`, which draw the same two symbols.

### Control loops

```text
fs.add_loop(variable: str, number: str | int | None = None) -> Loop
loop.element(letters: str) -> str   # a primary element: checks the first letter
loop.tag(letters: str) -> str       # a final control element: does not
loop.variable   # the measured-variable letter, upper-cased
loop.number     # the loop number, as text
loop.name       # "F-303", the loop's identity as a string
fs.loops        # list[Loop], in declaration order
```

Declares a control loop and returns the handle its members are tagged from, so
the number is typed once. `number` on `add_instrument` accepts the handle in
place of a literal.

```python
loop = fs.add_loop("F", 303)
fe  = fs.add(units.Fitting(loop.element("FE"), variant="venturi"))
feb = fs.add_balloon(fe, at="N", offset=38)
ft  = fs.add_instrument("FT",  loop, near=feb, at="N", offset=23)
fic = fs.add_instrument("FIC", loop, near=ft, at="E", offset=70, variant="shared")
cv  = fs.add(units.Valve(loop.tag("CV"), variant="control"))
fs.connect(ft.sig_out, fic.sig_in, kind="electric")
fs.connect(fic.sig_out, cv.actuator, kind="pneumatic")
```

That is loop 303 of
[`examples/11_ethanol_pid.py`](../examples/11_ethanol_pid.py), which declares
six loops and leaves ten balloons on literal numbers.

- **A loop is `(variable, number)`.** `add_loop("F", 101)` and
  `add_loop("L", 101)` are two loops on one sheet. Declaring the same pair twice
  raises; `variable` must be a single letter and `number` must be non-empty.
- **The loop replaces the number, not the letters.** Each balloon types its own
  functional letters and `add_instrument` checks the first of them against the
  loop, raising `ValueError` at that line: `add_instrument("TT", loop)` on an F
  loop names the loop's variable and what was passed. The redundancy is what
  makes the check possible at all.
- **A member that is not a balloon joins by naming what it is.** Both methods
  return a tag string, so a `Fitting`, a `Valve` or any other class joins on the
  same terms, and which of the two you call is which piece of equipment you have
  in hand.
  - **`loop.element(letters)`** is the **primary element** — the orifice plate,
    the venturi, the coriolis meter. It is lettered from the measured variable
    exactly as a balloon is, so it gets the same check: `element("TE")` on an F
    loop raises and names `FE`.
  - **`loop.tag(letters)`** is the **final control element**, and composes
    without a check because there is nothing to check. A sheet spells every
    control valve `CV-` whatever it strokes, so the letters do not track the
    loop. The number does, which is the half `tag()` supplies — CHEE4001 p.13
    assigns one number to the whole group of components a control scheme needs,
    and the valve is in the group.

  The distinction is in the two names and not in a `check=` flag on one of them,
  because it is a distinction between two pieces of equipment rather than
  between two strictnesses — and because a flag would have to default one way
  for both, leaving the safe call the one you had to remember to write.
- **A loop is a namespace, not a unit.** It has no frame and no ports, is never
  in `fs.units`, draws nothing and reaches no equipment list.
- **A loop number is allocated once and never renumbered**, unlike a stream
  number, which `renumber_streams()` re-derives on every `connect()`. A loop
  number leaves the drawing for a DCS database and a valve nameplate.
- **The loop-less form is unchanged.** `add_instrument("TI", 325)` and
  `add_instrument("I", 1, variant="logic")` take a literal number and always
  will: an indicator that is nobody's loop and a repeatable logic function with
  no measured variable have no loop to belong to.

Loops serialize to an optional `loops:` section of the spec and round-trip
through it; a sheet that declares none writes no section, so its spec is
unchanged. See [Declaring a flowsheet as data](#declaring-a-flowsheet-as-data).

#### Automatic loop numbers

Leave the number out and the sheet allocates the next one, counting from
`loop_number_start` (default `101`). On a draft, where the numbers and the count
of loops are both still moving, that is one thing fewer to retype each time a
loop is inserted. A loop series belongs to a plant area, so set the start to the
area this sheet draws; the default is a plausible unit-100 series to draw with
until you do.

```python
fs = Flowsheet("Ethanol Purification A300", loop_number_start=301)
press = fs.add_loop("P")        # P-301
temp  = fs.add_loop("T")        # T-302
flow  = fs.add_loop("F")        # F-303
```

- **One series for the sheet**, not one per measured variable: the numbers climb
  through whichever variable comes next, which is what `P&ID_301` draws —
  `P-301`, `T-302`, `F-303`, `L-304`, `F-305`, `L-306`, `T-307`, `F-308`. A loop
  is still the `(variable, number)` pair, so `add_loop("F", 101)` beside
  `add_loop("L", 101)` remains two loops.
- **Allocated at the `add_loop()` line**, so the numbers run down the page in the
  order the page declares them. A loop declared and never tagged still spends
  its number; a declaration that raises spends nothing.
- **Allocated and typed numbers mix.** A typed number reserves nothing and the
  counter skips nothing, so a sheet that types `F-316` and then allocates takes
  the series' next number, not 317. Should the counter reach a number already
  typed for the same variable, `add_loop()` raises at that line and names
  `loop_number_start` as the way clear.
- **A loop of one member is a legitimate use.** CHEE4001 p.13 assigns one number
  to the whole group of components that between them do the monitoring or
  control a scheme is for, and a group of one is a group — which is what the
  tail of `P&ID_301` is: `FE-313`, `PI-316`, `TI-319`, `LI-322`.
- **`to_dict()` freezes the sheet.** Every loop's number is written out as a
  literal, allocated or typed, so reading the spec back gives the numbers nailed
  down. Auto-numbering is the draft; the spec is the issue.

### Valve stations

```text
fs.add_valve_station(
    tag, *, x=None, y=None, mirrored=False, variant="control", number=None,
    isolation=True, reducers=True, bypass=True, drains=2,
    description="", bypass_over=None, tag_scheme=None,
    gap=30.0, bypass_rise=45.0, drain_drop=36.0,
    size=None, schedule=None, service=None, sequence=None, spec=None,
    insulation=None,
) -> ValveStation
```

Builds the assembly a control valve is installed in: two isolation valves, two
drain valves, one bypass valve on a leg tapped **outside** the isolations, and a
size change at each end. Along the run:

> bypass takeoff · isolation · drain tee · **reduction** · **control valve** ·
> **expansion** · drain tee · isolation · bypass rejoin

That is the arrangement the CHEE4001/7103 P&ID guidelines prescribe in words and
draw in their *EXAMPLE of a control valve system* figure. Twelve units and
twelve streams for one call.

```python
station = fs.add_valve_station("CV-303", x=670, y=440, mirrored=True,
                               description="Reflux", bypass_over="reduction",
                               service="AE", sequence=303, size=80,
                               schedule=80, spec="SS")
fs.connect(t_draw.branch, station.inlet, service="AE", sequence=303,
           size=80, schedule=80, spec="SS")
fs.connect(station.outlet, fe303.inlet)
fs.connect(fic303.sig_out, station.control.actuator, kind="pneumatic")
```

**What comes back.** A `ValveStation`: a frozen handle, **not** a unit. It has
no symbol, no ports of its own and no tag, is never in `fs.units`, and reaches
no equipment list. Its members are ordinary units already on the flowsheet and
already connected, so any of them can be re-pinned, re-tagged or instrumented.

| Member | What it is |
|---|---|
| `control` | the control valve, carrying `tag` |
| `upstream_isolation`, `downstream_isolation` | the two hand valves |
| `reduction`, `expansion` | the size change in and back out |
| `bypass` | the normally closed throttling valve on the leg |
| `upstream_drain`, `downstream_drain` | the normally closed drains |
| `tees` | the four junctions, in run order; each carries no tag |
| `members` | every member, in the order the run meets it |
| `inlet`, `outlet` | the `Port`s the piping either side connects to |

A member left out is `None`. Nothing of the station itself is serialized,
because after the call there is nothing left of it the drawing depends on:
`to_dict()` writes the members out and reading them back gives the same sheet.

**Tags.** `valve_station_tag_scheme` on the `Flowsheet`, or `tag_scheme` for one
station, spells the members out of the control valve's tag. The default
`"{letters}-{number}{suffix}"` gives, from `CV-303`:

| Role | `{letters}` | `{suffix}` | Default tag |
|---|---|---|---|
| `upstream_isolation` | `HV` | `A` | `HV-303A` |
| `downstream_isolation` | `HV` | `B` | `HV-303B` |
| `bypass` | `HV` | `C` | `HV-303C` |
| `upstream_drain` | `HV` | `D` | `HV-303D` |
| `downstream_drain` | `HV` | `E` | `HV-303E` |
| `reduction` | `RD` | `A` | `RD-303A` |
| `expansion` | `RD` | `B` | `RD-303B` |

`{role}` and `{control}` are available too, and a callable
`(role, control_tag) -> str` says anything a format string cannot. This is a
convention, not a rule: the guidelines are explicit that tagging *"depends on
the practice of the particular design office"*, and the issued reference sheet
tags none of these valves at all. `number=` overrides the number the scheme
fills in, for a control valve whose own tag carries a suffix its hand valves do
not (`add_valve_station("CV-301-1", number=301)` → `HV-301A`).

**Placement.** With `x` and `y` the station pins its own members: `x` is the
left edge of the drawn assembly and `y` is the run's **centreline**, so each
device lands on the line whatever its artwork measures. `mirrored=True` pipes
the run east to west, the same run drawn the other way round, still occupying
`x` rightwards. `gap`, `bypass_rise` and `drain_drop` are the spacing along the
run, the height of the bypass leg and the depth of a drain leg. `bypass_over`
stands the bypass valve over a named member instead of in the middle of its own
leg, which is what a station wants when a controller's output crosses the leg on
its way down to the actuator. Give `x` and `y` together or not at all; without
them the members lay out like any other unit.

**Line numbers.** The run through the station takes the number of whatever is
connected to `inlet`, carried through the valves, reducers and tees as any
inline device carries it. A branch off a tee starts a number of its own, so the
`size`/`schedule`/`service`/`sequence`/`spec`/`insulation` given here are what
the bypass and the two drains take, since a bypass is the same service, size and
spec as the run it goes round.

**Refusals.** A bypass with `isolation=False` raises: a bypass exists so the
unit keeps running while the control valve is isolated, and there is nothing to
isolate it with. So does a `drains` that is not 0, 1 or 2, one of `x`/`y`
without the other, and a `bypass_over` naming a member the station was told to
leave out.

### Anchoring a balloon

```text
fs.add_instrument(type, number, *, sensing=…, acting_on=…, near=…, at=…, offset=…)
instrument.attach(on, *, at=None, offset=45.0, angle=90.0, relation="sensing")
```

**Three keywords name the anchor, and they say different things.** Each takes a
`Stream` (tap the line) or a `Unit` (stand against equipment) and places the
balloon there; what they differ on is whether the sheet draws a line between the
two.

| keyword | means | drawn between them |
|---|---|---|
| `sensing=` | the balloon takes its reading from this | an impulse line, or a fine dashed instrument connection |
| `acting_on=` | the balloon commands this | a fine dashed instrument connection |
| `near=` | the balloon only *sits* here | **nothing** |

`near=` is what a control-room faceplate hung over the valve it drives wants: it
buys the position and says nothing else, and what reaches the actuator is a
signal, stated with [`connect()`](#signal-lines) and routed like one. Naming two
of the three raises, since a balloon is anchored to one thing and a second
relationship is a second line.

```python
lt  = fs.add_instrument("LT",  101, sensing=drum, at="S", offset=70)
lic = fs.add_instrument("LIC", 101, near=lt, at="S", offset=95, display="central")
fs.connect(lt.sig_out, lic.sig_in, kind="electric")
fs.connect(lic.sig_out, lv.actuator, kind="pneumatic")
fs.add_instrument("Z", 1, acting_on=xv, at="S", offset=46, variant="sis")
```

`on=` was all three at once — it bought a position and drew an edge nobody asked
for. It was removed in 0.1.3; it meant `sensing=`.

- The host is a `Stream` or a `Unit`. Anything else raises `TypeError`, and
  anchoring a balloon to itself raises `ValueError`.
- `at` is, on a stream, a fraction `0..1` along the host's **routed** path
  (default `0.5`); on a unit, a face `"N"`/`"S"`/`"E"`/`"W"` of its drawn box
  (default `"E"`). Out-of-range or wrong-typed values raise `ValueError`.
- `offset` is the distance from the tap to the balloon centre (default `45.0`).
  `offset=0` leaves an in-line primary element sitting *on* the line, which is
  how an orifice-plate FE is drawn. Negative raises.
- `angle` is the branch direction in degrees from the flow direction at the tap,
  counter-clockwise positive (default `90`, i.e. perpendicular). Measured from
  the flow, so a re-route cannot spin the tap. On a unit host the reference is
  the face's tangent, so `90` again points straight out.

A fine line is drawn from the tap to the balloon, and whether it is solid or
dashed is a statement about **that line**, asked of both its ends rather than of
the host alone. Solid says an impulse line, which is a piece of pipe: a length
of tubing between the process and the element, with the fluid the reading is
taken from inside it. That needs process fluid at one end and a device out in
the plant at the other, so it is drawn solid only where

- the host carries fluid — a process line, a vessel, an exchanger, an in-line
  element — rather than a measurement, which is what a balloon and a signal line
  carry; **and**
- the balloon is ISA-5.1's field-mounted one, the bare circle with no bar. Every
  other balloon is a location or function symbol saying the function is in the
  control room (`display="central"`, `"subsidiary"`), in the shared display
  (`variant="shared"`), in a computer (`"computer"`) or in a logic solver
  (`"sis"`/`"logic"`/`"interlock"`), and no tubing runs from a drum to any of
  those; **and**
- the relation is `sensing`. Tubing brings the fluid **to** the instrument, so a
  square `acting_on` the valve it strokes is not one however the other two
  answer: what runs down to the actuator is a command.

Everything else is **dashed**: a balloon hung off another balloon, a balloon teed
off a **signal line** — which is how a trip is drawn, not on a face of the
balloon it acts for but branched at a right angle off the line carrying the
command — and a trip square hung on the valve it strokes.

```python
trip = fs.connect(lic.sig_out, lv.actuator, kind="electric")
fs.add_instrument("I", 1, sensing=trip, at=0.25, offset=44, angle=-90, variant="logic")
```

Hanging the square on an alarm instead would draw the alarm as driving it, and an
alarm that acts is lettered `S` or `Z` rather than `A`. **ISO 15519-2 Table 2**
note 9 keeps `A` for an alarm function that stands on its own: where an `S` or a
`Z` raises an alarm as it acts, the `A` is not added in front of it. **§7.2.4**
is the same rule seen from the line: signal lines carrying different kinds of
control function are not joined.

Attached
balloons take no part in layout ranking and are drawn over the lines, so neither
an in-line element nor a stream number is lost underneath one. Balloons chain,
so an alarm on a controller on a transmitter resolves in order.

```python
s   = fs.connect(feed.outlet, fv.inlet)
ft  = fs.add_instrument("FT", 101, sensing=s, at=0.4, offset=60)        # above the tap
lic = fs.add_instrument("LIC", 101, near=ft, at="S", display="central") # under it
lic.annotate(high="LAH", low="LAL")                                     # the alarms
fs.add_instrument("I", 1, near=lic, at="S", offset=44, variant="logic") # interlock
```

### Letter codes outside the symbol

```text
instrument.annotate(*, safety=(), variable=(), high=(), low=()) -> Instrument
```

An alarm is a **function of a controller**, not a second instrument, so it is
written beside that controller's balloon and no line is drawn to it.
**ISO 15519-2 §5.2.5** (p. 22) puts any letter code carrying the modifiers H or
L outside the PCI symbol, and *shall* order the codes A, then S, then Z, with
the value each stands for rising as they go away from the symbol's centre line.

```python
lic304.annotate(high="LAH", low="LAL")
lsh611.annotate(high=("LAHH", "LSHH"))
ai301.annotate(variable="pH", safety="SIL 2")
```

The four arguments are **§5.1.3**'s four quadrants (p. 19) in its own order:

| argument | quadrant | §5.1.3 |
|---|---|---|
| `safety` | upper left | a reference to a typical diagram, or safety information such as a SIL or SIF identifier |
| `variable` | lower left | which variable is meant where the tag uses letter code U for multivariable: pH, µS, MJ/s |
| `high` | upper right | a high output or input function, an alarm or a switching action say |
| `low` | lower right | the same for a low one |

The quadrants are the **corners**, which is the clause's own reason for them:
keeping the four faces clear is what lets the symbol be connected horizontally
and vertically. So
annotating a balloon spends none of its four faces, and a connection arriving on
the centre line runs between a `high` code and the `low` one beneath it, as the
reference sheet draws it.

Each argument takes one code or several. Several in one quadrant come out
ordered A, then S, then Z outward whatever order they were given in, since the
standard fixes the sequence and there is no choice to express. Chainable, and an
argument left out is a quadrant left alone, so a second call replaces only what
it names; `high=()` empties one, which is a different request from not
mentioning it.

Codes are placed hard against the symbol and stepped **outward** if that is not
clear paper, scored against the sheet's lines and symbols the way an equipment
tag is; the quadrant itself never moves, being what the code means. The
equipment-tag and line-number passes are told where they landed, so nothing is
written across one.

### A primary element's balloon

```text
fs.add_balloon(element, *, at=None, offset=46.0, angle=90.0, **kwargs) -> Instrument
```

A primary element is **one instrument shown as two marks**: the thing in the
pipe, and the balloon carrying its tag. CHEE4001 p.10 is what makes it one
instrument — it defines the primary element, letter `E`, as the instrument that
measures the process variable, an orifice plate or a thermocouple say — and a
P&ID draws it with the fitting
**unlettered** and the tag in a balloon on a short impulse line.

```python
fe303 = fs.add(units.Fitting(flow303.element("FE"), variant="venturi"))
fs.add_balloon(fe303, at="N", offset=38)
ft303 = fs.add_instrument("FT", flow303, near=fe303.balloon, at="N", offset=23)
```

The tag is typed once, on the element, and moves: `element.tag` goes empty,
`element.balloon` is the balloon, and the sheet draws `FE-303` exactly once.
Both objects answer to it, which is why the pair joins the sheet's
[one thing, several marks](#building-the-topology) exemption instead of one of
them needing a second tag invented for it. The element keeps the plain name,
being what an equipment list schedules; the balloon is named `FE-303 (2)`, as a
repeated trip square is.

The relation is `sensing`, so a solid impulse line is drawn from the element to
the balloon. `offset` is measured from the element's face; the default is the
reference sheet's, whose FE balloon centre stands 1,05 balloon diameters off the
process line. A second balloon on one element raises, as does one on something
that draws no tag.

### Signal lines

```python
fs.connect(ft.sig_out, fic.sig_in, kind="electric")     # dashed
fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")  # slash ticks
```

`electric`, `pneumatic`, `data`/`software` and `capillary` each get their own
line style. Signal lines carry no arrowheads and no stream numbers, and are
excluded from the stream table. Both ends have to be signal connections, so a
signal kind between two process nozzles raises rather than drawing a control
line down a pipe run.

**They are also drawn at half the weight of a process line**, which is the cue a
reader separates the process from the instrumentation by before reading a single
dash pattern. **ISO 15519-1 §6.2**: where a drawing uses two or more line
widths, any two of them have to stand at least 2:1 apart. Its Table 1 puts
process-industry connections at 0,2 M and symbols at 0,1 M, and with M = 2,5 mm
(§11.1.2) that is the 0,5 / 0,25 mm pair. **ISO 15519-2 Annex A.1** spends the
pair per line type: A.1.01 pipeline **0,50**; A.1.02 instrument connection and
control connection **0,25**; A.1.03 pilot line and signal line **0,25**.

Which side of the pair a line falls on:

| Weight | Drawn |
|---|---|
| heavy (2 units, 0,53 mm on A3 at 1:1) | process streams (`material`, `energy`), equipment and symbol outlines, off-page connector flags |
| fine (1 unit, 0,26 mm) | every signal kind, the pneumatic cross-hatch marks on one, and instrument tap / impulse lines |

`energy` is a process kind and stays heavy: it is a physical conduit, and the
fine class in both Annex A entries is explicitly instrument, control and pilot.
The pneumatic cross-hatch is drawn at the weight of the line it marks rather
than heavier, since a supplementary symbol on a connection is a graphical symbol
and ISO 15519-1 §11.1.3 puts one at 0,1 M.

These are relative weights inside one drawing. They still scale with the sheet,
so a drawing that has been fitted down carries both of them down together; the
ratio holds, the millimetres do not. Holding a stroke at a physical width is
ISO 15519-1 §11.1.3's separate and larger problem, and `pandid` does not do it.

### Several signal lines on one balloon

`sig_in` and `sig_out` are **pools**. A second line off one is another
connection, not an error: the balloon mints `sig_out_2`, and the face selector
puts it wherever the new peer is.

```python
# split range: one controller, two valves
fs.connect(pic.sig_out, cv1.actuator, kind="pneumatic")
fs.connect(pic.sig_out, cv2.actuator, kind="pneumatic")

pic.sig_out.stream.dest.owner        # CV-301-1 -- the first line, unchanged
pic.port("sig_out_2")                # the second
```

A balloon is a circle, so every connection offers all four faces and a minted
one is drawn on the same nozzles as the pool's first member. Two live
connections never share a point; the selector will not put one on a placement
already spoken for.

- **`pv` is one tap.** An instrument taps one process point, so a second line to
  it raises. (A differential instrument tapping two points wants a second
  *named* tap; that is not this.)
- **`Valve.actuator` is one stem.** Split range is one actuator per valve with
  the controller holding two outputs.
- **`signal_port(name)`** reaches a member the balloon has not grown yet, which
  is how a spec names one and how a face is set on one in advance.
- **Four is the ceiling.** A balloon has four faces, so a fifth connection lands
  on a placement already taken and `validate()` reports `coincident-ports` as an
  error. That is the point to draw a trunk with stubs instead.

---

## Sheet furniture

Everything here lives in `pandid.document`. A title block or a box on the flowsheet
is drawn because it is there, whatever `border` is set to.

### `TitleBlock` and `Revision`

```python
from pandid.document import TitleBlock, Revision

fs.title_block = TitleBlock(
    title="Aromatics Recovery A100",      # the two title lines
    subtitle="Process Flow Diagram 1",
    drawing_number="PFD-1001",
    client="Aromatics Australia Pty Ltd",     # above the title; not an ISO field
    project="Aromatics Recovery Unit",
    company="PANDID",   # logo / company cell
    status="ISSUED FOR REVIEW",               # issue-status cell
    sheet="1", of_sheets="3", scale="NTS",
    drawn_by="A. Anderson", checked_by="J. Smith", approved_by="R. Lee",
    date="",                                  # blank fills in with today's date
    revisions=[
        Revision("B", "2026-07-01", "Issued for design", "AA", "JS", "RL"),
        Revision("C", "2026-07-12", "Added recycle loop", "AA", "JS", "RL"),
    ],
)
```

In `Revision(rev, date, description, by, checked, approved)` the last two are
optional per row and stay blank when omitted. The block-level
`drawn_by`/`checked_by`/`approved_by` backfill the newest row. Leaving
`TitleBlock.date` empty makes the renderer stamp the current date, so a
committed drawing changes day to day. Set it explicitly if you need reproducible
output.

`client` and `project` each rule a row above the title when they carry a value,
and none when they do not. Neither is a title-block field of any standard.
ISO 5457 specifies no data fields at all and defers them to ISO 7200, whose
mandatory "legal owner" is the organisation issuing the drawing, which is
`company`. The block carries seven of ISO 7200's eight mandatory fields:
`drawing_number`, `date`, `sheet`, `title`, `approved_by`, `drawn_by` and
`company`. The eighth, document type, has no cell.

`scale` is the scale cell. Left blank it reports the ratio the drawing was
actually placed at, which is a real number as soon as `page_size` fixes the
page (`1:2.47`) and nothing at all on a sheet sized to fit its drawing, since
there is then no scale to state. Give it a value to state one regardless:

```python
fs.title_block = TitleBlock(title="Transfer and Relief U100", scale="NTS")
```

The strip is fixed geometry, so a value too long for its cell is trimmed with an
ellipsis rather than run across the rule into the cell beside it. The render
says which field it trimmed, on `fs.warnings`, naming the field and quoting the
value in full — `to_drawio()` as well as `to_svg()`, in the same words, since
both measure one strip with one set of cell widths:

```python
fs.title_block = TitleBlock(title="Ethanol Purification A300")
fs.to_svg(page_size="A3", border="zone")
for w in fs.warnings:
    print(w)
# [warning] text-truncated: title was truncated to fit its cell:
#     'Ethanol Purification A300' drawn as 'Ethanol Purification A3…'
```

A cell with nothing worth trimming is drawn in full and reported as
`text-overruns-cell` instead: the company name, whose only break points are
between words, and the `SHEET n of m` count, half of which reads as a different
sheet. Both codes are rebuilt on every render, so shortening the field and
rendering again clears the finding.

### `Annotation` and `TableBox`

```text
Annotation(title="", rows=[], align="top-right", position=None,
           margin=0.0, width=None, font_size=11.0)

TableBox(title="", headers=[], rows=[], align="bottom-right", position=None,
         margin=0.0, font_size=11.0, col_align=None)
```

`align` docks the box **flush to the sheet frame** on a nine-point grid:
`"top-left"`, `"top"`, `"top-right"`, `"left"`, `"center"`, `"right"`,
`"bottom-left"`, `"bottom"`, `"bottom-right"`. Anything else raises
`ValueError`. `margin` insets a docked box from the frame edge (default `0` =
flush). `position=(x, y)` instead pins the box's **top-left corner** at absolute
sheet coordinates and ignores `align`.

`Annotation.rows` entries are either a plain `str` (one left-aligned line) or a
tuple/list of cells that align into columns. `TableBox.col_align` is per-column
`"l"`/`"c"`/`"r"`, defaulting to centred.

### Convenience constructors

```text
from pandid.document import equipment_list, notes, legend

equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right",
               position=None, margin=0.0, include=None, width=None)
notes(items, *, title="NOTES", align="top-right", position=None,
      margin=0.0, numbered=True, width=None)
legend(entries, *, title="LEGEND", align="top-left",
       position=None, margin=0.0, width=None)
```

All three return an `Annotation`. `legend()` accepts a dict or a sequence of
`(abbr, meaning)` pairs.

`equipment_list()` schedules **major equipment** as `(tag, description)`:
vessels, columns, tanks, reactors, separators, exchangers, heaters, coolers,
furnaces, pumps, compressors, blowers, turbines, ejectors, filters, dryers and
conveyors.
Valves, fittings, reducers, tees, vents and funnels are bulk items bought by the
line and covered by the piping class; mixers and splitters are junctions in that
line; feeds, products and instruments are not equipment. None of them is
scheduled. Where a unit has no `description`, the row says what its kind is
called (`E-101` reads `Heat Exchanger`).

`include=[…]` names the rows explicitly instead, in the order given, and takes
whatever it names. That is how a valve schedule, a real drawing in its own
right, is built from the same flowsheet. A tag that is not on the flowsheet
raises `ValueError`, naming it and the nearest tag that is: naming a row asserts
it exists, and `include=["P-101", "P-1O2"]` used to draw a schedule one line
short and say nothing.

```python
from pandid.document import equipment_list, legend, notes

fs.add(units.Column("T-101", description="Beer Column"))
fs.add_annotation(equipment_list(fs, align="top-right"))
fs.add_annotation(equipment_list(fs, title="VALVE SCHEDULE", align="right",
                                 include=["FV-101", "PSV-101"]))
fs.add_annotation(notes(["Sampling point on every product line."], align="top"))
fs.add_annotation(legend({"SS": "Stainless Steel 316L"}, align="top-left"))
```

### Off-page connectors

A boundary flag's `reference` is drawn as its second line, naming the drawing
the stream comes from or goes to:

```python
fs.add(units.Feed("Fermentation Broth", reference="PFD-201"))
```

The flag is the only thing with a second line to draw it on, so `reference=` on
a pump or a column raises `ValueError` naming the boundary to put it on.

A flag is drawn wide enough for its label and its `reference`, and that drawn
box is the obstacle the router keeps clear: a long name makes a wide one, so a
line that misses the arrow by eye can still be reported `route-crosses-unit`.

#### Composing a location reference

**ISO 15519-1:2010 Clause 9** gives the grammar a reference to another drawing is
spelled in. Two signs, and a fixed order: the solidus marks the sheet and the
full stop marks the column, row or zone, and the parts are presented in one
sequence — document, then sheet, then column, row or zone.

A part left out narrows the *scope* of the reference rather than changing its
shape, which is what the standard's Table 2 tabulates.
`pandid.document.location_reference()` composes the string, and reproduces every
row of that table:

```python
from pandid.document import location_reference

location_reference("4334", zone="B3")            # "4334/.B3"   zone B3 on single-sheet 4334
location_reference("7569", "12", "B3")           # "7569/12.B3" zone B3 on sheet 12 of 7569
location_reference(sheet="2")                    # "/2"         another sheet, same document
location_reference(sheet="12", zone="B3")        # "/12.B3"     zone B3 on sheet 12
location_reference(zone="B")                     # "/.B"        row B on the same sheet
location_reference(zone="3")                     # "/.3"        column 3 on the same sheet
location_reference(zone="B3")                    # "/.B3"       zone B3 on the same sheet
location_reference("PFD-302")                    # "PFD-302"    the document itself
```

It returns a plain string and `reference=` takes one, so this is a way to *spell*
a reference rather than a new kind of value, and a spec round-trips unchanged:

```python
fs.add(units.Product("Azeotropic Ethanol",
                     reference=location_reference("PFD-302", "12", "B3")))
```

`zone` is checked against §5.1.2, which designates columns with numbers and rows
with letters, so a zone is its row's letter then its column's number
(`"B3"`), a row is the letter alone and a column the number alone. `"3B"` raises
rather than sending a reader to the wrong place. The two reserved signs are
refused inside any part, since one there would be read as a separator.

**What is not done.** Three of Clause 9's neighbours are the drawing author's,
not the engine's, and `pandid` says so rather than guessing:

- **§12.6's placement rule**, which puts a connecting line's references in the
  outer grid zone of the content area, is left to `pin()`. The zone grid is
  measured at render time from the frame the furniture leaves, which is after
  `validate()` has run, and the reference sheets put their flags in the outer
  columns by authoring them there.
- **Reciprocal references** (§12.6 has the two ends reference one another)
  need the peer end, which is on another sheet. A `Flowsheet` is one sheet and
  there is no document object above it, so there is nothing to check against.
- **Filling a reference from the peer's zone** needs the same missing peer.

A bare document number is what an issued sheet actually carries: every off-page
flag on the three reference drawings in `professional_examples/` reads as a
service name over a document (`Fermentation Broth` over `P&ID-201`, `Azeotropic
Ethanol` over `PFD-302`), and not one names a sheet or a zone.

`header=True` says the flag stands for a **utility header** (cooling water,
steam, flare, plant air) rather than for one line crossing the sheet edge. A
header is a service tapped wherever it is wanted, so it may be added once per
tap and is labelled the same way at every one:

```python
for hx in (condenser, cooler):
    cws = fs.add(units.Feed("CWSH", header=True))
    cwr = fs.add(units.Product("CWRH", header=True))
    fs.connect(cws.outlet, hx.tube_in)
    fs.connect(hx.tube_out, cwr.inlet)
```

Both taps draw `CWSH`; the flowsheet names them `CWSH` and `CWSH (2)` so each is
still one unit to address. Without the word, two flags of one name raise: two
process boundaries sharing a label are a service the reader cannot resolve, and
only the author knows which case it is. Both drawings have to be of the same
thing, so a `Feed` and a `Product`, or two flags naming different `reference`
drawings, still clash.

---

## Validation

```python
issues = fs.validate()        # list[Issue], errors first
for i in issues:
    print(i)                  # "[warning] route-detour: stream S3 routes ..."
```

`Issue` is a frozen dataclass with `severity` (`"error"` / `"warning"`), `code`
and `message`.

`validate(diagram=…)` takes the drawing the findings are about, spelled as
[`to_svg()`](#rendering) takes it. Almost nothing depends on it — a flowsheet is
a flowsheet either way — but `nozzles-crowded` is about arrowheads, and a P&ID
draws none. It defaults to `"pfd"`; `render()` passes whichever drawing it is
making, so the warnings left on `fs.warnings` are about the sheet that came out.

| Code | Severity | Meaning |
|---|---|---|
| `pin-not-finite` | error | a pinned `x`/`y` is not a finite number |
| `pin-out-of-bounds` | error | a pinned `x`/`y` is negative (off-sheet) |
| `unit-overlap` | error | two units' drawn boxes overlap |
| `coincident-ports` | error | two connected ports on one unit resolve to the same point |
| `coincident-ports` | warning | …and one of them is a port the symbol never anchored, so it fell back to the centre of the box. No shipped symbol has such a gap, so this covers symbols registered from outside the package |
| `instrument-unplaced` | error | an attached balloon whose host chain never resolves, so layout could put it nowhere and the sheet cannot be drawn; see [Routing and instrument placement](#routing-and-instrument-placement) |
| `route-crosses-unit` | warning | a stream passes through a unit body it does not connect to |
| `route-detour` | warning | a route is more than 3× its direct span |
| `letter-sequence` | warning | a tag spells its control-function letters out of the order ISO 15519-2:2015 §5.2.4 requires (I, R, C, S, M, Z, A), so `FCI` where `FIC` was meant. One finding per tag, and the message names the tag it would have been |
| `gravity-turned` | warning | a unit whose symbol's function depends on gravity has been given a quarter turn, which ISO 15519-1:2010 §11.4.2 excepts from the general permission to turn. One finding per unit; see [Symbols that must not be turned](#symbols-that-must-not-be-turned) |
| `run-off-elevation` | warning | two connected nozzles on one horizontal run are *almost* level, missing by less than the shorter symbol is tall, so the line steps into a device and back out; see [Runs at one elevation](#runs-at-one-elevation) |
| `nozzles-crowded` | warning | two nozzles on one face both wear an arrowhead and are pitched closer than ISO 128-20 lets two parallel lines come, so the strip of paper between the heads is too thin to survive reproduction. One finding per face, and the message names the box that would fix it. Not made for a P&ID, which draws no heads. See [Nozzles and the arrowheads they carry](#nozzles-and-the-arrowheads-they-carry) |
| `nozzle-unconnected` | warning | a nozzle whose existence a count asked for (`n_inlets=`, `n_outlets=`, `n_feeds=`, `inputs=`, `outputs=`) carries no stream, so the sheet asserts a connection that is not drawn. One finding per family; only counted nozzles, and only process ones. See [Nozzles nothing is piped to](#nozzles-nothing-is-piped-to) |
| `stream-name-reused` | warning | auto-numbering picked a name another stream already answers to, so the two share one stream-table column and one of them is not tabulated at all. Only a *counted* name is reported: a run drawn in several `connect()` calls shares its name on purpose. See [Stream numbering](#stream-numbering) |
| `boundary-flow-missing` | warning | a stream with a `Feed` or a `Product` at one end states no property, on a sheet whose other streams state theirs. ISO 10628-1:2014 §4.3.2 d) makes the flow rates or quantities of ingoing and outgoing materials something a PFD shall contain, so the stream table keeps the empty column rather than dropping it the way it drops an empty internal one. A blank value is a report and is not flagged; see [Which streams get a column](#which-streams-get-a-column) |
| `route-not-settled` | warning | routing and instrument placement never agreed and `route()` ran out of passes; see [Routing and instrument placement](#routing-and-instrument-placement) |
| `deprecated` | warning | the sheet was built with a spelling that is being retired. The message names the replacement and the release the old one stops working in; see [Deprecated API](#deprecated-api) |
| `symbol-kind-unknown` | warning | a unit whose `kind` no symbol is registered for. It is drawn as a blank 60×60 box with no ports, which is what a `Unit` subclass from outside the package legitimately gets — and also what a misspelt `kind` gets. One finding per kind, with the nearest registered name |
| `label-overruns-symbol` | warning | a `Block` given a `width` of its own too narrow for the name it letters inside the box, so the name is drawn out through both sides. A block left to size itself always fits |
| `symbol-out-of-aspect` | warning | a `width`/`height` of a different shape from the symbol's own box, on a drawing that carries a **round** mark — today that is ISO item 20.6's drive motor, on a stirred vessel. The composition works the motor's size out from the body's box, so at any other shape it is drawn as an oval. A shell with no round mark on it may be any shape you like; see [Sizing a stirred vessel](#sizing-a-stirred-vessel) |
| `drawio-approximated` | warning | `to_drawio()` only: a symbol draw.io has no stencil for, exported as a built-in stand-in that does not draw all of it. The message names the unit and what the stand-in loses; see [Editing the sheet by hand](#editing-the-sheet-by-hand) |

Errors raise from `to_svg()`/`render()` unless you pass `check=False`. Warnings
never raise, and collect on `fs.warnings` after each render. That list describes
**the last render and nothing earlier**: it is emptied at the start of every
render, `check=False` included, so an empty list means nothing was found rather
than nothing was looked for. Copy it if you want two renders' findings. Geometric checks
need resolved frames, so they are made over the units that have one: before
layout that is none of them, and after it a balloon layout could not place is
the one unit skipped rather than the whole sheet.

### When the checks run

The findings split in two, and a render makes them at two different moments:

1. **Model checks**, before anything is laid out or routed:
   `pin-not-finite`, `pin-out-of-bounds`, `symbol-kind-unknown`,
   `gravity-turned`, `symbol-out-of-aspect`, `letter-sequence`,
   `nozzle-unconnected`, `stream-name-reused`, `boundary-flow-missing` and
   `deprecated`. Every one of these is a property of what you wrote down.
2. `layout()` and `route()`.
3. **Geometric checks**, over the frames and routes those produced:
   `unit-overlap`, `coincident-ports`, `nozzles-crowded`,
   `route-crosses-unit`, `route-detour`, `run-off-elevation`,
   `label-overruns-symbol`, `instrument-unplaced` and `route-not-settled`.

An error from either half raises, so a model error raises before any geometry
exists. That is the point of the order: `pin(x=float("nan"))` is a
contradiction the model check names exactly, and it is also a coordinate the
router starts from and does not come back from. Checking it afterwards made a
perfect finding about a drawing you could never obtain.

Warnings from both halves land on `fs.warnings` together, model findings first.

`fs.validate()` is unaffected and still answers with everything, errors first.
Call it after `layout()` and `route()` — or after a render, which runs them —
to hear the geometric half; on a sheet nothing has placed yet that half is
simply silent.

### Deprecated API

A retired spelling gives two signals: a standard `DeprecationWarning`, and a
`deprecated` finding from `validate()`. Python hides `DeprecationWarning` by
default outside `__main__`, so the finding is the one you can rely on seeing.
Both are built from one declaration and always read the same:

```text
[warning] deprecated: P-101: Pump(cooled=True) is deprecated and is removed in pandid 0.2.0; use Pump(jacket='cooling')
```

A deprecation lives for one release. It works throughout the release that
announces it and is deleted in the next, so the message always names a release
that has not shipped yet. The CHANGELOG lists it under `### Deprecated` when it
is announced and under `### Removed` when it goes.

**Seven are in flight**, all announced in 0.1.3 and all removed in 0.2.0. Each
is a `variant=` that named a *part* rather than a body, moved to the keyword
that names the part:

| Deprecated | Type instead | Does the drawing change? |
|---|---|---|
| `Vessel(variant="legs")` | `Vessel(supports="leg")` | yes — the ISO element goes under the standard 62 × 125 shell, not the 40 × 122.7 one |
| `Vessel(variant="skirted")` | `Vessel(supports="skirt")` | yes, the same way |
| `Reactor(variant="plain")` | `Reactor(internals="packing")` | yes — ISO item 27.8 X8141's crossed bed replaces a diagonal hatch that is no ISO mark, on the standard shell |
| `Reactor(variant="mixing")` | `Reactor(agitator="disc")` | yes — ISO item 1.27 X8006's dished-end shell, group-28 stirrer and motor replace a cone-bottomed box with a capsule on top; no ISO row draws a cone-bottomed agitated vessel |
| `Separator(variant="gravity")` | `Separator(characteristic="gravity")` | no |
| `Separator(variant="electrostatic")` | `Separator(characteristic="electrostatic")` | no |
| `Separator(variant="electromagnetic")` | `Separator(characteristic="electromagnetic")` | no |

**A warning says which.** Where the replacement is not a drop-in, the message
carries the change before it names the call:

```text
[warning] deprecated: R-101: Reactor(variant='plain') is deprecated and is removed in pandid 0.2.0; the drawing changes -- ISO item 27.8 X8141's crossed bed on the standard vessel shell, in place of this one's diagonal hatch, so use Reactor(internals='packing')
```

Where it is a drop-in the message says nothing extra, and that silence is the
claim that the two draw the same symbol.

The six spellings 0.1.2 announced were removed in 0.1.3:

| Removed in 0.1.3 | Type instead |
|---|---|
| `Separator(variant="cyclone"\|"gravity"\|"electrostatic").vapor` | `.overflow` |
| the same three separators' `.liquid` | `.underflow` |
| `Valve(variant="pneumatic")` | `Valve(variant="control")` |
| `add_instrument(on=…)`, and `on:` in a spec | `sensing=`, `acting_on=` or `near=` |
| `Instrument(variant="panel")` | `Instrument(display="central")` |
| `Instrument(variant="aux")` | `Instrument(display="subsidiary")` |

A drum or a wet scrubber keeps `vapor` and `liquid`; only the three drawings
that collect dust renamed theirs.

The finding rides on the object the call was made on, so a unit deprecated
during construction is reported even though it was not on a flowsheet yet. A
unit that is never added is never reported — `validate()` answers for the
drawing. A deprecated call with no flowsheet, unit or stream in scope has
nothing to ride on and is reported by every `validate()` in that process.

### Runs at one elevation

A unit is pinned by its **top-left corner**, and every symbol carries its
nozzles wherever its artwork puts them. A control valve is 15 tall and takes its
line at mid-body, so its nozzles sit 7.5 below the corner; a vessel takes its
inlet 50 below. Pinning a row of equipment to convenient corner-`y` values
therefore puts the *nozzles* on different elevations, and the router draws a
step into each device and a step back out:

```python
fv   = fs.add(units.Valve("FV-101", variant="control")).pin(x=270, y=180)  # nozzle at 187.5
drum = fs.add(units.Vessel("V-101")).pin(x=420, y=145)                     # nozzle at 195
```

7.5 apart, exactly half a valve. Nothing errors and no nozzle leaves its ink;
the sheet is only subtly wrong. `validate()` reports it as `run-off-elevation`
and names the cure, which is [`pin(port=…)`](#pinport) — the form that reads
the coordinate as the position of a *nozzle* rather than of the corner:

```python
fv.pin(x=270, port="inlet", y=195)      # put the nozzle on the run
```

The finding fires only on a **near** miss: an offset smaller than the shorter of
the two symbols is across the run. A large step between two pieces of equipment
is a change of elevation someone meant, and stays silent. So do vertical runs,
where the difference in `y` is the length of the drop rather than a miss; signal
lines, which carry a measurement and have no elevation; sheets with no pinned
elevation to have got wrong; and the eccentric reducer, whose two ends sit on
different centrelines because that is the whole point of the fitting.

### Nozzles and the arrowheads they carry

A PFD ends every process line in a filled triangle,
`pandid.render.symbols.ARROWHEAD` = 12 units long and, because the marker's
square viewBox maps onto a square viewport, exactly as much *across* the run. Two
of them side by side on one face therefore leave `pitch − 12` of paper between
two solid shapes, and **ISO 128-20:1996 §4.4** says how thin that strip may get:
two parallel lines are kept at least twice the widest of them apart, and never
under 0,7 mm. The sheet draws its process lines 2 units wide, so the clearance is
`MIN_HEAD_CLEARANCE` = 4 and the floor is `MIN_NOZZLE_PITCH` = 16.

A port family is spread across whatever face it has, so a short box closes that
strip without anyone noticing. A `Mixer` is drawn in a 50-unit box and spaces its
inlets 20 apart; give it a 35-unit box and the same two nozzles land 14 apart,
with 2 units of paper between two 12-unit triangles:

```python
mix = fs.add(units.Mixer("M-1", n_inlets=2, height=35))
fs.connect(fs.add(units.Feed("F1")).outlet, mix.in_1)
fs.connect(fs.add(units.Feed("F2")).outlet, mix.in_2)
fs.connect(mix.outlet, fs.add(units.Product("P")).inlet)
fs.to_svg()
[w.message for w in fs.warnings]
# ["M-1.in_1 and M-1.in_2 are 14.0px apart on M-1's W face, which leaves 2.0px
#   of paper between two 12px arrowheads -- under the 4px ISO 128-20:1996 4.4
#   asks between parallel lines, twice the weight this sheet draws them at.
#   Give the unit a box with room for them, M-1.height = 40"]
```

The rule is stated as the **clearance**, not as a multiple of the head, and the
difference matters: at the default 20 pitch those same two heads have 8 units of
paper between them — four line-widths — and read without effort, so nothing is
reported. Only one unit on the twenty shipped examples is inside the floor:
`10_ethanol_pfd`'s `M-301`, whose two feeds land 14.5px apart.

The cure is the box, and the message does the arithmetic: the drawn pitch is
proportional to the extent of the box across the face, so

```python
mix = fs.add(units.Mixer("M-1", n_inlets=2, height=40))   # nozzles 16 apart
```

is silent. Where the symbol offers the port a second placement the message also
names moving it with [`nozzle()`](#nozzle); a port placed by a series has only
the face the series gives it, so for a `Mixer` the box is the whole answer.
On a fixed [`page_size`](#rendering) a taller unit is a taller drawing, and the
drawing is fitted into what the furniture leaves — so check the title block's
scale note, which is what growing a box costs.

Only nozzles that actually **wear a head** are counted, and both of a pair. The
head is the path's `marker-end`, so it lands on the nozzle a stream *arrives*
at: a `Splitter`'s two outlets in that same 35-unit box sit 14 apart and read
perfectly well, because each of those heads is drawn at the far end of its
branch and the face carries two bare 2-unit lines. Signal lines wear no head on
either drawing, and neither does a run ending at a `Tee`, which is bare pipe.

**A P&ID draws no arrowheads at all**, so there is nothing there to crowd and the
finding is not made. `fs.validate()` answers for a PFD, which is what `to_svg()`
draws by default; pass the drawing you mean to get the findings that are about
it, which is what `render()` does for you:

```python
fs.validate(diagram="p&id")     # no nozzles-crowded: the sheet draws no heads
```

One finding per face, not per pair: three crowded nozzles are one crowded face
with one thing to do about it. A pair on the same *point* is the stronger
`coincident-ports` finding instead.

### Nozzles nothing is piped to

A unit whose nozzle count you choose has exactly the nozzles you asked for. Ask
for four and pipe three, and the sheet draws a mixer that combines four streams
and shows three lines going into it:

```python
mix = fs.add(units.Mixer("M-101", n_inlets=4))
for i in (1, 2, 3):                       # meaning in_1, in_2, in_3
    fs.connect(fs.add(units.Feed(f"F-{i}")).outlet, mix.inlets[i])
```

`inlets` is indexed from zero and the nozzles are numbered from one, so that
wires `in_2`, `in_3` and `in_4` and leaves `in_1` bare. `validate()` reports it:

```
M-101.in_1 carries no stream. M-101 was built with 4 numbered nozzles,
in_1..in_4, and 3 of them are piped, so the sheet asserts 4 connections and
draws 3. Connect it, or build M-101 with the 3 it uses.
```

Both cures, because only you know which was meant: a line you left off, or a
nozzle you never wanted. It costs more than a missing line, too — a family is
spread evenly across its face for **every** member it has, wired or not, so the
three lines that are drawn land 11.7 apart around a hole where `in_1` is,
instead of the 17.5 apart that `n_inlets=3` would have given them.

**Only counted nozzles.** A `vent`, a `relief`, a `drain`, a `duty`, an
exchanger's other side, a drain valve's outlet, a filter press's `wash_in` —
every fixed nozzle a class declares is offered to every instance whether the
sheet uses it or not, and leaving one open is a drawing decision. Declaring one
per variant rather than per class changes nothing here: a press run without a
displacement wash is a real machine, and a sheet that lets the cake fall to a
bin off the drawing is a real sheet. Every shipped example leaves such
nozzles open -- signal connections, exchanger utility sides, duties, reliefs,
drains, vents, station drain outlets, agitator drives, an ion exchanger's
regenerant pair, a filter press's displacement wash, and spare vessel and
column nozzles. None is reported.
What is reported is a *count that went unmet*, which is why the singular
spelling is silent too — a one-feed column's nozzle is called `feed`, not
`feed_1`, and no number was ever written down for it.

**Only process nozzles.** Signal connections are a different question: an
instrument may be placed against its equipment rather than drawn tapped off a
line, and a valve with nothing on its `actuator` is a hand valve. Counting does
not settle either, so this finding does not try.

No standard is cited because none is on point. ISO 15519-1 §12, *Connections*,
legislates how a connecting line is drawn — orientation, width, joints,
intersections, off-sheet references — and never that a connection point must
have one on it. This is the drawing disagreeing with its own declaration, which
needs no outside authority.

### Routing and instrument placement

`route()` places attached instruments and re-routes until the two agree, rather
than trading a fixed number of passes. A balloon is placed on its host's *routed*
path, and the box it lands in is an obstacle the next pass routes around, which
can bend that same path and move the balloon again, so the two chase each other
to a fixed point. Stopping early leaves a dense sheet with its balloons in one
place and its signal lines drawn to where they used to be.

A sheet can trade between two arrangements indefinitely, so the loop is capped at
`pandid.layout.attach.MAX_PLACEMENT_PASSES`. Every pass ends on a route, so
running out still leaves each line drawn to the balloon it belongs to.
`fs.route_converged` says whether the last run settled, and a run that did not
earns a `route-not-settled` warning: the drawing is coherent, but which of the
arrangements it caught is arbitrary, so the sheet is not reproducible until the
balloon-carrying lines are pinned with [`via()`](#streams).

A balloon takes its position from its host, so a chain of them has to end on
something the layout places. One that does not — two balloons attached to each
other, or a balloon tapping a line whose own end is such a balloon — can be put
nowhere. Placement leaves those on `fs.unplaced_instruments` and `validate()`
reports each as an `instrument-unplaced` error, naming the host it is waiting
on. It is an error rather than a warning because the renderer will not draw a
unit with no frame, so there is no sheet to warn about.

### Symbols that must not be turned

**ISO 15519-1:2010 §11.4.2**, *Orientation of graphical symbols*, allows a symbol
to be turned or mirrored so that it fits the layout the diagram actually has,
and then makes one exception: a symbol for a component or device whose function
depends on gravity must not be turned. It names two of them, the open tank
(2061) and the cyclone separator (X 2618), drawn at Figure 22 b).

Figure 22 b) draws those two: an open-topped U, and a body whose conical apex
points down with the vortex spiralling into it. Both do their job by gravity, and
both say something the plant cannot do once turned.

`Symbol.gravity_fixed` marks them, and `pin(orientation=...)` on a unit drawn
with one earns a `gravity-turned` warning:

```python
tank = fs.add(units.Tank("TK-301")).pin(x=300, y=200, orientation=90)
fs.to_svg()
[w.message for w in fs.warnings]
# ["TK-301 is turned 90°; ISO 15519-1:2010 11.4.2 excepts symbols where gravity
#   is a functionality from turning, and a tank/default is one of them"]
```

A **warning, not an error**. The sheet still draws, every nozzle still lands on
ink, and the only thing wrong with it is what it says about the plant, which is
the same kind of finding as `letter-sequence`. Where the equipment really is
installed lying down, the answer the clause itself gives is to draw a fresh
symbol in the orientation actually wanted, and two families ship one: the
message names `variant="horizontal"` where it exists.

Mirroring is left alone. §11.4.2 excepts *turning* only, and flipping a tank left
to right to put its nozzles on the other side is a placement the clause permits.
What a flip may not do is reverse an arrow the artwork carries — see
[Symbols whose artwork points somewhere](#symbols-whose-artwork-points-somewhere)
below, which is handled by drawing rather than by refusing, for exactly the
reason this paragraph gives.

The 86 marked symbols, and what in each one's artwork only means one thing one
way up:

| Symbols | Why |
|---|---|
| `separator` `default` `cyclone` `electrostatic` `gravity` `horizontal` `knockout` `scrubber` | separation by density: `cyclone` **is** ISO's X 2618, `gravity` says so in its name, and the hopper-bottomed three collect out of an apex |
| `separator` `venturi_scrubber` | fixed twice over: the family's hopper, and its own throat, which the artwork draws running down into it. Turned, the gas is accelerated into a wall |
| `separator` `sifter` `impact` `permanent_magnet` `electromagnetic` | listed for the hopper, not for what does the separating: a magnet sorts by magnetism and a sifter by size, and what fixes the attitude of all four is the fall into the hopper the artwork draws. Turned, the hopper is a roof |
| `tank` `default` `conical` `floating_roof` `sphere` | ISO's 2061: a free liquid surface, filled at the roof and drained at the floor, with `floating_roof` drawn floating on it |
| `tank` `conical_bottom` `conical_ends` `dished_roof_conical_bottom` | the same, drained at a cone's apex instead of at a floor, which is the fall the hopper-bottomed separators above are listed for. Turned, the cone is a roof and the tank drains nowhere |
| `tank` `gas_holder` | 2061 again, and the most literal case of it: the bell is drawn resting on the water in the seal, which is the whole mechanism. Turned, the seal runs out |
| `boiler` `default` | ISO item 4.1, 2532: steam collects in the dome because it is the shell's highest point. Turned, the dome is the lowest point and holds the liquid instead |
| `cooling_tower` `default` `induced_draft` `forced_draft` `general` `dry_natural` `dry_forced` `dry_induced` `wet_natural` `wet_forced` `wet_induced` `wet_dry_natural` | the warm water is distributed over the fill and falls through the draught into the basin the artwork draws under the machine. Turned, the water leaves sideways and the draught runs across the basin |
| `vessel` `default` `dished` `dome` `horizontal` `jacketed` `skirted` `legs` `insulated` `electrical_heating` | holdup with a vapour space: the vent is on the top head and the shell drains from the bottom, and four of them draw the brackets, skirt, legs or saddles they stand on |
| `vessel` `swaged` | the same, and one thing more: the vessel is drawn in two diameters with the larger below, so it is the bottom that holds the inventory. Turned, the two diameters are side by side and say nothing about either |
| `column` `default` `packed`, `reactor` `default` `plain` | liquid running down over trays or packing while vapour rises, and an agitator hanging in from above |
| `vent` `default` `breather` `exhaust_head`, `funnel` | open ends: what leaves rises, and an open end drawn pointing down is a drain |
| `stack` `default`, `flare` `default` | ISO items 4.7 (2041) and 4.8 (2591): a stack exhausts up and a flare burns off its tip up, the same "open end, and what leaves rises" claim as `vent` |
| `crushing_machine` `default`, `crusher` `default` `cone` `hammer` `impact` `jaw` `roller`, `mill` `default` `hammer` `impact` `roller` `vibration` | ISO group 11's trapezoid is wide at the mouth and narrow at the throat, with its feed tick above it and its discharge tick below: turned, the machine is fed through the opening its product falls out of |
| `elevator` `default` `z_form` | a machine whose purpose is to raise material: in at the boot, out at the head. Turned, it lowers it. The conveyors beside it are not marked, since a belt or a screw runs whichever way the plant needs |
| `dryer` `spray` `fluidized_bed`, `filter` `gas` `gas_fixed_bed` `gas_belt` | solids that fall: an atomiser in the roof, a bed on its distributor plate, and the dust hopper each gas filter casing draws under its medium |
| `dryer` `shelf` | ISO item 10.2, X8083: the mark is trays resting on shelves, which turned over is trays resting on nothing. `general`, `turbo` and `belt` are not marked, on the same reasoning `default` (the rotary drum) already was not |
| `feeder` `general` `rotary_valve` `rotary_table` `metering` | ISO group 19's hopper valves: solids drop in at the top and are metered out at the bottom, the same feed-tick-above/discharge-tick-below claim group 11's crushers make |
| `kneader` `default` | ISO item 12.4 X8134: twin shafts driven from above work a trough that holds its charge below them |
| `screening_device` `general` `coarse_rake` `fine_rake` `coarse_and_fine` `vibrating` `rotating_drum` `basket_reel` | ISO group 7's screens: oversize retained on a deck, undersize dropped through it -- group 11's hopper claim again, at this group's own wall-and-point outline |

Not marked, and deliberately: a pump, a compressor, a valve, an in-line fitting
or a heat exchanger is installed in whatever attitude the run wants, so turning
its symbol states nothing false, even where a nozzle happens to sit low
(`hex/kettle`) or the stencil draws a downward tap (`valve/bleed`). Nor is
`centrifuge`, despite drawing low the same way a hopper does: what does the
separating is rotation rather than a settling body or a free surface, which is
the case the exclusion is written for rather than an oversight of it. Nor is any
*liquid* filter, which is the sharpest case in the list: `fixed_bed` and
`gas_fixed_bed` draw the same bed the same way, and it is only the hopper the gas
casing adds underneath it that fixes an attitude. A bed driven by pressure drop
rests on its support the way every piece of plant rests on the ground, and that
is not the test. The reasons are recorded beside `GRAVITY_FIXED` in
`scripts/vendor_symbols.py`, which is where the flag is set for the vendored
symbols.

### Sizing a stirred vessel

`width=`/`height=` is taken as the final box, so a box of a different shape from
the symbol's own scales the artwork unevenly. For a shell that is the point — a
vessel is drawn at the proportions the plant has, and a tray deck or a packed bed
is a line that may be any length.

One mark is not a line. A stirred vessel carries ISO item 20.6's drive motor
above its crown, and the motor is a **circle**; the composition works its size
out from the shell's own box, so at a box of another shape it is drawn as an
oval. Sizing one out of shape earns `symbol-out-of-aspect`:

```python
rx = fs.add(units.Reactor("M-301", n_feeds=2, width=80, height=100))
[w.message for w in fs.validate()]
# ["M-301 is drawn 80x100 on a reactor/default whose own box is 62x131.778, ...
#   70% out of shape. ... Give M-301 a box of the same shape,
#   M-301.width = 47.05 for the height it has, ..."]
```

Two ways out, and the message names both: leave `width=` and `height=` unset and
let the symbol size itself, or keep the height you want and take the width that
goes with it. Nothing else is affected — the finding is only made for a drawing
that carries a round mark.

### Symbols whose artwork points somewhere

`Heater` and `Cooler` are one stencil pair. The same circle, the same zigzag, the
same diagonal — and which of the two you are looking at is *only* which end of
that diagonal carries the arrowhead: heat added, or heat removed. Flip either and
the head lands at the far end, where the other one draws it, so the sheet says
heat is added where it is removed.

That is not a reason to refuse the flip. §11.4.2 permits mirroring outright, and
what a reader asks for by flipping a condenser is its *nozzles* on the other side
— `examples/10_ethanol_pfd` flips one so the tower overhead rises into the shell
inlet dead straight. So `Symbol.directional` marks the drawing instead, and the
renderer holds it still under the flip while the nozzles move: the flip is undone
inside the `<defs>` entry and the `<use>` reapplies it, exactly as a symbol's own
lettering is kept readable under a transform.

```python
cond = fs.add(units.HeatExchanger("E-301", variant="condenser"))
cond.pin(x=430, y=56, mirrored="y")   # shell inlet underneath; arrow unchanged
```

Nothing is warned about and nothing is refused: the flip does what it was asked
to do and the arrow goes on saying what the stencil's author drew. The three
marked symbols are `heater/default`, `cooler/default` and `hex/condenser`, which
is the same drawing as `cooler/default`; the reasons are recorded beside
`DIRECTIONAL` in `scripts/vendor_symbols.py`.

#### Which placements reverse a mark, and which carry it

The eight placements a unit may take are the symmetries of a square, and they
split in two:

| placement | the mark | why |
|---|---|---|
| `mirrored="x"`, `mirrored="y"`, `mirrored="xy"` | **reversed** — undone | an axis flip lands the head at the other end of the mark, on a drawing the reader still sees the same way up |
| `orientation=180` | **reversed** — undone | a half turn *is* `mirrored="xy"`: the two flips composed. It is not a turn as far as the mark is concerned, and it puts the head exactly where the sibling symbol draws it |
| `orientation=90`, `orientation=270` | **carried** — left alone | a quarter turn puts the head on the *other* diagonal, which no upright drawing of either symbol occupies, and turns the box with it: what the reader sees is a symbol that has plainly been turned |

A quarter turn combined with a mirror still has its mirror half undone; only the
quarter turn itself is carried. That split is also the arithmetic one, which is
not a coincidence: an axis flip commutes with the per-axis scaling that fits a
symbol into its box and so cancels exactly inside the definition, while a quarter
turn does not, and on a box that is not square it cannot. `_reflections` in
`pandid/render/svg.py` is where it is worked out, and a directional symbol
therefore takes **four** `<defs>` entries across all sixteen placements rather
than sixteen.

---

## Declaring a flowsheet as data

An equipment list and a stream table are data, and usually already exist in a
spreadsheet, a YAML file or a simulator export. Declare the flowsheet as a plain
mapping and hand it to the engine instead of retyping it as Python.

```python
from pandid import Flowsheet

fs   = Flowsheet.from_dict(spec)         # a plain dict, from anywhere
fs   = Flowsheet.from_json("bfw.json")   # standard library only
fs   = Flowsheet.from_yaml("bfw.yaml")   # pip install 'pandid[yaml]'
spec = fs.to_dict()                      # writes the same spec back out
```

`to_dict()` round-trips. `Flowsheet.from_dict(fs.to_dict())` rebuilds an
equivalent flowsheet with the same equipment, nozzles, placement and drawing.
Only intent is written, never the engine's results (resolved frames, routed
paths, computed stream numbers), so the file stays short and re-lays out
cleanly. YAML is the one optional extra: `from_dict` and `from_json` need
nothing, and asking for YAML without PyYAML installed says exactly that.

### A complete sheet

```yaml
name: Feed Metering Skid          # the only required field
stream_naming_scheme: "S{n}"
stream_number_start: 1            # the S1 a flag draws
line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
line_number_start: 1001           # the 1001 inside 6"-P-1001-A1A
loop_number_start: 101            # where a loop with no number counts from
components: [Water, {name: Ethanol, formula: C2H6O}]

units:
  - {kind: Feed, name: Raw Feed, reference: PFD-100, pin: {x: 60, y: 275}}
  - {kind: Fitting, name: ST-101, variant: strainer, description: Suction Strainer}
  - {kind: Mixer, name: M-101, n_inlets: 3, description: Suction Header}
  - {kind: Pump, name: P-101, description: Feed Pump}
  - {kind: Splitter, name: SP-101, n_outlets: 2, description: Minimum-Flow Tee}
  - {kind: Valve, name: FV-101, variant: control, new_line_number: true,
     description: Spillback Valve}
  - {kind: Vessel, name: V-101, variant: horizontal, width: 130, height: 42,
     description: Surge Drum, port_faces: {inlet: N}}
  - {kind: Product, name: To Unit 200, reference: PFD-200}

loops:
  - {variable: L, number: 101}

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
  - {from: [FV-101, outlet], to: [M-101, in_3], draw_as_recycle: true}
  - {from: [V-101, outlet], to: [To Unit 200, inlet]}
  - {from: [LIC-101, sig_out], to: [FV-101, actuator], kind: electric}

stream_table_sections: [[Ethanol, Mass Fraction]]

title_block:
  title: Utilities U200
  subtitle: Process Flow Diagram 1
  drawing_number: PFD-2001
  company: PANDID
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

### The `units` section

`kind` (required) is the equipment class, in any spelling you would reasonably
write: `HeatExchanger`, `heat_exchanger` or `hex`, and an
[equipment class](#equipment-classes) by name (`Cyclone`, `kettle_reboiler`),
which is what `to_dict()` writes for one. `name` (required) is the tag.
Then `variant`, `description` (feeds the equipment list), `reference` (a boundary
flag's off-page drawing), explicit `width`/`height`, `label_pos`, `new_line_number`
(break the stream or line number at this inline item), `n_inlets` / `n_outlets`
for `Mixer` / `Splitter`, `n_feeds` for `Column` / `Reactor`, `feed_stages` (one
stage per feed, `null` for a feed that keeps the even spread) for `Column`,
`length` and `diameter` for `Conveyor`, `branch` (`outlet` / `inlet`) for `Tee`,
`large_end` (`inlet` / `outlet`) for `Reducer`, `normal_position` (`open` /
`closed`) for `Valve` and for `Fitting`'s `blind`, and `fail` (`open` / `closed` /
`last` / `drift_open` / `drift_closed` / `indeterminate`) for an actuated
`Valve`.

[What a body carries](#what-a-body-carries) is stated by the same keywords the
constructors take: `supports` for a `Vessel`, `agitator` and `internals` for a
`Reactor`, `internals` and `trays` for a `Column`, and `characteristic` for a
`Separator`. `null` asks for a bare body, which is not the same as leaving the
key out — a `Column` that says nothing is drawn with the trays a column draws.

```yaml
- {kind: Column, name: T-101, internals: valve_tray, trays: 30}
- {kind: Reactor, name: R-201, internals: packing, agitator: null}
- {kind: Vessel, name: D-301, supports: skirt}
```

### The `pin` and `port_faces` keys

`pin` mirrors [`pin()`](#pin) with `x`/`y` (absolute), `col`/`row` (grid),
`orientation` (`0`/`90`/`180`/`270`) and `mirrored` (`x`/`y`/`xy`). `x`/`y` are
always the corner here, a flag's included: what is written is the placement the
engine resolved, and reading it back has to put the flag where it was.

`port_faces` maps a port to the face it leaves from **as drawn**, so a mirrored
or turned unit takes the face the reader sees. It is an override: without it the
engine picks the face itself, and the top-level `auto_faces: false` is how you
stop it.

A `Block` also takes `port_order`, mapping a face to every connection on it in
the order they are drawn along it — [`order_on()`](#block-the-block-flow-diagram)
written down. `to_dict()` writes it only for a face that is not in declaration
order, so an ordinary block's entry is unchanged.

```yaml
- {kind: Block, name: Synthesis Loop, inputs: [W, S], outputs: [E, S],
   port_order: {S: [out_2, in_2]}}
```

### The `loops` section

Declared control loops, `{variable: F, number: 303}`, matching
[`add_loop()`](#control-loops). Members carry their whole tag, so the section
only records that the loop exists; a sheet that declares none writes no section
at all.

`number` is optional and omitting it allocates from `loop_number_start`, exactly
as omitting the argument to `add_loop()` does. `to_dict()` always writes a
literal, so a spec this package wrote reads back frozen.

### The `instruments` section

`type` (required) and `number` make the tag, so `{type: LIC, number: 101}` is
`LIC-101` elsewhere. `sensing`, `acting_on` and `near` name the anchor and mean
what they do in [`add_instrument()`](#anchoring-a-balloon): a unit, a named
stream, or `[unit, port]` for the line leaving that nozzle. `to_dict()` writes
that last form, since auto-numbered stream names are rewritten at render time.
`at`, `offset`, `angle`, `variant`, `display` and `port_faces` behave as in
[`add_instrument()`](#instrumentation), and `quadrants` is a mapping of
[`annotate()`](#letter-codes-outside-the-symbol)'s own argument names. An
instrument that names no anchor is laid out like any other unit.

A primary element's balloon is written on the **element's** entry, as
`balloon: {at, offset, angle, variant, display}`, since it carries the element's
tag and has none of its own to be an entry under.

### The `streams` section

`from` and `to` are `[unit, port]` pairs (or `{unit: ..., port: ...}`). `kind`
makes a signal line (`electric`, `pneumatic`, `data`, and the rest), `name`
overrides the auto number, `draw_as_recycle` nominates the recycle to cut, `via` forces
waypoints, and `properties` is that line's stream-table column. `size`,
`schedule`, `service`, `spec` and `insulation` are the
[line-number](#line-numbers) components, and `sequence` overrides the one
auto-numbering would assign, which is why `to_dict()` writes the components but
never the computed sequence.

### The `title_block` and `annotations` sections

`title_block` takes the [`TitleBlock`](#titleblock-and-revision) fields plus
`revisions`. Each `annotations` entry is one box, typed `equipment_list`,
`notes`, `legend`, `annotation` or `table`, placed with `align`, `position` and
`margin` exactly as in [Sheet furniture](#sheet-furniture).

### Spec errors

An error names the entry and what would have worked, so a typo cannot silently
drop a nozzle off the drawing:

```text
units[3] 'P-101': unknown key 'varient' (did you mean 'variant'?); allowed keys:
['description', 'height', 'kind', 'label_pos', 'name', 'pin', 'port_faces', ...]

streams[6].from: Pump 'P-101' has no port 'dischrge' (did you mean 'discharge'?);
available ports: ['discharge', 'suction']
```

Every failure raises `pandid.SpecError`, a `ValueError`.

Custom equipment is the one thing the spec layer does not reach; see
[What a custom unit does not get](#what-a-custom-unit-does-not-get).

---

## Command line

Installing the distribution installs a `pandid` command. `python -m pandid` is the
same entry point, for a checkout or an environment whose scripts directory is
not on PATH. It is a shell over the API above and adds nothing to it.

```text
pandid draw SPEC [-o OUT] [--page-size SIZE] [--border {none,zone}]
                 [--diagram {pfd,p&id}] [--stream-table]
                 [--jump-direction {vertical,horizontal}]
pandid validate SPEC
pandid symbols [--kind KIND]
```

`SPEC` is a spec file: `.yaml` or `.yml` (needs the `yaml` extra) or `.json`.
Any other extension is refused rather than guessed at. The format itself is
`pandid.spec`, documented under
[Declaring a flowsheet as data](#declaring-a-flowsheet-as-data).

### `draw`

Renders the spec and writes it. The output format comes from `-o`'s extension,
exactly as [`render()`](#geometry-and-output) decides it: `.svg`, or `.pdf` /
`.png` with the `pdf` extra. Without `-o` the drawing goes next to the spec,
under the same name with `.svg`.

| Option | The same as |
|---|---|
| `--page-size A3` | `page_size="A3"` |
| `--border zone` | `border="zone"` |
| `--diagram 'p&id'` | `diagram="p&id"` |
| `--stream-table` | `show_stream_table=True` |
| `--jump-direction horizontal` | `jump_direction="horizontal"` |
| `--debug`, `--debug 100` | `debug=True`, `debug=100` |

One line on stdout says what was drawn, and any warnings the sheet carries are
counted on stderr, since the drawing was still made:

```text
wrote plant.pdf  (A3, 14 units, 14 streams)
```

### `validate`

Reads the spec, runs `layout()` and `route()`, and prints `validate()`'s
findings as `severity: code: message`, one per line, with a count after them.
The layout runs first because the geometric checks have nothing to measure until
every unit has a frame, so without it only the spec reader's own findings would
be reported.

Warnings do not stop a render, so they do not fail the command either. An error
does.

### `symbols`

Lists every registered `(kind, variant)`, grouped by kind, one kind per line.
`--kind` takes any spelling a spec's `kind` takes (`Valve`, `heat_exchanger`,
`hex`), and an unknown one is refused naming the nearest match and the whole
catalogue.

```text
$ pandid symbols --kind valve
Valve  default  angle  ball  bleed  butterfly  butterfly_pneumatic  check  control  gate  globe
       hydraulic  knife  manual  motor  needle  pinch  plug  psv  regulator  relief  saunders
       solenoid  three_way
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | the command did what it was asked |
| `1` | the flowsheet was rejected: the spec could not be read or understood, validation found an error, or the engine refused the request (an unknown page size, an output extension it cannot write, a page too small for its own furniture) |
| `2` | the command line was wrong: an unknown flag, a missing argument, an option value the CLI checks itself |
| `3` | an optional extra the request needs is not installed: PyYAML for a YAML spec, the `pdf` extra for `.pdf` / `.png` |

Every failure is one line on stderr, beginning `error: `, carrying the engine's
own message. A traceback out of the CLI is a bug in the engine, not a bad spec.

```bash
pandid validate plant.yaml && pandid draw plant.yaml -o plant.pdf
```

---

## Custom equipment

Every class in the [port table](#port-table) is a `units.Unit` subclass with a
symbol registered for its `kind`. Neither half is closed, so a piece of plant the
library does not ship is a class and a symbol of your own.

This is for genuinely custom equipment. Anything a reader would recognise
from another sheet is better asked for as a stencil mapping (see
`CONTRIBUTING.md`): it then ships for everyone, is drawn in the same hand as the
rest of the catalogue, and is covered by the symbol invariants.

### The class

```python
from pandid import Flowsheet, units

class Crystalliser(units.Unit):
    kind = "crystalliser"
    PORTS = [
        ("feed", "inlet", "process"),
        ("mother_liquor", "outlet", "process"),
        ("crystals", "outlet", "process"),
    ]
```

`kind` is the equipment type, and the key the symbol registry is looked up by, so
it is what ties the class to its artwork. Reusing a shipped kind takes over that
kind's symbol, which is worth doing deliberately or not at all.

`PORTS` is one `(name, direction, role)` tuple per nozzle:

- **`name`** is what the port answers to, both as `unit.ports["feed"]` and as the
  attribute `unit.feed`, so make it a valid Python identifier. It must be unique
  on the unit; a repeat raises `ValueError`.
- **`direction`** is `"inlet"` or `"outlet"`. `connect(src, dst)` requires an
  outlet as `src` and an inlet as `dst`. Nothing checks the spelling when the
  class is written, so anything else surfaces at the first `connect()`.
- **`role`** is one of `process`, `feed`, `product`, `energy`, `utility`,
  `vapor`, `liquid`, `signal`. Anything else raises `ValueError` when the unit is
  constructed, listing the eight. Two of them change behaviour: `signal` makes
  the port a signal connection, which joins another signal connection and takes a
  signal `kind` (see [`connect()`](#building-the-topology)), and `energy` or
  `utility` at both ends promotes a `material` connection to `energy`. The rest
  state what the nozzle carries and are not otherwise interpreted.

Ports are built in declaration order, once, when the unit is constructed. The
nearest `PORTS` declaration in the class hierarchy is the whole list, so
overriding it in a subclass replaces the inherited one rather than adding to it.

Everything a shipped class has, a custom one has: `pin()`, `nozzle()`,
`description`, `label_pos`, `width`/`height` and the rest of the
[`Unit` constructor](#units-and-ports).

### The symbol

Without a symbol the unit draws a generic box (below) and every render says so,
as a `symbol-kind-unknown` warning naming the unit and the kind — a blank box is
also what a *misspelt* `kind` gets, and the two are the same file. To draw it
properly, register a `Symbol` under the same `kind`:

```python
from pandid.render.symbols import Symbol, default_registry

default_registry.register("crystalliser", Symbol(
    svg=(
        '<g id="sym_crystalliser">'
        '<path d="M 5 5 L 5 45 L 35 65 L 45 65 L 75 45 L 75 5 Z" '
        'fill="none" stroke="black" stroke-width="2"/>'
        '</g>'
    ),
    width=80.0,
    height=70.0,
    ports={
        "feed": (5.0, 15.0),
        "mother_liquor": (75.0, 15.0),
        "crystals": (40.0, 65.0),
    },
))
```

`svg` is the artwork in the symbol's own coordinates: `(0, 0)` top-left, spanning
`width` × `height`. Wrap it in a single `<g id="...">`. The renderer lifts the
group's children into a `<symbol viewBox="0 0 width height">` and places it with
`<use>`, so the drawing is scaled into whatever box the unit ends up with. The id
in the output is made from the kind and the variant; the id you write is what
names the symbol in error messages. Give every stroke an explicit `stroke-width`,
or it draws at the SVG default of 1 and comes out lighter than the rest of the
sheet.

`width` and `height` are the intrinsic size of that box. A `width=` / `height=`
on the unit overrides them, and the artwork is scaled into the result, unevenly
if that changes the aspect ratio, which is what a shell, a tank or an exchanger
wants, since the user asked for a box and the equipment simply becomes it. Pass
`stretchable=False` where the shape carries meaning instead: an ISA-5.1 balloon
is a circle at every size, so it keeps its proportions and is centred in the box,
and its ports are resolved against the artwork rather than the box edge the
artwork no longer reaches.

`bare_run=True` says the artwork is the pipe itself and nothing else, with the
run passing straight through it. Only the pipe tee is drawn that way among the
shipped symbols. It is what makes a PFD leave a line ending there untipped: an
[arrowhead](#which-drawing-this-is) says the material arrives somewhere, and a
symbol with no body of its own is a point on a line rather than a place. Leave it
alone for anything that draws a shape, which is everything else.

`ports` maps port name to a point in those same symbol coordinates. The names
must match the class's port names exactly. **Put every port on drawn ink.** A
stream is drawn to the port's point, so a nozzle in whitespace draws a pipe that
does not touch its equipment. `tests/test_symbol_invariants.py` enforces this for
every shipped symbol, each port within 2 units of the nearest stroke and no two
ports on one point, but it only sees the shipped registry, so a symbol of your
own is checked by eye. The one case the engine does catch is a port the symbol
never anchored: it falls back to the centre of the box, and if two such ports are
connected `validate()` reports [`coincident-ports`](#validation) as a warning.

Which face a port comes out of is decided by the nearest edge of the box, so
`(5.0, 15.0)` in an 80 × 70 box is 5 from the left and 15 from the top and is
therefore a west nozzle. A port that may be piped from more than one face
declares the whole menu in `port_faces`, one coordinate per face, which is what
makes it movable by [`nozzle()`](#nozzle).

`faceless_ports` names connections with no face of their own, the one legitimate
exception to "no two ports on one point". An instrument balloon is a circle, so a
signal may meet it anywhere and "in on the west, out on the east" is an artefact
of having to pick a default. Equipment nozzles are never faceless, and a faceless
port is still checked against the ones that do own a face.

`port_series` places a family of like ports whose membership the **unit** decides
rather than the symbol. A `Mixer(n_inlets=n)` has no fixed set of inlets, so the
symbol declares the rule and the coordinates are resolved once the count is
known. A `PortSeries` names the `prefix` its members are numbered from (`in_1`,
`in_2`, …), the `face` they spread along, the `pitch` they sit at, the `extent`
of the face they are squeezed into once that pitch would run them off the end,
and the point `at` along the face the run is centred on. `singular` names the
lone member of a family that is usually singular: a `Column` with one feed has a
nozzle called `feed`, and only grows `feed_1`, `feed_2` when given more than one.
A series is the sole authority for its own members, so naming one in `ports` as
well is rejected.

That is the whole workflow. The unit now behaves like any other:

```python
fs = Flowsheet("Salt Plant")
brine = fs.add(units.Feed("Brine"))
cr = fs.add(Crystalliser("CR-101", description="Salt Crystalliser"))
liquor = fs.add(units.Product("Mother Liquor"))
salt = fs.add(units.Product("Salt"))

fs.connect(brine.outlet, cr.feed)
fs.connect(cr.mother_liquor, liquor.inlet)
fs.connect(cr.crystals, salt.inlet)

fs.validate()                  # []
fs.render("crystalliser.svg")  # lays out, routes and draws
```

### A second style

`variant=` registers another drawing of the same kind, exactly as it does for the
shipped symbols. The class is unchanged: a variant is a visual style within a
functional type, so the two drawings carry the same ports.

```python
# forced_circulation is a second Symbol, drawn like the one above with the
# circulation loop added, and carrying the same three ports.
default_registry.register("crystalliser", forced_circulation, variant="forced_circulation")

fs.add(Crystalliser("CR-102", variant="forced_circulation"))
```

`default_registry.variants("crystalliser")` lists what is registered, `default`
first. A variant name nothing was registered under raises `ValueError` at the
first layout or render, naming the ones that were.

### Narrowing a class to its variants

That check is the registry's, and it is the right one while a class owns every
drawing of its kind: only the registry knows what artwork exists, so only the
registry can say a name is not among it.

A class that owns *some* of a kind's drawings knows more than that, and says so
with `VARIANTS`:

```python
class ForcedCirculation(Crystalliser):
    # "default" is listed and aliased, so naming the class alone asks for this
    # class's drawing rather than for the kind's plain one. A class that leaves
    # it out refuses to be built by name at all, since `variant` defaults to
    # "default" and a variant not in the list is a variant this class refuses.
    VARIANTS = ("default", "forced_circulation")
    VARIANT_ALIASES = {"default": "forced_circulation"}

ForcedCirculation("CR-102").variant                # 'forced_circulation'
ForcedCirculation("CR-102", variant="draft_tube")  # ValueError, naming the low-level form
```

An empty `VARIANTS` — what every class in the port table has, and no
[equipment class](#equipment-classes) — means "this class owns its whole kind",
and the check is skipped entirely. A non-empty one is a statement
that the rest of the kind's drawings belong to some other device, and the
constructor refuses them there and then, listing the ones this class does draw,
suggesting a near miss, and ending by naming the nearest ancestor that owns the
whole kind: a refused variant is still a drawing that exists, and
`Crystalliser(variant="draft_tube")` is how to reach it.

`VARIANT_ALIASES` maps a class-local variant name onto the registry's, for a
class that would rather spell one its own way:

```python
class Screen(Separator):
    VARIANTS = ("screen", "sifter")
    VARIANT_ALIASES = {"screen": "sifter"}

Screen("S-101", variant="screen").variant     # 'sifter'
```

**`unit.variant` stores the registry's spelling**, because that is the attribute
the symbol lookup and `pandid.portgeom` read to find the artwork. A rename is
therefore a spelling the constructor accepts, and not a second name the rest of
the package learns — so `fs.to_dict()` writes `sifter`, and a sheet written out
and read back has lost the rename. Listing both spellings in `VARIANTS`,
class-local first, is what keeps the file the class wrote a file the class
accepts.

### No symbol at all

A kind with nothing registered draws a **generic box**: an empty 60 × 60 square
with the tag beside it. Every port falls back to the centre of it, so the streams
all meet in the middle, and a connected pair of them is reported as the
`coincident-ports` warning. Nothing else is affected: the unit lays out, routes,
validates and renders. It is the cheap path when the topology is the point and
the shape of the box is not.

### What a custom unit does not get

- **A spec file.** `pandid.spec` builds units from the shipped classes by name, so
  it can neither read nor write one it has never heard of. `fs.to_dict()` raises
  `SpecError` naming the class rather than writing a spec that cannot be read
  back, and a `kind:` naming a custom class is refused the same way. A flowsheet
  using custom equipment is written in Python, not in YAML or JSON, and the CLI
  cannot draw it.
- **A row in the automatic equipment list.** `equipment_list(fs)` schedules the
  kinds listed under [Sheet furniture](#convenience-constructors), which is a
  fixed set. Name the tag in `include=[…]` to schedule it explicitly; the row
  then reads its `description`, or its kind in title case where it has none.

---

## Extension points

Both are `typing.Protocol`s. Implement the method and pass your object in.

```text
class LayoutEngine(Protocol):      # pandid.layout
    def layout(self, fs: Flowsheet) -> None: ...

class Router(Protocol):            # pandid.routing
    def route(self, fs: Flowsheet) -> None: ...

fs.layout(engine=MyEngine())
fs.route(router=MyRouter())
```

Defaults: `pandid.layout.SugiyamaLayoutEngine` (exported as
`default_layout_engine`) and `pandid.routing.DefaultRouter`.

The symbol registry is `pandid.render.symbols.default_registry`, a
`SymbolRegistry` with `register(kind, symbol, variant="default")`,
`variants(kind)` and `get(kind, variant="default")`. `get()` raises `ValueError`
for a variant that kind has no symbol for, naming the ones it does. A kind with
no symbols at all draws a generic box; registering one for a unit type of your
own is [Custom equipment](#custom-equipment).
`for_unit(unit)` is what the renderer and `pandid.portgeom` actually call: it is
`get()` for every fixed symbol, and for a symbol drawn to a size the unit
carries, such as a `Conveyor`, it builds one at that size. New *equipment*
symbols should come from the vendored stencil pipeline rather than being
hand-registered (see `CONTRIBUTING.md`).

---

## Standards

`pandid` draws in the idiom of the process-industry drawing standards. It does
not claim conformance to any of them, and nothing it produces has been certified
against one.

The set it works to is **ISO 10628-1** for the drawing rules, **ISO 15519-1** and
**-2** for what 10628-1 leaves to them, and **ANSI/ISA-5.1** for instrumentation.
No clause obliges a drawing to say which set it follows: ISO 14617-1:2025
Annex C is informative, and its *shall* asks only that the parties **agree** a
letter-code set. It is stated because the third choice is not an ISO one, and a
reader should not have to work that out from the drawing.

What it follows, feature by feature:

- **Equipment symbols** follow the conventions of **ISO 10628-2**. They are
  derived from the draw.io / diagrams.net P&ID stencil set, which makes no
  standards claim of its own, so a shape is matched to the ISO 10628-2 symbol
  where one exists rather than reproduced from the standard itself.
- **Instrument balloons, signal lines and tag letters** follow **ANSI/ISA-5.1**.
  ISO does not speak with one voice here. ISO 10628-1 §4.1 calls for
  instrumentation to IEC 62424. **ISO 15519-2:2015** is ISO's own standard for
  measurement and control on a process diagram, from the same subcommittee a
  year later, and it sends symbols to ISO 14617 and identification to IEC 81346;
  IEC 62424 and ISA 5.1 appear in its bibliography only. `pandid` takes neither
  ISO route, because ISA-5.1 is what North American practice draws and what the
  reference sheets this package was built against use. **ISO 15519-1 §7.1
  licenses half of that**, and only half: it lets another set of reference
  designation principles be used where the parties involved have agreed on it.
  That sits in clause 7, *Reference designations*, and reaches the tag
  letters. It says nothing about symbols or lines, which have no such escape:
  §11.1.1 is a `shall` that graphical symbols conform to ISO 14617 and
  IEC 60617, and §6.1 a `shall` that line types comply with ISO 128-20.
  The balloon outlines and the signal-line styles are therefore a **declared
  deviation** rather than a permitted alternative. ISA-5.1 §2.8.1(b) asks for
  agreement from its own side, that each exception be documented in the user's
  standard and on the drawing. `legend()` is where a sheet records it.
- **The gap to ISO 15519-2 is structural**, not a letter table. Its §5.1.1 builds
  the symbol from a circle or an extended circle, and its Table 1 draws
  only circles and stadiums, so the `shared` square, the `computer` hexagon and
  the `sis` and `interlock` diamonds have no ISO counterpart at all. Table 1
  codes location in three states, field / central / subsidiary, with no dashed
  line and no operator-accessibility axis. Table 2 has no `T` for transmitter
  and no `V` in any role: a transmitter is a symbol (Annex A.4.04), vibration
  falls under `S` and viscosity under `Q`. `FT-101` therefore has no reading in
  ISO 15519-2's terms at all.
- **Tag numbering** is therefore the ISA-5.1 **loop number** (`FIC-101`), not
  the IEC 81346 reference designation (`LAB01BP01`) that **ISO 15519-2** §5.3
  requires on the lower line of a symbol. A reader coming from ISO should expect
  the tags to look like this, and read it as the same documented exception.
  One ISO 15519-2 rule is enforced regardless, because it is about the letters
  and not the numbering: §5.2.4 orders the control-function letters
  I, R, C, S, M, Z, A, so `FIC` is right and `FCI` earns a `letter-sequence`
  warning on `fs.warnings`.
- **Valve fail position** is drawn as **letters**, `FO` / `FC` / `FL` / `FL/DO` /
  `FL/DC` / `FI` beside the valve, and this is a declared choice because three
  standards draw the one fact three ways. **ANSI/ISA-5.1-2009 Table 5.4.4**
  offers two of them itself, Method A as arrows or bars on the actuator stem and
  Method B as the letters, and its note 5.3.4(1) requires the user's own standard
  to record which of the two it has picked, which is what this bullet is.
  **ISO 15519-1 §11.3.1 c)** offers the third and encodes it geometrically:
  symbol 654's apex points towards the valve where the valve is closed at rest
  and away from it where the valve is open at rest, registered by
  **ISO 15519-2** Annex A.3 as
  `654V1A` fail close, `654V3A` fail open and `659A` fail freeze. `pandid` takes
  Method B on the authority of **PIP PIC001 clause 4.5.3.2**, the only one of the
  sources that chooses between the ISA pair: it calls for an automated valve's
  fail action in text, `FC`/`FO`/`FL`/`FI` after ISA-5.1, and comments against
  ISA's stem arrows. The
  placement is PIP's too, **clause 4.2.4.6(1)**, below the valve on a horizontal
  run and to the right of it on a vertical one. The reference sheets this package
  was built against draw their control valves as a bare diaphragm dome with
  neither letters nor stem arrows, so nothing on an issued drawing argued for the
  geometry, and the ISO encoding needs an actuator drawn on a stem clear of the
  body, which the stencil set this package draws from does not give it. See
  [Fail position](#fail-position).
- **A normally closed valve** is drawn with its body darkened solid on the
  authority of **PIP PIC001 clause 4.2.2.7**. It is not an ISA-5.1, ISO 10628 or
  ISO 15519 convention, and **ISO 15519-1 §11.4.5** prescribes a different
  answer: letters, not fill. See
  [Normally closed valves](#normally-closed-valves).
- **No arrowhead on a P&ID's process lines** is a declared deviation.
  **ISO 10628-1 §4.1** is unconditional: flow routes and flow directions are
  shown with lines and arrows. Two things in the same standard pull the
  other way — §4.4.2 leaves route and direction out of a P&ID's *basic*
  information and §4.4.3 b) makes it additional, and §5.3.3.3 softens the rule
  itself to arrows being incorporated in the lines — and the reference
  P&ID this package was built against draws none. A PFD keeps its heads. See
  [Which drawing this is](#which-drawing-this-is).
- **Sheet sizes** are the **ISO 216** A series, declared in millimetres on the
  SVG root so a sheet prints at its physical size.
- **The zone grid** runs **ISO 5457 §4.4**'s way: letters A.. top down, numerals
  1.. left to right, so zone A1 is the top-left corner and `location_reference`
  addresses (ISO 15519-1 Clause 9) name the region a reader would look at. The
  *ruling* is not ISO 5457's — §4.4's fixed 50 mm pitch and Table 2 field counts
  are replaced by an interval chosen to suit the sheet, and the §4.3/§4.5
  centring and trimming marks are not drawn. [Sheet size](#sheet-size) gives the
  clauses. ISO 15519-1 §5.1.2 asks for the centring marks only on a document
  prepared for microfilming.
- **The title block** carries the data fields **ISO 7200** specifies, which
  ISO 10628-1 §5.1.2 requires on a process diagram: identification number, date
  of issue, sheet number, title, approval person, creator, and legal owner,
  which is the issuing organisation and so is the `company` cell. `client` is
  not an ISO 7200 field; it is there because issued sheets carry one. ISO 7200's
  eighth mandatory field, **document type**, has no cell yet.
- **Relative line weights** follow **ISO 15519-1 §6.2**, which holds any two of
  a drawing's line widths at least 2:1 apart,
  spent as **ISO 15519-2 Annex A.1** spends it: a pipeline (A.1.01) at twice the
  weight of an instrument connection, control connection, pilot line or signal
  line (A.1.02, A.1.03). Process piping and equipment outlines are the heavy
  class; every signal kind, the instrument taps and the pneumatic cross-hatch
  are the fine one. On A3 at 1:1 that is 0,53 mm against 0,26 mm, which is the
  standard's 0,5 / 0,25 pair. See [Signal lines](#signal-lines).
- **Where a label sits on a pipe** follows **ISO 15519-1 §7.2.5**, which puts a
  connection's designation above a horizontal connecting line and to the left of
  a vertical one. That is where `pandid`
  puts a line number beside its run, turned to read bottom to top on a riser,
  which is one of the two reading directions §5.1.5 allows. §5.1.5's second
  sentence, holding a reference designation horizontal whatever way its symbol
  is turned, is a rule about a symbol's own designation and does not reach a
  connection. `pandid` also draws the number **on** the line where the run is
  long enough to carry it, which §7.2.5 words as a `should`, so that one is a
  divergence rather than a breach. See
  [Where the number sits on the line](#where-the-number-sits-on-the-line).
- **Off-page connector text** is composed by **ISO 15519-1 §9**, which reserves a
  solidus for the sheet and a full stop for the zone and fixes the sequence the
  three parts appear in. It is set out under
  [Composing a location reference](#composing-a-location-reference).
  `location_reference()` spells it, reproducing
  all seven rows of the standard's Table 2 (`7569/12.B3`, `/12.B3`, `/.B3`). A
  `reference` is still a plain string, because a document number on its own is
  what an issued sheet's flags actually carry: the three reference drawings this
  package was built against name `PFD-201`, `PFD-302`, `PCD-302` and `PFD-501`,
  and not one of them names a sheet or a zone. §12.6's placement rule, putting
  those references in the outer grid zone of the content area, is
  left to `pin()`, so the flag goes where the author puts it. Reciprocal
  references between the two ends of an interrupted line are outside the model,
  a `Flowsheet` being one sheet with no peer end to read a zone from.
- **Symbols where gravity is a functionality** are not turned. **ISO 15519-1
  §11.4.2** excepts them from the general permission to turn and mirror, naming
  the open tank (2061) and the cyclone separator (X 2618) as its two examples.
  86 registered symbols carry
  `Symbol.gravity_fixed`, and
  [Symbols that must not be turned](#symbols-that-must-not-be-turned) lists them.

The largest remaining gap against ISO 10628-1 is §5.3.1 and §5.4.2, and against
ISO 15519-1 is §6.2, whose floor is a physical one: no line of a finished
diagram on paper or equivalent media goes under 0,18 mm. Line widths and
character heights here are in drawing units and scale with the drawing, so the
weights above hold their *ratio* at any sheet size and nothing checks a width in
millimetres. (§11.1.3, the neighbouring clause, is the other rule and *is* kept:
a symbol's stroke does not change when the symbol is resized.) §7.2.3 is
unimplemented for a related reason — it asks that a single object's designation
be set off the symbol's centre lines, and `_label_place` puts every label
on one, the label having been placed to clear ink rather than to clear a
centre line.

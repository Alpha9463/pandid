# API reference

Everything a process engineer touches, verified against the source. Anything not
listed here is either internal or not part of the supported surface.

> **Scope.** `pandid` draws diagrams. There is **no mass or energy balance engine**:
> stream properties are strings you supply, and nothing is computed from them.
> `pandid.state.State` and the `state` slots on `Port`/`Stream` are reserved for a
> future backend and are never written by this library.

```python
from pandid import Flowsheet, Component, units
import pandid
pandid.__version__          # the installed version, e.g. "0.0.1"
```

---

## `Flowsheet`

```text
Flowsheet(name: str, *,
          stream_naming_scheme: str | Callable[[int], str] = "S{n}",
          line_numbering_scheme: str | Callable[[Stream], str]
              = "{size}-{service}-{sequence}-{spec}",
          line_number_start: int = 1001,
          auto_faces: bool = True)
```

The container and the single source of truth for connectivity.

- `stream_naming_scheme` is either a format string taking `{n}` (default
  `"S{n}"` → `S1`, `S2`, …) or a callable `int -> str`. Keyword-only.
- `line_numbering_scheme` is either a format string taking the line-number
  components (`{size}`, `{service}`, `{sequence}`, `{spec}`, `{insulation}`) or
  a callable `Stream -> str`, for a site whose convention is spelled some other
  way. Keyword-only. See [Line numbers](#line-numbers).
- `line_number_start` sets where the automatic sequence begins (default `1001`,
  so the first line is `…-1001-…`). Keyword-only.
- `auto_faces` lets the engine choose which face each movable port is piped
  from. See [automatic face selection](#automatic-face-selection). Keyword-only.

### Attributes

| Attribute | Type | Notes |
|---|---|---|
| `units` | `list[Unit]` | in insertion order |
| `streams` | `list[Stream]` | in creation order |
| `components` | `list[Component]` | |
| `auto_faces` | `bool` | engine picks movable ports' faces; default `True` |
| `warnings` | `list[Issue]` | soft findings from the last render |
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

The one exception is a **trip square** (`Instrument(variant="sis")`, its
`"logic"` spelling, or `variant="interlock"`), which is a logic function rather
than a device and is drawn at every place it acts, carrying the same tag each
time. A repeat is accepted and given a name of its own, so a stream endpoint, a
spec entry or an equipment-list row still means exactly one square. The two are
different ISA-5.1 symbols, so a tag drawn as both is still a clash:

```python
squares = [fs.add_instrument("I", 1, variant="logic") for _ in range(4)]
[s.tag for s in squares]     # ['I-1', 'I-1', 'I-1', 'I-1']   drawn four times
[s.name for s in squares]    # ['I-1', 'I-1 (2)', 'I-1 (3)', 'I-1 (4)']
```

Nothing else repeats. A second `LT-101` balloon is one loop number used twice,
and a square sharing its tag with a balloon is two symbols claiming to be the
same thing; both raise.

```text
connect(src: Port, dst: Port, *,
        kind: str = "material",
        name: str | None = None,
        tear_hint: bool = False,
        size=None, service=None, sequence=None, spec=None, insulation=None) -> Stream
```
Creates the stream. `src` must be an outlet and `dst` an inlet, both units must
already be on this flowsheet, and neither port may already carry a stream. Each
of those raises `ValueError`.

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

`name` overrides the auto-generated stream number. `tear_hint=True`
is advisory, nudging the cycle breaker toward tearing *this* edge when a recycle
loop is ambiguous.

`size` / `service` / `spec` / `insulation` are the line-number components, given
as text or a number. Supplying any of them identifies the line by its line
number instead of a stream number. `sequence` is filled by auto-numbering unless it is
given here. See [Line numbers](#line-numbers).

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
add_instrument(type, number="", *, on=None, at=None,
               offset=45.0, angle=90.0, variant="default", **kwargs) -> Instrument
```
See [Instrumentation](#instrumentation).

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
       styling: str = "default",
       page_size: str | None = None,
       jump_direction: str = "vertical",
       check: bool = True) -> str
```
Returns the SVG string, running `layout()` and `route()` first if they have not
run. With `check=True`, validation errors raise `ValueError` and warnings land
on `fs.warnings`.

```text
render(path: str | Path, *, show_stream_table=False, border=None,
       styling="default", page_size=None, jump_direction="vertical",
       check=True) -> None
```
Writes the drawing. The format comes from the extension: `.svg` (or no
extension) is pure Python; `.pdf` and `.png` need the optional `cairosvg`
backend and raise `ImportError` without it. Any other extension raises
`ValueError`.

```text
show() -> None                   # render to a temp file and open a browser
_repr_svg_() -> str              # Jupyter renders a flowsheet inline
```

### Rendering options

| Option | Values | Effect |
|---|---|---|
| `border` | `"none"`, `"zone"` | `"zone"` rules the sheet with the ASME-style zone-lettered drawing frame. Anything else raises `ValueError` |
| `styling` | `"default"`, `"pid"` | the older spelling of the same choice: `"pid"` means `border="zone"` |
| `show_stream_table` | `bool` | draws the stream property table (one column per unique material stream) |
| `check` | `bool` | run `validate()` first; errors raise, warnings collect |
| `page_size` | `None`, `"A4"`, `"A3"`, `"A2"`, `"A1"`, `"A0"` | `None` (the default) sizes the sheet to the drawing; a name draws a sheet of exactly that size |
| `jump_direction` | `"vertical"`, `"horizontal"` | which of two crossing lines gets the semicircle hop |

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
size it needed.

---

## Units and ports

Every unit type is reached through the `units` namespace. Ports are exposed both
as `unit.ports["name"]` and as attributes (`pump.suction`). An unknown attribute
raises `AttributeError` listing the real ports, and `unit.port("name")` raises
`KeyError` the same way. A type of your own is
[Custom equipment](#custom-equipment).

```text
Unit(name, variant="default", width=None, height=None,
     label_pos=None, description="", reference="")
```

- `name` is the equipment tag. It must be non-empty, and unique on the flowsheet
  save for the one symbol that repeats (see
  [Building the topology](#building-the-topology)).
- `variant` is the visual style within the class (see below). A name that kind
  has no symbol for raises `ValueError` listing the ones it does, at the first
  layout or render.
- `width` / `height` override the symbol's intrinsic size. They are taken as the
  *final* box, so a rotated unit gets exactly what you asked for.
- `label_pos` is `"top"`, `"bottom"`, `"left"`, `"right"` or `"center"`. Left
  unset, the engine picks the first free face in top → bottom → right → left
  order, so a nozzle's stream does not run through the tag.
- `description` is free text, and feeds the auto equipment list.
- `reference` is the off-page drawing reference, drawn as a boundary flag's
  second line. Only `Feed` and `Product` have that line, so giving it to
  anything else raises `ValueError`.

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
| `Vessel` | `vessel` | `inlet` *(in)*, `outlet` *(out)*, `vent` *(out/vapor)* |
| `Tank` | `tank` | `inlet` *(in)*, `outlet` *(out)* |
| `Separator` | `separator` | `feed` *(in)*, `vapor` *(out/vapor)*, `liquid` *(out/liquid)* |
| `Column` | `column` | `feed` *(in/feed)*, or `feed_1` … `feed_n`, `distillate` *(out/vapor)*, `bottoms` *(out/liquid)*, `reflux_in` *(in/liquid)*, `boilup_in` *(in/vapor)*, `reboiler_duty` *(in/energy)*, `condenser_duty` *(out/energy)* |
| `Reactor` | `reactor` | `feed` *(in/feed)*, or `feed_1` … `feed_n`, `outlet` *(out)*, `vent` *(out/vapor)*, `duty` *(in/energy)* |
| `HeatExchanger` | `hex` | `hot_in`, `hot_out`, `cold_in`, `cold_out`; `kettle` adds `bottoms` *(out/liquid)* |
| `Heater` | `heater` | `inlet` *(in)*, `outlet` *(out)*, `duty` *(in/energy)* |
| `Cooler` | `cooler` | `inlet` *(in)*, `outlet` *(out)*, `duty` *(out/energy)* |
| `Furnace` | `furnace` | `inlet` *(in)*, `outlet` *(out)*, `fuel` *(in/feed)* |
| `Filter` | `filter` | `inlet` *(in)*, `outlet` *(out)* |
| `Dryer` | `dryer` | `feed` *(in/feed)*, `product` *(out)* |
| `Conveyor` | `conveyor` | `feed` *(in/feed)*, `discharge` *(out)* |
| `Reducer` | `reducer` | `inlet` *(in)*, `outlet` *(out)* |
| `Fitting` | `fitting` | `inlet` *(in)*, `outlet` *(out)* |
| `Ejector` | `ejector` | `motive` *(in/utility)*, `suction` *(in)*, `discharge` *(out)* |
| `Vent` | `vent` | `inlet` *(in/vapor)* |
| `Funnel` | `funnel` | `outlet` *(out/feed)* |
| `Instrument` | `instrument` | `pv` *(in/signal)*, `sig_in` *(in/signal)*, `sig_out` *(out/signal)* |
| `Mixer` | `mixer` | `in_1` … `in_n` *(in)*, `outlet` *(out)* |
| `Splitter` | `splitter` | `inlet` *(in)*, `out_1` … `out_n` *(out)* |

Variable-port constructors take their count first:

```text
units.Mixer(name, n_inlets=2, variant="default", width=None, height=None,
            description="")
units.Splitter(name, n_outlets=2, variant="default", width=None, height=None,
               description="")
units.Column(name, n_feeds=1, variant="default", width=None, height=None,
             label_pos=None, description="")
units.Reactor(name, n_feeds=1, variant="default", width=None, height=None,
              label_pos=None, description="")
```

(`Mixer` and `Splitter` do not accept `label_pos`, unlike the fixed-port
classes.)

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

`Conveyor` takes a `length` instead of a `width`:

```text
units.Conveyor(name, length=80, variant="default", label_pos=None,
               description="")
```

`length` is the belt run. The symbol is a bar between two rollers and is drawn
to that length, so a longer conveyor grows the bar and its rollers stay the same
circles. It is the unit's whole size: `width=` and `height=` size the drawn box
instead, which would stretch the rollers, so a `Conveyor` refuses them and names
`length` in their place. A quarter turn stands the belt on end, where the length
is its height. The minimum is 40, two roller diameters, below which the rollers
overlap. `feed` is the tail end and can also be taken from the top face, since
material is dropped onto a belt rather than piped into it; `discharge` is the
head end and can also be taken from underneath, for a chute.

`Valve.actuator` is the signal connection on the valve, not a process nozzle. It
is where a controller output or an interlock terminates, and it will not take
process fluid. It sits on the top of the symbol, so the signal stops where it
meets the valve rather than running on into the body.

`unit.significant = True` on an inline unit (valve, reducer, fitting) breaks the
stream number across it (see [Stream numbering](#stream-numbering)).

### Variants

A **class** is a functional equipment type, defined by its ports. A **variant**
is a visual style within it. The first name in each list is that kind's
`default`, with the shape it draws in brackets.

| Class | Variants |
|---|---|
| `Pump` | `default` (centrifugal), `gear`, `screw`, `vacuum`, `peristaltic`, `submersible` |
| `Compressor` | `default`, `liquid_ring`, `reciprocating`, `rotary` |
| `HeatExchanger` | `default`, `shell_tube`, `straight_tubes`, `finned`, `plate`, `kettle`, `u_tube`, `hairpin`, `double_pipe`, `condenser`, `air_cooled`, `spiral`, `thin_film` |
| `Vessel` | `default`, `dished`, `jacketed`, `skirted`, `dome`, `horizontal` |
| `Tank` | `default` (dished roof), `conical`, `floating_roof`, `sphere` |
| `Separator` | `default` (knock-out drum), `horizontal`, `cyclone`, `gravity`, `scrubber`, `electrostatic` |
| `Reactor` | `default`, `plain` |
| `Column` | `default` (plain shell), `packed` |
| `Filter` | `default`, `gas`, `press`, `rotary`, `ion_exchange` |
| `Dryer` | `default`, `fluidized_bed`, `spray` |
| `Valve` | bodies: `default` (gate), `gate`, `globe`, `ball`, `butterfly`, `check`, `needle`, `three_way`, `control`, `plug`, `pinch`, `angle`, `psv`, `relief`, `bleed`<br>with a drawn operator: `motor`, `solenoid`, `hydraulic`, `pneumatic`, `manual`, `knife`, `butterfly_pneumatic`, `regulator` |
| `Fitting` | `default` (flanged connection), `flange`, `strainer`, `strainer_cone`, `orifice`, `rotameter`, `rupture_disc`, `sight_glass`, `sight_glass_lit`, `silencer`, `expansion_joint`, `static_mixer`, `hose`, `coupling`, `clamped_coupling`, `flame_arrestor`, `flame_arrestor_explosion_proof`, `flame_arrestor_detonation_proof`, `flame_arrestor_fire_resistant` |
| `Instrument` | `default` (field balloon), `panel`, `aux`, `shared`, `computer`, `sis` (diamond in a square, also spelled `logic`), `interlock` (plain diamond) |
| `Heater`, `Cooler`, `Furnace`, `Turbine`, `Blower`, `Reducer`, `Ejector`, `Vent`, `Funnel`, `Conveyor`, `Mixer`, `Splitter`, `Feed`, `Product` | `default` only |

`HeatExchanger(variant="kettle")` carries a fifth nozzle, `bottoms`. It is the
draw at the weir end of the shell, where what does not boil leaves as the
tower's bottoms product. No other exchanger has a weir, so no other variant has it, and
asking a plate exchanger for `.bottoms` raises.

Every exchanger answers to the same four nozzles, but not all four are piped
across the symbol. `hairpin` and `double_pipe` turn the tube round at the far
end and bring it back, so both tube nozzles are on the same face. `air_cooled`
is a fin-fan: the bundle is the piped side and is named hot, and the air is the
cold stream, drawn in under the bundle (`cold_in` on S) and out through the fan
(`cold_out` on N). `thin_film` is an evaporator standing on end, fed onto the
wiper at the top and drawing concentrate off the cone at the bottom, with the
jacket as the hot side.

`Column(variant="packed")` draws two beds of packing between their support
grids, which is the one column symbol with an internal. Its nozzles are the
default column's, at the same heights, so a sheet already drawn does not move
when the variant changes.

`Vessel(variant="jacketed")` puts `inlet` and `outlet` on the jacket's outer
wall rather than on the shell inside it, so the line stops where it meets the
equipment instead of being drawn across the jacket.

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

---

## Placement

### `pin`

```text
unit.pin(*, col=None, row=None, x=None, y=None,
         orientation=unchanged, mirrored=unchanged) -> Unit
```

Records placement **intent** and returns the unit, so it chains off `add()`.
The layout engine reads it and resolves the final geometry. Pinned axes are
honoured exactly, and unpinned units are placed around them. Grid intent
(`col`/`row`) and absolute intent (`x`/`y`) may be mixed, and absolute wins for
whichever axis it sets. `x`/`y` are the unit's frame origin, its **top-left
corner** in SVG coordinates, not its centre and not a nozzle.

A port sits at a fixed *fraction* of its symbol's box, so lining two items up
means matching those fractions, not their corners. `Feed` is the one exception
to "origin = top-left": its width is sized to its label text and the flag is
drawn extending **left** from `x + 50`, which is where its outlet nozzle sits.

```python
hx = fs.add(units.HeatExchanger("E-1")).pin(x=100, y=50)
fv = fs.add(units.Valve("FV-1")).pin(col=2, row=1, mirrored=True)
```

Calling `pin()` more than once merges: only the arguments you pass are updated,
`orientation` and `mirrored` included, so a later bare `pin(x=…)` nudges the
unit along without undoing a turn or a flip. A unit that has never been pinned
starts square and unflipped. Pass `orientation=0` / `mirrored=False` to put one
back.

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
| `Instrument` (`default`, `panel`, `aux`, `shared`, `computer`) | `pv`, `sig_in`, `sig_out` | `N`, `S`, `E`, `W` |

(The trip squares — `Instrument(variant="sis")`, `"logic"` and `"interlock"` —
offer no choice either.)
The home is the symbol's own nozzle. It is where the port sits with
`auto_faces` off, and the first entry of the menu the engine chooses from with
it on.

```python
# Both of these are conventions the geometry alone would not arrive at: the
# engine takes the shortest run, and a shortest run is not always the drawing.
drum = fs.add(units.Separator("V-1", variant="horizontal"))
drum.nozzle("feed", "N")      # always from above, however the header is laid in

lic = fs.add_instrument("LIC", 101, on=vessel, at="S", variant="panel")
lic.nozzle("sig_out", "W")    # keep the loop's output on the panel side
```

`port_face()` is the deprecated spelling of the same call. It read its `face` in
the symbol's own frame, so on a mirrored or rotated unit it names a different
face than `nozzle()` does. See the CHANGELOG.

---

## Streams

`connect()` returns a `Stream`. Useful members:

| Member | Type | Notes |
|---|---|---|
| `name` | `str` | the stream number, or the line number where the line has one; auto-assigned unless you passed `name=` |
| `source` / `dest` | `Port` | |
| `kind` | `str` | see `connect()` |
| `size` / `service` / `sequence` / `spec` / `insulation` | `str \| float \| None` | line-number components; `sequence` is filled by auto-numbering |
| `has_line_number` | `bool` | **read-only**, true once a component other than `sequence` is set |
| `is_recycle` | `bool` | **read-only**, computed by cycle detection during layout |
| `properties` | `dict[str, str \| float]` | free-form; rendered by the stream table verbatim |
| `color` | `str \| None` | SVG stroke colour override |
| `dasharray` | `str \| None` | SVG `stroke-dasharray` override |
| `route` | `Route \| None` | resolved waypoints; written by the router |

```text
via(waypoints: list[tuple[float, float]]) -> Stream
```
Forces the stream through those exact orthogonal pixel waypoints, overriding the
auto-router for that one stream. Chains off `connect()`:

```python
fs.connect(feed.outlet, hx.cold_in).via([(130, 65), (130, 110)])
```

### Stream numbering

`renumber_streams()` runs automatically inside `connect()` and again inside
`to_svg()`, so the number on the stream object you hold is the number the sheet
gets drawn with, and `s.name` can go straight into a report. A stream keeps its
number as it passes through an inline valve, reducer or fitting. Set
`unit.significant = True` to break the number at a unit that matters, which
renumbers the flowsheet there and then. Explicitly named streams are never
renumbered, and an explicit name on one segment names its whole group.

Process streams take the low numbers, energy streams (also drawn) follow, and
unlabelled signal lines come last. One sequence covers all three, so no two streams answer
to the same name and an energy or signal line never consumes a process number.

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

The components are `size`, `service`, `sequence`, `spec` and `insulation`, each
text or a number. The author supplies all but `sequence`, which auto-numbering
fills from `line_number_start` (default `1001`); set it yourself to tie into a
line that already exists on someone else's list. A component left unset drops
out, and so does the text introducing it, so a line with no spec issued yet
reads `6"-P-1001` rather than `6"-P-1001-`.

A line number is assigned by `renumber_streams()`, on exactly the terms a stream
number is: it carries **through** an inline valve, reducer or fitting, and
breaks at a unit marked `significant`, which is where the spec break goes. The
first segment of a group that carries components supplies them for the whole
group, so a run does not have to repeat its identity at every fitting. A stream
named explicitly with `connect(name=…)` is never reformatted, and a stream with
no components set is numbered exactly as it always was.

`line_numbering_scheme` spells the convention, as a format string over the
component names or as a callable taking the `Stream`. A format spec applies, so
a site that pads its sequence says so:

```python
Flowsheet("U100", line_numbering_scheme="{size}-{service}-{sequence:0>6}-{spec}-{insulation}")
Flowsheet("U100", line_numbering_scheme=lambda s: f"{s.service}-{s.size}-{s.sequence}")
```

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

On a vertical run the label is turned a quarter clockwise, so it reads bottom to
top and never upside down: the aligned-text convention of ISO 129-1 and
ASME Y14.5.

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

---

## Instrumentation

```text
fs.add_instrument(type, number="", *, on=None, at=None,
                  offset=45.0, angle=90.0, variant="default", **kwargs) -> Instrument
```

Constructs an `Instrument`, adds it, and attaches it when `on` is given. Extra
`**kwargs` go to the `Instrument` constructor (`width`, `height`, `label_pos`,
`description`).

`type` is the functional letter string and `number` the loop number.
`instrument.tag` is the full tag (`"FT-101"`) for equipment lists and
cross-references, while the balloon draws the letters over the **bare** number,
as a real sheet does. `units.Instrument("FT-101")` is also accepted and split.
`unit.name` is the same tag, except on a repeated interlock square where it is
what tells one square from another (see
[Building the topology](#building-the-topology)).

```python
ft  = fs.add_instrument("FT", 101)                        # field transmitter
fic = fs.add_instrument("FIC", 101, variant="panel")      # panel-mounted controller
fy  = fs.add_instrument("FY", 101, variant="computer")    # computing relay
```

### Attaching a balloon

```text
instrument.attach(on, *, at=None, offset=45.0, angle=90.0) -> Instrument
```

- `on` is the host: a `Stream` (tap the line) or a `Unit` (mount on equipment).
  Anything else raises `TypeError`, and attaching a balloon to itself raises
  `ValueError`.
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

An impulse line is drawn from the tap to the balloon: a fine solid line to a
process host, dashed where a balloon hangs off another balloon. Attached
balloons take no part in layout ranking and are drawn over the lines, so neither
an in-line element nor a stream number is lost underneath one. Balloons chain,
so an alarm on a controller on a transmitter resolves in order.

```python
s   = fs.connect(feed.outlet, fv.inlet)
fs.add_instrument("FE", 101, on=s, at=0.4, offset=0)                    # on the line
ft  = fs.add_instrument("FT", 101, on=s, at=0.4, offset=60)             # above the tap
lic = fs.add_instrument("LIC", 101, on=drum, at="E", variant="panel")   # on the drum
fs.add_instrument("LAH", 101, on=lic, at="N", offset=48)                # alarm
fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")   # interlock
```

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
    client="Aromatics Australia Pty Ltd",     # above the title, as ISO 5457 has it
    project="Aromatics Recovery Unit",
    company="THE UNIVERSITY OF QUEENSLAND",   # logo / company cell
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
and none when they do not.

`scale` is the scale cell. Left blank it reports the ratio the drawing was
actually placed at, which is a real number as soon as `page_size` fixes the
page (`1:2.47`) and nothing at all on a sheet sized to fit its drawing, since
there is then no scale to state. Give it a value to state one regardless:

```python
fs.title_block = TitleBlock(title="Transfer and Relief U100", scale="NTS")
```

A value too long for its cell is trimmed with an ellipsis rather than run across
the rule into the cell beside it.

### `Annotation` and `TableBox`

```text
Annotation(title="", rows=[], align="top-right", position=None,
           margin=0.0, width=None, font_size=11.0, anchor=None)

TableBox(title="", headers=[], rows=[], align="bottom-right", position=None,
         margin=0.0, font_size=11.0, col_align=None, anchor=None)
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

`anchor=` is a deprecated alias for `align=`. When both are given, `anchor`
wins.

### Convenience constructors

```text
from pandid.document import equipment_list, notes, legend

equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right", anchor=None,
               position=None, margin=0.0, include=None, width=None)
notes(items, *, title="NOTES", align="top-right", anchor=None, position=None,
      margin=0.0, numbered=True, width=None)
legend(entries, *, title="LEGEND", align="top-left", anchor=None,
       position=None, margin=0.0, width=None)
```

All three return an `Annotation`. `legend()` accepts a dict or a sequence of
`(abbr, meaning)` pairs.

`equipment_list()` schedules **major equipment** as `(tag, description)`:
vessels, columns, tanks, reactors, separators, exchangers, heaters, coolers,
furnaces, pumps, compressors, blowers, turbines, ejectors, filters, dryers and
conveyors.
Valves, fittings, reducers, vents and funnels are bulk items bought by the line
and covered by the piping class; mixers and splitters are junctions in that
line; feeds, products and instruments are not equipment. None of them is
scheduled. Where a unit has no `description`, the row says what its kind is
called (`E-101` reads `Heat Exchanger`).

`include=[…]` names the rows explicitly instead, in the order given, and takes
whatever it names. That is how a valve schedule, a real drawing in its own
right, is built from the same flowsheet. A tag that is not on the flowsheet
contributes no row.

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

---

## Validation

```python
issues = fs.validate()        # list[Issue], errors first
for i in issues:
    print(i)                  # "[warning] route-detour: stream S3 routes ..."
```

`Issue` is a frozen dataclass with `severity` (`"error"` / `"warning"`), `code`
and `message`.

| Code | Severity | Meaning |
|---|---|---|
| `pin-not-finite` | error | a pinned `x`/`y` is not a finite number |
| `pin-out-of-bounds` | error | a pinned `x`/`y` is negative (off-sheet) |
| `unit-overlap` | error | two units' drawn boxes overlap |
| `coincident-ports` | error | two connected ports on one unit resolve to the same point |
| `coincident-ports` | warning | …and one of them is a port the symbol never anchored, so it fell back to the centre of the box. No shipped symbol has such a gap, so this covers symbols registered from outside the package |
| `route-crosses-unit` | warning | a stream passes through a unit body it does not connect to |
| `route-detour` | warning | a route is more than 3× its direct span |

Errors raise from `to_svg()`/`render()` unless you pass `check=False`. Warnings
never raise, and collect on `fs.warnings` after each render. Geometric checks
need resolved frames, so they are skipped before layout has run.

---

## Command line

Installing the distribution installs a `pandid` command. `python -m pandid` is the
same entry point, for a checkout or an environment whose scripts directory is
not on PATH. It is a shell over the API above and adds nothing to it.

```text
pandid draw SPEC [-o OUT] [--page-size SIZE] [--border {none,zone}]
                 [--stream-table] [--jump-direction {vertical,horizontal}]
pandid validate SPEC
pandid symbols [--kind KIND]
```

`SPEC` is a spec file: `.yaml` or `.yml` (needs the `yaml` extra) or `.json`.
Any other extension is refused rather than guessed at. The format itself is
`pandid.spec`, documented in the README.

### `draw`

Renders the spec and writes it. The output format comes from `-o`'s extension,
exactly as [`render()`](#geometry-and-output) decides it: `.svg`, or `.pdf` /
`.png` with the `pdf` extra. Without `-o` the drawing goes next to the spec,
under the same name with `.svg`.

| Option | The same as |
|---|---|
| `--page-size A3` | `page_size="A3"` |
| `--border zone` | `border="zone"` |
| `--stream-table` | `show_stream_table=True` |
| `--jump-direction horizontal` | `jump_direction="horizontal"` |

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
Valve  default  angle  ball  butterfly  butterfly_pneumatic  check  control  gate  globe
       hydraulic  knife  manual  motor  needle  pinch  plug  pneumatic  psv  regulator
       relief  solenoid  three_way
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | the command did what it was asked |
| `1` | the flowsheet was rejected: the spec could not be read or understood, validation found an error, or the engine refused the request (an unknown page size, an output extension it cannot write, a page too small for its own furniture) |
| `2` | the command line was wrong: an unknown flag, a missing argument, an option value the CLI checks itself |
| `3` | an optional extra the request needs is not installed: PyYAML for a YAML spec, cairosvg for `.pdf` / `.png` |

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

Ports are built in declaration order, once, when the unit is constructed.
`_PORTS` is the name `PORTS` had while it was private; it is still read, so a
unit written against it keeps its nozzles, and it warns `DeprecationWarning`.

Everything a shipped class has, a custom one has: `pin()`, `nozzle()`,
`description`, `label_pos`, `width`/`height` and the rest of the
[`Unit` constructor](#units-and-ports).

### The symbol

Without a symbol the unit draws a generic box (below). To draw it properly,
register a `Symbol` under the same `kind`:

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
if that changes the aspect ratio — which is what a shell, a tank or an exchanger
wants, since the user asked for a box and the equipment simply becomes it. Pass
`stretchable=False` where the shape carries meaning instead: an ISA-5.1 balloon
is a circle at every size, so it keeps its proportions and is centred in the box,
and its ports are resolved against the artwork rather than the box edge the
artwork no longer reaches.

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

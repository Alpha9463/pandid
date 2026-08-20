# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `Absorber` and `Stripper`, a `Column` missing the return nozzles it does
  not have: an absorber carries no `reflux_in`, `boilup_in`,
  `reboiler_duty` or `condenser_duty`, and a stripper keeps the reboiler
  loop but not the condenser's. Both keep `internals=`, `trays=`,
  `n_feeds=` and `feed_stages=` unchanged; `Absorber` defaults
  `internals=` to `"packing"`.
- `Column(feed_stages=)` puts a feed on the stage it enters, in place of the
  even spread `n_feeds` draws by default.
- `Column(n_draws=)`, a side draw: `draw` / `draw_1` … `draw_n` on the east
  face, opposite the feeds, defaulting to zero since most columns have none.
  `draw_stages=` places one on a stage the same way `feed_stages=` does. A
  type checker resolves `col.draw_2` for a literal `n_draws=2` the same way
  it resolves `col.feed_2`; naming both `n_feeds` and `n_draws` above one at
  once falls back to the plain `Column`.
- `Feeder` for ISO 10628-2 group 19: `general`, `rotary_valve`,
  `rotary_table` and `metering`, plus `RotaryValveFeeder`,
  `RotaryTableFeeder` and `MeteringFeeder`.
- `SprayNozzle` for item 19.5, ticked on both faces.
- `Fitting` gains `rotary_mixer` (item 12.1 X2672) and `mixing_path`
  (item 12.3 X8184); `static_mixer` is registered as item 12.2 X2673.
- `Kneader` for item 12.4 X8134.
- `ScreeningDevice` for ISO 10628-2 group 7's seven rows -- `general`,
  `coarse_rake`, `fine_rake`, `coarse_and_fine`, `vibrating`,
  `rotating_drum` and `basket_reel` -- plus `CoarseRakeScreen`,
  `FineRakeScreen`, `CoarseAndFineScreen`, `VibratingScreen`,
  `RotaryDrumScreen` and `ReelScreen`. Not `separator/sifter`, which
  ships a different outline and stays `devices.Screen`.

### Fixed

- `Reactor(agitator="propeller")` and `agitator="impeller"` draw instead of
  raising.
- A type checker resolves `reactor.feed_2`, as it already did `mixer.in_2`.
- `Valve(variant="three_way")` anchors its third leg, `branch`; `ThreeWayValve`
  reaches it by name.
- A line number with its first scheme component unset no longer opens with a
  stray separator, e.g. `AE-1001-SS` rather than `-AE-1001-SS`.

## [0.1.3] - 2026-08-19

### Added

- Symbols can be composed from a body and ISO 10628-2's supplementary parts.
  All 37 parts of groups 26–29 ship, plus item 20.6's drive motor.
- `Reactor`, `Column`, `Vessel` and `Separator` say what is inside them:
  `agitator=`, `internals=`, `trays=`, `supports=`, `characteristic=`.
- `Reactor(variant="tubular")` draws a plug-flow reactor; `internals="packing"`
  a packed bed, `internals="fluidised_bed"` a fluidised one.
- `Crusher` and `Mill` for the jaw, cone, roller, hammer, impact and vibration
  types. Closes #218.
- `Centrifuge` for ISO 10628-2 group 9's eight rows, and `CrushingMachine` for
  item 11.1 X8084.
- `CoolingTower`, `VenturiScrubber`, `Elevator`, `Conveyor(variant="screw")`
  and `tank/gas_holder`.
- `Boiler`, `Stack` and `Flare`.
- `Dryer` gains `shelf`, `turbo` and `belt`; `cooling_tower` gains `general`
  and the eight ISO 10628-2 group-5 draught and fill drawings.
- `Conveyor(diameter=)` sets the roller a belt runs on, or the bore a screw
  turns in. `length=` is unchanged.
- A cake-forming filter draws its cake and its wash: `wash_in` and `cake` on
  `press`, `belt`, `rotary` and `rotary_scraper`; `regenerant_in` and
  `spent_regenerant` on `ion_exchange`.
- Five new examples: a stirred reactor train, a fixed-bed recycle loop, an
  absorber–stripper pair, a molecular sieve dryer and an alumina refinery.
- draw.io exports a composed symbol as a group of cells.
- A type checker resolves `mixer.in_1`, `splitter.out_2`, `column.feed_2` and
  `block.in_3`, and refuses a number the unit was not built with.
- `pinned_x()` and `pinned_y()` give the coordinate a pinned unit or one of
  its nozzles sits at.
- `Stream.at_boundary` is true when one end of a line is a `Feed` or a
  `Product`. `Stream.tabulate` marks which segment of a run the stream table
  reads.
- Three new `validate()` findings: `symbol-out-of-aspect`,
  `boundary-flow-missing` and `route-diagonal`.

### Changed

- **`pin(x=…, y=…)` on a `Feed` or a `Product` places the nozzle, not the frame
  corner.** Pass `port=None` for the old behaviour.
- `reactor/default` is a stirred tank with its agitator inside the shell and its
  motor above. The old drawing is `variant="mixing"`.
- A `Column` says what is inside it, and is drawn bare until it does.
- The stream table draws only the columns that carry something. A line to or
  from the sheet edge keeps its column and is reported if it is empty.
- The example columns carry the internals their service really has.
- Comments and docs cite the standards rather than reproducing their text, so
  no third-party clause ships in the package.
- Routing a dense sheet is an order of magnitude faster; `layout()` on a sheet
  that stacks is four times faster; building a large sheet is no longer
  quadratic in its own size.
- A supplementary part stretches with the body it is drawn in, and `Overlay`
  can mirror one.

### Deprecated

Each of these draws a **different** symbol from the spelling it replaces.

- `Reactor(variant="mixing")` → `Reactor(agitator="disc")`
- `Reactor(variant="plain")` → `Reactor(internals="packing")`
- `Vessel(variant="legs")` → `Vessel(supports="leg")`, `"skirted"` →
  `supports="skirt"`
- `Separator(variant="gravity")`, `"electrostatic"`, `"electromagnetic"` →
  `characteristic=`. These three draw the same symbol as before.

### Removed

**Breaking.** The six spellings 0.1.2 deprecated are gone.

- `add_instrument(on=…)` and `on:` in a spec → `sensing=`, `acting_on=` or
  `near=` (#137)
- `Instrument(variant="panel")` → `display="central"`; `"aux"` →
  `display="subsidiary"` (#181)
- `Valve(variant="pneumatic")` → `variant="control"` (#136)
- `vapor` and `liquid` on a cyclone, gravity or electrostatic separator →
  `overflow` and `underflow`

### Fixed

- A non-finite coordinate no longer hangs the render.
- A render checks the model before it builds any geometry, so a sheet the
  validator would reject no longer reaches the router.
- The spec can express a composed unit, and a spec read back carries its loop
  series on.
- A balloon round-trips through a spec with its placement and every field it
  carries.
- An edit made after a render reaches the next one, `layout()` called by hand
  takes the routes with it, and `layout()` draws the same sheet every time.
- Pins outside the first row or column are honoured: a row above the sheet no
  longer crashes, a pinned column no longer drags its upstream off the page,
  rebasing a stacked sheet no longer overwrites a pinned row, and a north
  satellite stays above the unit it feeds.
- A stream that jogs between its nozzles stays on both of them; the separation
  pass no longer resolves two runs closer than its own minimum; and the
  fallback route is checked against the obstacles before it is drawn.
- The zone grid runs ISO 5457's way: letters down, numerals right.
- Twelve filter and strainer symbols draw their dashed screen again, so the two
  backends draw the same equipment.
- A packed-bed reactor no longer comes out with a stirrer in the bed, and three
  stirred vessels were drawn out of shape.
- A stream-table column takes its values from the whole run.
- `Instrument("FT101")` is named `FT-101`, so a spec that references it loads.
- `Tee.branch_direction` is read off the branch nozzle rather than stored.
- `GravitySeparator` and `ElectrostaticPrecipitator` no longer warn about a
  variant their author never wrote, and `validate()` no longer reports
  `letter-sequence` against `ZSC`.
- A `label_pos` no side answers to is refused rather than silently drawn on top.
- Auto-numbering no longer walks over a stream name an author already used.
- A balloon layout could not place no longer makes `validate()` silent about
  the rest of the sheet.
- A hop is drawn only where there is room for its arc, so one no longer lands
  on the corner beside a crossing.
- A crossing the draw.io export cannot hop the right way round is drawn flat
  rather than the wrong way round, and is reported.
- Six things the draw.io export dropped without saying so are now reported;
  `fs.warnings` describes the last render and nothing earlier; and routing says
  why it left a stream undrawn.
- `pandid validate` takes `--diagram`, and `pandid draw missing.yaml` reports
  the missing file rather than a missing package.
- `examples/14_tank_farm.py` draws the signal from each transmitter to its
  indicator. `examples/10` and `examples/13` take cake from the filter's `cake`
  nozzle instead of teeing off the filtrate.

### Security

- A spec file could put script into the sheet drawn from it. Every string a
  user supplies is now escaped, and ids built from one are valid ids.
- A colour that is not a colour is refused rather than escaped.
- The sdist names the paths it must not ship rather than inheriting them from
  `.gitignore`.

## [0.1.2] - 2026-08-05

### Added

- **Alarms are lettered beside their controller instead of drawn as their own
  balloon (#253).** `instrument.annotate(high=…, low=…, safety=…, variable=…)`
  writes the codes in ISO 15519-2 §5.1.3's quadrants and draws no line to
  them. A balloon claimed a second instrument that appears on no list, and
  spent a face. The draw.io export writes them too.

- **A primary element and its balloon share one tag (#249).**
  `fs.add_balloon(element)` draws the tag in a balloon on a short impulse
  line; `element.tag` goes empty and `element.balloon` is the balloon. Tagging
  the fitting and its balloon alike was refused, so a sheet had to invent a
  junk tag. The four flow loops in the corpus are drawn this way; the
  pressure, level and temperature loops keep one symbol.

- **A P&ID draws its flanged connections without a unit for every flange.**
  `render(connections="flanged")` marks every equipment nozzle and both sides
  of every valve and in-line fitting; `connections="flanged-at-nozzles"` marks
  the nozzles alone; `connect(ends=…)` says either, or a `(source, dest)`
  pair, for one line. The default is `"none"`. Boundary flags, instrument and
  signal lines, reducers and tees are never marked, and a PFD draws none. The
  mark previously took a `Fitting(name, variant="flange")` unit per joint. It
  round-trips through a spec, and the draw.io export draws it.

- **Every rendered file says what drew it.** An SVG gains a `<title>`, a
  generator comment and an RDF `<metadata>` block with `dc:creator` and
  `dc:title`; a draw.io export puts the version in `agent`. A reader could not
  tell 0.1.0 output from 0.1.2 output. Golden fixtures drop the block, but
  `docs/gallery/` and `drawio-samples/` carry it, so a release regenerates
  them.

- **Every unit class is on the package.** `from pandid import Separator, Pump,
  Flowsheet` works — all thirty public names in `pandid.units` are
  re-exported, `Unit` among them. `units.Separator` beside a bare `Cyclone`
  was two import spellings for one hierarchy. Additive.

- **`examples/13_mineral_dewatering.py`: a solids circuit, drawn as a PFD.**
  Sixteen tagged items, and thirteen symbols no sheet had drawn —
  `separator/gravity`, `/cyclone`, `/scrubber`, `/permanent_magnet`,
  `filter/belt`, `dryer/default`, `furnace/default`, `blower/default`,
  `tank/conical_bottom`, `funnel/default`, `vent/exhaust_head`, `pump/screw`
  and `pump/peristaltic` — taking the gallery from 60 of the 157 registered
  symbols to 73. First example to build a `Blower`, `Dryer`, `Funnel` or
  `Furnace`, and the first with `Tee(branch="inlet")` junctions. It takes no
  `page_size`.

- **`Vessel` and `Tank` carry five nozzles, and the same five.** `relief`,
  `drain`, and `vent` — which a vessel already had and a tank now has as its
  conservation vent. A knock-out drum's liquid had nowhere to go and a tank
  could not breathe. Named roles rather than a count, since each stencil
  authors a coordinate per nozzle. Purely additive: nothing renamed, none of
  them numbered, no new spec key, every sheet byte-identical.

- **`examples/14_tank_farm.py`: a bulk liquid storage terminal, as a P&ID on
  A3.** Three storage vessels, the transfer system, the road loading rack and
  the vapour return. It adds 21 symbols nothing had drawn —
  `tank/floating_roof`, `tank/default`, `tank/sphere`, `vessel/legs`,
  `vent/breather`, `pump/gear`, `reducer/eccentric`, `reducer/concentric`,
  `valve/gate`, `valve/ball`, `valve/butterfly`, `valve/regulator`,
  `fitting/flame_arrestor`, `fitting/flame_arrestor_detonation_proof`,
  `fitting/blind`, `fitting/expansion_joint`, `fitting/strainer_basket`,
  `fitting/strainer_y`, `fitting/hose`, `fitting/positive_displacement` and
  `fitting/coriolis` — taking the gallery from 39 to 60. First sheet to
  allocate its loop numbers rather than type them.

- **Control loops number themselves.** `add_loop("F")` with the number left
  out takes the next from a per-sheet counter started by
  `Flowsheet(loop_number_start=…)`, default `101`, allocated in declaration
  order. Typed and allocated numbers mix; a loop is still the
  `(variable, number)` pair. Reaching a number already typed for the same
  variable raises. `to_dict()` writes every number as a literal.

- **`Flowsheet(stream_number_start=…)`.** Where `S{n}` starts counting,
  default `1`; moving it took a whole callable naming scheme before. It is not
  `line_number_start`, which moves a line number's `sequence`.

- **`loop_number_start` and `stream_number_start` in the spec**, and a
  `loops:` entry may leave its `number` out to allocate. `to_dict()` writes
  each key only when it differs from its default, so an older spec
  round-trips unchanged.

- **A deprecation mechanism: `pandid.deprecation.Deprecation`.** One
  declaration names the retired spelling, its replacement and the release the
  old one stops working in; `warn()` emits a `DeprecationWarning` *and* files
  a `deprecated` finding on `fs.validate()`, since Python hides the warning by
  default outside `__main__`. The finding rides on the object the call was
  made on. `CONTRIBUTING.md` carries the policy: a deprecation lives one
  release.

- **`validate()` reports `nozzle-unconnected` (#183):** a nozzle a *count*
  asked for that carries no stream. `Mixer("M-101", n_inlets=4)` with three
  inlets piped returned no findings at all. Only `n_inlets=`, `n_outlets=`,
  `n_feeds=`, `inputs=` and `outputs=` make such a nozzle; the fixed ones a
  class offers — reliefs, drains, vents, utility sides, duties, signal
  connections — stay silent. Nothing rendered moves.

- **An instrument takes several signal connections, on any face.** `sig_in`
  and `sig_out` are pools: a second line off one is minted as `sig_out_2`,
  `sig_out_3`, where before a controller could drive exactly one final
  element. Split range, separate high and low alarms, and an alarm that
  participates in a trip all need it. On a signal line either end may now be
  the unit — `fs.connect(ft305, fic305, kind="electric")`; process piping
  still names its nozzle. `pv` and `Valve.actuator` stay singular.

- **Export a sheet as a `.drawio` file.** `fs.to_drawio()`, and a `.drawio`
  path on `fs.render()`, write an editable draw.io / diagrams.net model: every
  unit a shape, every stream an edge. draw.io exports `.vsdx`, so this is also
  the route to Visio. It references draw.io's own stencils; the fifteen
  symbols with none are approximated with built-in shapes, and `docs/api.md`
  tabulates what each loses. **Not yet confirmed in draw.io** — nothing in the
  suite opens the file. The SVG is unchanged.

- **Each golden fixture is checked against the example it was copied from.**
  The suite rebuilt every sheet from an inline copy of the example's code, so
  a fixture could drift from `examples/NN_*.py` unnoticed — #230's corrected
  initials never reached the golden. Every example is now imported, rendered
  and compared, and a second check asserts every example has a scenario.

- **An example writes the draw.io export.** `examples/11_ethanol_pid.py` now
  writes `ethanol_pid.drawio` beside its SVG; the export was documented in
  three places and demonstrated in none of the fourteen examples. The file is
  gitignored and matches `drawio-samples/11_ethanol_pid.drawio` byte for byte.

- **`loop.element()`, for a primary element (#203).** It letters from the
  loop's measured variable and checks the letter, where `loop.tag()` composes
  without checking — so `flow_loop.tag("TE")` quietly yielded `TE-303`. A
  final control element is not lettered from the variable, so the two stay two
  methods. `tag()` is unchanged; `docs/api.md` and examples 04, 11 and 14 use
  the new call.

- **The draw.io export carries the stream table (#251).**
  `render("sheet.drawio", show_stream_table=True)` used to raise. The table is
  now `furniture.stream_table_layout`, shared with the sheet, so both measure
  the same columns; it goes out as a `shape=table`. `debug` is now the only
  render option a `.drawio` path refuses. No rendered SVG moves.

### Changed

- **`examples/11_ethanol_pid.py` draws loops 305 and 308 in full (#212).**
  `CV-305` and `CV-308` had no element, transmitter or controller behind them,
  so the README's lead sheet was not the drawing it redraws. Both are now
  cascades off `LIC-304` and `TIC-307`, and the declared series runs 301–308
  with no gap.

- **A balloon says what it has to do with the thing it is placed against
  (#137).** `add_instrument(on=…)` meant both "put the balloon here" and "draw
  an edge from here", so sheets stated relationships nobody had specified.
  Three keywords replace it: `sensing=` (an impulse line, or a fine dashed
  instrument connection), `acting_on=` (always dashed) and `near=` (position
  only, nothing drawn). Naming two of the three raises. `08`'s `LIC-201` stops
  being drawn tapped to a drum it is not piped to, and `Z-2` off `XV-301` and
  `Z-1` off `XV-601`/`XV-602` are dashed.

- **`variant` is the symbol, `display` is where the information is (#181).**
  ISO 15519-2 Table 1 tabulates two independent things and `variant` collapsed
  them. `display="field"` (no bar), `"central"` (one) and `"subsidiary"` (two)
  answer *where*. `variant="shared"` stays and defaults to `"central"`, so no
  sheet moved. Three combinations have no artwork registered — a squared
  balloon with two bars, a hexagon or a diamond with any bar — and raise.

- **A tank's fill is a menu, and its default moved to the shell (#226).**
  Every `Tank` variant fixed `inlet` on the crown, so no sheet could draw a
  bottom-filled tank. `default`, `conical`, `floating_roof` and `sphere` now
  anchor it low on the shell; the three hopper-bottomed variants keep the
  crown. Either is reachable through `tk.nozzle("inlet", "N")`, except on
  `floating_roof`, which has no fixed roof to weld to. `examples/14`'s
  `TK-601` moves to the shell and `TK-602` asks for the crown by name.

- **A control valve draws its actuator (#136).** `Valve(variant="control")`
  drew a Saunders body with nothing on top of it; it now draws the diaphragm
  dome over the body. The old drawing keeps its place as
  `Valve(variant="saunders")`. **This moves every sheet that draws a control
  valve**: the symbol is 19.8 tall rather than 15.0 and its nozzles sit 12.4
  below the top of the box rather than 7.5, so pin such a valve by its nozzle
  — `cv.pin(x=…, port="inlet", y=…)`. `fs.validate()` reports the difference
  as `run-off-elevation`.

- **The body and the actuator are two questions (#136).** `Valve` takes an
  `actuator=` keyword beside `variant=` —
  `units.Valve("XV-201", variant="butterfly", actuator="diaphragm")`.
  `variant="control"` stays as the shorthand for its pairing. The draw.io
  stencils fuse body and operator into one shape, so only the eleven pairings
  in `pandid.render.symbols.ACTUATED` can be drawn and any other is refused by
  name.

- **Naming a pairing's own actuator alongside it is allowed.**
  `Valve(variant="control", actuator="diaphragm")` used to raise; it now
  resolves to the variant already named. Each pairing accepts the operator its
  own drawing carries: `control` and `butterfly_pneumatic` take `diaphragm`,
  `motor` takes `motor`, `solenoid` `solenoid`, `hydraulic` `hydraulic`,
  `manual` `handwheel`. A disagreement still raises. A spec never carried
  `actuator`, and `ControlValve(actuator="diaphragm")` goes on working.

- **One drawing, one nozzle vocabulary (#138).**
  `Separator(variant="cyclone")`, `("gravity")` and `("electrostatic")` draw
  `overflow` and `underflow`, which is what `devices.Cyclone`,
  `devices.GravitySeparator` and `devices.ElectrostaticPrecipitator` have
  called them since the device layer landed; all three collect dust. 0.1.1
  kept `vapor`/`liquid` on the low-level form permanently, and that is
  withdrawn (see Deprecated). The drum's `default`, `horizontal` and
  `knockout` forms and the wet `scrubber` keep `vapor` and `liquid`. No
  drawing moved.

- **`examples/10`, `11` and `14`: comments explain the code and nothing
  else.** Every comment explaining process engineering is deleted rather than
  shortened; what is left is what a reader of the code cannot recover from it.
  The sheet's story moves to a much shorter module docstring. Nothing rendered
  moves.

- **`11` and `14`'s GENERAL NOTES keep only what the drawing cannot say.** The
  trip square's symbol key goes from both, which the LEGEND box already
  carries, as do the sentences counting how often it is drawn. The switches'
  independence, the arrestor ratings and the spectacle blind's duty stay.

- **`direction` is a rule about process nozzles.** `connect()` still refuses a
  pipe drawn the wrong way through a nozzle, but a signal connection is no
  longer held to it — the same alarm terminal is fed on one sheet and trips
  from it on another. Nothing that used to work stops working; calls that used
  to raise now draw. Every sheet is byte-identical.

- **`examples/11_ethanol_pid` declares its control loops.** `P-301`, `T-302`,
  `F-303`, `L-304`, `L-306` and `T-307` are declared with `add_loop()` and
  their members tagged from the handle, so a loop number is typed once per
  loop and `add_instrument` checks each member's first letter. The other ten
  balloons keep literal numbers. Refactor only — every tag is the string it
  was.

### Deprecated

- **`add_instrument(on=…)`, and `on:` in a spec (#137).** Use `sensing=`,
  `acting_on=` or `near=`. `on=` goes on working for 0.1.2 with a
  `DeprecationWarning` and a `deprecated` finding, means `sensing=`, and is
  removed in 0.1.3. Naming it together with any of the three raises.

- **`Instrument(variant="panel")` and `Instrument(variant="aux")` (#181).**
  Use `display="central"` and `display="subsidiary"`. Both were a location
  wearing the symbol-type argument's name. They draw the same two symbols, so
  no sheet moves; they warn, file a `deprecated` finding, and are removed in
  0.1.3. `to_dict()` writes the two axes separately.

- **`Valve(variant="pneumatic")` (#136).** Use `Valve(variant="control")`, or
  spell the pairing out as `Valve(variant="gate", actuator="diaphragm")`. It
  names a signal medium rather than a kind of valve, and as of this release it
  draws the same symbol `control` does. Warns, files a `deprecated` finding,
  and is removed in 0.1.3. `butterfly_pneumatic` is kept: it names a body with
  an actuator on it.

- **`vapor` and `liquid` on a dust-collecting separator.** On
  `Separator(variant="cyclone")`, `("gravity")` and `("electrostatic")`, use
  `overflow` and `underflow`. The old names go on reaching the same nozzles
  for 0.1.2, with a `DeprecationWarning` and a `deprecated` finding, and are
  removed in 0.1.3. Attribute access, `port()`, `nozzle()`, `pin(port=…)` and
  a spec file's endpoints are all covered; `sep.ports["vapor"]` is not and
  cannot be. Nothing changes for a drum or a scrubber.

### Fixed

- **The butane sphere's shell was drawn through both its crown nozzles
  (#268).** Converted stencils were rendered with transparent fills, but
  draw.io fills these shapes with the page colour and their authors draw for
  it: a body is the last `<fillstroke>` in the shape and covers the nozzles,
  legs and vanes behind it. Bodies are opaque now, on the sheet and on the
  draw.io export; sheets 02, 03, 06, 10, 11, 14 and 15 move.

- **A `.drawio` export with no `page_size` was cropped across several sheets
  when draw.io exported it to PDF.** With no `pageWidth`/`pageHeight` written,
  draw.io bounded the PDF with its locale-dependent default page; PNG and SVG
  were never affected. Every export now states a page — the paper where there
  is paper, the drawing's extent where there is not — with `page` `"0"`
  unpaged and `"1"` on a fixed page. `scripts/drawio_samples.py` was also
  dropping `connections`, so the committed sample of the flanged sheet had no
  joints in it.

- **`variant="shared"` drew no location bar (#181).** No bar means a
  field-mounted display (ISO 15519-2 Table 1), and a shared display is the
  control room. The bar runs the circle's full diameter and the tag sets above
  and below it. Examples 04, 11 and 14 move, with their goldens and gallery
  files.

- **A fail-position mark's halo erased an adjacent impulse line (#223).** The
  mark now steps along its face instead of only stepping past the equipment
  tag. `examples/14` gets `fail="closed"` back on both receipt valves, and the
  general note that stood in for it is gone.

- **A line number no longer lands on a mark it cannot see.** A leader head is
  kept clear of the ends of a run; a drawn joint is the same misreading and
  now counts, and flange marks joined the ink a number's halo dodges.
  `AE-304-150-80-SS` and `AE-309-100-80-SS` move.

- **A line number's plate erased half of an outline it sat flush against
  (#243).** The obstacle set was the geometric box, and an outline is stroked
  centred on that box, so half the pen lay outside it. Boxes are now grown by
  half the drawn weight plus a clearance, wherever they are used — equipment
  tags, line numbers, leader lines and the draw.io export alike. Six symbols
  across three sheets were being cut.

- **The storage sphere's ports did not land on the nozzles it draws (#225).**
  `relief` and `vent` now take the two crown stubs and `outlet` the belly
  nozzle; `inlet` (west, with an east alternate through
  `nozzle("inlet", "E")`) and `drain` (south) go low on the shell.
  `examples/14`'s butane receipt had been arriving at bare shell. Two new
  invariants hold every drawn nozzle to a port and keep no port in the gap
  between two.

- **A resized symbol's line width changed with it, and differently in each
  axis** (ISO 15519-1 §11.1.3). The artwork is now redrawn at the placed size
  rather than stretched by its viewport, so each `stroke-width` is the weight
  its author drew. Four vendored families — `vessel/default`,
  `separator/default`, `column/packed` and `valve/butterfly_pneumatic` — were
  wrong even at their natural size. Geometry is untouched.

- **`examples/14_tank_farm`: the pump suction had a bend in it, and the vapour
  return crossed the whole sheet.** `P-601` was pinned on the large end of the
  eccentric reducer `RD-601`, whose two nozzles are not on one centreline; it
  now takes the reducer's outlet elevation. The tanker vapour return
  counterflowed the length of the sheet (ISO 15519-1 §13.2) and now stands at
  the rack it serves, with both off-page flags on the east edge.

- **`HS-601` tagged a hose as an instrument.** `HS` is a letter code
  ISO 15519-2 §5.2.2 constructs, so the tag read as a PCI symbol. The loading
  hose is now `HOS-601`.

- **Three sheets carried a real drawing's checker and approver.** `RG` and
  `HVL`, the initials on `professional_examples/P&ID_301.pdf`, had been copied
  into `10_ethanol_pfd`, `11_ethanol_pid` and `14_tank_farm`. They are now
  `JS` and `RL`. `AA` stays: that is the repo's author.

- **The scale cell reported a fit ratio on a diagram that is not to scale.**
  Left blank, `TitleBlock.scale` reports the ratio the renderer placed the
  drawing at; `10`, `11` and `14` now state `scale="NTS"`. The default is
  unchanged.

- **`to_drawio` takes `page_size` and `border`.** A drawing made
  `page_size="A3"` opened on draw.io's default page with no frame. The file
  now states the page, docks the furniture to it and rules the zone border;
  omit `page_size` and nothing changes. The exported zone grid is a snapshot,
  true of the drawing as it left pandid and not after the model is edited.

- **draw.io tables no longer clip their own contents.** Columns took
  proportional shares of the box rather than their measured widths, so `HPSSH`
  came out `HPSS`; they are measured now at the size each table is drawn at.
  The title block's eleven fields drew no text at all and are ruled at their
  own row height, bottom-aligned.

- **A pipe tee draws no ink of its own, and the pipes close the junction.**
  The cell showed a stub sticking out of the run. Every stream meeting a tee
  now lands on the box centre; the cell stays, invisible, so dragging the
  junction takes its pipes with it.

- **The `.drawio` export draws the instrument connections.** A tap line is not
  a stream, so all twenty of `examples/11_ethanol_pid`'s balloons came out
  floating free of the plant. Each is now an edge, pinned to the balloon and,
  where the host is plant, to the host.

- **A pneumatic signal line is marked as one.** It exported solid and thin,
  told apart from an electric line by nothing. The double cross-hatch goes out
  as a pair of `line` cells parented to the edge, so the marks ride a
  re-route, though one keeps its exported angle if the line is later routed
  through a turn.

- **Sheet furniture docks where the sheet docks it.** The title block,
  equipment list, notes and legend were stacked down the left of the drawing
  while the drawing ran out past them; both backends now share
  `pandid.render.furniture.dock()`. A `.drawio` file has no paper, so the
  frame is grown around the drawing rather than being a page.

- **The equipment list, notes, legend and title block are ruled tables.** Each
  was a single value with `<br>` runs in a plain rectangle. Anything columnar
  now exports as a draw.io table that opens as an editable grid, the title
  strip as two of them; its merged geometry does not survive, since a table
  row gives every cell the same height. A box whose rows are plain sentences
  stays a box.

- **An off-page flag is a pennant with its tag inside it.** `Feed` and
  `Product` exported as an unlabelled rectangle with the label above it. They
  are now draw.io's `offPageConnector`, turned to point along the flow, with
  the tag and off-page reference inside.

- **A pipe tee is drawn in the pipe's own ink.** It exported at the stencil
  hairline and draw.io's default weight, so every junction was a lighter,
  thinner rule bridging two heavier pipes.

- **Two more the export got wrong.** A dash pattern is multiplied by the
  stroke width unless `fixDash=1`, so a `dasharray` came out at twice its
  length; every dashed edge now carries the flag. And a cell that states a
  `direction` now also states `legacyAnchorPoints=1`, since draw.io's two
  anchor-point algorithms disagree there.

- **Documentation: a final control element does take its loop's number.**
  0.1.1 shipped the opposite claim in `pandid/loops.py`, `docs/api.md` and
  `tests/test_loops.py`. What does not track is the **letters** — a sheet
  spells every control valve `CV-` — so `loop.tag()` still composes without
  checking a first letter. No behaviour changes.

## [0.1.1] - 2026-08-01

**A sheet regenerated on this version is not the sheet 0.1.0 drew.** Symbol
geometry, stroke weights, label and line-number placement and the whole PDF/PNG
export backend all moved, so the same flowsheet renders to different bytes and
nothing in your code says so. All eleven sheets 0.1.0 shipped are redrawn, and
every `.png` with them. If a drawing has been issued, diff it before reissuing
it.

Nothing was removed or renamed. Everything below is an addition, or a correction
to what was drawn.

### Added

- **`debug=`: the coordinate system, drawn on the sheet.**
  `to_svg(debug=True)` and `render(..., debug=True)` draw a coordinate grid, a
  cross on every point `pin(x=, y=)` sets and a dot on every port, each
  labelled with the name and the numbers the API takes; `debug=100` sets the
  spacing, and `pandid draw --debug [SPACING]` is the same switch. Placement
  is absolute and neither point it is written against was drawn. Works on
  `.svg`, `.pdf` and `.png`. Off by default, and off is byte for byte the
  sheet drawn before it existed.

- **`Block.order_on()`: where a connection sits along the face it is on**
  ([#192](https://github.com/Alpha9463/pandid/issues/192)). A face said which
  wall a connection was on and nothing about where along it, so the ordinary
  BFD recycle could not be drawn. It takes the ports `ports_on()` returns, not
  their names, and must name every connection on the face. `to_dict()` writes
  a reordered face as `port_order`.

- **A variable-port family is now a typed sequence**
  ([#175](https://github.com/Alpha9463/pandid/issues/175)). `Mixer.inlets`,
  `Splitter.outlets`, `Block.inlets`/`outlets` and `Column`/`Reactor.feeds`
  are `tuple[Port, ...]` in declaration order, so `m.inlets[0] is m.in_1` and
  `for p in m.inlets` type-checks. Iterating a family meant `m.port(f"in_{i}")`
  and a hand-rolled loop. The tuple is indexed from zero while the nozzles are
  numbered from one. Purely additive.

  `Block`'s accessors are renamed with it: `inputs`/`outputs` become
  **`input_faces`/`output_faces`**, leaving `inlets`/`outlets` for the ports,
  and **`ports_on(face)` returns the ports** rather than their names. `Block`
  is unreleased, so nothing that shipped is affected, and the constructor
  keeps `inputs=`/`outputs=`.

- **`units.Block`: the block flow diagram**
  ([#164](https://github.com/Alpha9463/pandid/issues/164)). One labelled box
  per plant section; there was no way to draw one. `inputs` and `outputs` are
  one face per connection, in order, with a plain count as the shorthand; the
  nozzles are `in_1` … `in_n` and `out_1` … `out_m`, numbered across the whole
  family so moving one to another side never renames it. The box sizes itself
  to what it carries, `width`/`height` still win, and a box too small for its
  connections is refused. **Pin a block flow diagram** until
  [#168](https://github.com/Alpha9463/pandid/issues/168) is fixed.
  `equipment_list()` skips a block.

- **`pandid.devices`: 42 equipment classes over the `kind` + `variant` model**
  ([#146](https://github.com/Alpha9463/pandid/issues/146)).
  `devices.Cyclone("S-1")`, `devices.KettleReboiler("E-101")`. Every name is
  re-exported from the package and subclasses the `pandid.units` class that
  owns its kind, so `isinstance` is unaffected and
  `fs.add(devices.Cyclone("S-1")).underflow` resolves under mypy. A class is
  what the equipment is; `variant=` is how it is drawn. Nothing shipped moves,
  and `Separator(variant="cyclone")` stays supported indefinitely.

- **`Cyclone`, `GravitySeparator` and `ElectrostaticPrecipitator` call their
  draws `overflow` and `underflow`**
  ([#138](https://github.com/Alpha9463/pandid/issues/138)). All three collect
  dust, and the drawings had called the catch `liquid`.
  `Separator(variant="cyclone")` keeps `vapor`/`liquid`, so one drawing
  answers to two vocabularies depending on which class you construct.
  (Withdrawn in the next release.)

- **`docs/api.md` lists the equipment classes**
  ([#147](https://github.com/Alpha9463/pandid/issues/147)). An *Equipment
  classes* table, one row per class, and the *Variants* table restructured
  from "kind → every drawing of it" to "class → the drawings it owns". Both
  are held to the live registry by a test.

- `Unit.PORT_ANCHORS`: nozzle name → the name the symbol anchors it under, for
  a class that renames one of its drawing's nozzles. Without it a renamed
  nozzle got the centre of the box, and two of them landed on one point.

- `Unit.VARIANTS` and `Unit.VARIANT_ALIASES`
  ([#145](https://github.com/Alpha9463/pandid/issues/145)). A subclass may
  name the drawings it owns and is refused any other **at construction**
  rather than at the first render. Nothing shipped moves: every class in the
  port table leaves `VARIANTS` empty, which is how a class says it owns its
  whole kind. `VARIANT_ALIASES` renames a variant class-locally, and
  `to_dict()` writes the registry's spelling. `HeatExchanger` and `Separator`
  add their per-variant nozzles through a new `_variant_ports` classmethod,
  which returns nothing on a subclass declaring its own `PORTS`.

- **`validate()` reports `nozzles-crowded`**
  ([#155](https://github.com/Alpha9463/pandid/issues/155)): two nozzles on one
  face whose arrowheads leave less paper between them than ISO 128-20 §4.4
  allows between parallel lines. Nothing errored and every nozzle was on its
  ink. Only nozzles that wear a head count, and a P&ID draws none, so
  `validate(diagram=…)` takes the drawing it is answering about. One shipped
  example is reported; no golden moves.

- Every unit class declares its nozzles as class annotations (`suction: Port`),
  so `pump.suction`, `sep.feed` and `hx.shell_in` are attributes a type
  checker can see; the package shipped `py.typed` while every nozzle read as
  `Any`. The annotations bind nothing and no golden moves.

  Two things went with them. `Unit.__getattr__` is hidden from type checkers
  and from them only (`if not TYPE_CHECKING:`), since mypy reads a class that
  has one as having whatever attribute it is asked for. And `Flowsheet.add`,
  `Unit.pin` and `Unit.nozzle` now return the class they were given rather
  than the base `Unit`; all three already returned it at runtime. **A nozzle
  no class declares is therefore a type error**, which reaches the numbered
  families (`in_1` … `in_n`) and the per-variant nozzles
  (`HeatExchanger.bottoms`, `Separator.overflow`); both keep working at
  runtime and through `unit.port(name)`.

- Four more `Vessel` variants: `legs`, `insulated` (lagged, hatched down both
  walls), `electrical_heating` (a resistor element on the shell wall) and
  `swaged` (one vessel in two diameters). The first two take `skirted`'s and
  `jacketed`'s boxes and nozzles verbatim. `electrical_heating` drops its
  `outlet` to the clear wall below the element.

- Three more `Tank` variants, for tanks that drain to a cone: `conical_bottom`,
  `conical_ends` and `dished_roof_conical_bottom`. The last takes `default`'s
  port map verbatim, with `outlet` resolving to the cone's apex. All seven new
  variants join the symbols ISO 15519-1 §11.4.2 forbids turning, taking that
  count to 41.

- Four `Separator` variants that separate mechanically rather than into
  phases: `sifter`, `impact`, `permanent_magnet` and `electromagnetic`. All
  four join the symbols ISO 15519-1 §11.4.2 forbids turning, for the hopper
  they fall into.
- `Separator`'s nozzles are per-variant, as `HeatExchanger`'s already are:
  those four carry `feed`, `overflow` and `underflow` in place of
  `feed`/`vapor`/`liquid`. `Separator("V-101")` and the six variants 0.1.0
  shipped keep `feed`/`vapor`/`liquid`, in that order, and no golden moves.
- Five `Filter` variants, naming the medium the casing is drawn around:
  `fixed_bed` and `gas_fixed_bed` (a granular bed), `belt` and `gas_belt` (a
  cloth on two rollers), and `rotary_scraper` (`rotary`'s drum with a knife).
  Each is piped `inlet` west and `outlet` east at mid-height. `Filter`'s ports
  are unchanged.
- `gas_fixed_bed` and `gas_belt` join `filter/gas` among the symbols
  ISO 15519-1 §11.4.2 forbids turning, for the dust hopper each draws;
  `fixed_bed` and `belt` draw none and stay turnable.
- `validate()` reports `run-off-elevation`: two connected nozzles on one
  horizontal run that are *almost* level, missing by less than the shorter
  symbol is tall, so the router draws a step into each device and back out.
  The message names the cure, `pin(port=…, y=…)`. A large deliberate step, a
  vertical run, a signal line, an unpinned sheet and the eccentric reducer are
  silent. No golden moves.
- `Separator(variant="knockout")` draws the knock-out drum the default used
  to, demister pad and level gauge and all, at the size and with the nozzles
  it had.
- Python 3.14 is supported and tested; the floor is unchanged at 3.10. The
  optional `pdf` extra installs on 3.14 too.

### Changed

- **`README.md` leads with `11_ethanol_pid`**, the P&ID, rather than
  `03_distillation_train`. `10_ethanol_pfd` and `11_ethanol_pid` also gain
  goldens: they were the most-shown sheets and the only two with no regression
  protection.

- **`docs/gallery/` is regenerated, and a check now holds it to the examples**
  ([#180](https://github.com/Alpha9463/pandid/issues/180)). The gallery had
  drifted and nothing noticed — `04_control_loop.svg` showed a drawing the
  package had stopped producing. All twelve sheets are rebuilt,
  `12_block_flow_diagram` joins the page, and `tests/test_gallery.py` renders
  every example and compares. `scripts/gallery.py` is the one command that
  rebuilds it, and it fills a blank `TitleBlock.date` from the newest
  revision, so `03` and `08` stop carrying a date that moves every day. The
  PNGs are now 2400 px wide rather than 1600.

- A spec may name any of the new device classes (`kind: Cyclone`, or its
  snake_case spelling), and `to_dict()` can write one out. The internal `kind`
  tag (`kind: pump`) still names the class that owns the whole kind. Arguments
  keyed to a class (`normal_position`, `fail`, `n_feeds`, `large_end`, …) are
  matched by inheritance rather than by class name now, so a `ControlValve`
  takes `fail:`. ([#146](https://github.com/Alpha9463/pandid/issues/146))

- `pip install 'pandid[pdf]'` now gives a working PDF and PNG export on a
  machine with nothing else installed
  ([#141](https://github.com/Alpha9463/pandid/issues/141)). The extra pulled
  in cairosvg, which needs a libcairo no PyPI wheel ships, so the install
  reported success and the first `fs.render("x.pdf")` died in the import. It
  is now svglib, ReportLab and pypdfium2, which resolve to wheels on Windows,
  Linux and macOS for 3.10 through 3.14. Both formats survive and the PDF is
  still vector. **The typeface changes** from the system `sans-serif` to
  Helvetica, so the lettering is the same everywhere and embeds no font.
  Geometry is unchanged, and an export now refuses rather than silently
  dropping a construct the backend cannot draw.

- `Separator(variant="default")` is drawn as the plain dished-head vertical
  cylinder `Vessel` and `Column` share, reproportioned to `Vessel`'s 62 x 100
  box rather than the column's 100 x 200. It was the knock-out drum, whose
  level gauge is drawn twice over as soon as a real level instrument is added.
  Its nozzles are unchanged in name and role. Examples 01 and 05 move, and
  their goldens.

### Fixed

- **A line number with no run beside the words now carries a leader to it**
  ([#155](https://github.com/Alpha9463/pandid/issues/155)). Placement wrote
  the number wherever it found free paper, unattached, so `AE-304-150-80-SS`
  read as an annotation of the drum it had drifted to; ISO 15519-1 §7.2.5
  requires a leader in that case. What decides it is whether more than half
  the number has its own run alongside it. The leader follows §6.4 and is
  oblique. One is drawn, on `11_ethanol_pid`.

- **A label's halo no longer paints out the symbol underneath it.** Neither
  placement pass had been told a graphical symbol was on the paper, so on
  `11_ethanol_pid` D-301's tag ate a quadrant of LT-304's balloon and
  HV-301C's ate the edge of PIC-301's square. Both passes now rank a symbol
  above everything else they weigh, and the search may walk one band further
  out. Two tags and one line number move.

- **`examples/12_block_flow_diagram`'s ammonia recycle runs under the row.**
  It came back into the Synthesis Loop's south face straight across the purge,
  needing a line hop to say so. One declaration changes, `outputs=["E", "W"]`
  to `["E", "S"]`: crossings 1 → 0, hop arcs 1 → 0.

- **`examples/11_ethanol_pid` letters its trips `Z`, not `I`.** ISO 15519-2
  Table 2 gives `Z` for switching and `I` for indicating, the one thing a trip
  does not do, and its note 9 keeps `A` off an alarm that acts. The high and
  low alarms move to §5.1.3's quadrants and `PT-318` gets its own tap. The
  general notes are rewritten to match. Lettering only: no sheet moves.

- **`examples/03_distillation_train` pipes its overheads shell side**
  ([#186](https://github.com/Alpha9463/pandid/issues/186)). The vapour ran
  into each condenser's tube side, where both reference PFDs put cooling
  water. `E-101` and `E-201` take `shell_in`/`shell_out`, stand on their own
  towers' axes and are flipped top to bottom; `V-101` and `V-201` are raised
  30 units. No stream is added.

- **`examples/03_distillation_train` draws its towers as columns.** `T-100`
  and `T-200` had a single overhead product, no reflux drum, no reboiler and
  no internal returns. Both now carry a condenser draining into a reflux drum
  (`V-101` / `V-201`) that parts at a `Tee` into reflux and distillate, and a
  kettle reboiler (`E-102` / `E-202`) returning boilup, so `P-100A/B` takes
  the net bottoms. Both loops close through `reflux_in` and `boilup_in`, so
  neither is modelled as a recycle. This is the largest sheet movement in the
  release.

- **A flipped condenser no longer reverses its heat-flow arrow**
  ([#155](https://github.com/Alpha9463/pandid/issues/155)). Only the end of
  the diagonal that wears the arrowhead tells `Heater` and `Condenser` apart,
  so a `mirrored="y"` condenser said the opposite of its unflipped sibling.
  `Symbol.directional` holds a marked drawing's ink still under a mirror or
  `orientation=180` while its nozzles still move; a quarter turn is carried.
  Marked: `heater/default`, `cooler/default`, `hex/condenser`.

- **An instrument's link is drawn as the line it is, not as the class of what
  it hangs on** ([#155](https://github.com/Alpha9463/pandid/issues/155)). One
  logic function on `11_ethanol_pid` was drawn as impulse tubing in one place
  and as a signal in four, and on `07` and `08` a control-room controller was
  drawn piped to a drum. A link is solid only where both ends answer: process
  fluid at one, and ISA-5.1's bare circle at the other. Two goldens move.

- **Examples 04 and 11 stopped drawing loops the standards forbid.** `04`'s
  level loop had no transmitter, so `LT-101` now stands between `V-101` and
  `LIC-101` and the trip tees off that measurement (ISO 15519-2 Figure 17 b).
  Both files drew controllers as bare `variant="panel"` circles and use
  `variant="shared"` now. `11`'s alarms were chained controller → high → low →
  SIS, against ISO 15519-2 §6.2, §7.2.4 and Table 2 note 9; both pairs now fan
  off their controller as dead ends, and `LIC-304` moves onto the valve it
  strokes.

- **An instrument's impulse line is orthogonal, and a test says so**
  ([#155](https://github.com/Alpha9463/pandid/issues/155)). Three shipped taps
  were drawn on the diagonal, against ISO 15519-1 §12.1 and §12.4. All three
  were author `angle=` choices and all are re-routed: `04`'s interlock square
  takes no face at all and is teed off the `LIC-101` → `LV-101` signal line,
  and that sheet grows 36px taller. A balloon off its tap's own row or column
  still cannot be drawn orthogonally
  ([#170](https://github.com/Alpha9463/pandid/issues/170)).

- **A balloon teed off a signal line is drawn dashed**, not solid — it was
  drawn as tubing on a pipe. A tap on the process stays solid. Nothing shipped
  hung a balloon on a signal line, so no golden moves.

- Symbol line weights use the geometric mean of both scale axes, not one
  ([#158](https://github.com/Alpha9463/pandid/issues/158)). A single axis drew
  an elliptical pen on the four reproportioned families; `column/packed`'s bed
  grid came out at half its shell's weight.

- Lettering in the `.pdf` and `.png` exports is drawn at the size the sheet
  sets it in. It came out at three quarters of that — every stream number,
  line number, balloon tag, equipment tag, title-block row, legend entry and
  note on every exported sheet. The `.svg` was always right.

- Lettering the renderer centres vertically is centred in the `.pdf` and
  `.png` exports too. It sat about a quarter of its type size above the point
  it was centred on, so a label and the white halo drawn round the same centre
  came apart. `middle`, `baseline`, `auto`, `alphabetic` and `central` all
  resolve; any other value is refused rather than placed on a guess.

- A unit given a `width`/`height` of its own is drawn at the sheet's line
  weight ([#153](https://github.com/Alpha9463/pandid/issues/153)). The `<use>`
  scaled the symbol's viewport, ink and all — the relief valve fixed in
  [#152](https://github.com/Alpha9463/pandid/issues/152) merged into a blob. A
  resized placement now gets its own `<defs>` entry with every weight divided
  by the box's scale; a unit left to size itself renders byte-identically. A
  box that also *reshapes* the artwork is corrected by the geometric mean.

- `valve/psv`, `valve/relief` and `valve/butterfly_pneumatic` come out at the
  size the rest of the family is drawn at. All three shipped at roughly half a
  gate valve's length, so a PSV's spring hatching closed into a solid wedge
  and a relief PRV's bonnet into a dot. **A sheet that sized its PSV by hand
  to compensate should drop the override** — `examples/07_metering_skid.py`
  and `examples/09_line_numbers.py` dropped their `width=40, height=68`. This
  has been so since 0.1.0 and is not a regression.

- Curved equipment heads are drawn on the ellipse the stencil asked for: a
  radius correction was applied twice, so a dished head met in a cusp or came
  out shallower than the stencil drew it. Seventeen symbols are redrawn —
  `hex`/`kettle`, `hex`/`hairpin`, `hex`/`u_tube`, `column`/`packed`,
  `reactor`/`default`, `reactor`/`plain`, `separator`/`horizontal`,
  `separator`/`knockout`, `vessel`/`horizontal` and the eight dished-end
  `vessel` variants. No nozzle, box or canvas dimension moves.

- A label's opaque halo no longer deletes a line that is not its own.
  Placement seeded the symbols and the equipment tags as occupied and not one
  routed segment, so a line number cut whatever pipe passed behind it and an
  equipment tag cut the impulse line from a tap to its balloon. Every routed
  segment and impulse line is seeded now; the one line a halo may still cover
  is the run whose number is written in it (ISO 15519-1 §7.2.5). An equipment
  tag steps *along* its face before trying another, and gives way to an
  impulse line before a pipe.
- A `Column`'s feed family is centred between its two duty arrows, so every
  feed lands on the trayed section however many there are. Centred on 130 in a
  200-unit shell, the second feed of two came out past `reboiler_duty` and the
  fourth of four below `boilup_in`; it is centred on 105 now and spread over
  0.35 of the shell. Both column variants are fixed. The single-feed nozzle
  moves 25 up, so examples 03, 06, 10 and 11 move with it.
- Examples 03, 04, 07 and 09 no longer dogleg into their in-line devices. Each
  pinned its valves, orifice plate, strainer and sight glass by the **corner**
  while the equipment around them put its nozzles on another elevation. They
  are placed with `pin(port=…, y=run_y)` now, which asks the symbol where its
  own nozzle sits. Placement only; no symbol moved.

## [0.1.0] - 2026-07-28

First public release. `README.md` is the tour, [`docs/api.md`](docs/api.md) is
the reference, and [`docs/gallery/README.md`](docs/gallery/README.md) walks the
eleven examples.

### Added

- **Topology.** `Flowsheet` is the container and the single source of truth for
  connectivity, with `add()`, `connect()`, `add_component()` and
  `add_annotation()`. 28 typed `Unit` classes declare named ports reachable as
  `unit.ports[name]` or as attributes (`pump.suction`), and a typo raises an
  error naming the real ports. `connect()` validates every connection: outlet
  to inlet only, both units on the same flowsheet, one stream per port, and
  signal against process. A `Unit` subclass of your own declaring its `kind`
  and `PORTS` is laid out, routed and drawn like a shipped class.
- **Assemblies and branching.** `Tee` is the pipe tee, drawn as bare pipe and
  scheduled nowhere, so a bypass, drain, vent or PSV takeoff puts no equipment
  on the sheet that the plant does not contain.
  `Flowsheet.add_valve_station()` builds the eight devices and four tees a
  control valve is installed in, in one call.
- **Numbering.** Automatic stream numbers carry one number *through* inline
  valves, reducers and fittings. Line numbers (`size`, `schedule`, `service`,
  `spec`, `insulation`, plus an auto-filled `sequence`) are assembled by
  `line_numbering_scheme`, so a line number survives an in-line fitting and
  breaks where the spec break is marked.
- **Layout.** Sugiyama-style automatic layout: cycle breaking, layer
  assignment, crossing reduction and coordinate assignment, with the main flow
  line straightened onto one axis. The geometry model separates intent (`Pin`,
  written only by `Unit.pin()`) from result (`Frame`, written only by the
  engine), which makes `layout()` idempotent. `pin()` takes a grid cell or
  exact coordinates, a quarter turn, a mirror, and `port=` to place a
  **nozzle** rather than a corner. Port faces and equipment tags are chosen
  from where each peer landed, and `nozzle()` overrides that pick.
- **Routing.** Orthogonal A\* over a visibility graph, with port anchors
  projected onto unit boundaries, used-edge penalties so runs do not overlap,
  crossing jump-gaps, and separation of co-located parallel runs.
  `Stream.via([...])` forces explicit waypoints. `route()` places attached
  instruments and re-routes until the two agree.
- **Rendering.** SVG with **no runtime dependencies**; `.pdf` and `.png` go
  through the optional `cairosvg` backend. `page_size="A4"`..`"A0"` draws a
  sheet of exactly that ISO 216 size, `border="zone"` rules the ASME-style
  zone frame, and `diagram="p&id"` draws process lines without arrowheads.
  Signal lines are drawn at half the weight of process pipe, the 2:1 ratio
  ISO 15519-1 §6.2 requires. A `TitleBlock`, `Revision` rows, and docked
  `Annotation` / `TableBox` furniture (`equipment_list()`, `notes()`,
  `legend()`) are drawn whatever the border, and text that cannot fit its cell
  is reported on `fs.warnings` rather than drawn across a rule.
- **Symbols.** 139 registered `(kind, variant)` pairs across 28 kinds,
  generated from the draw.io / diagrams.net P&ID stencils by
  `scripts/vendor_symbols.py` and matched to ISO 10628-2 where a symbol
  exists. Feed/Product flags, the variable-port Mixer and Splitter, the pipe
  tee and the ANSI/ISA-5.1 balloons are hand-drawn originals. Every port is
  checked to land on drawn ink, and `variant=` is checked against the
  registry.
- **Instrumentation (ISA-5.1).** `add_instrument()` and the `Instrument` unit
  draw the functional letters over a loop number, in six balloon variants plus
  the two trip squares ANSI/ISA-5.1-2009 distinguishes. `Instrument.attach()`
  anchors a balloon to the stream or equipment it reads, with an impulse line
  to the tap. Typed signal lines (`electric`, `pneumatic`, `data`, `software`,
  `capillary`) are legal only between two signal connections.
  `Flowsheet.add_loop()` declares a control loop, so the loop number is typed
  once and each balloon's own letters are checked against it.
- **Valve marking.** `Valve(normal_position="closed")` darkens the body
  (PIP PIC001 4.2.2.7) or writes `NC` beside it where a filled body would hide
  the device (ISO 15519-1 §11.4.5), and refuses on a control or relief valve.
  `Valve(fail=...)` writes the six ANSI/ISA-5.1-2009 Table 5.4.4 codes beside
  an actuated valve. `Fitting(variant="blind")` takes the same
  `normal_position` and changes shape rather than fill.
- **Validation.** `Flowsheet.validate()` returns `Issue` records, errors
  first. Errors such as overlapping pinned units raise from `render()`;
  warnings such as a route crossing a unit body, a tag whose letters are out
  of ISO 15519-2 §5.2.4 order, or a gravity-dependent symbol given a quarter
  turn collect on `fs.warnings`.
- **Spec format.** `Flowsheet.to_dict()` / `from_dict()` round-trip the whole
  topology as JSON-safe data, and `pandid.spec` reads the same shape from YAML
  or JSON. An unknown key is rejected rather than ignored, and the message
  names the key it was probably meant to be.
- **Command line.** A `pandid` command, installed with the distribution:
  `pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone`,
  `pandid validate plant.yaml`, and `pandid symbols --kind valve`. Exit codes a
  build script can gate on, and every user-provokable failure is one line on
  stderr rather than a traceback. Built on `argparse`, so the package still
  has no runtime dependencies.
- **Packaging and tooling.** `pandid/py.typed` (PEP 561), a golden-SVG
  regression suite, symbol- and route-invariant suites, CI on Python 3.10 to
  3.13, and a release workflow that checks the tag against
  `pandid.__version__` and publishes over PyPI Trusted Publishing.
  `pandid.__version__` is the only place the version is written.

### Changed

Two attributes were renamed on the way to this release. Nothing was published,
so there is no alias and the old spellings do not exist. **Both are also spec
keys**, so a file written against a pre-release checkout has to be edited: the
reader rejects an unknown key rather than ignoring it, and names the new one.

- `Unit.significant` is now **`Unit.new_line_number`**, and the unit spec key
  `significant:` is now `new_line_number:`. It marks the inline item at which a
  line number breaks and a new one starts.
- `connect(tear_hint=...)` and `Stream.tear_hint` are now
  **`draw_as_recycle`**, and the stream spec key `tear_hint:` is now
  `draw_as_recycle:`. It marks a stream to be drawn as a recycle loop.

Neither rename changes a drawn sheet.

### Removed

The deprecated aliases, on the same reasoning: nothing has been published, so
keeping them preserves compatibility with code that cannot exist. This follows
the clean breaks already made for `hot_*` to `shell_*` on heat-exchanger
nozzles.

- `styling=` on `to_svg()` / `render()`. Use `border="zone"` and
  `diagram="p&id"`, which are independent and name the two things it bundled.
- `anchor=` on `Annotation`, `TableBox`, `equipment_list()`, `notes()` and
  `legend()`. Use `align=`.
- `Unit.port_face()`. Use `Unit.nozzle()`, whose `face` is the compass point on
  the finished sheet. The two disagreed on a rotated or mirrored unit, so
  **rewrite each call site with the face the reader sees** rather than
  substituting the name (#26).
- `Symbol.port_alts` and `Symbol.free_ports`. Declare the whole menu, home
  placement included, in `Symbol.port_faces`; the faceless set is
  `Symbol.faceless_ports`.
- `Unit._PORTS`. Use `Unit.PORTS`, the same list of `(name, direction, role)`
  tuples under a name that does not call a required attribute private.

### Licence

Licensed under the **PolyForm Small Business License 1.0.0**: free for
individuals, research, teaching, and companies under 100 people and 1,000,000 USD
revenue; a commercial licence is required above either threshold.
Source-available rather than OSI open source.

The vendored draw.io symbol geometry remains **Apache-2.0**. The stencil artwork
carries one additional field-of-use restriction on top of that grant, naming
Atlassian products and marketplace distribution and excluding diagram output;
`NOTICE` reproduces it in full, lists which files fall under which licence, and
both texts ship in the distribution.

[0.1.3]: https://github.com/Alpha9463/pandid/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Alpha9463/pandid/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Alpha9463/pandid/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

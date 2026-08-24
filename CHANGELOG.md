# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`SteamTrap`**: the drawing every steam system needs at each low point
  and each drip leg, and the one in-line device the library had no way to
  draw (#367). ISO 10628-2 Table 2 item 24.15, registered 2181, which is
  where the standard files it, in its fittings group. Drawn as that row
  draws it: a body
  4 M across, a full diameter at 45 degrees from its lower left to its
  upper right, and the half below that line filled — the contrast being
  the whole of what tells it from a plain circle. Reachable as
  `SteamTrap("T-701")` or as `Fitting(variant="steam_trap")`, and it
  takes the registry to 229.

  Hand-drawn rather than vendored, and the reason is the interesting
  part. The draw.io P&ID set ships a shape called *Steam Trap* which is
  an empty 50 × 50 rectangle **byte-identical to the same file's
  *Desuper Heater***, so mapping it would have registered one blank box
  under two device names. `scripts/vendor_symbols.py` refused it on
  those grounds and recorded why; this supplies the artwork the refusal
  was waiting for.

  `examples/15_condensing_turbine` drops the workaround the issue named.
  Its separator drain went straight off the sheet as
  `Product("Steam Trap Drain")` — a boundary flag standing in for a
  device in the run — and now passes a real `T-701` on its way to the
  condensate header.

  The draw.io export has no stencil to name, so it is a stand-in — and
  the stand-in draws what it can. A single built-in over the cell would
  have been an oval half again too wide with both leads inside it, so
  the cell carries three pieces instead: the body ellipse and a line for
  each lead, placed by the symbol's own dimensions so the two backends
  cannot drift. What is left is the mark, and that is what the export
  reports losing.
- **`_Approximation(pieces=…)`**: a draw.io stand-in may now be several
  built-ins with a rectangle each, in fractions of the cell, rather than
  one shape stretched over the whole of it. `inscribed=` already drew a
  second outline filling the same box, which is right for a square with
  a diamond in it and wrong for anything whose parts sit at different
  places along the cell.
- **`drawio-approximated` now also reports a reproportioned body.** A
  symbol that may not be distorted is centred on the sheet and
  letterboxed, and no draw.io built-in can be told to keep its shape, so
  an author who sizes one to a box of another shape gets a drawing the
  two backends disagree about. That was silent. It now says so, and only
  when it happens — a quarter turn swaps the cell's width and height and
  is not a resize, which the comparison now allows for.
- **`tests/test_symbol_identity.py`**: no two registered drawings may be
  byte-identical unless the library *says* they are the one drawing —
  either the same `Symbol` object under two keys (`centrifuge/default`
  and `centrifuge/decanter`; `instrument/logic` and `instrument/sis`) or
  one vendored stencil under two names (a bare `Valve` is a gate valve;
  a bare `Separator` is the drum a bare `Vessel` is). Anything else is
  two drawings that merely happen to match, which is what a placeholder
  is. The comparison ignores the `id` a symbol carries to be `<use>`d
  by, since that follows the variant spelling and would otherwise hide
  every duplicate behind the very names that duplicate it.

  A duplicate needs two drawings, and the original defect was one
  placeholder mapped on its own — so a second guard asks what each
  drawing *is*: a registered drawing is never a bare rectangle
  coincident with its own box, which is what an unconverted placeholder
  looks like at any size. `block/default` is the one drawing that is
  legitimately its own box and is named.

  The vendored stencil files are checked at their own level too: every
  group of byte-identical shapes upstream ships is recorded, so a
  re-vendor that brings in a new one has to be looked at, and no group
  may reach the registry with two members still identical.
- **`Evaporator`, `Thickener` and `Kiln`**: three pieces of equipment the
  registry had no symbol for, and all three were being faked in a shipped
  example with an apology in its source (#474). `examples/21_alumina_refinery`
  drops all three workarounds.

  **`Evaporator`** is five bodies on one shell -- `default` (two tubesheets
  around a boxed element, for a duty sized before the element is picked),
  `calandria`, `falling_film`, `climbing_film` and `plate` -- with five
  nozzles: `feed`, `vapor`, `concentrate`, and a steam chest of `heating_in`
  and `condensate`. Not a `HeatExchanger` variant, because the vapour is a
  stream of the plant rather than boil-up returned to a tower, and that is a
  nozzle an exchanger has not; `EV-901` was drawn as a kettle reboiler until
  now. The chest is fed on the **west** wall and drained on the east, so a
  multiple-effect train drawn left to right hands each effect's vapour to the
  next one's `heating_in` without routing it round the body. There is no
  forced-circulation body: one is drawn as this body plus its circulating
  heater and pump, three tagged items, because that is what a real sheet
  schedules.

  **`Thickener`** is the settling machine every minerals plant and every water
  and wastewater works is built around -- feed, `overflow` at the weir,
  `underflow` out of the raked cone -- and the rake is composed onto it:
  `rake=` names an ISO 10628-2 group-28 stirrer, defaulting to item 28.4
  C2021's cross-beam, and `rake=None` leaves the plain settling tank. It
  replaces `Separator(characteristic="gravity")`, which is item 8.3 X8031: a
  tall hopper-bottomed drum, the shape of a dust collector, with nothing to
  draw a rake with. A clarifier is the same machine at a different duty and is
  this class.

  **`Kiln`** is a kind rather than a `furnace` variant, and the nozzles are the
  argument: a furnace heats a stream inside *tubes* and its flue gas is not a
  stream of the plant, while a kiln puts the solids in the fire and sends the
  spent gas on to a cyclone or a gas-cleaning train. So it draws `feed`,
  `product`, `offgas`, `fuel` and `air`, and `offgas` is what a fluidised-bed
  *drier* standing in for a calciner did not have. Three bodies: `default` (the
  rotary kiln, since an unqualified kiln is one), `fluidized_bed` and `shaft`.

  Nine drawings, taking the registry to 228. `RotaryKiln`,
  `FluidizedBedCalciner`, `ShaftKiln`, `CalandriaEvaporator`,
  `FallingFilmEvaporator`, `ClimbingFilmEvaporator` and `PlateEvaporator` are
  the classes over them.
- `Evaporator(supports=)`: the ISO group-26 element an evaporator stands on,
  the keyword `Vessel` already takes. It is the one composition layer an
  evaporator has, and deliberately: a heating element is not a tabulated
  supplementary symbol, so it is the body rather than a part drawn in one.
- `Separator(n_feeds=)`: a separator fed by more than one stream, spelled the
  way `Column` and `Reactor` already spell it (#452). A wash-water settler
  takes its wash beside the stream it is washing, a flare knock-out drum takes
  a header per relief system, and neither had to be drawn through a mixer that
  is not on the plant. The nozzles are `feed_1` … `feed_n` down the body's own
  wall, top to bottom, with `feed` kept as an alias at one, and a type checker
  resolves `Separator(n_feeds=3).feed_2` and refuses `.feed_9` -- on the
  equipment classes over it too, so `Cyclone("CY-1", n_feeds=2)` narrows to
  `Cyclone2` rather than to a `Separator`. `separator.feeds` is the whole
  family as a tuple.

  `variant="horizontal"` is the one drawing that refuses a second feed, and
  says why: its charge nozzle is authored on three faces so the face selector
  can put it on the head the line comes from, and a family is one band on one
  face -- a drawing may carry the menu or the family, and that one carries the
  menu.

  A one-feed separator is drawn exactly where 0.1.3 drew it on every variant.
  On the hopper-bottomed bodies -- the cyclone, the scrubbers, the mechanical
  separators and the three composed collectors -- the family grows *down* the
  wall from that nozzle rather than straddling it, which is what keeps the
  first feed where it was; `pandid.render.symbols.PortSeries` gained an
  `align=` for it.
- A `Feed` or a `Product` takes **any number of streams on its connection**
  (#454). One header entering a drawing and serving three users is ordinary,
  and forcing three flags for one header misrepresents the plant; the second
  `fs.connect(cws.outlet, ...)` used to raise `port CWSH.outlet is already
  connected`. The extra ports are `outlet_2`, `outlet_3`, ... (`inlet_2` ... on
  a `Product`), minted as the lines are made, and `cws.outlet` still means the
  first line. Each stream stays a stream of its own -- its own number, its own
  line number, its own row in the stream table, its own route -- and the flag is
  drawn once, every run reaching it at the tip of the pennant.

  **A process nozzle still takes one stream, deliberately.** Two pipes on a real
  nozzle is a tee, `Tee` draws one, and relaxing the rule everywhere would let
  an author draw a branch with nothing on the sheet marking it. A flag is not a
  nozzle: it is a mark saying the material crosses the sheet edge here, so it is
  also the one unit whose connections resolve to one point on purpose and the
  one the `coincident-ports` finding is not made for.
- `Flowsheet.add_control_loop()`: the single-variable feedback loop -- one
  transmitter, one controller, one final element -- in the one statement an
  engineer says it in, in place of four objects, two signal connections and
  hand-tuned placement (#439). It takes the control valve rather than making
  one, since the valve already stands in the run; letters the transmitter and
  the controller from the measured variable; states no standoff of its own, so
  the balloons take `add_instrument`'s defaults and #428's resolver keeps them
  apart; and returns a `ControlLoop` whose `transmitter`, `controller`,
  `final_element`, `measurement` and `output` are ordinary units and streams,
  still pinnable and still connectable. `examples/04_control_loop.py` draws its
  level loop this way and the golden it draws is unchanged.
  `transmitter_letters` and `controller_letters` take the member's **whole**
  functional code (`"FIC"`, not the `"IC"` after the `F`), which is the
  spelling `add_instrument` and `Loop.tag()` already take and the only one that
  can be checked against the loop; both default to the loop's own lettering, so
  the measured variable is still typed once (#448).
- `Tank(inputs=)`/`Vessel(inputs=)` and `outputs=`: a tank or a vessel fed (or
  drawn) by several streams, `Block`'s connection API over vendored artwork
  instead of a grown box -- `in_1`/`in_2`/... on whichever faces are named,
  squeezed onto a wall rather than growing it, `nozzle()`/`order_on()` to
  move and order them. At the default of one each, `inlet`/`outlet` are still
  the bare names they always were and no existing sheet moves (#342).
- `Dryer` gains `heating_in` and `vent`: the heating medium in and the
  moisture it leaves with, on every variant, alongside `feed`/`product`.
  A gas-suspension calciner no longer has to tee its combustion gas into
  the solids feed line or let product and off-gas leave on one nozzle to
  be parted downstream -- the port set the drawing needs is there.
- `DistillationColumn`, `Absorber` and `Stripper` over a `Column` that is now
  the general tower -- a feed, an `overhead` product and a `bottoms` one,
  nothing that assumes anything inside it boils (#400). `DistillationColumn`
  adds the reflux loop and the reboiler: `reflux_in`, `boilup_in`,
  `reboiler_duty`, `condenser_duty`. `Stripper` adds the reboiler alone,
  `boilup_in` and `reboiler_duty`, sitting beside `DistillationColumn` rather
  than under it. `Absorber` adds nothing -- it neither boils nor refluxes,
  and *is* a general tower. All three keep `internals=`, `trays=`, `n_feeds=`
  and `feed_stages=` unchanged from `Column`; `Absorber` defaults
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
- A new `validate()` finding, `stream-table-missing` (#365). `show_stream_table`
  ships `False`, so a process flow diagram with a `Feed` or a `Product` and
  no property stated on any stream was silently short of ISO 10628-1:2014
  4.3.2 d) -- name and quantify every ingoing and outgoing material -- and
  nothing said so. `boundary-flow-missing` already reports the same clause
  from the other end, for a sheet that has started tabulating and left one
  column out; this is the sheet that has not started at all. PFD-only, since
  4.3.2 governs a process flow diagram and a P&ID answers to a different
  clause, 4.4.2, that this does not attempt. The default stays `False`: a
  table drawn without data would only replace a missing table with a
  columns-of-dashes one, which states the denomination half of d) and not
  the flow-rate half, so flipping it does not on its own reach conformance
  -- the missing piece is data only the author has, which is what the new
  finding says.
- **`Flowsheet.show()` takes every keyword `render()` takes, and opens a
  window rather than a browser (#472).** It took none of them, so the one
  call an author makes while drafting was the one that could not preview a
  stream table, a page size, a P&ID or the coordinate overlay;
  `fs.show(show_stream_table=True, page_size="A3", diagram="p&id")` now
  draws what `fs.render(..., same words)` writes. The two signatures are
  held equal by a test rather than kept in step by hand, so a keyword added
  to `render()` and not to `show()` fails on the day it lands.

  The sheet opens in a resizable window, scaled to whatever size the window
  has and closing on Escape, and the call blocks until it is closed --
  `matplotlib.pyplot.show()`'s behaviour, without matplotlib. `dependencies`
  is still empty: the window is stdlib tkinter, and the SVG is rasterised
  for it by the same optional `pdf` extra `render("sheet.png")` already
  uses. Without a display or without that extra -- CI, a container, SSH
  without X11 -- the sheet goes to the browser as before, and the reason it
  went there is printed rather than left to be guessed at. Neither path
  hangs or raises on a headless machine.

  The temporary file no longer leaks. A window is handed bytes and writes
  nothing at all; the browser fallback keeps one file per process,
  overwritten by each `show()` and dropped on the way out.
- **`fs.stream_table.font_size`: the stream table can be sized (#473).**

  ```python
  fs.stream_table.font_size = 8.0
  ```

  It **rules the table and not only its lettering.** The row height and both
  minimum column widths follow it in proportion, so the table's footprint
  actually shrinks: on the fifteen-column sheet the issue describes, 8.0 takes
  the table from 902x80 to 687x61 drawing units, which is the difference
  between a drawing that fits A3 and one that raises. Setting only the glyphs
  would have done nothing at all for that sheet, since every column of a table
  of short names and short values sits on its minimum width. Left unset the
  table is sized exactly as it always was, and every shipped sheet is
  byte-identical.

  **An object rather than another keyword on `render()`**, which already
  carries nine that three of the four output calls restate. A table option
  describes the sheet rather than the file -- it means the same to
  `to_drawio()` as to `to_svg()` -- so it is settled on the flowsheet and said
  once for every way the sheet comes out, and the next table option is a field
  on `StreamTableOptions` rather than a tenth keyword on four signatures. It
  round-trips through the spec as `stream_table:`, and a sheet that leaves the
  table alone writes no such section, so its spec is the file it was before.
  `stream_table_sections` stays where it is: it is content -- the heading text
  the table draws -- and belongs beside `title_block` and `annotations`, not
  among the drafting choices.
- **`fs.stream_table.label_width` and `.column_width`: the table's two width
  floors can be raised, lowered or dropped (#477).**

  ```python
  fs.stream_table.column_width = "auto"     # rule the stream columns to content
  ```

  Every column was already measured from its contents and only *held up* by a
  floor -- 122 drawing units for the row-label column, 52 for a stream column.
  Those two numbers are a legibility judgement, they stay the default, and they
  are worth their width on the sheet they were chosen for and nothing at all on
  the sheet whose values carry their units. So they are now fields: a number is
  the floor exactly as before, and `"auto"` drops it. On
  `examples/13_mineral_dewatering.py` that takes the table from 1370 to 1182
  drawing units, and on `21_alumina_refinery.py` from 2982 to 2593.

  **The stream columns stay one width**, which is the decision the issue left
  open. A stream table is read down for one stream and across for one property,
  so `"auto"` measures every stream name and every value in the table and rules
  every column at the widest of them, rather than fitting each to its own cell:
  columns that did not line up would be a worse drawing than wide ones. The
  headings are in that measurement rather than beside it, so no column is ever
  ruled narrower than the stream number over it. `"auto"` is therefore never
  wider than the floor it drops but is not a promise of a narrow table -- one
  `1013.25 mbara` among three-figure values rules every column at it, and a
  table `"auto"` does nothing for is one whose widest cell was already ruling.

  Both compose with `font_size`, which scales them as it scales the row height:
  both are stated at the type size they were chosen against, so 122.0 set by
  hand is the 122.0 that was there. The gutter between a rule and a glyph is
  untouched and does not scale, which is what keeps a content-ruled table safe
  in the `.drawio` export, where a cell insets its own label before the sheet's
  pad is added. All 21 shipped sheets are byte-identical.
- **The types the reference names are on the package** (#441): `Port`,
  `Stream`, `Pin`, `Frame`, `Route`, `Loop`, `ControlLoop`, `ValveStation`,
  `Issue`, `TitleBlock`, `Revision`, `Annotation` and `TableBox`. `docs/api.md`
  named `ControlLoop` as a return type three times and none of the thirteen
  could be imported from `pandid`, so a reader who followed the reference
  exactly wrote `from pandid import ControlLoop` and got an `ImportError` --
  the documentation describing an API the package did not have. Every one is a
  type a reader is *handed*: `connect()` returns a `Stream`, `add_loop()` a
  `Loop`, `validate()` a `list[Issue]`, and a package shipping `py.typed` is
  asking to be annotated against.

  The rule the reference now follows, and `tests/test_documented_types.py`
  enforces: **a type the documentation names bare is importable from `pandid`,
  and a type that is not is named with the module it lives in.** Nine are on
  the second footing rather than the first, because they are machinery a reader
  never types -- `pandid.state.State` (reserved for a balance engine),
  `pandid.document.StreamTableOptions` (every flowsheet has one; nothing
  constructs it), `pandid.render.symbols.Symbol`, `PortSeries` and
  `SymbolRegistry` (reached with `default_registry`, which is not a type, on
  the import line the custom-equipment section already shows -- and keeping the
  renderer out of `import pandid` keeps the topology layer's import free of
  it), and the four layout and routing extension points. Nothing is removed or
  renamed, so every existing spelling -- `pandid.loops.ControlLoop`,
  `from pandid.document import TitleBlock` -- still imports.

### Changed

- **Equipment now says where its neighbours are drawn, and the sheet is
  fitted to every such claim at once (#447, closing #444 and #446).**
  Vertical position on a P&ID is not elevation: a condenser is drawn top
  right of its column because that reads clearly, and nothing in the
  package encoded it. Two class attributes now do. `Unit.PLACES` maps a
  nozzle to the compass point a unit connected there is drawn at
  (`Column.PLACES["overhead"] == "NE"`), and `Unit.LAYOUT_CONFIDENCE`
  says how hard this kind of equipment insists -- 8 for a tower or a
  reactor, 4 for a vessel, 2 for a machine in the train, 0 for a valve
  or a fitting, which sit *in* the line and state nothing about it.
  Adding a unit means adding those two attributes; the solver never
  changes.

  Every stream states **two** claims, one authored by each end, and they
  are free to disagree -- a column's `overhead -> NE` and its condenser's
  own north-facing inlet do. Nothing is ranked and nothing is dropped:
  the sheet minimises `sum of w * (p[subject] - p[author] - step) ** 2`
  per axis, which is `A p = b` with `A` the weighted graph Laplacian, and
  it is solved exactly rather than relaxed towards. There is no
  tolerance, no sweep cap and no "did not converge": one elimination
  order, one answer, one rounding step. Confidence is stiffness rather
  than authority, so a claim resists deformation at *both* ends and a
  unit wired into half the sheet becomes hard to move by connection
  count alone.

  `06_column_reflux` is what this is for: laid out from its topology
  alone it drew the tower upside down, condenser under the column and
  reboiler over it. It now draws the condenser and its drum top right
  and the reboiler bottom right. The same inversion on `03`, `16`, `19`
  and `21` is gone, and across the corpus the auto-placed sheets fall
  from 10 route crossings to 3 on `03`, 4 to 1 on `15` and 7 to 6 on
  `19`.
- **A pin is a boundary condition, held fixed and never solved for.** It
  cannot be traded away by a later pass, because it is not a term in the
  fit at all: its row and column are struck out of the system and
  carried into the constant. `pin(col=)`/`pin(row=)` on a *free-standing
  instrument* is honoured again, exactly (#444) -- stage 2 computed the
  column and then let its collision search walk the balloon off it -- and
  a column past the last one the sheet used is continued at the grid's
  own pitch rather than dropped in silence.
- **The gap between two columns is 120 px, not 100.** It is where the run
  between them is drawn and where its line number is written, and ISO
  15519-1 §7.2.5 wants that number beside its own line. The longest
  number in the corpus is a little under 90 px of lettering, which 100
  left nothing either side of.
- **A nozzle fixed to a face now places the unit that carries it (#431).**
  The old placement pass was a longest path in which every stream was read
  as one step to the east, so the geometry a symbol had already fixed --
  a column's overhead on the crown, a relief valve's inlet under its
  body, a reboiler return at the bottom -- reached nothing that decided
  where a box went. Placement is now two systems of difference
  constraints, one per axis, read off those faces per **endpoint**: a
  unit whose *west* port carries a stream is east of that stream's far
  end, and one whose *north* port carries it is south of it. An edge free
  at both ends still falls back to the flow order, so a sheet of plain
  blocks lays out as it always did. Splitting the axes is what lets a
  return line say *below* and nothing about along, which is why the two
  ends of a relief line are no longer placed at opposite corners of the
  sheet and drawn round the outside to meet (#430).
- **The engine draws the process first and the instrumentation onto it
  (#431).** The stage boundary was *has a host*; it is now process versus
  control. Stage 1 places every unit that carries material against every
  ``kind="material"`` stream; stage 2 places every balloon -- attached
  and free-standing -- and every signal run against that frozen geometry.
  A control loop is therefore no longer a cycle in the flow graph, so
  nothing tears a feedback wire to break one. Stage 1 also reserves the
  paper stage 2 will need, by inflating a unit's footprint by the
  balloons hanging off it.
- **A ribbon wider than the paper is folded into bands (#429).** A
  position is ``(band, column, row)`` from the start rather than a cut
  made afterwards, because cutting a solved ribbon puts a stream across
  the break running right to left -- which is the very inconsistency
  between geometry and nozzle the constraint solver exists to remove. A
  sheet that fits is left exactly as it was.
  Laid out with every ``pin()`` stripped, ``21_alumina_refinery`` comes
  out 2982 x 1860 against the ribbon's 6460 x 1509, and the corpus's
  eleven ``unit-overlap`` errors fall to one.
- `pandid.layout.SugiyamaLayoutEngine` is now `ConstraintLayoutEngine`;
  `default_layout_engine` is unchanged. `pandid.layout.layering`,
  `pandid.layout.ordering` and `pandid.layout.stacking` are replaced by
  `pandid.layout.solver`, `claims`, `place`, `halo`, `stages` and
  `control`. All six were private modules of the engine.

- **A valve, fitting, piping accessory or instrument balloon draws at half
  the weight of the equipment beside it (#305).** ISO 10628-1 §5.3.1 rules
  three line weights and one constant covered every symbol on a sheet, so a
  hand valve was drawn as heavily as the vessel it is bolted to. `Valve`,
  `Fitting` (and its `Reducer`, `Vent`, `Funnel`, `Ejector` siblings) and
  `Instrument` now draw at half the weight `Vessel`, `Pump`, `Column` and
  every other equipment and machinery symbol does; a `Symbol`'s `trim`
  says which class it is in, and both backends read it off the resolved
  symbol rather than off the unit's `kind`. **This moves every sheet that
  draws one of those kinds** -- 14 of the 21 shipped examples, and the
  goldens and gallery sheets with them. Nothing about a unit's box, ports
  or tag placement changes, only the ink its outline is stroked with.
  Where ISO 15519-1 §11.1.3 gives every symbol one flat weight and 10628-1
  §5.3.1 splits equipment from this finer class, pandid now follows
  10628-1: its own scope clause names it the application standard for
  this industry's diagrams, over 15519-1's general one. §5.3.1 a)'s third
  weight, a highlighted main flow line distinguished from a subsidiary
  one, is not part of this change -- pandid does not yet classify a
  stream as either, and is left for its own issue.

- **`Column` is the general tower; `DistillationColumn` is the specific
  one (#400).** `Column` used to carry every nozzle a distillation column
  has, so `Absorber`/`Stripper` inherited four of them dishonestly:
  Python cannot un-declare an inherited annotation, so a type checker saw
  a reflux nozzle on a tower that raised the moment one was connected.
  `t: units.Column` still accepts an `Absorber`, a `Stripper` or a
  `DistillationColumn`, exactly as before -- only which class carries
  which nozzle has changed, matching `Separator`, the one other class
  with a family of narrower subclasses. No drawing moves: all four still
  draw the same `kind="column"` symbol.

### Deprecated

Nothing about the drawing changes below; only where a nozzle lives in the
class hierarchy, or what it is called.

- `Column(...).reflux_in`, `.boilup_in`, `.reboiler_duty` and
  `.condenser_duty` → build the tower as `DistillationColumn` instead,
  which is what actually has them now. `Absorber` and `Stripper` never
  carried these honestly and do not carry this grace period either --
  reaching for one on either is a hard error, as it was before.
- `Column(...).distillate`, and the same on `Absorber`/`Stripper`/
  `DistillationColumn` → `.overhead`, the position name every tower's top
  product leaves through -- `distillate` is a distillation word, and an
  absorber's overhead product is stripped gas, not distillate.

### Fixed

- A **main flow line is drawn twice the weight of the equipment it enters**
  (#490). ISO 10628-1 5.3.1 states three line widths in the ratio 4:2:1, and
  the renderer had collapsed the first two into one number: a process run and
  the vessel it ran into were both 2 units, so the emphasis the clause exists
  to produce did not happen. A run is now 4 units and every sheet in the corpus
  moves.

  The three widths are a new `pandid.render.weights.LineWeight`, named for what
  each is -- `MAIN_FLOW`, `EQUIPMENT`, `DETAIL` -- and each stated as its own
  multiple of the grid module rather than as a width, so no rung can be moved
  without the ratio moving with it. Both backends read it; the draw.io exporter
  no longer keeps its own copy of two of the numbers. Every stroke either
  renderer emits now names a rung, and a test reads the two source files back
  to keep it that way, so an element added later cannot be given a width
  without first being put in one of the clause's three classes.

  Two things that had been written as a *width* and are not:
  a flange mark is 5.3.1 c)'s rung and not the run's, which is also the only
  rung where the pair of faces clears the gap 5.3.2 asks between two parallel
  lines; and the head on a line-number leader is a size, which had been written
  as the ratio between two rungs and would otherwise have halved on its own.

  The **line hop** follows the rung too, and had to. It was a flat radius of
  5, so a run widening from 2 units to 4 took the paper between the arc and
  the run it bridges from 0,75 mm to 0,25 mm -- measured on the raster -- and
  at that width the crescent closes and the mark reads as a junction where
  there is none. `HOP_R` is now the clearance the sheet has always drawn plus
  a half-pen of each of two main flow runs, which restores the 0,75 mm
  exactly. Two of the corpus's 53 crossings are too near a corner to carry the
  larger arc and are drawn plain instead -- ambiguous where the merged arc was
  wrong, and what all 393 crossings on the reference sheets in
  `professional_examples/` do anyway.

  No clause sizes that gap, and none is cited as if it did: ISO 10628-1 5.3.2
  is about parallel lines and does not reach a crossing. 5.3.4 in fact
  prescribes an *interruption* rather than a bridge, which is #499.

  Both of the drawing's remaining departures now **report** rather than being
  drawn in silence, which is the whole of what changed about them:

  - **`crossing-unmarked`**, from the renderer, when a crossing has too little
    run either side to carry its arc and is drawn bare. A bare crossing is not
    neutral on a sheet where every other one carries an arc -- it reads as a
    junction -- so the sheet names both runs and the point. Two on the shipped
    corpus, out of 53.
  - **`lines-crowded`**, from `validate`, when two runs run beside each other
    with less paper between them than ISO 10628-1 5.3.2 leaves: twice the wider
    of the two, and never under 1 mm. Six on the shipped corpus, where at 0,2 M
    there were none. Only pairs that actually run *together* count -- the two
    that merely abut end to end are not a pair a reader has to tell apart.

  Neither is fixed here: giving those runs the room is the router's, whose own
  separation is 6 units and derived from nothing (#498). What changed is that a
  drawing which no longer conforms says so on the sheet that fails.

  What else moved: `MIN_HEAD_CLEARANCE` follows the rung it is twice of, so
  `nozzles-crowded` now reports four crowded mixers on the shipped examples
  that were under the old floor and are over the new one; and a stream label
  stands off a run by half its pen plus a unit of paper, which relocated seven
  labels across the twenty-one golden sheets. No unit, symbol, port or run
  moved on any sheet.


- **draw.io child cells now turn with the symbol they are part of.** A
  parent cell's `direction` says how *its own* shape paints; mxGraph does
  not carry it into a child's geometry. So every drawing this exporter
  builds as a parent plus children came apart when it was laid on its
  side: a composed reactor drew an upright agitator across a vessel lying
  the other way, and a steam trap drew its body and both leads as tall
  slivers side by side, with the ink meeting neither nozzle. Both the
  `pieces=` stand-ins and the ISO supplementary `overlays` now place each
  child through `portgeom.symbol_to_box` — the same map the nozzles and
  the SVG artwork already use, so a part cannot drift from the port it is
  drawn under — and restate the parent's quarter turn so the shape paints
  the way the drawing does. The overlay half of this had been wrong since
  compositions landed; nothing in the corpus turns one, which is why it
  went unseen.
- The **two committed sheets made from one example no longer disagree about the
  date that example leaves blank** (#491). `03_distillation_train` and
  `08_from_data` state no `TitleBlock.date`, so `SvgRenderer` fills the cell with
  `datetime.now()` — right for a sheet drawn today, impossible for one committed
  to a repository. Both artefacts made from them therefore pinned that field, and
  they pinned it *differently*: `tests/golden/` to the arbitrary constant
  `2026-01-01`, `docs/gallery/` to the newest revision's date. The two sheets
  stood permanently one cell apart, and the cost was not the cell — it was that
  `test_the_example_draws_the_same_sheet_as_its_fixture` had to carry
  `_DATE_LEFT_TO_THE_RENDERER`, a list of which sheets were allowed to differ in
  which field, stated across all twenty-one scenarios to describe two.

  The fixtures now pin what the generator derives: the date of the sheet's own
  newest revision, which is the date it was issued at (`03` → `2026-08-01`,
  `08` → `2026-07-02`, both read off the revision rows those sheets already
  draw). The exception is deleted, not merely unused, and the two goldens move by
  the one DATE line each — which now agrees with the REV cell beside it.
  `test_no_fixture_dates_a_sheet_differently_from_the_generator` asserts the
  invariant over every scenario rather than the two, so an example that *starts*
  leaving its date blank is caught when it is written.

  `scripts/gallery.py`'s substitution still fills only a **blank** field; a date
  an author stated is theirs. That was measured rather than assumed: made
  unconditional, an overwriting `_stamp` is caught by exactly one of the
  twenty-one sheets, and only because `11_ethanol_pid` happens to be dated five
  days after its last revision. `test_the_generator_leaves_a_date_the_sheet_states_alone`
  now asks that question directly.

- **A title block that does not fit its box is no longer settled quietly**
  (#370). Every cell of the strip measured its value and abbreviated it, and
  every one of those decisions reached the author only as ink: `validate()` said
  nothing, and the finding a render did make named the field and quoted the
  value without saying by how much it missed. Four things change.

  **The drawing title is lettered smaller rather than abbreviated.** It is the
  only value on the strip set above the strip's reading size, and the only one
  read straight through instead of matched character by character against
  another document -- so it has size to give back before it has meaning to give
  up. It is set down to whatever fits, floored at the subtitle's size so the
  band cannot say the wrong thing about which line is the title, and abbreviated
  only below that. `examples/17_stirred_reactor_train` is the shipped sheet this
  moves: *Propylene Glycol Reaction* was being issued as *Propylene Glycol
  Reacti…*, and is now drawn whole at 12,0 in place of 12,5.

  **How much of a value survives is decided the way its width is measured** --
  and `text_width` measures two ways, so `clip` now cuts two ways, on the same
  test. The cut used to be `int(room / (size * _ADV)) - 1` for everything:
  characters at the *Latin* advance, while the decision to cut at all was
  `text_width`'s, which charges a CJK or fullwidth codepoint a full em and a
  combining mark nothing. The two disagreed by the ratio between those rates, so
  a fullwidth title kept 28 characters measuring 290 units for a 187-unit cell
  and was drawn straight through the sheet count beside it, on every page size
  from A4 to A0.

  A string of narrow codepoints alone measures `len(s) * size * adv`, a closed
  form, and keeps the cut that inverts it -- exact, and the arithmetic every
  sheet this package has drawn was cut by. Anything with a wide codepoint or a
  combining mark in it has no such closed form and is walked forward through the
  one expression `text_width` evaluates, so the prefix kept is a prefix
  `text_width` agrees fits.

  **Making *both* ends walk was the obvious repair and the wrong one.** Summing
  per-character widths lands a rounding away from the same characters measured
  whole, so seventy room/size pairs over a sweep of the strip's own type sizes
  cut a character earlier or later than they always had -- 30 characters fit a
  126-unit cell at 7,5 exactly, and the walk kept 29. That is `_total`'s
  complaint about `sum()` pointed at a different pair of numbers, and the answer
  is the same one: measure and use the identical arithmetic. A sweep of 16 772
  width/size/weight cases holds both halves.

  **`validate()` reports an over-long field before anything is drawn.** Every
  width the strip rules is a constant, so whether a value fits is settled by the
  block alone; the check now runs in the model half, where it can reach the
  author rather than describe a sheet that has already been issued. A render
  measures the same strip and replaces the findings with its own.

  **The finding says by how much, and names the field you would edit.**
  `text-truncated` and `text-overruns-cell` now give the width the value needs,
  the width the cell has and the ratio between them, the way `route-detour`
  states its two lengths -- so the author reads how much has to come out instead
  of guessing.

  And the name is the *source*, not the cell, spelled `source -> cell` where the
  two differ. Half the strip's cells draw a value some other field supplied, and
  every one of them named the cell: a blank `title` drew the flowsheet's name and
  reported `title`, a blank `scale` the fitted ratio, a blank `date` today's, the
  REV cell the newest revision's `rev`, and a backfilled `drawn_by` reported
  `revisions[0].by`. Each sent the author to a field they had never set. The
  `SHEET n of m` cell is the reverse case -- one cell, two fields -- and is named
  `sheet/of_sheets` rather than `sheet`.

  **One thing to fix is one finding.** The company cell stacks its name over
  several lines, so a group of companies repeating a word too wide to break
  reported that word once per line. Findings are de-duplicated over the whole
  layout, in one place rather than at each of the three that collect them.

  **Two fields could be lost without any cell overrunning, and both now say
  so.** A `company` name that wraps to more lines than the strip is deep was
  drawn out through the top and the bottom of the block in silence
  (`title-block-company-overflows`). And `drawn_by`/`checked_by`/`approved_by`
  fill the newest revision row's BY / CHK'D / APP'D cells and have nowhere else
  to go, so they went undrawn two ways -- a block with no revisions has no row
  for them, and a newest revision that states a signatory of its own keeps the
  cell. Both are `title-block-signatory-undrawn`, one finding per cause; a row
  stating the *same* name is silent, since the value is on the sheet and which
  field put it there is nobody's problem. Two of ISO 7200's mandatory data
  fields, accepted and dropped.

  **A field of nothing but spaces is the blank it means.** Whitespace is
  *truthy*, so it defeated every fallback the block has: `title="   "` drew
  three spaces instead of the flowsheet's name, `status` and `drawing_number`
  lost their em dash, a whitespace `scale` turned the four-cell bottom band on
  with nothing to put in it, a whitespace `client` or `project` ruled an empty
  row and made the whole strip *taller*, and a whitespace `company` was
  accepted, wrapped to no lines and drawn nowhere. Six of the block's fields
  answered differently from the blank they mean, and the SVG's `<title>` -- the
  document's accessible name -- was emitted as spaces where the code that drops
  an empty one could not see it. All of them are read through one function now,
  at the read rather than on the dataclass, since `fs.title_block.title = ...`
  is the documented way to shorten a field and re-render.

  That is #494's reproduction too, which found the same defect from the other
  side: `TitleBlock(date="   ")` left `tb.date == "   "` and drew a visually
  blank DATE cell on an issued sheet. The block is still exactly what the author
  typed -- the normalising is done at the read, not on the dataclass -- and it
  is the cell that stops being blank.

  **And a blank half of the sheet count takes the block's own default.**
  `sheet` and `of_sheets` are the only two fields of `TitleBlock` that default
  to something other than blank -- a drawing with no set behind it is sheet 1 of
  1 -- and left blank they drew `SHEET  of 1`, a count naming no sheet, on both
  backends and with nothing reported: the string as a whole sits well inside its
  55 units, so no cell was over its room and there was nothing for a width check
  to say. Half a sheet count reads as a *different sheet*, which is why that
  slot draws a long count whole rather than abbreviating it, and an empty half
  is the same loss with none of the ink. The fallback is read off the dataclass
  rather than written into the strip, so what an author sees in the block's
  signature is what a blank field draws, and the next field given a default is
  settled the day it is added.

  **And a value the author stated is drawn as stated, whatever its type.**
  Every field of the block is annotated `str` and nothing enforces it, so
  `TitleBlock(sheet=1, of_sheets=3)` is an ordinary thing to type and has always
  worked -- `str(1)` is `"1"`. Reading a field for *truthiness* rather than for
  whether it was set broke that for the falsey half: `sheet=0` was discarded as
  blank and then filled in with the field's default, so an author who stated
  sheet 0 was issued sheet **1**. That is this entry's own subject committed by
  the fallback above -- one stated value silently changed to another, which is
  worse than the blank the fallback exists for, because blank at least meant
  unset. The read now asks whether the field is `None`, and everything else is
  drawn as written. Refusing a non-string at the door was the other defensible
  answer and is not the one taken: it would break `sheet=1`, which reads
  naturally, works today and has nothing to do with the defect. The SVG's
  accessible document name asks the same question through the same function
  rather than keeping a second copy of the test, which is how it came to be the
  one read still deciding by truthiness.

  **Both fallbacks are the strip's, and are chosen after that read.** A blank
  title draws the flowsheet's name and a blank date today's, and both choices
  used to be made by each of the three callers, on the raw value -- so
  whitespace passed them and *then* normalised to nothing, with the value it
  should have fallen back to already thrown away. A `date` of spaces issued a
  sheet with an empty DATE cell, and a `title` of spaces was a truncation the
  drawing reported and `validate()` did not, the two having answered different
  questions about one block. The renderers and the validator now hand both
  fallbacks over unchosen.

  What that buys is the guarantee the whole finding rests on: over every field
  of the block in all three states -- unset, blank (whitespace, which is the
  blank it means) and stated but unfittable -- `validate()` reports word for
  word what the rendered sheet reports, and what `to_drawio()` reports. Each
  case also asserts *which* findings it must produce, so three silences do not
  satisfy it.

  **The drawing number now has one budget, however the sheet is asked for.**
  The bottom band is ruled at four fixed shares whether or not there is a scale
  to write in the scale box. It used to rule three when there was none and hand
  the room back to the cells that identify the drawing -- and the scale cell
  appears when the block states a scale *or* when a page size lets the renderer
  state the ratio it fitted the drawing at. So `drawing_number` was budgeted 118
  units by `to_svg()` and 88 by `to_svg(page_size="A3")`: the same
  `PFD-111111111` fitted one call and was silently abbreviated by the other, and
  no check that had not been told the page size could say which. A fixed slot is
  what `_SHEET_W` already does for the title, for the same reason -- and it is
  what lets the model check measure this band at all, every width in it now
  being a constant.

  A title block is a form: its boxes are ruled by the form and filled in by the
  drawing, so an unstated scale leaves an empty box rather than removing one.
  Four shipped sheets gain a ruled SCALE box and their DRAWING No / DATE / REV
  cells take the widths the other seventeen already had: `08_from_data`,
  `13_mineral_dewatering`, `16_demineralised_water` and `21_alumina_refinery`.

  Those three cells carry **initials**, being the only signatory cells the strip
  rules, so `examples/03`, `08` and `09` now set `drawn_by="AA"` in place of
  `drawn_by="A. Anderson"`. The full names were never drawn -- the revision rows
  state their own -- and would have been abbreviated to `A. An…` had those rows
  left the cells free. No drawing changes.

  The sweep behind it covers all fourteen scalar fields of `TitleBlock` and all
  six of `Revision`, and it takes that list from `dataclasses.fields` rather
  than writing it out: a field added to the block is swept the day it appears.
  Each field is swept in four states -- unset, blank, a value its cell holds and
  one it cannot -- and the third asserts the value reaches *both* rendered
  files, in **every cell ruled for it**. A cell that draws nothing overruns no
  room, so it is silent, so the validator and the two renderers agree about it
  perfectly; that is where `SHEET  of 1` lived. Counted per cell rather than
  searched for across the document, because `Revision.rev` is drawn twice -- the
  grid's REV column and the bottom band's REV box -- and either copy alone
  answers a search of the whole sheet.


- A **nozzle can no longer be drawn off the body it belongs to** (#488). A
  tank's or a vessel's inlets and outlets are a family whose count and faces
  are the unit's, so the drawing spreads them from the one nozzle the stencil
  anchored. That nozzle is a point and says nothing about how much wall there
  is either side of it, and nothing else did either: the run was centred on it
  and bounded only by a fraction of the *box*. A tank fills low on its shell --
  ten above the floor, deliberately, so a flammable liquid is not splash-filled
  (#226) -- so a family straddling that nozzle hung half of itself below the
  floor. `examples/21_alumina_refinery` shipped with M-901's and M-902's third
  inlet 8,9px under the bottom of the tank, with the stream to it ending in
  blank paper beside a symbol it never reached, and `validate()` was silent on
  both.

  `Symbol.bands` is the dimension that was missing: per face, the stretch of it
  a connection may be drawn on -- the straight shell, held off the weld at each
  end -- declared per symbol in `scripts/vendor_symbols.py` beside the nozzle
  coordinates rather than worked out from the artwork at run time. **Every face
  either family may be piped from names one**, on all eighteen holdup bodies.
  A dished roof, a cone apex and a dished head meet their box at a single
  point, and that is a band of no length rather than a missing band: one nozzle
  sits on it and a second beside it would be drawn in mid-air over the roof, so
  the second one is **refused** -- at construction, where the author wrote it,
  and again in the call that builds the artwork. Three `inputs=["N"]` on a
  dished-roof tank used to draw the outer two 2,65 units clear of the dome:
  inside the box, off the drawing, and unreported.

  `spread()` takes the band as an **outer limit**: the run is squeezed to fit
  inside it and then slid, by the least it can, until it is inside it. So no
  member of any family is ever outside its band, at any count, for any anchor,
  any pitch and any body height, and the same call carries the mixer, splitter,
  column, reactor and separator families. It is an outer limit rather than the
  binding one -- the span is `min(pitch x (n-1), extent x along, hi - lo)`, and
  `extent` is the tighter of the three on six of the thirty-six walled faces --
  but it is the only one of them that says *where* a run may be laid down,
  which is what `extent` could never state. Sliding rather than re-centring is
  what keeps a family that has room exactly where it was.

  The band travels with the ink: `compose()` carries and shifts it, so
  `Vessel(supports=...)` keeps the wall its body declares, and a `pin=` that
  overrides the spread for one member (`Column(feed_stages=)`) is clamped into
  it too. A limit one route ignores is not a limit.

  **Nothing drawn with one connection moves.** Every stencil's own nozzle is
  inside its own band, so a lone inlet or outlet still lands on precisely the
  coordinate it always did, on every face of every body. Two sheets change:
  `10_ethanol_pfd`'s M-302 (two fills) and `21_alumina_refinery`'s M-901 and
  M-902 (three each). All three are pinned by a nozzle, so the streams into
  them do not move at all -- the tank body drops to cover the fills, taking its
  outlet, vent, relief and drain with it. `21_alumina_refinery` also levels its
  caustic make-up flag with the inlet it feeds, which the corrected geometry
  made a 25px step.

  `validate()` reports the class of defect under a new code,
  `nozzle-off-body`: a nozzle the symbol places, drawn outside its own unit's
  box. It is silent on everything this package can draw -- the geometry above
  makes it so -- and is there for a symbol registered from outside it.

- A **utility header is no longer sunk by the consumers it feeds** (#459). A
  heater's steam nozzle is drawn on the bottom of the symbol, and the layout
  read that face as the heater asserting that its supply belonged *below* it on
  the sheet. Five heaters on one header mustered 10 against a flag with no
  opinion of its own, and the header was drawn under the whole bank with ten
  laterals running back up past every consumer: 24 crossings on a sheet two
  grid pins drew cleanly. The face is a drawing detail and not a claim, so
  `Unit.PLACES` now takes an entry of `None` -- "this nozzle's face is where
  the pipe attaches and nothing more" -- and `Heater.utility_in`,
  `Cooler.utility_out`, `Furnace.fuel`, `Dryer.heating_in`,
  `Filter.regenerant_in`, `Filter.spent_regenerant` and `CoolingTower`'s
  makeup, blowdown and air intake declare it. Not the same as leaving a nozzle
  out of `PLACES`, which still reads its face.

  Ten more classes were placed by their artwork alone and are now placed by a
  stated convention: `ScreeningDevice` is fed from the **west** rather than
  through its roof and passes its undersize south east; `Boiler.steam` leaves
  east rather than up off the dome; and `Furnace`, `Boiler` and `CoolingTower`
  (4), `Turbine`, `Mixer` and `Splitter` (2) are on the confidence rung their
  kind of equipment belongs to instead of the base 1 -- a manifold at 1 was the
  weakest non-zero class in the library, and it is the only header primitive
  here. `18_fixed_bed_recycle` is redrawn: its fuel gas subsystem now sits on
  one band instead of split across the sheet.
- `Flowsheet.add_control_loop()` validates everything before it writes
  anything, so a rejected call leaves the sheet exactly as it found it (#433).
  It made five mutations in sequence with no rollback, so a tag clash on the
  controller left the loop declared and the transmitter drawn, an invalid
  `output_kind` left both balloons and the measurement line, and a refused call
  with the number left out consumed one anyway -- the retry came back `L-102`,
  a number nobody typed, on a drawing whose loop numbers leave it for a DCS.
  Correcting the argument and calling again now lands the loop on the number it
  asked for the first time.
- `Flowsheet.add_instrument()` anchors the balloon before it joins the sheet,
  so a placement it refuses -- `at="up"`, a face on a stream host, a fraction
  on a unit host -- no longer leaves the balloon registered under its tag with
  a corrected retry reporting a duplicate (#433).
- `add_control_loop()` and `add_instrument()` refuse a `Loop`, a `measuring=`
  or an `acting_on=` belonging to another flowsheet. Taken, they drew a sheet
  that could not be read back: `Flowsheet.from_dict(fs.to_dict())` raised with
  nothing of that name to attach to, because the other sheet's units and loops
  are in no spec this sheet writes (#433). `connect()` has always checked
  endpoint ownership; this is the same question asked wherever else an author
  hands in an object.
- `01_ammonia_loop`, `02_manual_layout`, `04_control_loop`, `05_reactor_recycle`,
  `06_column_reflux`, `07_metering_skid` and `16_demineralised_water` state a
  flow on every stream that crosses the sheet edge and render with
  `show_stream_table=True`, so the reference corpus no longer raises the
  `stream-table-missing` finding it ships the check for (#410). A relief line
  carrying no flow in normal service states that with a blank value rather
  than a number, the same convention `boundary-flow-missing` already reads.
- A sheet with a stream table and no other furniture -- no border, no title
  block, no annotation -- now docks the table through the same
  `dock()` every other piece of furniture is placed by, instead of a
  separate calculation that put it at different coordinates than the
  `.drawio` exporter, which always docks through `dock()`, drew it at.
- `Reactor(agitator="propeller")` and `agitator="impeller"` draw instead of
  raising.
- A type checker resolves `reactor.feed_2`, as it already did `mixer.in_2`.
- `Valve(variant="three_way")` anchors its third leg, `branch`; `ThreeWayValve`
  reaches it by name.
- A line number with its first scheme component unset no longer opens with a
  stray separator, e.g. `AE-1001-SS` rather than `-AE-1001-SS`.
- `add_valve_station(bypass_over=...)` naming a member the station was told
  to leave out is now refused before any member joins the sheet, instead of
  after ten units are already on it.
- `TableBox(col_align=...)` raises on an entry outside `"l"`/`"c"`/`"r"`
  instead of silently centring it.
- `stream_table_sections` naming a property no stream in the table sets now
  warns instead of the heading silently never appearing.
- `TableBox`/`Annotation` furniture placement no longer calls the builtin
  `sum()`, whose float algorithm changed in CPython 3.12 (gh-100425) and
  could round 0,1 unit differently from a plain running total on the same
  values -- a column 5 or 15 characters wide could land its own centring on
  that tie and draw 0,1 unit apart on 3.11 and on 3.12+. `19_absorber_stripper`
  no longer needs to keep its utilities table off the tie by choice of header.
- A unit's `width`/`height` is refused if it is not a positive, finite
  number. A negative or zero size reached `<use width=... height=...>` and
  the `viewBox` beside it, which the SVG spec calls an error on either; a
  conformant reader drew nothing for the symbol, silently, while its tag
  and the pipe routed to its nozzle were drawn as if it were still there.
- `connect()` refuses a stream whose source and destination are the same
  port. Nothing stopped a signal connection -- the one port shape with no
  fixed direction -- being run from a nozzle back to itself; undrawn but
  undetected, since the resulting zero-length spike is exactly what the
  renderer's own collinear-run collapse then erases.
- `from_dict()` resolves a plain `Column`'s retired nozzles (`reflux_in`,
  `boilup_in`, `reboiler_duty`, `condenser_duty`) the same way accessing
  them at run time does, instead of only checking `unit.ports` directly. A
  stream connected to one of them wrote out under its name from `to_dict()`
  same as any other, but `from_dict()` raised on reading it back -- the
  one-release grace period #400 gave those four broke round-tripping the
  very sheet it was there to keep working.
- `Feed`/`Product` given an explicit `height=` now draw a pennant that fills
  it -- inset off the placed height, nozzle centred in the middle of it --
  instead of the same 20-unit strip near the top of whatever box the sheet
  reserved. The default (unsized) flag is unchanged, since its height was
  already the symbol's own 50 units.
- `Mixer`/`Splitter` take `label_pos=` in the constructor, matching every
  other tagged unit; setting it after construction already worked.
- `Reactor`/`Column`'s single charge nozzle is now really named `feed_1`,
  numbered from one the way `Mixer`'s `in_1` always was, so raising
  `n_feeds` from one no longer silently drops every `.feed_1` reference and
  `.feed_1` resolves at `n_feeds=1` where it used to raise. `feed` stays as
  a bare alias for it at one feed, so an existing `.feed` reference and a
  `pin(port="feed")`/`nozzle("feed", ...)` call are unaffected. No drawing
  moves: the alias is not a second port, so a single feed is placed exactly
  as before.
- A tag's estimated width counted codepoints, so a CJK character was
  charged the same width as a Latin letter though it draws close to a full
  em: an equipment tag's erasing halo, a block's own box and a boundary
  flag's label could all come out well under what the name actually drew,
  and `label-overruns-symbol` shared the same blind formula as the boxes
  it checked, so it agreed with the shortfall instead of catching it.
  `text_width`, the halo, `block_symbol`, the check and
  `resolve_size` now share one script-aware measure
  (`pandid.render.furniture.script_counts`): a wide (CJK/fullwidth)
  character draws a full em, a combining mark draws nothing, and an
  ambiguous-width character (Greek, Cyrillic, most symbols) is read as
  narrow, per Unicode's own no-context default. A Latin, digit or
  punctuation string still measures exactly as it did -- no shipped,
  Latin-tagged drawing moves.
- `layout()`'s cycle-breaking walk no longer recurses to the depth of the
  longest unbranched chain. A sheet a few hundred units past
  `sys.getrecursionlimit()` hit `RecursionError` from inside the library,
  and the exact chain length that failed moved with the limit and with how
  deep the caller already was -- the same sheet could draw in a script and
  crash inside a web request (#413). The walk now runs on an explicit
  stack instead of the call stack, which removes the limit rather than
  raising it; a chain of 20,000 units lays out where 1,500 used to crash.
  The rewrite is a mechanical one, not a re-ordering, so which edge gets
  marked the recycle is unchanged -- checked directly by comparing the new
  walk's marking against the old recursive one over generated topologies.
- `Column.internals`/`.trays`/`.feed_stages`/`.draw_stages`, `Reactor.agitator`
  and `Vessel.supports` refuse a reassignment after construction instead of
  accepting it and changing nothing (#415). Each is read exactly once, in
  `__init__`, to build the overlays and place the nozzles it describes;
  `col.feed_stages = [...]` after the fact raised nothing and moved no
  nozzle, silently disagreeing with the drawing already built from the
  value the constructor was actually given. Reassigning any of the six now
  raises `AttributeError` naming the constructor keyword to build a new
  unit with instead -- the same answer `Tee.branch_direction` already gives
  a caller who tries to turn a takeoff into a return after the nozzle is
  built. `width`/`height`, which do propagate, are unaffected. The refusal
  is declared once per class and inherited, so `DistillationColumn`,
  `Absorber` and `Stripper` refuse `internals`/`trays`/`feed_stages`/
  `draw_stages` the same way `Column` does, rather than each needing its
  own.

### Security

- draw.io reads a cell's `value` as HTML, so a tag an author's text carried
  (a unit name, a description, a stream property, a title-block field, …)
  rendered as markup there while the SVG export drew it literally. Author
  text is now escaped for that HTML layer before composing a label, so both
  backends draw the same tag as the same tag.

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

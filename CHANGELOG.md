# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `fs.package("PK-301", [p301a, p301b, f301], description="Dosing Package",
  reference="VENDOR DWG 4711")` draws a package unit as a dash-dot boundary
  frame round its units, tagged outside its upper-left corner, and lists it in
  the equipment list above them. Layout keeps other units out of the frame, and
  `validate()` reports `package-encloses` for one drawn inside it.
- `validate()` warns `valve-under-arrowhead` when a valve or fitting is drawn
  so near the nozzle it feeds that the arrowhead into the nozzle reaches over it,
  and says how to clear it: an `at=` for a valve alone on its line, the `at=`
  bounds that keep the line's order where other items share it, or the end or
  neighbour to move where pinned ends leave no room.
- `fs.line_list()`, `fs.equipment_list()` and `fs.instrument_index()` return
  the sheet's schedules as rows, ready for `csv.DictWriter` or pandas.
- `Document([fs1, fs2]).validate()` checks a set of sheets against each other:
  off-page connectors without a partner or on lines that disagree, a tag on two
  kinds of equipment, a drawing number on two sheets, and references to
  drawings outside the set.
- `Vessel` and `Evaporator` draw manholes and sockets on their walls:
  `Vessel("D-101", manholes=[("E", 0.3)], sockets=[("W", 0.7)])`. Each socket
  is a port, `socket_1`, `socket_2`, and so on.
- On a PFD, `validate()` warns when an energy line does not name its carrier.
  Name it with `fs.connect(..., service="LP steam")`, which its line number draws.
- `Crystallizer` draws a draft-tube baffle crystallizer with `feed`, `vapor`,
  `overflow` and `product` nozzles. `agitator=` names the stirrer in its draft
  tube, or `None`.
- `FlotationCell` draws a mechanical flotation cell with `feed`, `concentrate`
  (from the froth launder), `tailings` and `air` nozzles. `agitator=` names the
  rotor on its shaft, or `None`.
- `CombustionChamber` draws a chamber burning fuel to hot gas: air at `inlet`,
  `fuel` from below and the gas out of `outlet`. `Furnace(variant="general")`
  draws the ISO 10628-2 furnace.
- `CentrifugalFan` and `AxialFan` draw those fans, and
  `Blower(variant="general")` draws the ISO 10628-2 fan.
- `Silo` draws the closed silo of ISO 10628-2 and `Bunker` its open bunker,
  each with a conical bottom: solids enter at `feed` and leave at `discharge`,
  and a silo vents through its roof at `vent`.
- `MixerSettler` draws one solvent-extraction stage with `light_in`,
  `heavy_in`, `light_out` and `heavy_out`. `ExtractionColumn` is a sieve-tray
  column whose two feeds enter its top and bottom stages.
- `Deaerator` draws a storage drum with its deaerating column on top: `feed`
  and `vent` on the column, `steam` into the drum and `outlet` from its floor.
- `JacketedReactor` is a stirred reactor in a heating or cooling jacket, with
  a utility inlet and outlet on the jacket: `jacket_in`, low on the jacket,
  and `jacket_out`, high on it.
- On a PFD whose lines state properties, a render without the stream table
  warns that none of them is drawn. `validate()` follows the last render, and
  `validate(show_stream_table=True)` or `pandid validate --stream-table` asks
  about a sheet drawn with it.
- `validate()` warns `line-through-support` when a line enters a vessel through
  its legs, brackets or ring. Leave the vessel's `height` unset, or give a
  larger one, so its shell grows clear.
- `validate()` warns `line-field-undrawn` when a line-number field set in
  `connect()` is not drawn: `name=` replaces the line number,
  `line_numbering_scheme` leaves the field out, or the field is stated past a
  valve or tee that carries another segment's number on. It names the fix.
- A flat-floored `Tank` draws off from either wall as well as the floor, and an
  upright `Vessel` takes its inlet on either wall or the top head and its outlet
  on either wall: `Tank("TK-1").nozzle("outlet", "E")`. A counted one moves
  there toward its peer where that draws fewer bends.
- A `Reactor` takes a feed on its top head beside the drive, a `Column` its
  feeds and draws on either wall at their stage height, and an upright
  `Separator` its feeds on either wall: `Reactor("R-1").nozzle("feed", "N")`.
  Layout moves one there toward its peer where that draws fewer bends.

### Changed

- `Blower()` draws the ISO 10628-2 fan instead of a compressor.
- `connect()` no longer needs `kind=` for a signal line: a line to a valve
  with a diaphragm actuator, or none drawn, is pneumatic and any other is
  electric. `add_control_loop()` infers its output line the same way, so a
  loop acting on a motor or solenoid valve, or on another controller, now
  draws an electric signal.
- A counted `Block`, `Tank` or `Vessel` connection, as in `inputs=2`, moves to
  the face toward its peer where that draws fewer bends; a list such as
  `inputs=["W", "N"]` keeps every face as given, even on a single inlet.
- A `Vessel` is drawn to the size it is given rather than stretched to it:
  `width` and `height` are the drawn box, the heads, supports, manholes and
  sockets keep their own size, and the straight shell takes the rest. With no
  size given, the shell grows until its inlets and outlets clear the supports.
- `render()` lays out and checks a sheet faster, most of all when units are
  pinned by a nozzle.

### Deprecated

These are removed in 0.4.0.

- `pandid.document.equipment_list()`, the drawn box, and the spec box
  `type: equipment_list`. Use `equipment_table()` and `type: equipment_table`.
- `duty` on `Reactor(variant="jacketed")`, which now draws `jacket_in`. Use
  `JacketedReactor`, with `jacket_in` for the jacket's supply and `jacket_out`
  for its return.
- Reassigning `variant` on a built `Valve`, `Vessel`, `Tank`, `Filter`,
  `HeatExchanger`, `Reactor` or `Separator`, whose ports or faces come from it.
  Build a new unit with `variant=`.

### Fixed

- A balloon whose signal nozzle faces into a unit close by turns its nozzles
  to clear sides, so its lines are no longer drawn through that unit, where
  that adds no crossing or other finding.
- A pump, compressor or fan fed from a `Feed` flag and feeding a unit far along
  the train is drawn in the column beside that unit, where that adds no
  crossing, bend or finding, instead of at the sheet's left edge.
- A unit moves up or down to meet a feed or product flag held under another
  unit in its column, so the line between them runs straight, where that adds
  no crossing, bend or finding.
- Lines that cross on their way into a mixer are laid on lanes even where they
  share their stretch of the gap with only some of the lines beside them, so the
  last two pumps of a header of tees no longer cross into the mixer.
- The equipment list and `fs.equipment_list()` include centrifuges and
  crushing machines.
- A `Tee` whose branch serves a unit drawn above the run turns its branch north,
  so a header of tees no longer draws each branch as a box crossing back through
  the run. `tee.pin(mirrored=False)` keeps the branch south.
- A valve or fitting on a line from a `Splitter`, or into a `Mixer`, sits next
  to the unit at the line's other end, so a bank of pumps draws its isolation
  valves beside the pumps without crossings. One given `at=` keeps its place.
- A balloon takes any number of signal lines. Lines on one side of it leave
  from separate points on its outline instead of stacking on one point.
- The `boundary-flow-missing` warning is made on a PFD only, not on a sheet
  drawn with `diagram="p&id"` or `diagram="bfd"`.
- Units pinned with `pin(row=)` and no `col=` are drawn in row order across the
  sheet, so `pin(row=2)` is drawn above `pin(row=3)` in another column.
- `route()` no longer turns a line into a nozzle from the side when it could
  run straight in with one bend fewer.
- A `Reactor` sets its feeds far enough apart that their arrowheads do not
  touch, so `Reactor("R-1", n_feeds=2)` no longer raises `nozzles-crowded`.
- The tubular reactor is drawn taller, so `Reactor("R-1", variant="tubular",
  n_feeds=3)` sets its three feeds far enough apart that their arrowheads do not
  touch.
- Lines drawn side by side no longer push a pipe into a unit body: a run moved
  off a shared track, and the segments either side of it, keep clear of every unit.
  A run with no clear track nearby stays on the track the router laid it on.
- A balloon hung from a transmitter, as in `add_instrument("TIC", 1, near=tt,
  face="S")`, is set at least an arrowhead clear of the line the transmitter
  taps, so `route()` settles instead of drawing that line through the balloon.
- `validate()` reports a `route-crosses-unit` warning for a slanted `via()` leg
  drawn through a unit, including the unit the line connects to.
- `on=` puts a valve, fitting or valve station on a recycle line, including one
  connected with `draw_as_recycle=True`, before or after the sheet is rendered.
- On a sheet drawn with `diagram="p&id"` or `diagram="bfd"`, the stream table
  drops the column of a line that crosses the sheet edge and states no property.
  A PFD keeps that column.
- A controller is not hung off its valve's actuator where its `via()` line would
  pass through it more often than where it stands unhung.
- A tank or vessel with several inlets or outlets on one wall, such as
  `Tank("TK-1", outputs=["S"] * 4)`, gives each its own nozzle clear of the
  vent, relief and drain on that wall.
- Equipment or a line valve that would be drawn on a balloon pinned with
  `pin(x=, y=)` is moved clear of it and of the balloons hung on it.
- Reassigning `variant` on a unit built with supports, an agitator, internals,
  manholes or sockets redraws them on the new body and keeps any overlays added
  since, or refuses a body that cannot carry them and keeps the old one.
- `route()` routes a line again where moving it off a shared track makes it
  cross lines its route did not count, and keeps the new drawing only if it
  has no more crossings, bends or findings.
- A vessel whose supports, manholes or sockets widen its box draws every inlet
  or outlet on the wall it was given, so
  `Vessel("D-1", variant="dished", inputs=4, supports="bracket")` draws.
- `line.color` and `line.dasharray` set after `on=` has split the line style
  the whole line, including the pipework of a valve station on it.
- A sequence set in `connect()` is drawn in the line number when another
  segment of the line states the other fields, and alone when none does:
  `fs.connect(..., sequence="2740")` draws `2740` instead of `S1`.
- A valve's actuator sits on the body's centre line, so a balloon added with
  `near=valve, face="N"` drops its signal line straight onto it. Symbol sizes and
  nozzle positions are no longer rounded to a tenth, so `pinned_x()` and
  `port_offset()` can differ in the second decimal.
- A valve station put on a line with `fs.add_valve_station("CV-1", on=line)`
  draws its run, bypass and drains in the line's `color` and `dasharray`.
- A `Feed` or `Product` too short to letter, such as `Feed("Air", height=20)`,
  is refused with the height that fits, `height=42`, or `height=48` with a
  `reference`, instead of failing `nozzle-off-body` when drawn.
- Layout, routing, labels and the sheet edge keep clear of a `Feed` or `Product`
  as its pennant is drawn, not of the blank paper above and below it, so a
  sheet with a flag at its top or bottom is framed tighter.
- Where neither side of a symbol has room for both codes of a pair, such as
  `annotate(high="TAH", low="TAL")`, one is written on each side instead of
  over a line.
- `route()` ends the run a line leaves a nozzle on clear of every other unit,
  so a signal line between two balloons no longer cuts through a third
  standing between them.
- Where `route()` finds no path for a line and draws it through a unit, it
  draws it round the units in its way along a clear lane where that draws no
  worse; otherwise `validate()` reports `route-crosses-unit` as before.
- A valve station put with `on=` on a line between stacked units is turned to
  run up or down the line, with room kept for it between the units, instead of
  being drawn over the unit above.
- A sheet fitted to its drawing reaches past a tag drawn beside a unit at its
  edge, so `label_pos="right"` on the last unit no longer cuts its tag off.
- An angle valve put on a line with `on=`, such as
  `fs.add(Valve("HV-1", variant="angle"), on=line)`, is set at a corner of the
  line, so the line turns through the valve instead of bending to leave it.
- `nozzle()` on a `Tank` or `Vessel` inlet or outlet names the face as drawn
  again, so a turned or mirrored tank draws the nozzle on the face named.
- A balloon hung on another balloon, such as `fs.add_instrument("LIC", 101,
  near=lt)` on a pinned `LT`, is no longer drawn across that balloon's tap line.
- A balloon attached with `face=` to a face whose middle a line leaves from taps
  the face beside that nozzle, so its tap line no longer runs along the pipe.

## [0.2.0] - 2026-11-05

Every sheet without pins draws differently from 0.1.5.

### Added

- Put a valve, fitting or control-valve station into a line with `on=`:
  `fs.add(Valve("HV-101"), on=line)`.
- `help(pandid)` is a short guide to drawing with pandid.
- `validate()` reports lines that touch units, arrowheads or nozzles, material
  that crosses from one side of an exchanger to the other, and misspelt
  symbol variants.
- Support for Python 3.15.

### Changed

- Equipment is laid out in columns that follow the flow, and `route()` no
  longer moves units.
- An in-line valve or fitting turns to run along its pipe.
- `pin(row=)` orders units down their column instead of naming a grid row.
- A balloon's side on a unit is set with `face=`; `at=` is only a position
  along a line.
- Many unit classes, such as `Feed`, `Valve`, `Vessel` and `Block`, take
  `width`, `height` and other options by keyword only.
- Error messages and `validate()` findings name the call that fixes them.
- The examples are numbered from 01 and show only the tables and boxes they
  need. The alumina refinery is drawn on three linked sheets.

### Deprecated

These are removed in 0.3.0.

- `at=` for a balloon's side on a unit. Use `face=`, and `controller_face=`
  for `controller_at=`.
- `default_input_face()` and `default_output_face()` on `Tank` and `Vessel`.
  Set faces with `inputs=` and `outputs=`, and read them from `input_faces`
  and `output_faces`.
- `PLACES` and `LAYOUT_CONFIDENCE` on a unit class. Use `nozzle()` or
  `pin(orientation=..., mirrored=...)`.
- `routing.Router`. Pass `fs.route()` any object with a `route(fs)` method.
- `DefaultRouter(recover_exits=)`. Use `DefaultRouter()`.
- `Stream.line_components()`. Read the stream's `size`, `service` and other
  fields directly.

### Removed

- The spellings deprecated in 0.1.3 and 0.1.4:
  - `Vessel(variant="legs")` and `"skirted"`: use `supports="leg"` and
    `"skirt"`.
  - `Reactor(variant="plain")` and `"mixing"`: use `internals="packing"` and
    `agitator="disc"`.
  - `Separator(variant="gravity")`, `"electrostatic"` and `"electromagnetic"`:
    use `characteristic=`.
  - `reflux_in`, `boilup_in`, `reboiler_duty` and `condenser_duty` on a
    `Column`: use `DistillationColumn`. Use `overhead` for `distillate`.
  - `DEFAULT_INPUT_FACE` and `DEFAULT_OUTPUT_FACE`: use `input_faces` and
    `output_faces`.
- `ControlLoop.variable`, `.number`, `.name`, `.tag()`, `.element()` and
  `.check()`. Use them on `ControlLoop.loop`.
- `Port.state`, `Port.side`, `Unit.params` and
  `pandid.document.location_reference`. Stream conditions stay on
  `Stream.state`.
- The `layout-search-*` warnings and the internal layout modules behind them.
- The ammonia loop example, which another example already covers.

### Fixed

- Parallel banks of equipment draw without crossing lines.
- Lines keep clear of unit bodies, arrowheads and tags, and a route set with
  `via()` keeps its points.
- A unit pinned to a row between two stacked units is drawn between them.
- A valve or fitting pinned with a turn and a mirror sits on its pipe with
  its inlet upstream.
- Balloons are tidier: tap lines leave the unit square, a balloon keeps off
  the line it taps, a controller stands beyond the valve it drives, and alarm
  letters keep off flange marks.
- Line numbers fit their plates, and tags fit their halos.
- Normally closed valves, expanders and thin symbol lines are drawn at the
  right weight.
- draw.io output matches the SVG more closely, and reports text that does not
  fit and crossings it cannot mark.
- A refused call leaves the sheet as it was.
- Bad values are refused with a clear error instead of drawing wrongly or
  crashing.
- Spec files accept numpy numbers, keep YAML values such as `0101` and `1:30`
  as text, refuse a key written twice, and round-trip a few more settings.
- Numbered nozzles such as `Mixer("M", n_inlets=3).in_3` pass mypy and
  pyright.

## [0.1.5] - 2026-08-26

### Fixed

- Process lines are drawn at the weight of the equipment they enter again,
  not twice as heavy.
- Stream-number diamonds are square and filled white, and their outline is no
  longer notched by the number.

### Changed

- A stream number in a diamond or circle reads upright on a vertical line.

## [0.1.4] - 2026-08-25

### Added

- `crossing_style` marks a crossing with a break (the default), a bridge or
  nothing.
- Stream numbers can sit in a diamond, circle or box.
- The stream table can be sized, or drawn on its own sheet with
  `show_stream_table="sheet"`.
- `diagram="bfd"` marks a sheet as a block flow diagram.
- `Evaporator`, `Thickener`, `Kiln` and `SteamTrap`.
- `Flowsheet.show()` takes the same options as `render()` and opens a window.
- `Port`, `Stream`, `TitleBlock` and the other documented types import from
  `pandid`.

### Changed

- `pin(port=...)` survives turning, mirroring or resizing the unit.
- `Column` is the general tower and `DistillationColumn` the distillation one.
- Valves, fittings and balloons are drawn lighter than equipment, and main
  process lines heavier.

### Fixed

- The steam trap drew the wrong symbol.
- Text is measured at its real width, so long tags are no longer cut short.
- A title-block value too long for its cell is reported instead of cut off.
- Options that were silently ignored now take effect or are refused.
- A refused `connect()` or render leaves the flowsheet unchanged.
- `validate()` checks the sheet last rendered.
- Fewer avoidable crossings.

## [0.1.3] - 2026-08-19

### Added

- Equipment shows what is inside it: agitators, internals, trays, supports and
  separation type.
- Plug-flow, packed-bed and fluidised-bed reactors.
- New equipment: `Crusher`, `Mill`, `Centrifuge`, `CrushingMachine`,
  `CoolingTower`, `VenturiScrubber`, `Elevator`, `Boiler`, `Stack`, `Flare`,
  screw conveyors and gas holders, and more dryer and cooling-tower drawings.
- Cake-forming filters draw their cake and wash nozzles.
- `pinned_x()` and `pinned_y()` give where a pinned unit or nozzle sits.
- `validate()` reports stretched symbols, missing boundary flows and diagonal
  routes.
- Five new examples.

### Changed

- `pin(x=, y=)` on a `Feed` or `Product` places its nozzle, not its corner.
  Pass `port=None` for the old behaviour.
- The default reactor is a stirred tank, and a `Column` is drawn bare until
  you say what is inside it.
- The stream table shows only the columns that carry something.
- Large sheets route and lay out much faster.

### Deprecated

- `Reactor(variant="mixing")` and `"plain"`, `Vessel(variant="legs")` and
  `"skirted"`, and `Separator(variant="gravity")`, `"electrostatic"` and
  `"electromagnetic"`. Use `agitator=`, `internals=`, `supports=` and
  `characteristic=`.

### Removed

- The spellings deprecated in 0.1.2:
  - `add_instrument(on=)`: use `sensing=`, `acting_on=` or `near=`.
  - `Instrument(variant="panel")` and `"aux"`: use `display="central"` and
    `"subsidiary"`.
  - `Valve(variant="pneumatic")`: use `variant="control"`.
  - `vapor` and `liquid` on dust separators: use `overflow` and `underflow`.

### Fixed

- Pins anywhere on the sheet are honoured, and `layout()` draws the same sheet
  every time.
- An edit made after a render shows in the next one.
- Composed units and balloons round-trip through a spec.
- Filter screens, packed-bed reactors and stirred vessels draw correctly.
- Zone borders letter their rows and number their columns.
- draw.io reports what it cannot draw.
- `pandid validate` takes `--diagram`.

### Security

- Text from a spec file is escaped, so it cannot put script into a drawing.

## [0.1.2] - 2026-08-05

### Added

- Export to editable draw.io with a `.drawio` path, which also opens the way
  to Visio.
- `render(connections="flanged")` marks flanged joints.
- `instrument.annotate(high=..., low=...)` writes alarm letters beside a
  controller.
- `fs.add_balloon(element)` gives a primary element and its balloon one tag.
- Control loops and stream numbers number themselves, from
  `loop_number_start=` and `stream_number_start=`.
- An instrument can take several signal lines.
- `Vessel` and `Tank` have `relief`, `drain` and `vent` nozzles.
- `validate()` reports nozzles that were asked for but left unconnected.
- Deprecated spellings warn, and `validate()` reports them.
- Every unit class imports from `pandid`.
- Rendered files record the pandid version that drew them.
- Two new examples: mineral dewatering and a tank farm.

### Changed

- `add_instrument()` takes `sensing=`, `acting_on=` or `near=` to say how a
  balloon relates to what it is placed against.
- `display=` sets where an instrument is read, separately from `variant=`.
- A control valve draws its actuator, and `Valve(actuator=)` sets it
  separately from the body.
- A tank fills through its shell by default.
- Dust separators name their nozzles `overflow` and `underflow`.

### Deprecated

- `add_instrument(on=)`, `Instrument(variant="panel")` and `"aux"`,
  `Valve(variant="pneumatic")`, and `vapor` and `liquid` on dust separators.

### Fixed

- Symbol bodies are opaque, so a shell no longer draws through its nozzles.
- A resized symbol keeps its line weight.
- Labels no longer cover the lines, marks and outlines beside them.
- A shared-display balloon draws its bar.
- draw.io files state their page, so draw.io no longer crops them, and their
  tables no longer clip their text.

## [0.1.1] - 2026-08-01

Sheets drawn on this version differ from 0.1.0, so compare a drawing before
reissuing it.

### Added

- `Block` draws block flow diagrams.
- `pandid.devices` adds 42 named equipment classes, such as `Cyclone` and
  `KettleReboiler`.
- Type checkers see every nozzle, and numbered nozzles come as tuples such as
  `Mixer.inlets`.
- `debug=True` draws the coordinate grid, pins and ports on the sheet.
- More `Vessel`, `Tank`, `Separator` and `Filter` drawings.
- `validate()` reports crowded nozzles and runs that are nearly level.
- Support for Python 3.14.

### Changed

- `pip install 'pandid[pdf]'` works with no system libraries. PDF and PNG
  lettering is Helvetica.
- The default separator is a plain vessel; the knock-out drum is
  `variant="knockout"`.

### Fixed

- PDF and PNG lettering is the right size and centred.
- Resized symbols keep their line weight, curved heads draw the right shape,
  and relief valves are full size.
- A line number away from its line gets a leader, and labels no longer hide
  symbols or lines.
- Instrument lines run at right angles and are drawn in the right style.
- A flipped condenser keeps its arrow direction.
- Column feeds land on the trayed section.

## [0.1.0] - 2026-07-28

First public release.

- Build a flowsheet from units with named nozzles and connect them; pandid
  lays out the equipment and routes the lines.
- Draw PFDs and P&IDs as SVG with no dependencies, or as PDF and PNG with an
  optional extra.
- 139 equipment symbols, instrument balloons, control loops, and line and
  stream numbers.
- Title blocks, zone borders, equipment lists, notes and legends.
- `validate()` reports problems on a sheet.
- Read and write flowsheets as JSON or YAML, and draw or check them with the
  `pandid` command.
- Licensed under the PolyForm Small Business License 1.0.0; the vendored
  symbols are Apache-2.0.

[Unreleased]: https://github.com/Alpha9463/pandid/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Alpha9463/pandid/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/Alpha9463/pandid/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/Alpha9463/pandid/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Alpha9463/pandid/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Alpha9463/pandid/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Alpha9463/pandid/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

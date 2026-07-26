# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

First public release. Nothing has been published to PyPI yet, so every entry
below is part of the initial feature set rather than a change to something users
have. Bug-fix commits from development are folded into the capability they
repaired, since no released version ever carried the defect. The exception is
`### Deprecated`, which records an alias that already exists in the API surface
and is kept working.

### Added

#### Topology model

- `Flowsheet`, the container and single source of truth for connectivity, with
  `add()`, `connect()`, `add_component()` and `add_annotation()`.
- `connect()` validates every connection: outlet → inlet only, both units on the
  same flowsheet, and one stream per port.
- Typed `Unit` classes declaring named ports: `Feed`, `Product`, `Pump`,
  `Compressor`, `Blower`, `Valve`, `Vessel`, `Tank`, `HeatExchanger`, `Heater`,
  `Cooler`, `Reactor`, `Separator`, `Column`, `Mixer`, `Splitter`, `Reducer`,
  `Fitting`, `Ejector`, `Vent`, `Funnel`, `Furnace`, `Turbine`, `Filter`,
  `Dryer` and `Instrument`. Ports are reachable both as `unit.ports[name]` and
  as attributes (`pump.suction`), and a typo raises an error naming the real
  ports.
- Variable-port `Mixer(n_inlets=…)`, `Splitter(n_outlets=…)` and
  `Column(n_feeds=…)` / `Reactor(n_feeds=…)`. A tower fed more than once, as in
  extractive distillation where the solvent enters above the feed tray, spreads
  `feed_1` … `feed_n` down the shell wall between the two duty arrows, so no
  count can reach the reflux and boilup returns opposite. One feed keeps the
  singular `feed` and the nozzle it always had.
- `Column.reflux_in` / `Column.boilup_in` return nozzles and `Reactor.vent`, so
  an overhead or reboiler loop closes on the column instead of being modelled as
  a recycle to some upstream unit.
- `HeatExchanger(variant="kettle").bottoms` is the liquid draw at the weir end
  of a kettle reboiler. A tower's bottoms product physically leaves from there,
  so it no longer has to be taken off a splitter in the sump line, which puts a
  piece of equipment that does not exist on the sheet and in the equipment list.
- `Valve.actuator`, the signal connection on the valve, so a controller output
  terminates on the final control element.
- `Component` registry and a `State` slot on `Port`/`Stream`, reserved for a
  future mass/energy-balance backend. No balance solving is performed.
- `Stream.is_recycle` as a read-only computed property. Recycles are detected
  by the engine's cycle-breaking phase and are never declared by the caller.
  `tear_hint=True` is advisory input to that choice.
- `Flowsheet.to_dict()` for JSON-safe serialization of the topology.
- Automatic stream numbering (`stream_naming_scheme`, default `"S{n}"`) that
  carries one number *through* inline valves, reducers and fittings.
  `unit.significant = True` breaks the number at an important valve. Explicitly
  named streams are left alone. Numbering settles inside `connect()`, so the
  number on the stream you hold is the number that gets drawn. Process streams
  take the low numbers, with energy streams and then unlabelled signal lines
  after them.
- Line numbers. This is the identifier a P&ID actually labels a line with, and
  the one the line list, the stress calculation and the isometric key on. `connect()`
  takes `size`, `service`, `spec` and `insulation`; auto-numbering fills
  `sequence` from `line_number_start` (default `1001`), and
  `line_numbering_scheme` (default `"{size}-{service}-{sequence}-{spec}"`, a
  format string or a callable) spells the site's convention. A line number is
  assigned by the same pass as a stream number, so it carries through in-line
  fittings and breaks where `significant` marks the spec break; an unset
  component drops out with its separator, an explicitly named stream is never
  reformatted, and a stream with no components set is numbered exactly as
  before. The stream table heads each column with the line number.

#### Layout

- Sugiyama-style automatic layout: cycle breaking, layer assignment, crossing
  reduction and coordinate assignment, emitting a resolved `Frame` per unit.
- Straightened process spine. The main flow line is aligned onto one axis, and
  equipment is centre-aligned on a common flow axis.
- Geometry model that separates intent from result: `Pin` (written only by
  `Unit.pin()`) versus `Frame` (written only by the layout engine), so
  `layout()` is idempotent.
- `Unit.pin()` to a grid cell (`col`/`row`) or exact coordinates (`x`/`y`), with
  `orientation` (0/90/180/270 clockwise quarter turns) and `mirrored`
  (`True`/`"x"`, `"y"`, `"xy"`). Pinned and auto-placed units mix freely.
  Repeated calls merge: only the arguments passed are written, so nudging a unit
  with a second `pin(y=…)` keeps the turn and the flip the first one asked for,
  and `orientation=0` / `mirrored=False` are how you put them back.
- Automatic port-face selection: a port its symbol authors on more than one face
  is put on the face the unit at the other end of the stream is actually on,
  scored by the orthogonal run plus the detour a face pointing away would cost.
  A reflux drum under its condenser is fed from the top, and a controller takes
  its output on the side its valve is on, without anyone saying so. It runs as a
  layout phase, once every drawn box is settled and before anything reads a
  face; the choice lands on the resolved `Frame`, so it is a result rather than
  intent and `layout()` stays idempotent. Nozzles fixed by physics have one
  placement and are never considered, and the selector will not land two live
  connections on one point. `Flowsheet(auto_faces=False)`, or the spec's
  top-level `auto_faces` key, turns it off and leaves every port on its symbol's
  own nozzle.
- `Unit.nozzle()` pipes a port from a named face of the unit *as drawn*,
  accepting `top`/`bottom`/`left`/`right` as well as the compass points. It
  overrides the engine's pick, because the engine removes detours but does not
  adjudicate drawing conventions. A port can only take a face its symbol
  authored a coordinate for, so the moved nozzle still lands on drawn ink; a
  nozzle fixed by physics has one placement and raises. The choice is re-checked
  against any later `pin()`, and the resolver raises rather than falling back to
  the home nozzle if a face becomes unreachable.
- Automatic label placement: an equipment tag goes to a face no connected
  nozzle occupies, so a stream no longer runs through its own label. It runs
  after face selection, so the face it dodges is the one the stream really
  leaves from.

#### Routing

- Orthogonal A\* router over a visibility graph, with port anchors projected
  onto unit boundaries and used-edge penalties so runs do not overlap.
- Crossing jump-gaps and separation of co-located parallel runs.
- `Stream.via([...])` to force a stream through explicit orthogonal waypoints.

#### Rendering

- SVG output with no runtime dependencies. `Flowsheet.to_svg()` returns the
  string, `Flowsheet.render(path)` infers the format from the extension, and
  `.pdf`/`.png` go through the optional `cairosvg` backend.
- `Flowsheet.show()` opens the drawing in a browser, and a flowsheet renders
  inline in Jupyter via `_repr_svg_`.
- Canvas fitted to content, with no letterboxing, no clipping and uniform 2 px
  symbol strokes.
- A stream number or line number drawn parallel to the line it names, on a wipe
  so no line strikes through the text. It sits on the line only where the run
  can still show pipe past the wipe at each end, and steps beside the line where
  it cannot, which is the usual answer for a line number a dozen characters
  wide. On a vertical run it is turned to read bottom to top, per the
  aligned-text convention of ISO 129-1 and ASME Y14.5, and wherever it lands it
  slides along its own run until it clears the equipment, tags, balloons and
  other numbers already on the sheet.
- `page_size="A4"`..`"A0"` draws a sheet of exactly that size instead: the border
  and title strip rule to the page edges and the drawing is fitted into what they
  leave, scaled down uniformly if it is too big and never enlarged if it is not.
  A page too small for its own furniture raises rather than clip it. Fixing the
  page also fixes the zone grid, so a note referring to zone D-4 still means D-4
  after the next revision grows the drawing.
- `jump_direction="vertical" | "horizontal"` on `to_svg()` / `render()` selects
  which of two crossing lines gets the semicircle hop.
- 100 registered `(kind, variant)` symbols following ISO 10628-2 / ISA-5.1,
  generated from the draw.io / diagrams.net P&ID stencils (Apache-2.0) by
  `scripts/vendor_symbols.py`. Feed/Product flags, Mixer, Splitter and the
  instrument balloons are hand-drawn originals.
- `Symbol` validates its own declaration, so a third-party symbol gets the same
  protection the invariant suite gives the shipped ones: a placement keyed to a
  face its coordinate does not land on, or restating a port's home face at a
  different point, raises instead of being silently dropped, and
  `Symbol.coincident_ports()` warns about two ports on one coordinate. Only the
  connections named in `Symbol.faceless_ports` may share a placement, since an
  instrument balloon is a circle and a signal may meet it anywhere.
- `variant=` is checked against the registry: a name the kind has no symbol for
  raises `ValueError` naming the nearest match and the whole catalogue, rather
  than drawing that kind's `default` and letting the typo reach the printer.
  `SymbolRegistry.variants(kind)` enumerates them. A kind with no symbols at
  all, such as a `Unit` subclass of your own, still draws a generic box, since
  there is no catalogue to hold its variant against.
- A symbol's own lettering, such as the `M` in a motor operator or the `S` in a
  solenoid, stays upright and readable under every placement transform. Flipping
  a valve to put its operator below the line is a statement about the equipment,
  not about the letter stamped on it.
- `Symbol.port_series` places a family of like ports whose membership the *unit*
  decides rather than the symbol. `Mixer(n_inlets=n)` and `Splitter(n_outlets=n)`
  therefore give every inlet or outlet a nozzle of its own, spread along the flat
  face, for any `n`. Previously the triangles drew exactly two and the rest fell
  back to the centre of the box, landing every extra stream on one point. Two
  ports still sit exactly where they always have, so no existing sheet moves.
- A full-width engineering title strip, drawn whenever the flowsheet carries a
  `TitleBlock`. Both reference PFDs have a title strip and an equipment list, so
  the furniture belongs to the sheet rather than to one drawing type: `border=`
  is the separate choice of whether the zone-ruled ASME-style drawing frame is
  ruled around it, and a border a sheet did not ask for is not drawn.
  `TitleBlock` plus `Revision` rows carry the metadata, with per-row
  `by`/`checked`/`approved` initials.
- `TitleBlock.client` and `.project` rule a row each above the drawing title,
  where ISO 5457 puts the owner of the drawing; a block naming neither is ruled
  no row for them.
- `TitleBlock.scale` fills the scale cell, alongside the drawing number and the
  revision index as ASME Y14.1 has it. Left blank it reports the ratio the
  drawing was actually placed at, which is a real number once `page_size` fixes
  the page, and nothing at all on a sheet sized to fit its drawing, where no
  scale exists to state.
- Title-strip values too long for their cell are trimmed with an ellipsis, so a
  long client or project name cannot run across the rule into its neighbour or
  under the sheet count.
- Sheet furniture docked flush to the frame on a nine-point `align` grid, or
  hand-placed with `position=(x, y)`: `Annotation`, `TableBox`, and the
  `equipment_list()` / `notes()` / `legend()` constructors. Like the title
  strip, a box added to the flowsheet is drawn on the sheet whatever the border.
- An unknown `border=` or `styling=` raises rather than silently drawing the
  plain sheet.
- Optional stream property table (`show_stream_table=True`) with section headers
  injected via `Flowsheet.stream_table_sections`. Property values are supplied
  by the caller as strings; the engine does not compute them.
- Off-page connectors: a `Feed`/`Product` flag's `reference` is drawn as its
  second line. A flag is the only thing with a second line, so `reference=` on
  equipment raises and names the boundary to put it on.

#### Instrumentation (ISA-5.1)

- `Flowsheet.add_instrument(type, number, …)` and the `Instrument` unit, drawing
  the functional letters over a bare loop number the way a real sheet does.
  Balloon variants: `default` (field), `panel`, `aux`, `shared` (DCS square),
  `computer` (hexagon), `logic` (interlock square).
- `Instrument.attach(on=…, at=…, offset=…, angle=…)` anchors a balloon to the
  stream or the equipment it reads, with an impulse line drawn to the tap.
  `angle` is measured from the flow direction at the tap, so a re-route cannot
  spin it, and `offset=0` leaves an in-line primary element sitting on the line.
  Attached balloons take no part in layout ranking.
- Typed signal lines through `connect(kind=…)`: `electric` (dashed),
  `pneumatic` (slash ticks), `data`/`software` and `capillary`, all with no
  arrowheads and no stream numbers. A pneumatic line is drawn *solid* and marked
  with double cross-hatches, so the hatch is the only thing distinguishing it
  from process pipe. Every run long enough to hold a mark gets one, however
  short.
- A balloon's signal connections may be taken on any face, since a circle has no
  natural side.
- The `panel` and `aux` variants draw a location bar across the middle of the
  circle, and the tag clears it: functional letters wholly above, loop number
  wholly below.

#### Validation

- `Flowsheet.validate()` returns `Issue` records, errors first. Errors such as
  overlapping pinned units and negative or non-finite coordinates raise from
  `render()` rather than emit a silently wrong drawing. Warnings such as a route
  crossing a unit body or a grossly indirect route collect on `fs.warnings`.
- `coincident-ports` covers two connected ports on one unit that resolve to the
  same point, so one stream terminates exactly on top of the other. It is an
  error where both are nozzles the symbol places, and a warning where either is
  a port the symbol never anchored and which therefore fell back to the centre
  of the box, which is a gap in the symbol rather than a contradiction on the
  sheet. No shipped symbol has such a gap.

#### Tooling, tests and packaging

- Golden-SVG visual regression suite over a fixed corpus of scenarios
  (`tests/test_golden.py`, fixtures in `tests/golden/`), regenerated with
  `PFD_UPDATE_GOLDEN=1`.
- Symbol-invariant suite over every registered `(kind, variant)`: well-formed
  SVG, ports inside the bounding box, ports on drawn ink, no two ports
  coinciding.
- GitHub Actions CI: `ruff check`, `ruff format --check tests`, `mypy pfd`
  (blocking), and `pytest` on Python 3.10, 3.11, 3.12 and 3.13.
- `pre-commit` configuration mirroring the CI lint gates.
- Nine runnable examples in `examples/`, each usable from the repository root
  or from `examples/` itself, and rendered into `docs/gallery/`.
- Packaged as the **`pandid`** distribution, how "P&ID" is said out loud. The
  import name is `pfd`, since plain `pfd` is taken on PyPI by an unrelated
  project.
- Licensed under the **PolyForm Small Business License 1.0.0**: free for
  individuals, research, teaching, and companies under 100 people and
  1,000,000 USD revenue; a commercial licence is required above either
  threshold. Source-available rather than OSI open source. The vendored draw.io
  symbol geometry remains **Apache-2.0**, as that licence requires. `NOTICE`
  lists exactly which files fall under which, and both texts ship in the
  distribution.
- `pfd/py.typed`, the PEP 561 marker, so an installing project's type checker
  reads the annotations instead of treating the whole package as `Any`.
- `pfd.__version__` is the only place the version is written; the build backend
  reads it from there, so the distribution metadata cannot disagree with it.
- Release workflow (`.github/workflows/release.yml`): pushing a `v*` tag re-runs
  the four gates, checks the tag against `pfd.__version__`, builds the sdist and
  wheel, and uploads to PyPI over Trusted Publishing (OIDC, no API token).

### Deprecated

- `styling="pid"` on `to_svg()` / `render()`. Use `border="zone"`, which names
  what it actually does now that the title strip and the docked boxes follow the
  furniture the flowsheet carries rather than this option. `styling="pid"` still
  means `border="zone"`; asking for both at once, disagreeing, raises.
- `anchor=` on `Annotation`, `TableBox`, `equipment_list()`, `notes()` and
  `legend()`. Use `align=` instead. The alias still works and wins over `align`
  when both are given.
- `Unit.port_face()`. Use `Unit.nozzle()` instead. **This alias is not
  behaviour-preserving on a rotated or mirrored unit**, and the
  `DeprecationWarning` announcing it is invisible by default outside
  `__main__`, so it is called out here rather than left to be discovered.
  `port_face()` read its face in the *symbol's own* frame, with the placement
  transform applied afterwards, while `nozzle()` reads it as the face on the
  finished sheet. On an untransformed unit the two agree. On one pinned
  `mirrored="x"` they are opposites, so `port_face("inlet", "E")` put the nozzle
  on the drawn west (#26). Where the symbol authors no placement on the drawn
  face, the call that used to succeed now raises instead of silently piping from
  the wrong side. Rewrite each call site with the face the reader sees.
- `Symbol.port_alts`. Declare the whole menu, home placement included, in
  `Symbol.port_faces`. `Symbol.free_ports` is now `Symbol.faceless_ports`. Both
  old spellings still register.

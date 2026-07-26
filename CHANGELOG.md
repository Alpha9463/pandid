# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

First public release. Nothing has been published to PyPI yet, so every entry
below is part of the initial feature set rather than a change to something users
have. Bug-fix commits from development are folded into the capability they
repaired, since no released version ever carried the defect; the exception is
`### Deprecated`, which records an alias that already exists in the API surface
and is kept working.

### Added

#### Topology model

- `Flowsheet` — the container and single source of truth for connectivity, with
  `add()`, `connect()`, `add_component()` and `add_annotation()`.
- `connect()` validates every connection: outlet → inlet only, both units on the
  same flowsheet, and one stream per port.
- Typed `Unit` classes declaring named ports: `Feed`, `Product`, `Pump`,
  `Compressor`, `Blower`, `Valve`, `Vessel`, `Tank`, `HeatExchanger`, `Heater`,
  `Cooler`, `Reactor`, `Separator`, `Column`, `Mixer`, `Splitter`, `Reducer`,
  `Fitting`, `Ejector`, `Vent`, `Funnel`, `Furnace`, `Turbine`, `Filter`,
  `Dryer` and `Instrument`. Ports are reachable both as `unit.ports[name]` and
  as attributes (`pump.suction`); a typo raises an error naming the real ports.
- Variable-port `Mixer(n_inlets=…)` and `Splitter(n_outlets=…)`.
- `Column.reflux_in` / `Column.boilup_in` return nozzles and `Reactor.vent`, so
  an overhead or reboiler loop closes on the column instead of being modelled as
  a recycle to some upstream unit.
- `Valve.actuator` — the signal connection on the valve, so a controller output
  terminates on the final control element.
- `Component` registry and a `State` slot on `Port`/`Stream`, reserved for a
  future mass/energy-balance backend. No balance solving is performed.
- `Stream.is_recycle` as a read-only computed property — recycles are detected
  by the engine's cycle-breaking phase and are never declared by the caller.
  `tear_hint=True` is advisory input to that choice.
- `Flowsheet.to_dict()` — JSON-safe serialization of the topology.
- Automatic stream numbering (`stream_naming_scheme`, default `"S{n}"`) that
  carries one number *through* inline valves, reducers and fittings;
  `unit.significant = True` breaks the number at an important valve. Explicitly
  named streams are left alone. Numbering settles inside `connect()`, so the
  number on the stream you hold is the number that gets drawn; process streams
  take the low numbers, with energy streams and then unlabelled signal lines
  after them.

#### Layout

- Sugiyama-style automatic layout: cycle breaking, layer assignment, crossing
  reduction and coordinate assignment, emitting a resolved `Frame` per unit.
- Straightened process spine — the main flow line is aligned onto one axis, and
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
- `Unit.nozzle()` — pipe a port from a named face of the unit *as drawn*,
  accepting `top`/`bottom`/`left`/`right` as well as the compass points. A port
  can only take a face its symbol authored a coordinate for, so the moved nozzle
  still lands on drawn ink; a nozzle fixed by physics has one placement and
  raises. The choice is re-checked against any later `pin()`, and the resolver
  raises rather than falling back to the home nozzle if a face becomes
  unreachable.
- Automatic label placement: an equipment tag goes to a face no connected
  nozzle occupies, so a stream no longer runs through its own label.

#### Routing

- Orthogonal A\* router over a visibility graph, with port anchors projected
  onto unit boundaries and used-edge penalties so runs do not overlap.
- Crossing jump-gaps and separation of co-located parallel runs.
- `Stream.via([...])` to force a stream through explicit orthogonal waypoints.

#### Rendering

- SVG output with no runtime dependencies; `Flowsheet.to_svg()` returns the
  string, `Flowsheet.render(path)` infers the format from the extension, and
  `.pdf`/`.png` go through the optional `cairosvg` backend.
- `Flowsheet.show()` opens the drawing in a browser, and a flowsheet renders
  inline in Jupyter via `_repr_svg_`.
- Canvas fitted to content — no letterboxing, no clipping, uniform 2 px symbol
  strokes, and stream-number labels drawn on a wipe so the line never strikes
  through the text.
- 100 registered `(kind, variant)` symbols following ISO 10628-2 / ISA-5.1,
  generated from the draw.io / diagrams.net P&ID stencils (Apache-2.0) by
  `scripts/vendor_symbols.py`; Feed/Product flags, Mixer, Splitter and the
  instrument balloons are hand-drawn originals.
- `Symbol` validates its own declaration, so a third-party symbol gets the same
  protection the invariant suite gives the shipped ones: a placement keyed to a
  face its coordinate does not land on, or restating a port's home face at a
  different point, raises instead of being silently dropped, and
  `Symbol.coincident_ports()` warns about two ports on one coordinate. Only the
  connections named in `Symbol.faceless_ports` — an instrument balloon is a
  circle, so a signal may meet it anywhere — may share a placement.
- `variant=` is checked against the registry: a name the kind has no symbol for
  raises `ValueError` naming the nearest match and the whole catalogue, rather
  than drawing that kind's `default` and letting the typo reach the printer.
  `SymbolRegistry.variants(kind)` enumerates them. A kind with no symbols at all
  — a `Unit` subclass of your own — still draws a generic box, since there is no
  catalogue to hold its variant against.
- A symbol's own lettering — the `M` in a motor operator, the `S` in a solenoid —
  stays upright and readable under every placement transform. Flipping a valve to
  put its operator below the line is a statement about the equipment, not about
  the letter stamped on it.
- `Symbol.port_series` places a family of like ports whose membership the *unit*
  decides rather than the symbol. `Mixer(n_inlets=n)` and `Splitter(n_outlets=n)`
  therefore give every inlet or outlet a nozzle of its own, spread along the flat
  face, for any `n` — previously the triangles drew exactly two and the rest fell
  back to the centre of the box, landing every extra stream on one point. Two
  ports still sit exactly where they always have, so no existing sheet moves.
- `styling="pid"` — a zone-ruled ASME-style drawing border and a full-width
  engineering title strip. `TitleBlock` plus `Revision` rows carry the metadata,
  with per-row `by`/`checked`/`approved` initials.
- Sheet furniture docked flush to the frame on a nine-point `align` grid, or
  hand-placed with `position=(x, y)`: `Annotation`, `TableBox`, and the
  `equipment_list()` / `notes()` / `legend()` constructors.
- Optional stream property table (`show_stream_table=True`) with section headers
  injected via `Flowsheet.stream_table_sections`. Property values are supplied
  by the caller as strings; the engine does not compute them.
- Off-page connectors: a `Feed`/`Product` flag's `reference` is drawn as its
  second line.

#### Instrumentation (ISA-5.1)

- `Flowsheet.add_instrument(type, number, …)` and the `Instrument` unit, drawing
  the functional letters over a bare loop number the way a real sheet does.
  Balloon variants: `default` (field), `panel`, `aux`, `shared` (DCS square),
  `computer` (hexagon), `logic` (interlock square).
- `Instrument.attach(on=…, at=…, offset=…, angle=…)` anchors a balloon to the
  stream or the equipment it reads, with an impulse line drawn to the tap.
  `angle` is measured from the flow direction at the tap, so a re-route cannot
  spin it; `offset=0` leaves an in-line primary element sitting on the line.
  Attached balloons take no part in layout ranking.
- Typed signal lines through `connect(kind=…)`: `electric` (dashed),
  `pneumatic` (slash ticks), `data`/`software`, `capillary` — no arrowheads and
  no stream numbers. A pneumatic line is drawn *solid* and marked with double
  cross-hatches, so the hatch is the only thing distinguishing it from process
  pipe; every run long enough to hold a mark gets one, however short.
- A balloon's signal connections may be taken on any face, since a circle has no
  natural side.
- The `panel` and `aux` variants draw a location bar across the middle of the
  circle, and the tag clears it: functional letters wholly above, loop number
  wholly below.

#### Validation

- `Flowsheet.validate()` returns `Issue` records, errors first. Errors —
  overlapping pinned units, negative or non-finite coordinates — raise from
  `render()` rather than emit a silently wrong drawing. Warnings — a route
  crossing a unit body, a grossly indirect route — collect on `fs.warnings`.
- `coincident-ports` — two connected ports on one unit that resolve to the same
  point, so one stream terminates exactly on top of the other. An error where
  both are nozzles the symbol places; a warning where either is a port the
  symbol never anchored and which therefore fell back to the centre of the box,
  which is a gap in the symbol rather than a contradiction on the sheet. No
  shipped symbol has such a gap.

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
- Eight runnable examples in `examples/`, each usable from the repository root
  or from `examples/` itself, and rendered into `docs/gallery/`.
- Packaged as the **`pandid`** distribution — how "P&ID" is said out loud. The
  import name is `pfd`; plain `pfd` is taken on PyPI by an unrelated project.

### Deprecated

- `anchor=` on `Annotation`, `TableBox`, `equipment_list()`, `notes()` and
  `legend()` — use `align=`. The alias still works and wins over `align` when
  both are given.
- `Unit.port_face()` — use `Unit.nozzle()`. **This alias is not
  behaviour-preserving on a rotated or mirrored unit**, and the
  `DeprecationWarning` announcing it is invisible by default outside
  `__main__`, so it is called out here rather than left to be discovered.
  `port_face()` read its face in the *symbol's own* frame, with the placement
  transform applied afterwards; `nozzle()` reads it as the face on the finished
  sheet. On an untransformed unit the two agree. On one pinned `mirrored="x"`
  they are opposites — `port_face("inlet", "E")` put the nozzle on the drawn
  west (#26) — and where the symbol authors no placement on the drawn face, the
  call that used to succeed now raises instead of silently piping from the
  wrong side. Rewrite each call site with the face the reader sees.
- `Symbol.port_alts` — declare the whole menu, home placement included, in
  `Symbol.port_faces`. `Symbol.free_ports` is now `Symbol.faceless_ports`. Both
  old spellings still register.

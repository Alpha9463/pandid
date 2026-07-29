# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `Separator(variant="default")` is drawn as the plain dished-head vertical
  cylinder, the same draw.io stencil `Vessel` and `Column` already share, and is
  reproportioned to the 62 x 100 box `Vessel` comes out at rather than the
  column's 100 x 200. It was the "Knock-out Drum", which draws a level gauge and
  a demister pad into the equipment artwork: the gauge is drawn a second time as
  soon as a real level instrument is added, and `Separator` is the generic flash
  drum, which does not necessarily have a mesh pad. `vessel`/`horizontal` and
  `separator`/`horizontal` were already one stencil under two sets of nozzle
  names, so this makes the upright pair consistent with the lying one. Its
  nozzles are unchanged in name and role: `feed` on the west shell wall at
  mid-height, `vapor` and `liquid` on the two head crowns. Examples 01 and 05
  move, and so do the goldens for them.

### Added

- Five `Filter` variants, naming the medium the casing is drawn around:
  `fixed_bed` and `gas_fixed_bed` (a granular bed between two retention
  screens), `belt` and `gas_belt` (a cloth running between two rollers), and
  `rotary_scraper` (the rotary drum of `rotary` with the knife that lifts the
  cake off it). Each is piped `inlet` west and `outlet` east at mid-height, as
  the rest of the family is, so swapping one filter for another is a change of
  artwork and not of piping. `Filter`'s ports are unchanged.
- `gas_fixed_bed` and `gas_belt` join `filter/gas` among the symbols
  ISO 15519-1 §11.4.2 forbids turning. Each draws a dust hopper under its
  medium, which is where what the medium sheds is collected; `fixed_bed` and
  `belt` draw the same medium with no hopper, are driven by pressure drop
  across it, and stay turnable.
- `validate()` reports `run-off-elevation`: two connected nozzles on one
  horizontal run that are *almost* level, missing by less than the shorter of
  the two symbols is tall. A unit is pinned by its top-left corner and each
  symbol carries its nozzles where its artwork puts them, so pinning a row to
  convenient corner-`y` values silently puts the nozzles on different
  elevations and the router draws a step into each device and back out. Nothing
  errored and no nozzle left its ink, which is what made it worth a finding.
  The message names the cure, `pin(port=…, y=…)`. A large deliberate step, a
  vertical run, a signal line, a sheet with no pinned elevation, and the
  eccentric reducer (whose two ends sit on different centrelines on purpose)
  are all silent. Rendering is unchanged and no golden moves.
- `Separator(variant="knockout")` draws the knock-out drum the default used to,
  demister pad and level gauge and all, at the size and with the nozzles it had.

### Fixed

- Examples 03, 04, 07 and 09 no longer dogleg into their in-line devices. Each
  pinned its valves, orifice plate, strainer and sight glass by the **corner**
  while the equipment around them put its nozzles on a different elevation, so
  the router had to step into every device and back out of it: 18 short jogs
  across the four sheets, most of them exactly half a valve height. They are now
  placed with `pin(port=..., y=run_y)`, which asks the symbol where its own
  nozzle sits, so no half-height is written down and no rescaling of the artwork
  can leave a device off its run. No symbol moved; this is placement only. In 03
  the feed row also sat 25 above `T-100`'s feed nozzle, because the offset it was
  aligned to had gone stale, and the whole run now lands on the nozzle itself.
  The goldens and the gallery images for those four move with them.

## [0.1.0] - 2026-07-28

First public release. Nothing was published before it, so everything below is the
initial feature set rather than a change to something users have, and the entries
are headlines rather than a description of the library. `README.md` is the tour,
[`docs/api.md`](docs/api.md) is the reference, and
[`docs/gallery/README.md`](docs/gallery/README.md) walks the eleven examples.
Later releases will list changes rather than capabilities.

### Added

- **Topology.** `Flowsheet` is the container and the single source of truth for
  connectivity, with `add()`, `connect()`, `add_component()` and
  `add_annotation()`. 28 typed `Unit` classes declare named ports reachable as
  `unit.ports[name]` or as attributes (`pump.suction`), and a typo raises an
  error naming the real ports. `connect()` validates every connection: outlet to
  inlet only, both units on the same flowsheet, one stream per port, and signal
  against process. A `Unit` subclass of your own declaring its `kind` and
  `PORTS` is laid out, routed and drawn like a shipped class.
- **Assemblies and branching.** `Tee` is the pipe tee, drawn as bare pipe and
  scheduled nowhere, so a bypass, a drain, a vent or a PSV takeoff no longer puts
  equipment on the sheet that the plant does not contain.
  `Flowsheet.add_valve_station()` builds the eight devices and four tees a
  control valve is installed in, in one call.
- **Numbering.** Automatic stream numbers carry one number *through* inline
  valves, reducers and fittings. Line numbers (`size`, `schedule`, `service`,
  `spec`, `insulation`, plus an auto-filled `sequence`) are assembled by
  `line_numbering_scheme` and assigned by the same pass, so a line number
  survives an in-line fitting and breaks where the spec break is marked.
- **Layout.** Sugiyama-style automatic layout: cycle breaking, layer assignment,
  crossing reduction and coordinate assignment, with the main flow line
  straightened onto one axis. The geometry model separates intent (`Pin`, written
  only by `Unit.pin()`) from result (`Frame`, written only by the engine), which
  is what makes `layout()` idempotent. `pin()` takes a grid cell or exact
  coordinates, a quarter turn, a mirror, and `port=` to place a **nozzle** rather
  than a corner. Port faces and equipment tags are then chosen automatically from
  where each peer actually landed, and `nozzle()` overrides that pick where a
  drawing convention has to be stated.
- **Routing.** Orthogonal A\* over a visibility graph, with port anchors projected
  onto unit boundaries, used-edge penalties so runs do not overlap, crossing
  jump-gaps, and separation of co-located parallel runs. `Stream.via([...])`
  forces explicit waypoints. `route()` places attached instruments and re-routes
  until the two agree rather than trading a fixed number of passes.
- **Rendering.** SVG with **no runtime dependencies**; `.pdf` and `.png` go
  through the optional `cairosvg` backend. `page_size="A4"`..`"A0"` draws a sheet
  of exactly that ISO 216 size, `border="zone"` rules the ASME-style zone frame,
  and `diagram="p&id"` draws process lines without arrowheads. Signal lines are
  drawn at half the weight of process pipe, the 2:1 ratio ISO 15519-1 §6.2
  requires. A `TitleBlock`, `Revision` rows, and docked `Annotation` / `TableBox`
  furniture (`equipment_list()`, `notes()`, `legend()`) are sheet furniture drawn
  whatever the border, and every cell is measured before it is written into, so
  text that cannot fit is reported on `fs.warnings` rather than drawn across a
  rule.
- **Symbols.** 139 registered `(kind, variant)` pairs across 28 kinds, generated
  from the draw.io / diagrams.net P&ID stencils by `scripts/vendor_symbols.py`
  and matched to ISO 10628-2 where a symbol exists. Feed/Product flags, the
  variable-port Mixer and Splitter, the pipe tee and the ANSI/ISA-5.1 balloons are
  hand-drawn originals. Every port is checked to land on drawn ink, at every box
  shape a unit can be given. `variant=` is checked against the registry, so a
  typo raises naming the nearest match rather than reaching the printer.
- **Instrumentation (ISA-5.1).** `add_instrument()` and the `Instrument` unit
  draw the functional letters over a loop number, in six balloon variants plus
  the two trip squares ANSI/ISA-5.1-2009 distinguishes. `Instrument.attach()`
  anchors a balloon to the stream or equipment it reads, with an impulse line to
  the tap. Typed signal lines (`electric`, `pneumatic`, `data`, `software`,
  `capillary`) are legal only between two signal connections.
  `Flowsheet.add_loop()` declares a control loop, so the loop number is typed
  once and each balloon's own letters are checked against it.
- **Valve marking.** `Valve(normal_position="closed")` darkens the body
  (PIP PIC001 4.2.2.7) or writes `NC` beside it where a filled body would hide
  the device (ISO 15519-1 §11.4.5), and refuses on a control or relief valve
  (clause 4.2.2.10). `Valve(fail=...)` writes the six ANSI/ISA-5.1-2009 Table
  5.4.4 codes beside an actuated valve. `Fitting(variant="blind")` takes the same
  `normal_position` and changes shape rather than fill.
- **Validation.** `Flowsheet.validate()` returns `Issue` records, errors first.
  Errors such as overlapping pinned units raise from `render()` rather than emit
  a silently wrong drawing; warnings such as a route crossing a unit body, a tag
  whose letters are out of ISO 15519-2 §5.2.4 order, or a gravity-dependent
  symbol given a quarter turn collect on `fs.warnings`.
- **Spec format.** `Flowsheet.to_dict()` / `from_dict()` round-trip the whole
  topology as JSON-safe data, and `pandid.spec` reads the same shape from YAML or
  JSON. An unknown key is rejected rather than ignored, and the message names the
  key it was probably meant to be.
- **Command line.** A `pandid` command, installed with the distribution:
  `pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone`,
  `pandid validate plant.yaml`, and `pandid symbols --kind valve`. Exit codes a
  build script can gate on, and every user-provokable failure is one line on
  stderr rather than a traceback. Built on `argparse`, so the package still has
  no runtime dependencies.
- **Packaging and tooling.** `pandid/py.typed` (PEP 561), a golden-SVG regression
  suite, symbol- and route-invariant suites, CI on Python 3.10 to 3.13, and a
  release workflow that checks the tag against `pandid.__version__` and publishes
  over PyPI Trusted Publishing. `pandid.__version__` is the only place the version
  is written; the build backend reads it from there.

### Changed

Two attributes were renamed on the way to this release. Nothing was published, so
there is no alias and the old spellings simply do not exist. **Both are also spec
keys**, so a YAML or JSON file written against a pre-release checkout has to be
edited: the reader rejects an unknown key rather than ignoring it, and names the
new one.

- `Unit.significant` is now **`Unit.new_line_number`**, and the unit spec key
  `significant:` is now `new_line_number:`. It marks the inline item at which a
  line number breaks and a new one starts, which is what the new name says and
  the old one did not.
- `connect(tear_hint=...)` and `Stream.tear_hint` are now
  **`draw_as_recycle`**, and the stream spec key `tear_hint:` is now
  `draw_as_recycle:`. It marks a stream to be drawn as a recycle loop.

Neither rename changes a drawn sheet: every golden fixture and all eleven example
SVGs are byte-identical across it.

### Removed

The deprecated aliases, on the same reasoning: nothing has been published, so
keeping them preserves compatibility with code that cannot exist. This follows the
clean breaks already made for `hot_*` to `shell_*` on heat-exchanger nozzles.

- `styling=` on `to_svg()` / `render()`. Use `border="zone"` and
  `diagram="p&id"`, which are independent and name the two things it bundled.
- `anchor=` on `Annotation`, `TableBox`, `equipment_list()`, `notes()` and
  `legend()`. Use `align=`.
- `Unit.port_face()`. Use `Unit.nozzle()`, whose `face` is the compass point on
  the finished sheet. The two disagreed on a rotated or mirrored unit, since
  `port_face()` read its face in the symbol's own frame, so **rewrite each call
  site with the face the reader sees** rather than substituting the name (#26).
- `Symbol.port_alts` and `Symbol.free_ports`. Declare the whole menu, home
  placement included, in `Symbol.port_faces`; the faceless set is
  `Symbol.faceless_ports`.
- `Unit._PORTS`. Use `Unit.PORTS`, the same list of `(name, direction, role)`
  tuples under a name that does not tell the one attribute a subclass must set
  that it is private.

### Licence

Licensed under the **PolyForm Small Business License 1.0.0**: free for
individuals, research, teaching, and companies under 100 people and 1,000,000 USD
revenue; a commercial licence is required above either threshold. Source-available
rather than OSI open source.

The vendored draw.io symbol geometry remains **Apache-2.0**, as that licence
requires. The stencil artwork carries one additional field-of-use restriction on
top of that grant, naming Atlassian products and marketplace distribution and
excluding diagram output; `NOTICE` reproduces it in full, lists exactly which
files fall under which licence, and both texts ship in the distribution.

[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

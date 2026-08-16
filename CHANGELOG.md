# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A reactor, a column, a vessel and a separator now say what is *inside*
  them.** Four keywords, one per ISO 10628-2 part group, each naming a
  supplementary symbol the standard tabulates:

  ```python
  Reactor("R-101", agitator="turbine")                    # ten group-28 stirrers
  Reactor("R-201", internals="packing", agitator=None)    # a packed bed
  Column("T-101", internals="valve_tray", trays=30)       # eight group-27 internals
  Vessel("D-301", supports="skirt")                       # four group-26 supports
  Separator("V-201", characteristic="gravity")            # three group-29 marks
  ```

  `variant=` goes on choosing the **body**; these choose what is drawn in it,
  and the two were previously the same word. That is why a `Reactor` could not
  be jacketed *and* packed, and why a jacketed `Vessel` could not stand on
  legs: `variant=` had already been spent. It is also what ISO does — its
  group 2 is not a vocabulary of towers, it is one shell drawn eight times with
  a different group-27 internal in it, so an absorber, a stripper, an adsorber
  and a molecular sieve are one drawing told apart by its tag.

  An agitator brings a `drive` nozzle, at the top of the shaft where ISO item
  1.27 X8006 draws the motor; a reactor without one has no `drive`. Trays,
  supports and characteristics are marks no line reaches and bring nothing.

- **`Reactor(variant="tubular")`, a plug-flow reactor**, and
  `Reactor(variant="jacketed")`, the stirred tank inside a heating jacket that
  is ISO item 1.27 X8006 itself. The tubular shell is original artwork — ISO
  has no tubular-reactor symbol and neither has draw.io's P&ID set, so it is
  built to item 3.7 reg 2514's construction, a shell with a serpentine tube in
  it. **It has no `vent`**: a pipe with a bed in it has no vapour space, and a
  nozzle nothing is ever routed to is a nozzle an author has to be told to
  ignore.

- **Three symbols that carry an ISO registration number.** Items 8.3 X8031,
  8.6 X8125 and 8.8 X8126 are now built by composition rather than vendored —
  one separating vessel carrying one group-29 characteristic each, which is
  what the standard draws — and each records the number of the row it
  reproduces in `Symbol.iso_reg`. They are the first three of the library's
  160 drawings to claim one; the rest is a backfill of its own.

- **draw.io exports a composition as a group of cells.** A composed symbol
  names no stencil — a `shape=` names *one* drawing, so a stirred tank exported
  under the vessel's own reference would come out a bare vessel with the thing
  that made it a reactor silently gone. It is drawn as the body's cell with one
  child cell per part, each at the same fraction of the body's box the sheet
  uses, and the ten agitators name draw.io's own `mxgraph.pid.agitators`
  shapes. `tests/test_drawio.py` holds both backends to drawing the same parts
  in the same places.

- **The ISO 10628-2 groups 26–29 artwork.** Twenty-five supplementary symbols,
  in `pandid/render/iso_parts.py`: four supports (leg, bracket, skirt, ring),
  all eight internals (tray, tray with baffle, bubble-cap, valve, sieve, filter
  insert, fluidised bed, packing), all ten agitators, and the three
  characteristics — gravity, electrostatic, electromagnetic — the standard is
  shown composing onto a separating vessel. Until now the package had no
  agitator at all, which is why it could not draw a stirred tank, and no tray,
  which is why it could not draw a distillation column.

  Original drawings, built to the construction ISO states rather than traced
  from its figures: measured off Table 2 in grid modules and re-drawn on
  `iso_parts.M`, the same 2,5 mm module ISO 14617-1 §4.3 lays its own artwork
  out on. Each part names the Table 2 row it claims to be, so the claim is
  checkable; `tests/test_iso_parts.py` holds all twenty-five to it.

  They are drawn at half the weight of an equipment outline, which is ISO
  10628-1 §5.3.1's split between b) equipment symbols and c) the in-line detail
  band, and is what makes a tray read as detail inside a shell rather than as a
  second shell.

  One correction to note. The agitator shafts are **solid**. Table 2 draws a
  short thin stroke one module above each agitator, which reads as the top of a
  dashed shaft; clause 5 says it marks a preferred connection and "is not a
  part of the graphical symbol", and every shaft under it is a single stroke.

  `python scripts/symbol_sheet.py --parts out.svg` draws the set on its grid
  for review, with every composition the library ships under it.

- **A symbol can be composed from a body and ISO 10628-2's supplementary
  parts.** Groups 1–25 of that standard's Table 1 name whole apparatus; groups
  26–29 name the parts you overlay onto one — supports and manholes, trays and
  packing, the ten agitators, and the characteristic that says what settles or
  precipitates inside a body. Clause 5 makes composing from them a `shall` for
  any symbol the standard does not tabulate, and every pandid symbol was an
  atomic SVG string with no way to. `Symbol` now carries `overlays`, a part
  registry sits beside the symbol registry, and `compose()` resolves the two
  into one cached `Symbol` the renderer places exactly as it places any other.
  A part is placed in *fractions* of the body's box, so it survives the body
  being resized; a part whose shape carries meaning keeps its aspect and holds
  the whole composition to its own; and a part drawn outside the body — ISO
  item 1.27 hangs a drive motor above the top head — grows the box and moves
  the body into it.

  The artwork is the entry above and the keywords that ask for it are the
  entry above that; between them they are what makes a reactor a stirred tank
  and a column a tray column.

  Two things go with it. A part must name the Table 2 row it claims to be —
  subject group, item number and registration number — because composing is
  only ever justified by the standard composing at that point, and a mark with
  no registered number is not a supplementary symbol. `Symbol` gains an
  optional `iso_reg` for the same traceability, left empty everywhere until
  each drawing has been checked against the standard one at a time.

### Changed

- **`reactor/default` is a stirred tank drawn as a stirred tank.** It was
  draw.io's "Mixing Reactor": a rectangle with a V bottom and the stirrer's
  motor perched in a box outside the shell. It is now the same dished-end
  cylinder the vessel, the flash drum and the column are cut from, with the
  agitator on a shaft through the top head — ISO item 1.27 X8006's
  construction, measured off Table 2. The old drawing is kept, under
  `Reactor(variant="mixing")`, because it is still what some plants draw.

- **`column/default` is drawn with trays.** The package held a hand-drawn tray
  column that `_vendored_symbols.py` silently registered over with a plain
  "Pressurized Vessel" capsule, so every distillation column pandid has ever
  drawn came out as a bare drum with no internals at all — the dead code was
  the more conformant of the two. A `Column` now composes eight ISO item 27.1
  trays onto the shell, which is the count and the pitch ISO item 2.6 X8011
  draws, at half the shell's line weight. `Column(internals=None)` is the bare
  shell for anyone who wants it, and `column/packed` is unchanged: it draws its
  beds in its own artwork.

- **Seven golden sheets move**, and only where one of the above is on them:
  `01_ammonia_loop` and `05_reactor_recycle` (a reactor), `03_distillation_train`,
  `06_column_reflux` and `11_ethanol_pid` (a column), `10_ethanol_pfd` (both) and
  `13_mineral_dewatering` (a gravity separator). Nothing else on any of them
  changes.

- **The example columns are the towers they are tagged as.** Six `Column()`
  calls across five examples all drew the same generic deck, which is what a
  reader copying one would carry into their own sheet. Each now names the
  internal its service really has, with a line beside it saying why: `T-100`
  "Light Ends Column" is `valve_tray` (clean, but it swings with the upstream
  rate and a valve holds efficiency where a sieve deck weeps), `T-200` "Product
  Column" is `sieve_tray` (base-loaded on a clean feed, so the turndown a valve
  buys is never used), `T-701` "Main Fractionator" is `baffle_tray` (a shed
  deck has no perforation to plug in a coking service), and the ethanol `T-301`
  "Beer Column" is `sieve_tray` on both the PFD and the P&ID (yeast and grain
  solids, so nothing that can settle or seize). `D-801` "Degasser Tower" stays
  `variant="packed"`: a CO2 stripper wants area and pressure drop rather than a
  deck, and that body draws its own beds.

  The drawn counts are 10 to 18 rather than the real tray count of any of them,
  for the reason `DEFAULT_TRAYS` gives: a forty-tray column is not drawn with
  forty lines on any sheet, and past about twenty a deck stops reading as a
  deck. Four golden sheets and four gallery sheets move, along with the two
  `.drawio` samples that carry one of these columns.

- **A supplementary part stretches with the body it is drawn in**, where the
  agitators and the characteristics had been declared unstretchable. That flag
  does not mean "draw this part carefully": it letterboxes the part on its
  rectangle *and* makes the whole composed symbol unstretchable. The first
  lifted a stirred tank's `drive` eight units clear of the head it comes
  through; the second would have centred a reactor in the box its author asked
  for while every stencilled neighbour beside it filled one. draw.io's own ten
  agitator stencils — the same ten ISO items — are every one of them
  `aspect="variable"`.

  For the same reason no part declares `directional`. That flag holds the
  artwork still under a flip and moves only the nozzles, which is sound only
  where the artwork under the moved nozzle is the artwork that was under the
  original: a settling arrow's body is a hopper, and held still under a
  vertical flip its feed nozzle lands twenty units below the cone. What says a
  settling chamber may not be turned is `gravity_fixed`, which is ISO 14617-1
  §4.5's own word for it, and it is unchanged.

- **`Overlay` can mirror a part.** Table 2 draws item 26.2's support bracket
  and item 26.4's support ring against a wall on one side, and a vessel
  standing on either wants a pair. A second registered part would have been a
  second registration number for a symbol ISO numbers once.

- **Routing a dense sheet is an order of magnitude faster.** The visibility
  graph scanned every obstacle for every grid point and every candidate edge.
  `examples/11_ethanol_pid.py` lays a 394x283 lane grid over 146 obstacles, so
  that is 16 million rectangle tests before the search has started, and under a
  profiler 99% of `route()` was spent building the graph rather than searching
  it. The obstacles are now indexed against the lanes once — an interval per
  row and per column — and every test is asked of only the few that can reach
  the point or the segment in hand. `route()` on that sheet falls from 2.4s to
  0.2s, and across all sixteen examples from 3.4s to 0.3s. It is the same graph
  and the same search: every golden fixture and every gallery sheet is byte for
  byte what it was. `scripts/route_bench.py` prints the numbers.

- **Building a large sheet is no longer quadratic in its own size.** Stream
  numbering runs on every `connect()`, because the name on the stream you are
  handed back has to be the name that gets drawn — but it re-derived every name
  on the sheet to do it, walking every unit to find the inline runs and every
  stream to name them. That is linear work per connection and quadratic over a
  build: 200 streams cost 0.02s of it and 1600 cost 1.17s, with 4.6s of a 4.7s
  build inside numbering. `connect()` now names the line it just added.
  Appending one leaves almost every name alone, and there are only three shapes
  it can take: a run of its own, which becomes the last group; the next segment
  of a run already drawn, which renames at most that run; or a join between two
  runs, which really does renumber the sheet and says so. Every name still
  comes out of the same call the full pass makes, so the two cannot drift, and
  `renumber_streams()` re-derives everything as before. The connect loop over
  1600 streams falls from 1.17s to 0.005s, and the cost of adding one line is
  flat from 200 streams to 3200 instead of growing with the sheet. Byte for
  byte the same drawing: every golden fixture and every gallery sheet is
  unmoved. `scripts/renumber_bench.py` prints the numbers.

- **Three comments in the routing and geometry layers describe the code under
  them.** `find_path`'s docstring said a path "must arrive heading the
  opposite direction" at the goal port, while the loop bans only arriving from
  *behind* and the comment beside it sets out why entering from the side is
  allowed: 53 of the 232 arrivals across the examples are the case the
  docstring called impossible. `portgeom`'s module docstring claimed that every
  function there takes a resolved box rather than reading `unit.frame` —
  `port_faces`, `resolve_size` and `port_offset` all fall back to it — and that
  everything there wraps `resolve_port`, where three do and the rest are its
  peers. And `ink_box` returned early on a non-positive symbol box, a guard
  that prevented nothing: its only caller divides by those two values the
  moment it has the answer, so a zero raised `ZeroDivisionError` either way.

### Deprecated

Six `variant=` spellings that named a **part** rather than a body, each moved
to the keyword that names the part. All work throughout 0.1.3 and are removed
in 0.2.0; each draws what it always drew, so no sheet moves until it is
deleted.

- **`Vessel(variant="legs")` → `Vessel(supports="leg")`** and
  **`Vessel(variant="skirted")` → `Vessel(supports="skirt")`.** ISO group 1
  items 1.16–1.19 are a vessel outline plus a group-26 element, composed;
  pandid vendored whichever two of the four the stencil set happened to ship,
  which is why a bracket and a ring were unreachable. As a keyword it works on
  every vessel variant, so a jacketed vessel can now stand on legs.

- **`Reactor(variant="plain")` → `Reactor(internals="packing")`.** The stencil
  draws a charge vessel with a packed bed hatched into it, which is that
  composition drawn whole.

- **`Separator(variant="gravity")`, `"electrostatic"` and `"electromagnetic"` →
  `Separator(characteristic=…)`.** The three group-8 rows whose every mark is a
  numbered group-29 part.

**`Separator(variant="cyclone")` is not deprecated and is not going.** ISO
14617-1 §4.5 names X2618 by registration number as a symbol in its own right,
and group 29 has no vortex to compose one from, so a hydrocyclone is a distinct
drawing and `variant=` is the right way to ask for it. The same holds for the
sifter, the impact separator, the permanent magnet and the wet scrubber.

### Removed

**Breaking.** The six spellings 0.1.2 deprecated are gone in 0.1.3, which is
the release each of their warnings named. Every replacement draws what the old
spelling drew, so no sheet moves; what changes is that the old spelling now
raises where it used to warn.

- **`add_instrument(on=…)`, and `on:` in a spec (#137).** Use `sensing=`,
  `acting_on=` or `near=`; `on=` meant `sensing=`. The call raises
  `TypeError`, and `on:` in a spec is an unknown key.

- **`Instrument(variant="panel")` and `Instrument(variant="aux")` (#181).**
  Use `display="central"` and `display="subsidiary"`. Both raise `ValueError`
  naming the `display=` to write. Refused by name rather than left to the
  registry, which still draws those two symbols under those two names.

- **`Valve(variant="pneumatic")` (#136).** Use `Valve(variant="control")`, or
  spell the pairing out as `Valve(variant="gate", actuator="diaphragm")`. No
  `pneumatic` artwork is registered, so it is refused at render like any other
  variant the registry has not got. `butterfly_pneumatic` is kept.

- **`vapor` and `liquid` on a dust-collecting separator.** On
  `Separator(variant="cyclone")`, `("gravity")` and `("electrostatic")`, use
  `overflow` and `underflow`. Attribute access raises `AttributeError`;
  `port()`, `nozzle()` and `pin(port=…)` raise `KeyError`; a spec file's
  endpoint raises `SpecError`. Each names the nozzles the unit has. Nothing
  changes for a drum or a scrubber, which keep `vapor` and `liquid`.

`pandid.deprecation` and the `deprecated` finding stay: they are what the next
retirement is declared with. Nothing is deprecated in this release.

Two branches inside the router that could not change a drawing are gone as
well. Neither is API and no sheet moves; both are recorded because the next
reader would otherwise take them for working code.

- **The A\* boundary penalty.** It charged 2000 for an edge running along an
  obstacle's edge, and no such edge ever reached it: `Rect.intersects_segment`
  bounds an obstacle inclusively, so a run exactly on `x_min` or `y_max`
  counts as intersecting it and the visibility graph never builds the edge.
  Counted over the whole corpus it fired 0 times in 815,416 axis-aligned
  edges. Preferring a lane off the boundary means letting those edges exist
  first, which is a change to `visibility.py`.

- **The halved heuristic on recycle streams.** `h = h / 2.0` was there to
  "explore the longer recycle lanes", but scaling an admissible heuristic
  cannot change which path A\* returns — only how greedily it looks for it.
  The recycle paths across the sixteen examples are identical without it, and
  the search does 42% less work getting them (16,312 pushes against 23,137).
  A real preference for the recycle lanes has to be a change to `cost`, as the
  off-lane charge beside it is.

### Fixed

- **The spec format could not express a composed unit, and quietly downgraded
  one.** The keywords above landed on four equipment classes without
  `pandid/spec.py` learning them, so `to_dict()` wrote a skirted vessel as
  `{kind, name}` and `from_dict()` read it back as a vessel standing on
  nothing. Every one of them was lost: `Reactor(agitator="anchor")` came back
  stirred by the general item 28.1, `Column(internals="sieve_tray", trays=18)`
  came back as the eight generic decks a column draws when nobody says
  otherwise, and `Column(internals=None)` — a bare shell asked for on purpose —
  came back with those same eight in it.

  The state was dropped on the way **out**, which is why nothing caught it: the
  file and the flowsheet read back from it agreed exactly, and only the drawing
  had changed. It is the failure the balloon round trip had, so it is closed the
  same way — the keywords are now declared once, on the class that takes them,
  as `Unit.COMPOSITION`, and both directions of the spec read that declaration
  rather than a list of their own. `Unit.composition_defaults()` says what each
  keyword means on a given body, and the constructors ask it too, so "a reactor
  is a stirred tank unless it says otherwise" is one sentence rather than one in
  the constructor and another in the serializer.

  A stated `null` now survives as a statement: a body told `internals: null` is
  drawn bare, where one that says nothing keeps the part its class draws. Only
  what differs from that default is written, as everywhere else in the format,
  so an ordinary reactor's entry is the entry it always was.

  `Separator(characteristic=)` is written as itself and no longer as the
  `variant=` it folds into. The fold is how the drawing is found, but the
  variant spelling of it is deprecated and goes at 0.2.0 — so a sheet written
  out and read back warned today and would have been refused then, without
  anybody having edited it.

  No golden fixture or gallery sheet moves: this is what a flowsheet is written
  down as, and nothing about how one is drawn.

- **A render validated the sheet after building it, so a sheet the validator
  would refuse reached the engine anyway.** `to_svg()`, `to_drawio()` and
  `render()` all documented validation as running first and all ran
  `layout()`, then `route()`, then `validate()`. `pin(x=float("nan"))` is the
  case that shows what that cost: `pin-not-finite` names the contradiction
  exactly, and the same coordinate is one the router starts from and does not
  come back from — so on the default `check=True` the render never returned
  and the finding was made about a drawing nobody could obtain.

  The checks now run in two halves. `validate.model_issues()` reads what the
  author wrote down — `pin-not-finite`, `pin-out-of-bounds`, `gravity-turned`,
  `letter-sequence`, `nozzle-unconnected`, `stream-name-reused`, `deprecated`
  — and runs *before* any geometry; `validate.geometry_issues()` reads the
  frames and routes and runs once they exist. An error from either half
  raises, so a model error raises before a coordinate has been resolved.
  Warnings from both land on `fs.warnings` together.

  The split is an order and not a subset: `fs.validate()` still answers with
  every finding, errors first, and `check=False` still skips all of them. Most
  rules are geometric and could not move — an overlap needs two boxes — so
  each was classified rather than the call relocated wholesale. `gravity-turned`
  went with the model half because a quarter turn is intent: `Pin` is the only
  thing that sets one and layout copies it onto the `Frame` unchanged. No
  golden fixture or gallery sheet moves; this reorders checks and draws nothing
  differently.

- **Auto-numbering walked over the stream names an author had already
  used.** A group named by hand consumed nothing from the number series, so on
  a `stream_number_start=100` sheet `connect(..., name="S100")` followed by a
  plain `connect()` numbered the second stream `S100` as well. The stream table
  is one column per distinct name, so the two runs shared a column and one of
  them was not tabulated at all, while both drew the same label — and nothing
  said so. A named group now takes a place in the sequence rather than skipping
  one, which also lines the series up with the sheet: the fourth run drawn is
  the fourth number whether or not the three before it were named by hand. No
  golden fixture or gallery sheet moves, none of the sixteen examples mixing
  the two ways of naming.

  Counting cannot close it completely, because a name is free text and
  `name="S102"` on that same sheet still meets the third number the counter
  reaches. `validate()` reports what is left as `stream-name-reused`, naming
  the run that took the counted name and what to do about it. Only a name
  *auto-numbering* chose is reported: a run drawn in several `connect()` calls
  is one stream and is meant to carry one label — `examples/10_ethanol_pfd.py`
  draws `S-305` over five of them and `examples/11_ethanol_pid.py` gives four
  pairs of segments one line number each — and a duplicate an author typed
  cannot be told from one they meant. A counted name can: nobody chose it, and
  the counter's one promise is that it is free.

- **A balloon nothing could place made `validate()` silent about the whole
  sheet.** Instrument placement gives up when a pass places nothing — two
  balloons attached to each other have a host chain with no end — and it gave
  up without a word, leaving the balloons frameless. Geometric checks were
  gated on *every* unit having a frame, so one such balloon skipped
  unit-overlap, coincident-ports and nozzles-crowded for every other unit on
  the sheet, and a drawing with overlapping equipment on it came back clean.
  Placement now records what it could not place, `validate()` reports each as
  an `instrument-unplaced` error naming the host it waits on, and the
  geometric checks are made over the units that have a frame rather than all
  or none.

- **A primary element's balloon round-trips through a spec.** `to_dict()` wrote
  a balloon's description, size, label position and quadrant lettering, and
  `from_dict()` then refused every one of them as an unknown key: a sheet built
  with `fs.add_balloon(fe, description="Venturi meter")` could be written to a
  file that would not load. The reader now takes the same fields for a balloon
  as it does for any other instrument, less the tag and the anchor, which
  `balloon_of` already names.

- **A balloon that was pinned stays where it was put.** The writer left the
  balloon out of the pass that records placement, so `pin()` and `nozzle()` on
  a balloon never reached the file. Because neither direction carried them, a
  sheet read back from its own spec compared *equal* to it while the drawing
  had moved. `new_line_number` on any instrument had the matching hole on the
  read side, and is accepted now too.

- **An edit made after a render reaches the next one.** `to_svg()`,
  `to_drawio()` and `render()` decided whether to lay the sheet out by asking
  whether any unit still lacked a frame, and that is true only before the very
  first layout. So from the second render on, every change was drawn from the
  first render's geometry and the file came out byte-identical — a `pin()`, an
  `add()`, a `connect()`, a `nozzle()`, a new `width`, `variant` or
  `label_pos`. A notebook, which draws through `_repr_svg_`, baked the
  placement it happened to display first.

  The flowsheet now records that its geometry is stale and re-runs whichever
  stage is. A sheet nobody changed is still laid out and routed once and no
  more, which is what the old guard was buying.

- **`layout()` called by hand takes the routes with it.** A route is measured
  against the frames, so replacing the frames left every run describing the
  sheet it was routed for: `render → pin() → layout() → render` drew each line
  from its current nozzle to the old path, as a diagonal. No shipped sheet
  moves.

- **A row pinned above the sheet crashed the coordinate pass.** `pin(row=-1)`
  names the band over row 0, and the bands were built counting up from 0, so
  the pin indexed a band that was never made and `layout()` raised
  `KeyError: -1`. The bands now run from the first row the sheet names. Row 0
  still anchors the top margin where nothing goes above it, so `pin(row=2)`
  keeps the two empty bands it asks for.

- **A pinned column dragged the rank feeding it off the page.** Slack removal
  slid each rank to one short of its nearest successor, which is a move to the
  *left* when that successor is pinned: `A → B → C` with `A.pin(col=3)` and
  `C.pin(col=0)` put `B` in column −1, four columns behind the unit feeding it.
  A rank now only moves right, which is the invariant the pass was written for.
  Two pins with a longer chain between them than the gap they leave cannot both
  be honoured, and the derived rank is the one that holds its ground.

- **A column left of 0 switched crossing reduction off without saying so.** The
  barycentre sweeps counted from column 0, so a sheet pinned to the left of it
  had an empty range in both directions: all four passes ran over nothing and
  the sheet came out in insertion order. The sweeps now run between the columns
  that exist.

- **Rebasing a stacked sheet overwrote the row the author pinned.** Where a
  north or south connection lands a unit below row 0 and a pin fixes the bands,
  the stacking constraint is dropped so the pin can stand. The loop that did it
  walked every unit rather than the stacked ones, so a `pin(row=-1)` was itself
  renumbered.

- **A stream that jogs between its nozzles was dragged off one of them.** The
  pass that separates parallel runs resolved a cluster one track per *stream*,
  taking the first port-attached run's height as the whole stream's. A stream
  whose two nozzles sit a few pixels apart contributes two port-attached runs
  at two heights, so the second was pulled onto the first one's track: the jog
  collapsed to a zero-length segment and the run that held the nozzle left it.
  Each port-attached run now claims its own track. A run that is free to move
  and whose own stream is pinned in the same cluster still joins that nozzle,
  which is what un-doubles the line, so no shipped sheet moves. The pass also
  works in runs now — a maximal chain of collinear segments — rather than in
  single segments, so a line the simplifier kept in two pieces cannot be
  offset into a diagonal.

- **The separation pass could resolve two runs closer than its own minimum.**
  It measured each run's track to the nearest pixel and then applied
  `target - track` to the unrounded waypoint, so a run settled up to half a
  pixel off the slot it was given: three runs placed on a 6px grid finished
  5.2px apart, closer than the spacing the pass exists to enforce. Tracks are
  the raw coordinate now, and candidate slots are compared at the spacing
  exactly instead of with half a pixel of slack.

- **Routing says why it left a stream undrawn.** Three paths out of the router
  dropped a stream with no line and no word, and each leaves `stream.route`
  None, which draws nothing and sends every later render back through routing.
  A port with no owning unit was caught by an `assert` — stripped under
  `python -O`, where it became an `AttributeError` naming none of this — and
  now raises a `ValueError` naming the port. A unit with no frame and a port
  with no anchor were skipped silently and now warn, naming the stream and
  what is missing.

- **The fallback route no longer leaves a zero-length segment behind.** When
  the search finds no path at all, the router falls back to an L through the
  two escape projections. Where those share a column the corner lands on top
  of the first of them, and the simplifier keeps both — it never drops a
  projection point — leaving a zero-length segment that the separation pass
  then reads as a horizontal run on a track the stream does not occupy. The
  fallback drops a point that repeats the one before it.

- **A non-finite coordinate no longer hangs the render.** `pin(x=float("nan"))`
  — or an infinity, or a non-finite width — made `to_svg()`, `to_drawio()` and
  `render()` never return, on a sheet `validate()` was already reporting as
  `pin-not-finite`. A\* terminates because `visited[state] <= g` settles each
  state at most once, and that comparison is false for every NaN: nothing was
  settled, every state re-expanded, and the queue's growing paths ate memory
  until the process died. The router now refuses such a sheet before it builds
  the visibility graph, with a `ValueError` naming the unit and the coordinate,
  which is the last point either can be named.

  Termination no longer rests on the numbers behaving, either. `find_path`
  refuses a non-finite endpoint outright and will not expand more than
  `MAX_EXPANSIONS_PER_NODE` states per graph node — eight, where the hardest of
  323 real searches across the sixteen examples expands 0.85 — raising rather
  than looping. A search that will not converge is a bug worth a traceback,
  not a drawing that never arrives.

### Security

- **A spec file could put script into the sheet drawn from it.** `Stream.color`
  and `Stream.dasharray` reached their SVG attributes unescaped, so
  `color: 'black" onload="alert(1)'` in a `.yaml` closed the attribute and
  opened an event handler on the `<path>` — and an SVG is opened in a browser.
  Every string a user fills in now goes through one escaper
  (`pandid.render.escape`) on its way into either document, attribute values
  and text nodes alike: unit names, tags, descriptions, off-page references,
  instrument letters, loop numbers, stream names and line-number components,
  stream properties, every title-block and revision cell, and the title, rows,
  headers and cells of every annotation, note, legend and table.

  It also drops the characters XML has no spelling for. A `NUL` or a `BEL` in a
  tag cannot be escaped into legality — XML 1.0 §2.2 admits tab, newline and
  carriage return and nothing else below `U+0020`, numeric references included
  — and one of them anywhere made the whole file unopenable, in both backends.
  A control character has no glyph, so nothing a drawing could have shown is
  lost by leaving it out.

  `tests/test_escape.py` is the property, not a list of cases: twelve shapes of
  hostile string through every field, on both backends, asserting each render
  parses, carries no attribute the value invented, and leaves every `url(#…)`
  and `href="#…"` pointing at an id that exists.

- **An id built from a colour was not always an id.** The arrowhead marker was
  named by pasting the colour into a string, so `color="rgb(1,2,3)"` minted
  `arrow_rgb(1,2,3)` — a legal attribute value and not a legal XML name. A
  browser drops the definition and draws the line with no arrowhead, while a
  PDF export, which resolves the reference itself, still draws one: two files
  disagreeing about the drawing, with nothing said. Marker ids and `<symbol>`
  ids are now minted by one function that answers with a name whatever it is
  given, and the `url(#…)` and `href="#…"` reaching them are written from the
  same call, so a definition and its reference cannot disagree. Where
  sanitising would be lossy a digest of the original is appended, so two
  colours never land on one definition. `arrow_black` and `arrow_0a7` are
  unchanged, and no golden or gallery sheet moves.

- **A colour that is not a colour is now refused, not escaped.** Escaping
  `black" onload="alert(1)` leaves a well-formed document whose `stroke` is a
  string no renderer recognises — and an unrecognised paint is *ignored*, so
  the line is drawn with no stroke at all and disappears off a drawing whose
  whole job is to say what is connected to what. `Stream.color` and
  `Stream.dasharray` are checked as they are set, against the shapes SVG writes
  one in, and the `ValueError` names the field, the line and what to write
  instead. The shape is what makes the value safe to put in an SVG attribute
  and in a draw.io `style=` key; a misspelled keyword is a typo rather than an
  injection and is left to `validate()`. See `pandid.streams.check_color`.

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

[0.1.2]: https://github.com/Alpha9463/pandid/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Alpha9463/pandid/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

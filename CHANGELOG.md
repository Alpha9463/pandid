# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Every rendered file says what drew it.** An SVG opened straight into
  `<!-- Background -->` and said nothing about its origin; a draw.io export said
  `agent="pandid"` with no version, so a reader could not tell 0.1.0 output from
  0.1.2 output. Both now carry the package and the version that produced them.

  An SVG gets, as the first children of `<svg>`, a `<title>` holding the sheet's
  own name — the title block's title if it has one, the flowsheet's name
  otherwise — followed by a generator comment and an RDF `<metadata>` block with
  `dc:creator` and `dc:title`. `<title>` earns its place twice: it is what a
  browser shows as a tooltip and what a screen reader announces as the
  document's name. A draw.io export puts the version in `agent`, which is the
  attribute draw.io itself writes a producer string into, and leaves `host` the
  bare application name.

  Openly, in a comment and a metadata element, and not as a hidden mark. Both
  formats are plain text, so concealment buys nothing a comment does not; one
  edit removes it, so its absence would prove nothing; and an invisible string in
  a controlled engineering document surfaces on select-all-copy and in any text
  extractor, into a deliverable nobody chose to put it in.

  Bumping the version does not move the golden fixtures. `_normalize` in
  `tests/test_golden.py` drops the block, which is fenced between two marker
  comments so that dropping it is a slice between two known lines rather than a
  version pattern hunted across the document. `docs/gallery/` and
  `drawio-samples/` are committed *rendered* output and do carry the version, so
  a release regenerates them; `CONTRIBUTING.md` says so under Releasing.

- **Every unit class is on the package.** `from pandid import Separator, Pump,
  Flowsheet` works, alongside the device classes that have been importable that
  way since the layer landed. `units.Separator` beside a bare `Cyclone` was two
  spellings for a base class and its own subclass, which is a distinction the
  import line made and the type system does not.

  All thirty public names in `pandid.units` are re-exported, `Unit` among them:
  it is the base a custom unit subclasses, so it is a name you type even if not
  one you instantiate. `pandid.Separator is pandid.units.Separator`. Additive —
  `from pandid import units, devices` is unchanged, and `units.Kind(variant=…)`
  is still how you reach the drawings that get no class of their own.

- **`examples/13_mineral_dewatering.py`: a solids circuit, as a PFD.** The first
  sheet in the gallery that is not a fluids plant. A flotation concentrate is
  thickened, dewatered on a vacuum belt filter, dropped as cake onto a conveyor,
  dried in a direct-fired rotary drum, recovered out of its own drying gas by a
  cyclone and cleaned of tramp steel by a magnet; the spent gas is scrubbed and
  pulled to the stack by an induced-draught fan. Sixteen tagged items, twelve of
  them scheduled.

  It draws thirteen `(kind, variant)` symbols that were registered and had never
  appeared on a sheet — `separator/gravity`, `/cyclone`, `/scrubber`,
  `/permanent_magnet`, `filter/belt`, `dryer/default`, `furnace/default`,
  `blower/default`, `tank/conical_bottom`, `funnel/default`,
  `vent/exhaust_head`, `pump/screw` and `pump/peristaltic` — taking the gallery
  from 60 of the 157 registered symbols to 73. It is the first example to build
  a `Blower`, a `Dryer`, a `Funnel` or a `Furnace` at all. Coverage was the
  reason to draw the sheet and not the reason for anything on it: every item is
  argued in a comment beside it, and the symbols a dewatering circuit does not
  want (a second filter, a second dryer, a second magnet) are left out.

  Four of its five junctions are `Tee(branch="inlet")`s where a second stream
  **joins** a run rather than leaving it. That is the reverse of the takeoff
  tees `10` draws, and neither the gallery nor the golden corpus had one. Every
  tee ends a stream number, so each of the twenty-four columns of the stream
  table is true of the line it names and the sheet's total-flow balance closes:
  297.06 t/h in over five inlet flags, 297.03 t/h out over five and the stack,
  no item out by more than 0.04 t/h.

  Like `03` and `08` it takes no `page_size` — twenty-four streams side by side
  is wider than A3 carries beside a utilities summary — so it is also the first
  golden fixture whose *furniture* rather than whose drawing sets the sheet
  width. It is drawn as a PFD on the model of `professional_examples/PFD_301`,
  with an equipment list, a sectioned stream table, a utilities summary and no
  instrumentation at all, which is ISO 15519-2 §4.2's "In the start of a project
  the representation in process flow diagrams (PFD) is pure functional".

- **`Vessel` and `Tank` carry five nozzles, and the same five.** `relief` is the
  connection a PSV or a rupture disc is mounted on, `drain` the low-point liquid
  draw-off, and `vent` — which a vessel already had — is now a tank's
  conservation vent as well. A fixed-roof tank breathes through a roof nozzle
  that is neither the fill nor the draw; a pressure sphere's fire-case relief is
  a third connection by definition, since a relief path must not run through a
  valve someone can close; and a knock-out drum's liquid had nowhere to go,
  because on nine of the ten vessel drawings the `outlet` is on the shell wall
  and the bottom head carried nothing at all. `examples/14_tank_farm.py` states
  all three in its docstring as things a real sheet carries and that one could
  not.

  **Named roles rather than a count**, which is the one place this departs from
  `Mixer`, `Splitter`, `Column`, `Reactor` and `Block`. A vessel's connections
  are positioned by what they are for: CHEE4001 p.7 puts a relief "vertically,
  upward, and at the top of the container", so `Tank(outlets=3)` would offer
  three interchangeable draws with nothing to stop the relief being placed on
  the floor. A role also has somewhere to go — each of the seventeen tank and
  vessel stencils authors a coordinate for each of its five nozzles, measured
  onto its own artwork — where a count has no bound and would place its sixth
  nozzle by spreading it along a face the drawing may have no ink on.

  Purely additive: the new nozzles are appended, nothing is renamed or moved,
  none of them is numbered so `nozzle-unconnected` stays silent on a tank
  nobody drained, the spec needs no key of its own since the port set follows
  from `kind:`, and every golden and gallery sheet is byte-identical.

- **`examples/14_tank_farm.py`**: a bulk liquid storage terminal, drawn as a
  P&ID on a fixed A3 sheet. Three storage vessels and the reason each is the
  vessel it is -- a floating roof over motor spirit, a fixed roof over ethanol
  that a floating roof would put rainwater into, a sphere for butane, which at
  ambient is a liquid only under its own pressure and therefore leaves through a
  let-down regulator rather than a pump. Around them the transfer system, the
  road loading rack, and the vapour system that takes back what loading
  displaces, with a conservation vent, a deflagration arrestor between that vent
  and the drum it protects, and a detonation-rated one in the rack return where
  the run is long enough for a deflagration to accelerate.

  It is the sheet that draws the storage, containment and line-fitting families.
  Before it the gallery drew 39 of the 157 registered `(kind, variant)` symbols;
  it adds 21 more that nothing had ever drawn, taking the gallery to 60 --
  `tank/floating_roof`, `tank/default`, `tank/sphere`, `vessel/legs`,
  `vent/breather`, `pump/gear`, `reducer/eccentric`, `reducer/concentric`,
  `valve/gate`, `valve/ball`, `valve/butterfly`, `valve/regulator`,
  `fitting/flame_arrestor`, `fitting/flame_arrestor_detonation_proof`,
  `fitting/blind`, `fitting/expansion_joint`, `fitting/strainer_basket`,
  `fitting/strainer_y`, `fitting/hose`, `fitting/positive_displacement` and
  `fitting/coriolis`. It is also the first sheet whose loop numbers are
  *allocated* rather than typed: `add_loop("L")` is written without a number and
  the sheet counts out L-601, L-602, P-603, F-604, F-605 in declaration order.

- **Control loops number themselves.** `add_loop("F")` with the number left out
  takes the next one from a single per-sheet counter, started by
  `Flowsheet(loop_number_start=…)` (default `101`) and allocated at the
  `add_loop()` line, so declaration order is allocation order. Typed and
  allocated numbers mix on one sheet; a loop is still the `(variable, number)`
  pair, so `F-101` and `L-101` remain two loops.

  The default is a three-digit unit-100 number rather than a bare 1, for the
  reason `line_number_start` is 1001: what comes out is an engineering document,
  and `FIC-1` is not a tag anyone writes on a P&ID, while `FIC-101` is an
  ordinary unit-100 loop. Both sheets in the corpus that number loops use three
  digits — `examples/04_control_loop` runs the 100 series and
  `examples/11_ethanol_pid` the 300 — because a loop series belongs to a plant
  area, so an author still has to say which area their sheet is either way. All
  the default decides is what the drawing reads like until they do.

  One series across measured variables, not a counter per variable, because that
  is what a sheet draws: `P&ID_301` runs `P-301`, `T-302`, `F-303`, `L-304`,
  `F-305`, `L-306`, `T-307`, `F-308`, and its notes block says "Note that
  instrument number are unique to this drawing". The counter is naive — no
  reservation list, no skipping, no collision search — because nothing outside
  the loop set spends a loop number: a final control element takes its loop's,
  CHEE4001 p.11 numbering a flow loop's element, transmitter, controller and
  valve all 504 under the p.13 rule that "A loop number is assigned to each
  group of components required to perform the desired function of the monitor or
  control scheme". Where the counter does reach a number typed by hand for the
  same variable, `add_loop()` raises at that line rather than silently skipping
  or duplicating.

  This does not weaken "a loop number is allocated once and never renumbered";
  it is where the once happens. That rule is about a number which has *left* the
  drawing for a DCS, and nothing leaves a draft. `to_dict()` is the freeze: it
  writes every loop's number as a literal, allocated or typed, so a sheet read
  back from its spec is nailed down. The argument is made in full in
  `pandid/loops.py`.

- **`Flowsheet(stream_number_start=…)`.** Where `S{n}` starts counting (default
  `1`, which is what it always did). A sheet numbering `S100` upward previously
  had to supply a whole callable naming scheme to move a number by 99. It is not
  `line_number_start`, which moves the `sequence` component of a *line* number,
  the `1001` inside `6"-P-1001-A1A`; a sheet can want one and not the other.

- **`loop_number_start` and `stream_number_start` in the spec**, alongside
  `line_number_start`, and a `loops:` entry may now leave its `number` out to
  allocate. `to_dict()` writes each key only when it differs from its default,
  so a spec written before this release and one written after are the same file.

- **A deprecation mechanism: one declaration, a warning and a `validate()`
  finding.** `pandid.deprecation.Deprecation` names a retired spelling, the
  spelling that replaces it and the release the old one stops working in. Its
  `warn()` emits a standard `DeprecationWarning` *and* records a `deprecated`
  finding, from one sentence built once, so the two cannot come to say different
  things. Both are needed: Python hides `DeprecationWarning` by default outside
  `__main__`, and `fs.validate()` is what an author is told to run and what an
  agent is told to check, so either signal alone is one nobody sees.

  The finding rides on the object the call was made on, because a deprecated
  call happens at construction while `validate()` runs after layout — a unit
  built before `fs.add()` has no flowsheet to record against, so it carries the
  finding itself and `validate()` collects from the sheet and everything the
  sheet holds. That is the shape `fs.warnings` and `fs.route_converged` already
  have: a fact settled in an earlier phase, parked on an object, read out later.
  A call with no pandid object in scope at all files against the process and is
  then reported by every `validate()` in it, which over-reports rather than
  drops.

  The policy is now in `CONTRIBUTING.md` instead of in anyone's head: a
  deprecation lives for one release, announced under `### Deprecated` and
  deleted under `### Removed` in the next, and `tests/test_deprecation.py` fails
  if any declaration names a release that has already shipped.

  Nothing is deprecated yet. `Valve(variant="control")`, the dry separators'
  catch and the `pin()` default are the customers and are changes of their own.
  The mechanism draws nothing, so `tests/golden/` and `docs/gallery/` are byte
  for byte what they were — checked by hashing a fresh render against the
  committed files, not by the suite going green.
- **`validate()` reports `nozzle-unconnected`:** a nozzle a *count* asked for
  that carries no stream. `Mixer("M-101", n_inlets=4)` with three inlets piped
  drew a complete, plausible sheet and returned no findings at all, so the
  drawing asserted a stream that did not exist — issue #183, from the off-by-one
  a user writes coming from `m.inlets` being indexed from zero while the nozzles
  are numbered from one.

  Deciding what counts as unconnected is the whole of the change. Over the
  fourteen shipped examples 252 ports carry no stream and every one is
  legitimate: 165 signal connections, 26 heat-exchanger utility sides, 14
  duties, 14 reliefs, 14 drains, 11 vents and 8 station drain outlets ("a drain
  runs down to a funnel on the floor, which is not on this sheet"). All 252 are
  nozzles a *class* declares, offered to
  every instance whether the sheet uses one or not. A **numbered** nozzle is not
  offered but asked for — `n_inlets=`, `n_outlets=`, `n_feeds=`, `inputs=`,
  `outputs=` are the five arguments that make one — so a bare member of such a
  family is a number the author wrote down that the drawing did not meet. Zero
  of the 252 is one, and the rule is silent on all fourteen while still
  inspecting 36 counted nozzles across eight of them.

  It is visible on the paper as well as in the model: a family is spread evenly
  across its face for every member it has, wired or not, so that four-inlet
  mixer draws its three lines 11.7px apart around a 17.5px hole rather than the
  17.5px apart `n_inlets=3` would have given them. The message names both cures,
  since the finding cannot tell a line left off from a nozzle never wanted.

  Scoped to **process** nozzles, as the issue asks. Signal connections are a
  different question — an instrument may be placed against its equipment rather
  than tapped off a line — and counting does not settle it. The singular
  spelling of a family is silent for the same reason the fixed nozzles are: a
  one-feed column's nozzle is `feed`, not `feed_1`, and no count produced it.

  No standard is cited. ISO 15519-1 §12, *Connections*, was read for one and
  governs only how a connecting line is drawn; neither it nor ISO 15519-2 nor
  the CHEE4001 guidelines oblige a connection point to carry a line. Nothing
  rendered moves: `tests/golden/` and `docs/gallery/` are byte for byte what
  they were, checked by hashing a fresh render against the committed files.
- **An instrument takes several signal connections, on any face.** A balloon had
  exactly one `sig_in` and one `sig_out`, so a controller could drive one final
  element and a measurement could feed one balloon. `sig_in` and `sig_out` are
  now **pools**: a second line off one is another connection rather than an
  error, minted as `sig_out_2`, `sig_out_3` and placed on whichever face suits
  where its peer is.

  ```python
  fs.connect(pic301.sig_out, cv1.actuator, kind="pneumatic")   # 0-95%
  fs.connect(pic301.sig_out, cv2.actuator, kind="pneumatic")   # 95-100%
  ```

  That is `P&ID-301`'s own loop 301, which this package could not draw. Two
  other things it could not draw come with it: a measurement feeding a high and
  a low alarm on separate lines, which ISO 15519-2 §6.2 (p. 14) requires be
  "drawn separate between the PCI symbols", and an alarm that takes an input and
  an output because it participates in a trip.

  On a **signal line** either end may now be the unit instead of one of its
  connections, and the engine picks: `fs.connect(ft305, fic305, kind="electric")`.
  Process piping still names its nozzle, because which nozzle a pipe runs to is
  the whole question.

  `pv` stays singular — an instrument taps one process point — and so does
  `Valve.actuator`: split range is one actuator per valve with the controller
  holding two outputs.

- **Export a sheet as a `.drawio` file.** `fs.to_drawio()`, and `.drawio` on
  `fs.render()`, write the drawing as an editable draw.io / diagrams.net model:
  every unit is a shape, every stream an edge between two of its connection
  points. draw.io exports `.vsdx` natively, so this is also the route to Visio.

  It references draw.io's shapes rather than emitting a tracing of them, which
  is only possible because the symbols in this library *are* draw.io's P&ID
  stencils (`NOTICE`). The key each one is filed under is derived from the
  package on the stencil file's root element and the shape's own name, by
  mxGraph's own rule, at the moment the artwork is converted — read out of the
  XML and never written down, so a re-vendor cannot leave a reference naming a
  shape that no longer exists. draw.io answers an unresolvable reference with a
  plain rectangle and no error, so `tests/test_drawio.py` walks all 143 drawings
  the registry can produce and holds every reference against the vendored
  stencils, and checks every box, waypoint and connection point against what the
  SVG renderer computes for the same sheet.

  The fifteen symbols drawn here rather than vendored have no draw.io stencil
  and are approximated with draw.io's *built-in* shapes, which cannot fail to
  resolve: a balloon is a circle, a computer balloon a hexagon, an interlock a
  diamond, a mixer a triangle, a tee a line, and the rest rectangles. Each
  approximation names what it loses, and so do the four sheet details a model
  has no room for — line jumps, pneumatic hatching, instrument tap lines and
  searched label placement. Sheet furniture exports as labelled boxes below the
  drawing. `docs/api.md` tabulates the lot.

  **Not yet confirmed in draw.io.** The document is checked structurally and
  geometrically here; nothing in the suite opens it.

  Nothing about the SVG changes: `tests/golden/` and `docs/gallery/` are byte
  for byte what they were, checked by regenerating both from a fresh render.

- **Each golden fixture is now checked against the example it was copied from.**
  `tests/test_golden.py` rebuilds every sheet from an inline copy of the
  example's code, so the suite was green whenever the fixture matched the
  golden — whether or not either matched `examples/NN_*.py`. That drift was not
  hypothetical: #230 corrected real people's initials in
  `examples/13_mineral_dewatering.py`, and the golden went on reading the old
  ones because the golden is built from the fixture.

  Every example is now also imported, rendered and compared against the same
  golden, so a divergence fails on the next test run rather than on the next
  screenshot. The examples are scripts that write files and print, so the
  capture in `scripts/gallery.py` is reused rather than reimplemented: it runs
  each one with `Flowsheet.render` replaced, catching the flowsheet and the
  options it was about to be drawn with and writing nothing anywhere. A second
  check asserts that every example has a scenario at all, so a new sheet cannot
  arrive unguarded.

### Changed

### Deprecated

- **`Valve(variant="pneumatic")` (#136).** Use `Valve(variant="control")`, or
  spell the pairing out as `Valve(variant="gate", actuator="diaphragm")`. It
  goes on drawing for 0.1.2 with a `DeprecationWarning` and a `deprecated`
  finding on `fs.validate()`, and is removed in 0.1.3.

  Two reasons at once. It names a **signal medium**, and a medium is not a kind
  of valve — "the pneumatic one" picks out no body, no operator and no duty. And
  as of this release it names the **same drawing** `control` names, so it is the
  second of two spellings for one symbol, and it was the one an engineer had to
  go and find because the obvious one drew a valve with nothing on top of it.

  `butterfly_pneumatic` is deliberately kept. It names a *body* with an actuator
  on it, which is a valve you can point at on a rack, and it is the only
  spelling for its drawing. Reach it either way — `variant="butterfly_pneumatic"`
  or `variant="butterfly", actuator="diaphragm"`.

- **`vapor` and `liquid` on a dust-collecting separator.** On
  `Separator(variant="cyclone")`, `("gravity")` and `("electrostatic")` the two
  draws are now `overflow` and `underflow`. The old names go on reaching the
  same nozzles for 0.1.2 and are removed in 0.1.3, with a `DeprecationWarning`
  and a `deprecated` finding on `fs.validate()` naming the replacement.

  ```python
  sep = units.Separator("CY-401", variant="cyclone")
  fs.connect(sep.vapor,     scrubber.feed)    # deprecated
  fs.connect(sep.overflow,  scrubber.feed)    # type this
  ```

  Every way to a nozzle by name is covered: attribute access, `port()`,
  `nozzle()`, `pin(port=…)` and a spec file's endpoints — a `.yaml` or `.json`
  written against 0.1.1 still reads, and `to_dict()` writes the new names, so
  reading and re-writing one upgrades it. `sep.ports["vapor"]` is not covered
  and cannot be: it is the dict itself, and the rename is a fact about what is
  in it. Nothing changes for a drum or a scrubber, whose draws really are the
  two phases.

### Changed

- **A control valve draws its actuator (#136).** `Valve(variant="control")` drew
  a Saunders body — a bowtie with a weir arc inside it and nothing on top — so
  the variant an engineer types for a control valve drew the one thing a control
  valve cannot be without. It now draws the diaphragm actuator: a dome on a
  short stem over the body, which is what `professional_examples/P&ID_301.pdf`
  draws on all six of its CVs. **ISO 15519-2:2015 Table 5** (p. 19) lists
  *"specific graphical symbols for process equipment incl. prime movers …,
  valves incl. actuators, connections, etc."* as **basic** information for a
  P&ID: the actuator is part of what the symbol is for.

  The old drawing is a real valve body and keeps its place as
  `Valve(variant="saunders")`. What it is not is a control valve.

  This moves every sheet that draws a control valve. The symbol is 19.8 tall
  rather than 15.0 and carries its body under the dome, so its nozzles sit 12.4
  below the top of the box rather than 7.5. **Pin such a valve by its nozzle**
  — `cv.pin(x=…, port="inlet", y=…)` — rather than by a literal or by its
  centreline; `fs.validate()` reports the difference as `run-off-elevation` and
  names the `pin()` that cures it.

- **The body and the actuator are two questions (#136).** `Valve` takes an
  `actuator=` keyword beside `variant=`: `variant` is the **body**, `actuator`
  is **what strokes it**.

  ```python
  units.Valve("HV-101", variant="globe")                      # a plain globe valve
  units.Valve("CV-303", variant="control")                    # a control valve
  units.Valve("XV-201", variant="butterfly", actuator="diaphragm")
  units.Valve("SV-401", variant="solenoid")                   # = actuator="solenoid"
  ```

  That is **ISO 15519-2 Table A.3**'s own model, stated in its registration
  numbers: A.3.01 registers the bowtie alone (2101A), A.3.40–A.3.45 register the
  actuators alone, and A.3.20 — *"Control valve, general … shown with general
  actuator"* — carries 2101A, 210A and P050B at once, because the control valve
  symbol *is* the body symbol with an actuator symbol on it. `variant="control"`
  stays as the shorthand for that pairing, since it is what an engineer types
  and what a sheet draws six times.

  The draw.io stencil set **fuses** the two: every actuated valve it ships is
  one shape drawing a body and an operator together, so the pairings that can be
  drawn are the ones it draws — `pandid.render.symbols.ACTUATED`, eleven keys
  over five actuators. A globe body under a diaphragm is not among them and is
  refused by name, listing the pairings that are. Synthesising the missing ones
  was refused: a composed symbol has no `drawio_shape`, and the draw.io export
  would hand back a traced picture where every other valve is a native editable
  stencil.

- **One drawing, one nozzle vocabulary (#138).** `Separator(variant="cyclone")`,
  `("gravity")` and `("electrostatic")` draw `overflow` and `underflow`, which
  is what `devices.Cyclone`, `devices.GravitySeparator` and
  `devices.ElectrostaticPrecipitator` have called the same three drawings'
  nozzles since the device layer landed. All three collect *dust*, and a hopper
  full of dust is not a `liquid`.

  Up to 0.1.1 the low-level form kept `vapor`/`liquid`, and `pandid/devices.py`
  recorded the split as the permanent cost of correcting the names without a
  break: one drawing answered to two vocabularies, and which you got depended on
  which class you constructed. That is withdrawn.

  Scope is those three drawings and nothing else. The four whose draws really
  are phases keep `vapor` and `liquid`: the drum in its `default`, `horizontal`
  and `knockout` forms, and the wet `scrubber`, whose products are a cleaned gas
  and a dirty scrubbing liquid. The mechanical separators (`sifter`, `impact`,
  `permanent_magnet`, `electromagnetic`) already drew the over/under pair.

  No drawing moved. The artwork still anchors `vapor` and `liquid` on all three
  stencils, and `Separator._VARIANT_ANCHORS` maps the rename onto it — the same
  mechanism `devices.Cyclone` used, moved down to the base so the two forms
  cannot disagree again. All 14 goldens and every gallery sheet are byte for
  byte what they were, checked by regenerating both.

- **`examples/10`, `11` and `14`: comments explain the code and nothing else.**
  The three were 40%, 58% and 54% prose; a reader looking for what a line does
  walked past a paragraph on why a gear pump suits a metering duty first. Every
  comment explaining process engineering is deleted rather than shortened, and
  what is left is what a reader of the code cannot recover from it: magic
  coordinates, choices that look arbitrary (`on=tt307` and not `on=tic307`), the
  library limitations behind an odd shape (#137, #169, #222, #223, #225, #226),
  and the clauses that are the reason a call is written the way it is. The
  sheet's story moves to the module docstring, which is also much shorter.
  10: 277 → 257 lines, 40% → 35% prose. 11: 671 → 453, 58% → 38%.
  14: 661 → 462, 54% → 34%. Nothing rendered moves.

- **`11` and `14`'s GENERAL NOTES keep only what the drawing cannot say.** Out
  go `"Diamond in square: safety instrumented system logic, code Z."` from both,
  which is a symbol key on sheets that already carry a LEGEND box, and the two
  sentences counting how many times the trip square is drawn, which a reader can
  see. `14`'s trip note keeps its first sentence, which states what the trip
  does. Everything not inferable from the drawing stays — the switches'
  independence, the arrestor ratings, the spectacle blind's duty — and
  `"XV-601 and XV-602 fail closed."` now says in a comment that it stands in for
  a mark the sheet cannot draw until #223 is fixed.

- **`direction` is a rule about process nozzles.** Fluid enters a nozzle or
  leaves it, so `connect()` refuses a pipe drawn the other way, exactly as
  before. A signal connection has no such fact to be right about — the same
  alarm terminal is fed on one sheet and trips from it on another — so it is no
  longer held to the field. Which end of its line a signal port took is read off
  `Stream.source`/`Stream.dest`, which is exact because a port holds at most one
  stream. Nothing that used to work stops working; calls that used to raise now
  draw.

  Every sheet in `tests/golden/` and `docs/gallery/` is byte for byte what it
  was, checked by hashing a fresh render of all fourteen examples in both
  corpora against the committed files.


- **`examples/11_ethanol_pid` declares its control loops.** The README's lead
  sheet typed a literal number on all 26 of its balloons. Six of them are
  groups — CHEE4001 p.13, "A loop number is assigned to each group of components
  required to perform the desired function of the monitor or control scheme" —
  so `P-301`, `T-302`, `F-303`, `L-304`, `L-306` and `T-307` are declared with
  `add_loop()`, and their sixteen balloons, the reflux venturi `FE-303` and the
  two control valves the sheet numbers from a loop are tagged from the handle.
  A loop number is now typed once per loop instead of once per balloon, and
  `add_instrument` checks each member's first letter against its loop's measured
  variable at the line that writes it.

  The other ten keep literal numbers, which is what they should do. `FI-314`,
  `PI-315`, `TI-321` and `TI-325` are single local readings with no transmitter
  under them and no controller over them. `PT-318` serves the trip and only the
  trip, so `P-318` would be a loop of one member: the number is typed once
  either way and there is no second letter to check. The five `Z` squares have
  no measured variable at all, `Z` being what the function does rather than what
  it reads. `CV-301-1`, `CV-305` and `CV-308` type their tags too, for reasons
  of their own: `CV-301-1` is one of PIC-301's two split-range valves and its
  suffix is a station member index no loop handle spells, while `CV-305` and
  `CV-308` belong to loops 305 and 308 — the slave halves of two cascades this
  sheet draws in short, wiring each master straight to the valve. A final
  element's number does track its loop; only its letters do not.

  Refactor only. Every tag is the string it was, so
  `tests/golden/11_ethanol_pid.svg` and `docs/gallery/11_ethanol_pid.{svg,png}`
  are byte for byte what they were — checked by hashing a fresh render against
  the committed files, not by the suite going green. Running the measured-
  variable check over the densest sheet in the corpus for the first time
  rejected nothing: every balloon's first letter already agreed with its loop.

### Fixed

- **The storage sphere's ports did not land on the nozzles it draws (#225).**
  `tank/sphere` is the one stencil in the registry that draws its nozzles as
  nozzles — three flanged stubs, two on the crown and one under the belly — and
  none of its five ports was on one. `inlet` sat at the top centre midway
  between the two crown stubs, so `examples/14`'s butane receipt arrived at bare
  shell; `outlet` sat on the base rail of the *support skirt*, ten units below
  the nozzle drawn for it, so the sheet drew product leaving the structure.

  The three drawn nozzles now carry the three duties the drawing is about:
  `relief` and `vent` on the crown (CHEE4001 p.7 puts a protective device
  "vertically, upward, and at the top of the container", and a vapour space is
  at the top by definition), and `outlet` on the belly nozzle. `inlet` and
  `drain` are both liquid and go low on the shell either side of it — `inlet`
  west by default with an east alternate reachable through
  `nozzle("inlet", "E")`, `drain` south, which is the face its role asks for.
  They are not stacked on the belly nozzle with the outlet, because two ports on
  one placement draw two streams on one point.

  Two new invariants over all 157 registered symbols hold the correspondence:
  every drawn nozzle carries a port, and no port sits in the gap between two
  nozzles drawn on one face. The sphere was the only symbol failing either.

- **A resized symbol's line width changed with it, and changed differently in
  each axis.** ISO 15519-1 §11.1.3 (p. 28) is a *shall*: "When the size of a
  symbol is changed, the line width shall be unchanged." A `<symbol>` placed
  under `preserveAspectRatio="none"` scales its ink as readily as its geometry,
  so a vertical line came out at `sx` and a horizontal one at `sy`, and no
  `stroke-width` can undo a difference that depends on which way the element
  runs. The compensation that shipped took the geometric mean of the two, which
  put the average right and every individual line wrong: `V-604`'s shell walls
  drew 2.48 against its own heads' 1.61 — 1.53:1 inside one outline, against
  process lines at a flat 2.0 — and §6.2 (p. 19) leaves nothing between 1:1 and
  2:1 to call that instead. Twenty stretched placements across the golden corpus
  were affected, eleven of them visibly.

  So was a case no placement could reach: the four vendored families whose own
  artwork is wrapped in an uneven `scale()` — `vessel/default`,
  `separator/default`, `column/packed` and `valve/butterfly_pneumatic` — drew an
  ellipse at their *natural* size, a separator's shell walls at 2.23 against its
  heads' 1.80 on any sheet that resized nothing at all.

  The artwork is now redrawn at the placed size instead of being stretched by
  its viewport: every scale group and the placement are flattened into the
  coordinates, and each `stroke-width` is stated at the weight the symbol's
  author drew, so no uneven scale is left above any stroke anywhere.
  `vector-effect="non-scaling-stroke"` says the rule directly and browsers
  honour it, but svglib has never heard of the property and drops it in silence,
  which would have left the `.svg` right and every exported PDF and gallery PNG
  exactly as wrong as before. Geometry is untouched — every drawn point on the
  corpus lands within 1.2e-6 px of where it did.

- **`examples/14_tank_farm`: the pump suction had a bend in it, and the vapour
  return crossed the whole sheet.** `RD-601` is the eccentric reducer, whose two
  nozzles are deliberately not on one centreline — flat on top, the small end's
  axis sits half the bore difference above the large end's — and `P-601` was
  pinned on the *large* end's elevation, so the run stepped 2.4 units straight
  out of the fitting whose entire purpose is that the crown of the line does not
  step. The pump is now pinned at the reducer's outlet elevation, asked of the
  symbol with `port_offset()`, and everything the discharge sets moves with it.

  The tanker vapour return ran east edge to west, a return stream counterflowing
  for 1200 units against ISO 15519-1 §13.2 (p. 28), "the direction of the main
  flow should be from left to right or from top to bottom" — a *should*, and the
  only clause on flow direction in any of the three documents on disk. The
  vapour system now stands at the rack it serves with both off-page flags on the
  east edge, so `VAP-610` comes in on one row and `VAP-612` leaves on the row
  below. `V-604`'s vent riser has to top out clear of the E10 rack, which puts
  the two rows lower than the old single row: the drawing is 96 units taller and
  the A3 fit falls from 1:1.19 to 1:1.29.

- **`HS-601` tagged a hose as an instrument.** ISO 15519-2 Table 2 (p. 11) gives
  `H` as the process variable "Human observation" and `S` as the control
  function "Switching (open loop)", and §5.2.2/§5.2.3 build a letter code string
  as the one followed by the other — so `HS` is exactly what the standard
  constructs and §5.1.1 draws it in a PCI symbol. The loading hose is now
  `HOS-601`, which breaks the string at a letter that is neither a control
  function nor a Table 3 modifier.

- **Three sheets carried a real drawing's checker and approver.** `RG` and `HVL`
  are the initials on `professional_examples/P&ID_301.pdf` and had been copied
  into `10_ethanol_pfd`, `11_ethanol_pid` and `14_tank_farm`. They are now `JS`
  and `RL`, the fictional pair `03` and `09` already use. `AA` stays: that is
  the repo's author.

- **The scale cell reported a fit ratio on a diagram that is not to scale.**
  Blank, `TitleBlock.scale` makes the sheet report the ratio the renderer placed
  the drawing at, so `10` read `1:1.31`, `11` `1:1.23` and `14` `1:1.19`.
  CHEE4001 p.2: "Do not represent the real length of pipes on P&IDs. P&ID is a
  'Not to Scale' (NTS) drawing." All three now state `scale="NTS"`, as `03` and
  `09` do. The default is unchanged.

- **`to_drawio` takes `page_size` and `border`, and the export is a sheet when
  it is given them.** A drawing made `page_size="A3"` opened on draw.io's
  default page with no frame around it. The file now states the page for draw.io
  to rule, docks the furniture to that page rather than to the drawing's own
  bounds, fits the drawing into what the furniture leaves, and rules the
  zone-ruled border on it — all through the `furniture.dock`, `svg._fit_scale`
  and new `furniture.zone_layout` the rendered sheet uses, so the two open at
  the same size on the same paper. Omit `page_size` and nothing changes: the
  drawing keeps its own coordinates on an unbounded canvas.

  One caveat, now in `to_drawio`'s docstring: a zone grid is an address space
  (ISO 15519-1 Clause 9) that `Feed.reference` writes into, and it holds only
  while the sheet does. What is exported is a **snapshot of the grid**, true of
  the drawing as it left pandid and not after the model has been edited.

- **draw.io tables no longer clip their own contents.** Columns were given
  proportional shares of the box instead of their measured widths, and were then
  drawn at draw.io's default 12 having been measured at 11, so `HPSSH` came out
  `HPSS` and `APP'D` came out `APP'`. Columns are now measured with
  `furniture.text_width` at the size each table states it is drawn at. The title
  block's eleven fields, stretched to fill an eighty-unit strip, were rows 5.6
  units tall that drew no text at all; both halves are ruled at their own row
  height, bottom-aligned, and the dock is told the height they need.

- **A pipe tee draws no ink of its own, and the pipes close the junction.** The
  cell showed a stub sticking out of the run. Every stream meeting a tee now
  lands on the box centre, so the three legs draw the meeting themselves —
  flush by construction, with each leg still straight. The cell stays, invisible,
  so dragging the junction takes its pipes with it.

- **The `.drawio` export draws the instrument connections.** An instrument
  mounted with `add_instrument(..., on=…)` gets a tap line, which is not a
  stream and so was not among the edges the export walked: all twenty of
  `examples/11_ethanol_pid`'s balloons came out floating free of the plant.
  ISO 15519-2 §5.1.1 does not leave that open — the PCI symbol *shall* be
  connected to the process system with a solid line and to the control system
  with a solid or dashed one — so an export without them is not a P&ID. Each is
  now an edge, pinned to the balloon and, where the host is a piece of plant,
  to the host, so it stays attached when either is dragged. `tap_lines()` and
  `impulse_tap()` moved to module scope in `pandid.render.svg` and both backends
  read them, so there is one answer to where a tap runs and whether it is solid.

- **A pneumatic signal line is marked as one.** It exported solid and thin,
  which told it apart from a process line by weight alone and from an electric
  one by nothing. The double cross-hatch (ISO 15519-2 Annex A.1.09, type 433A)
  now goes out as a pair of `line` cells parented to the edge, at the points
  `pneumatic_marks()` puts them, so they ride the line when it is re-routed.
  ISO 15519-2 §6.2 sanctions the mark where most of the diagram's signal lines
  are electric, which is `examples/11`'s case. Two departures from the sheet:
  a mark keeps the angle it was exported at if the line is later re-routed
  through a turn (mxGraph does not orient a shape to an edge), and the pair is
  two cells rather than one glyph.

- **Sheet furniture docks where the sheet docks it.** The title block, equipment
  list, notes and legend were stacked in a column down the left of the drawing
  at x=26 while the drawing ran out to x=1540. The band arithmetic that places
  them came out of `SvgRenderer._place_furniture` into
  `pandid.render.furniture.dock()`, which is a statement about a sheet rather
  than about SVG, and both backends now call it. A `.drawio` file has no paper,
  so the frame is grown around the drawing rather than being a page — on a sheet
  rendered at `page_size="A3"` the corners are the drawing's corners, not the
  page's.

- **The equipment list, notes, legend and title block are ruled tables.** Each
  was a single `value` with `<br>` runs in a plain rectangle. Anything columnar
  now exports as a draw.io table (`shape=table` with `childLayout=tableLayout`,
  row and cell children), which opens as an editable grid. The title strip goes
  out as two tables — the six-column revision history, heading row at the foot
  where the sheet rules it, and the identification fields as label/value rows.
  Its merged geometry does not survive: the sheet spans a title across the strip
  and rules the drawing number, scale, date and revision as four cells on one
  line, and a table row gives every cell the same height. A box whose rows are
  plain sentences stays a box, since ruling one column into a grid would invent
  structure the author did not write.

- **An off-page flag is a pennant with its tag inside it.** `Feed` and `Product`
  exported as an unlabelled rectangle with the label placed *above* it.
  draw.io's `offPageConnector` is the sheet's polygon exactly — five points,
  flat back, one end drawn to a point — turned a quarter to point along the
  flow, and the tag and off-page reference now sit in the flag as they do on the
  sheet. The cell is the pennant rather than the unit box, which the flag is
  drawn inset inside. `step`, the obvious candidate, cuts a chevron notch into
  the flag's back that no setting removes.

- **A pipe tee is drawn in the pipe's own ink.** It exported at the stencil
  hairline `#111` and draw.io's default weight, so the twelve units of run
  through every junction were a visibly lighter, thinner rule bridging two
  heavier pipes. It is black at the pipeline's weight, which is what
  `sym_tee` is.

- **Two more the export got wrong without anything on a sheet showing it**, both
  read out of mxGraph's source rather than seen. A dash pattern is multiplied by
  the stroke width unless `fixDash=1`, so a pattern given to a stream through
  `dasharray` came out at twice its length on a process line; every dashed edge
  now carries the flag. And draw.io ships two anchor-point algorithms that
  disagree for a north or south `direction` — the newer one swaps the bounds'
  width and height whatever `anchorPointDirection` says — so a cell that states
  a `direction` now also states `legacyAnchorPoints=1` and stops depending on
  which is the default.

- **Documentation: a final control element does take its loop's number.** 0.1.1
  shipped the opposite claim in `pandid/loops.py`, `docs/api.md` and
  `tests/test_loops.py` — that neither the letters nor the number of a final
  element track its loop — and cited `LIC-304` driving `CV-305` on the reference
  sheet as the evidence. The reading was wrong. That sheet carries `FE-305`,
  `FT-305` and `FIC-305`: 304 is a level-to-flow cascade whose slave is loop
  305, and `CV-305` is loop 305's own final element. `TIC-307`/`FIC-308`/
  `CV-308` is the same arrangement. The sheet settles it without either
  cascade — `LIC-306` strokes `CV-306` and `TIC-312` strokes `CV-312` — and
  CHEE4001 p.11 labels a flow loop's control valve `Loop No.` alongside its
  element, transmitter and controller, all four numbered 504, under p.13's rule
  that one number is assigned to each group of components a control scheme
  needs. The valve is in the group.

  What does not track is the **letters**: the sheet spells every control valve
  `CV-`, whatever it strokes, so `loop.tag()` still composes without checking a
  first letter. No behaviour changes — `tag()` supplied the loop's number before
  and supplies it now — but the reason it is right is the reverse of the one
  recorded, and the wrong reason was about to be built on.

## [0.1.1] - 2026-08-01

**A sheet regenerated on this version is not the sheet 0.1.0 drew.** Symbol
geometry, stroke weights, label and line-number placement and the whole PDF/PNG
export backend all moved, so the same flowsheet renders to different bytes and
nothing in your code raises, warns or otherwise says so. All eleven sheets 0.1.0
shipped are redrawn, and every `.png` with them, the raster backend and its
resolution having both changed. If a drawing has been issued, diff it before
reissuing it.

Nothing was removed or renamed. Everything below is an addition, or a correction
to what was drawn.

### Added

- **`debug=`: the coordinate system, drawn on the sheet.**

  Placement is absolute and neither of the two points it is written against is
  drawn, so `pin(x=270, y=180)` (a corner) and `pin(port="inlet", y=195)` (a
  nozzle) are easy to confuse. `to_svg(debug=True)` and `render(..., debug=True)`
  draw them.

  ```python
  fs.render("draft.svg", debug=True)   # default 50-unit grid
  fs.render("draft.svg", debug=100)    # ...or set the spacing
  ```

  A faded red grid carrying its own coordinates, a red cross on the point every
  `pin(x=, y=)` sets, a blue dot on every port, and each of them labelled with
  the name and the numbers the API takes. Drawn in drawing coordinates and under
  the diagram, so the numbers on the sheet are the numbers to type back in and
  nothing on the sheet is obscured. Each label is placed against the finished
  drawing, stepping clear of its lettering and of the other labels, and carries
  a fine line back to its own marker where it had to go far to find room. Works
  on `.svg`, `.pdf` and `.png`, and on a fixed `page_size`, where the lettering
  holds its size on paper while the grid stays on the drawing's own numbers.
  `pandid draw --debug [SPACING]` is the same switch.

  Off by default, and off is byte for byte the sheet that was drawn before it
  existed. It is scaffolding, not drawing: nothing issued should carry it.
  `examples/02_manual_layout.py` is drawn with it on, and now pins one train by
  the corner and the other by the nozzle so the overlay has the difference to
  show. It does not replace [#154](https://github.com/Alpha9463/pandid/issues/154),
  which is about not having to compute the coordinates at all; this is about
  reading the ones you did.

- **`Block.order_on()`: where a connection sits along the face it is on.**
  ([#192](https://github.com/Alpha9463/pandid/issues/192))

  A block's face said which wall a connection was on and nothing about where
  along it, and a wall carrying both kinds drew every input before every
  output — so the ordinary BFD recycle, entering on the side nearer the section
  that produced it, could not be drawn.

  ```python
  loop = fs.add(units.Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"]))
  loop.order_on("S", [loop.out_2, loop.in_2])    # purge west, recycle east
  loop.order_on("S", loop.ports_on("S")[::-1])   # ...or just turn the wall round
  ```

  It is `ports_on()`'s writer and takes what that hands back: the ports, not
  their names, so a typo is a type error rather than a quietly wrong drawing.
  Name every connection on the face — the call is a statement of the drawing,
  not a nudge at it, and one that leaves a connection unplaced is refused, as is
  one naming a connection on another face. First is the low end of the face on
  the box's own axes, west on a north or south face and north on a west or east
  one, so a mirrored block draws that first member on the right of the sheet,
  exactly as the face itself follows the box.

  Nothing changes for a block that does not call it: the drawn order is still
  the declared one. `to_dict()` writes a reordered face as `port_order` and
  omits the key otherwise.

  `examples/12_block_flow_diagram.py` uses it, and its recycle stops running the
  width of the sheet to reach back past the purge: 481 drawing units to 281.

- **A variable-port family is now a typed sequence.**
  ([#175](https://github.com/Alpha9463/pandid/issues/175))

  `Mixer.inlets`, `Splitter.outlets`, `Block.inlets`/`outlets` and
  `Column`/`Reactor.feeds` are `tuple[Port, ...]` in declaration order: the
  ports themselves, so `m.inlets[0] is m.in_1`.

  ```python
  mixer = fs.add(units.Mixer("M-101", n_inlets=len(headers)))
  for header, inlet in zip(headers, mixer.inlets):
      fs.connect(header.outlet, inlet)
  ```

  Iterating a family meant `m.port(f"in_{i}")` and a hand-rolled loop, and none
  of it was visible to a type checker. It could not be: the count is chosen at
  construction, and Python has no integer generic, so no annotation spells
  `in_1` … `in_n`. A generated class per arity would have typed
  `Mixer("M", n_inlets=3)` and missed `Mixer("M", n_inlets=len(feeds))`, which
  is the call a sheet built from a stream table actually writes. The arity is
  still not in the type — it cannot be — but `m.inlets[0]` is a `Port` to mypy,
  `for p in m.inlets` checks, and a computed count works.

  The tuple is indexed from zero while the nozzles are numbered from one, so
  `inlets[0]` is `in_1`; nothing re-bases it. `enumerate(m.inlets, start=1)`
  gives the number and the port together, and `m.port("in_3")` reaches one by
  its number — it is the only 1-based route a type checker can follow, since
  `m.in_1` still resolves to nothing under mypy and always has. A one-feed
  `Column` still spells its nozzle `feed`, and `feeds` is the one-tuple holding
  it.

  Purely additive: `m.in_1`, `m.port("in_3")` and the `ports` dict are
  untouched.

  `Block`'s accessors are renamed in the same change, so each is named for what
  it returns. `inputs`/`outputs` become `input_faces`/`output_faces` — they
  returned `['W', 'W', 'N']`, compass letters rather than the connections the
  name promises — leaving `inlets`/`outlets` for the ports; and `ports_on(face)`
  now returns the **ports** rather than their names, so "connect whatever is on
  the north" no longer means `[b.port(n) for n in b.ports_on("N")]`, a round
  trip through the very dict the families exist to spare. All four are tuples.
  `Block` is unreleased, so nothing that shipped is affected, and the
  constructor keeps `inputs=`/`outputs=`, where "the inputs are on these faces"
  is what the argument says.

- **`units.Block`: the block flow diagram.**
  ([#164](https://github.com/Alpha9463/pandid/issues/164))

  A BFD sits a level above the PFD: one labelled box per plant section, the
  streams between them named, nothing inside them drawn. There was no way to
  draw one, because `unit/default` is a 60x60 box with no ports on it.

  ```python
  rx = fs.add(units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"]))
  fs.connect(recycle.out_1, rx.in_3)     # in on the north face
  rx.nozzle("out_2", "S")                # ...and out of the bottom
  ```

  `inputs` and `outputs` are one face per connection, in order, with a plain
  count as the shorthand for the common case (west in, east out). The nozzles
  are `in_1` … `in_n` and `out_1` … `out_m`, numbered across the whole family
  rather than per face, so moving one to another side never renames it.

  **The box sizes itself to what it carries.** A BFD box is precisely the thing
  that gathers many streams, and squeezing eight of them into the height a
  one-inlet block was drawn at makes arrowheads that touch and read as one blob.
  So the height follows the west and east counts and the width follows the north
  and south ones, at a pitch measured off the arrowhead the renderer actually
  draws. Eight inputs on one wall make a taller block. `width`/`height` still
  win where they are given, and a box too small for the connections is refused
  rather than drawn crushed, the way a `Conveyor` refuses a belt run its rollers
  do not fit in — including where a `pin()` turn is what makes it too small.

  **Pin a block flow diagram** until [#168](https://github.com/Alpha9463/pandid/issues/168)
  is fixed. The layout engine ranks units by process flow order and does not yet
  know that a connection on the north face wants its source *above* it, so a BFD
  left to lay itself out sends those streams up and over the sheet.
  `examples/12_block_flow_diagram.py` is a worked, pinned sheet, and
  `docs/api.md` says the same.

  A block is not scheduled equipment: `equipment_list()` skips it, because a box
  standing for a whole section is not a purchasable item. It declares no
  variants and gets no `pandid.devices` subclass — a block is a block.

- **`pandid.devices`: 42 equipment classes over the `kind` + `variant` model.**
  ([#146](https://github.com/Alpha9463/pandid/issues/146))

  `devices.Cyclone("S-1")`, `devices.KettleReboiler("E-101")`,
  `devices.CentrifugalPump("P-101")`. Every name is re-exported from the
  package, so `pandid.Cyclone` and `pandid.devices.Cyclone` are one class, and
  every one of them is a subclass of the `pandid.units` class that owns its
  kind — a `GearPump` *is* a `Pump`, so nothing that asks `isinstance` changes.

  Two things it buys. An engineer looking for a cyclone finds `Cyclone` rather
  than having to know it is spelled `Separator(variant="cyclone")`; and the
  nozzles are declared on the class, so `fs.add(devices.Cyclone("S-1")).underflow`
  resolves to a `Port` under mypy and `.underflw` is an error before the sheet
  is drawn.

  The split follows one rule: **a class is what the equipment is, `variant=` is
  how it is drawn.** A variant becomes a class when it names a distinct
  scheduled item; it stays a variant when it names a support, a roof, a
  cladding, an attitude, a drawn internal, a certification rating or a body
  style. So a gate valve and a ball valve are one class and two variants, while
  a check valve is a class of its own — it has no actuator, which is a fact
  about the device rather than about its picture. That is why the valves split
  six ways on behaviour rather than twenty-three ways on body.

  Nothing shipped moves. All 156 registered `(kind, variant)` pairs build the
  same nozzles, store the same `unit.variant` and resolve to the same
  coordinates as before; `Separator(variant="cyclone")` stays supported
  indefinitely and is still the only way to reach the ninety-one drawings that
  get no class of their own.

  The module is **generated** by `scripts/gen_devices.py`, which refuses to run
  unless every registered `(kind, variant)` is claimed exactly once — by a
  class, or by an explicit entry saying which class's style it is. Vendor a new
  stencil and the generator stops until someone has said what the equipment
  *is*, which is the one question a symbol table cannot answer for itself.

- **`Cyclone`, `GravitySeparator` and `ElectrostaticPrecipitator` call their
  draws `overflow` and `underflow`.** All three collect *dust*, and the drawings
  have called the catch `liquid` since 0.1.0; the new classes correct it while
  `Separator(variant="cyclone")` keeps `vapor`/`liquid` **permanently**, because
  every sheet drawn against 0.1.0 depends on it. The accepted, permanent cost is
  that one drawing then answers to two nozzle vocabularies depending on which
  class you constructed. See the `pandid.devices` module docstring, which says
  so outright rather than leaving it to be met by surprise.
  ([#138](https://github.com/Alpha9463/pandid/issues/138))

- **`docs/api.md` lists the equipment classes.** An *Equipment classes* table
  beside the port table, one row per class with its `kind`, its base and only
  the nozzles that differ from that base, and the *Variants* table restructured
  from "kind → every drawing of it" to "class → the drawings it owns", which is
  where a class-local spelling — `DustCollector(variant="belt")` for
  `filter/gas_belt` — becomes visible. Both tables are held to the live registry
  by a test, so a drawing nobody documented fails the suite the way one nobody
  classified already fails the generator.
  ([#147](https://github.com/Alpha9463/pandid/issues/147))

- `Unit.PORT_ANCHORS`: nozzle name → the name the symbol anchors it under, for a
  class that renames one of its drawing's nozzles. Without it a renamed nozzle
  asks the artwork for an anchor it does not have and is given the fallback, the
  centre of the box, so two renamed draws land on one point and their streams
  stack. Declaring both names on the *symbol* is not the alternative it looks
  like: two names at one coordinate is exactly what `Symbol.coincident_ports()`
  reports, because a symbol cannot tell a rename from two nozzles drawn on top
  of each other. So the rename is a fact about the class and lives on the class.

- `Unit.VARIANTS` and `Unit.VARIANT_ALIASES`. A subclass may now name the
  drawings it owns, and is refused any other **when it is constructed** rather
  than at the first layout or render.
  ([#145](https://github.com/Alpha9463/pandid/issues/145))

  Nothing shipped moves. Every class in the port table leaves `VARIANTS` empty,
  which is how a class says it owns its whole kind, and the check is inert for
  it: `Separator(variant="cyclone")`, `HeatExchanger(variant="kettle")` and
  every other `Kind(variant=…)` builds exactly the nozzles it always did, and a
  variant nothing is registered under is still refused where it always was, by
  `SymbolRegistry.get` when the artwork is asked for. That path is not replaced;
  a class that owns a whole kind has no list to check against, because only the
  registry knows what artwork exists.

  What the attribute buys is the class that owns *some* of a kind's drawings.
  Such a class can say that a variant naming another device is wrong, and say it
  on the line that asks for it, listing the ones it does draw, suggesting a near
  miss, and ending with the low-level form — `Separator(variant='sifter')` —
  so that a refusal is a redirection rather than a dead end.

  `VARIANT_ALIASES` renames a variant class-locally. What is stored is the
  **registry's** spelling, since that is what `SymbolRegistry.for_unit` and
  `pandid.portgeom` read to find the artwork, so `to_dict()` writes the registry
  name and not the rename. List both spellings in `VARIANTS`, class-local first,
  where that round trip matters.

  `HeatExchanger` and `Separator` add their per-variant nozzles through a new
  `_variant_ports` classmethod, which returns nothing on a subclass that
  declares its own `PORTS`. Both add those nozzles after `super().__init__()`
  has laid down `PORTS`, so without it a subclass declaring its whole nozzle
  list and inheriting either constructor added `shell_in` twice and raised
  `"already has a port named 'shell_in'"`.

- **`validate()` reports `nozzles-crowded`:** two nozzles on one face of a unit
  pitched so close that the arrowheads they carry leave less paper between them
  than a drawing standard allows between any two parallel lines.
  ([#155](https://github.com/Alpha9463/pandid/issues/155))

  A PFD ends every process line in a 12px filled triangle, and that triangle is
  as wide across the run as it is long, so two of them on one face at pitch `p`
  leave exactly `p − 12` of paper. A port family spread down a short face closes
  that strip: `10_ethanol_pfd`'s M-301 takes two feeds 14.5px apart, leaving
  2.5px — 0.51 mm on the A3 sheet it is issued at, under the 0,7 mm ISO 128-20
  will not go below at any line weight. Nothing errored, the connectivity was
  right and every nozzle was on its ink, which is what made it worth a finding.

  The floor is `pandid.render.symbols.MIN_NOZZLE_PITCH`, the `ARROWHEAD` the
  renderer actually draws plus `MIN_HEAD_CLEARANCE` — **ISO 128-20:1996 §4.4**'s
  minimum space between parallel lines, twice the 2px weight the sheet draws
  those lines at. Both come off the artwork rather than off a preference, and
  tests read the head back out of a rendered marker and the clearance back off
  the renderer's own line weight, so neither can drift. The message quotes the
  white it measured and names the box that would fix it
  (`M-301.height = 111`).

  Only nozzles that actually wear a head are counted, and both of a pair. A
  stream *leaving* takes its head at the far end, so a splitter's outlets read
  as two bare 2px lines however tightly they are pitched; so do signal lines and
  runs ending at a tee. **A P&ID draws no heads at all**, so the finding is not
  made for one: `validate(diagram=…)` takes the drawing it is answering about,
  and `render()` passes the one it is making.

  One unit across the shipped examples is reported, `10_ethanol_pfd`'s M-301.
  Rendering is unchanged and no golden moves.


- Every unit class declares its nozzles as class annotations (`suction: Port`),
  so `pump.suction`, `sep.feed` and `hx.shell_in` are attributes a type checker
  and an editor can see. They were built by `_add_port`'s `setattr`, which
  neither can follow, so the package shipped `py.typed` while every nozzle on it
  read as `Any` and a misspelled one was found only when the sheet was drawn.

  The annotations bind nothing: an annotation with no value lands in the class's
  `__annotations__` and nowhere else, so construction, the `ports` dict and the
  drawn sheet are untouched and no golden moves.
  `tests/test_port_annotations.py` walks every `Unit` subclass in the package,
  builds one, and checks the declarations against the ports in both directions,
  so the two spellings of one fact cannot drift.

  Two things had to go with them, because annotations alone check nothing.

  `Unit.__getattr__` is now hidden from type checkers and from them only
  (`if not TYPE_CHECKING:`; the method is defined exactly as before when Python
  runs, and a typo still raises the same message, byte for byte). mypy reads a
  class that has one as having whatever attribute it is asked for, so leaving it
  visible would have answered every `sep.liqid` with `Any` and the declarations
  would have bought a better hover and nothing else.

  `Flowsheet.add`, `Unit.pin` and `Unit.nozzle` now return the class they were
  given rather than the base `Unit`. Every sheet is written
  `p = fs.add(units.Pump("P-101"))`, and `-> Unit` threw the subclass away at
  the one call each unit passes through, so `p.suction` resolved through the
  base class and no declaration on `Pump` was ever consulted. Nothing changes at
  runtime: all three already returned the object handed to them.

  **A nozzle no class declares is therefore a type error now**, which is the
  point, and it reaches two things besides typos: the numbered families a count
  decides (`Mixer`'s `in_1` ... `in_n`, `Splitter`'s `out_1` ... `out_n`) and
  the nozzles only some variants carry (`HeatExchanger`'s `bottoms`,
  `Separator`'s `overflow`). Both keep working at runtime and through
  `unit.port(name)`, and the second is what a per-variant subclass will answer.

- Four more `Vessel` variants, vendored from the same draw.io stencil file the
  rest of the family comes from: `legs` (the shell standing on a pair of legs),
  `insulated` (lagged, with the insulation hatched down both walls),
  `electrical_heating` (a resistor element on the shell wall) and `swaged` (one
  vessel in two diameters, the larger below).

  Three of them are a change of artwork and nothing else. `legs` is
  `skirted`'s shell and heads to the unit, in `skirted`'s 40 × 122.7 box, and
  takes its nozzles verbatim; `insulated` is `jacketed`'s, in `jacketed`'s
  52 × 95.4 box, with the cladding drawn on the same two lines the jacket
  panels' outer walls are on. Swapping between any of them moves nothing on a
  sheet already drawn.

  `electrical_heating` is the exception and says so: the element occupies the
  east shell wall across the shell's mid-height, so its `outlet` drops to the
  clear wall below rather than having its run drawn through the heater.

- Three more `Tank` variants, for the tanks that drain to a cone rather than to
  a floor: `conical_bottom` (flat roof), `conical_ends` (a cone at each end) and
  `dished_roof_conical_bottom`. The last takes `default`'s port map verbatim —
  the roof is the same arc over the same chord, so the `inlet` is on the same
  crown, and `outlet` resolves to the cone's apex where on `default` it resolved
  to the flat floor.

  All seven join the symbols ISO 15519-1 §11.4.2 forbids turning, taking the
  count to 41. The vessels for the family's own reason (a vent on the top head
  over a free surface), and the three cone-bottomed tanks for the fall into the
  cone, which is what the hopper-bottomed separators are already listed for:
  turned, the cone is a roof and the tank drains nowhere.

  Nothing already drawable changes. The regenerated symbol file is purely
  additive, 63 lines added and none removed, and no golden moves.

- Four `Separator` variants that separate **mechanically** rather than into
  phases: `sifter` (a screen deck), `impact` (a baffle), `permanent_magnet` and
  `electromagnetic`. All four are one hopper-bottomed body apart from the
  internal that names them, and all four join the symbols
  ISO 15519-1 §11.4.2 forbids turning, listed for the hopper rather than for
  what does the separating: a magnet sorts by magnetism, and what fixes its
  attitude is the fall into the hopper the artwork draws.
- `Separator`'s nozzles are per-variant, the way `HeatExchanger`'s already are,
  because those four cannot use the flash drum's. A sifter's two draws are size
  fractions and a magnetic separator's are a bulk stream and the tramp metal
  pulled out of it; neither is a vapour or a liquid. They carry `feed`,
  `overflow` and `underflow` in place of `feed` / `vapor` / `liquid`.

  The pair names the two *positions* the artwork has — the anchors are the draw
  high on the body wall and the draw on the hopper apex — rather than what
  arrives on them, on the same principle the exchanger's `shell`/`tube` nozzles
  follow, and it is the ordinary vocabulary of classification and solid-liquid
  separation. Neither name says which of the two is the product, because that is
  a fact about the service and not about the machine: the same screen is a
  scalping screen and a sizing screen depending on what is wanted out of it.

  Nothing already drawable changes. `Separator("V-101")` and all six of the
  other variants 0.1.0 shipped keep `feed` / `vapor` / `liquid`, in that order,
  with the same directions and roles, and no golden moves.


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
- Python 3.14 is supported and tested. The trove classifier is declared and
  CI runs the suite on 3.14 alongside 3.10 to 3.13. The floor is unchanged
  at 3.10: this widens the supported range at the top and nothing else. No
  package code had to change to get there, since `pandid/` imports only the
  standard library and none of what it imports is touched by 3.14's
  removals; the suite passes unchanged and no golden moves. The optional
  `pdf` extra installs on 3.14 too, as its own entry below records.

### Changed

- **`README.md` leads with `11_ethanol_pid`**, the P&ID, rather than
  `03_distillation_train`, and names what it shows: instrumentation, five
  control loops, hand-isolated valve stations, line numbers, a zone-ruled A3
  frame, a title block and a general-notes box. `10_ethanol_pfd` and
  `11_ethanol_pid` also gain goldens. They were the densest and most-shown
  sheets and the only two with no regression protection, so every change made to
  them went in unguarded; both fixtures come out byte for byte equal to what the
  example scripts draw, and reproduce under `PYTHONHASHSEED` 12345, 999 and
  4242.

- **`docs/gallery/` is regenerated, and a check now holds it to the examples.**
  ([#180](https://github.com/Alpha9463/pandid/issues/180))

  The gallery had drifted and nothing noticed: `04_control_loop.svg` sat on
  `main` through a dozen rendering PRs showing a sheet 526 units tall with an
  instrument panel on it and no LT-101, a drawing the package had stopped
  producing. Each of those PRs was right to defer the re-rasterise; what was
  missing was anything that saw it had not happened. All twelve sheets are
  rebuilt, `12_block_flow_diagram` joins the page, and `tests/test_gallery.py`
  renders every example and compares — the guard `_vendored_symbols.py` got in
  #150 and `docs/api.md` in #179, for the last generated artefact without one.

  `scripts/gallery.py` is the one command that rebuilds it. It imports each
  example with `Flowsheet.render` stubbed, so there is no output file to copy
  and no rename to get wrong, and it refuses to run unless `pandid` was imported
  from the checkout — `examples/_bootstrap.py` prepends the repo root only when
  `pandid` is not already importable, so on a machine with a release installed
  the examples otherwise render against *that*. It also fills a blank
  `TitleBlock.date` with the newest revision's date before rendering, so `03`
  and `08` no longer carry a date that moves every day.

  The PNGs are now 2400 px wide rather than 1600. The width is measured: in a
  crop of one title-block revision row's description cell, the darkest pixel of
  the 7,5-unit lettering runs 50–65 of 255 at 1600 px and 0–29 at 2400, and the
  inked fraction of the cell stops climbing there. Twelve rasters weigh 1,65 MiB
  at 2400 against 1,00 at 1600 and 2,15 at 3000.

- A spec may now name any of the new device classes (`kind: Cyclone`, or its
  snake_case spelling), and `to_dict()` can write one out — it could not before,
  since `pandid.spec` built its class table from `pandid.units` alone and
  refused anything else on the way out. The internal `kind` tag (`kind: pump`)
  still names the class that owns the whole kind, deliberately: fifteen device
  classes carry `kind == "pump"`, so folding both layers into that alias would
  have made `pump` mean whichever of them iterated last, and the answer would
  have moved about as classes were added. Arguments keyed to a class
  (`normal_position`, `fail`, `n_feeds`, `large_end`, …) are now matched by
  inheritance rather than by class name, so a `ControlValve` takes `fail:` for
  exactly the reason its base does.
  ([#146](https://github.com/Alpha9463/pandid/issues/146))

- `pip install 'pandid[pdf]'` now gives a working PDF and PNG export on a
  machine that has nothing else installed. It did not before: the extra pulled
  in cairosvg, which reaches libcairo through cairocffi, which `dlopen`s a
  shared library that no wheel on PyPI ships. The install therefore reported
  success and the first `fs.render("x.pdf")` died in the *import* with
  `OSError: no library called "cairo-2" was found`, unless the machine happened
  to have GTK or something else carrying cairo — which is why it worked on some
  developer machines and on no fresh one. On Windows the fix was a manual GTK
  install. ([#141](https://github.com/Alpha9463/pandid/issues/141))

  The extra is now svglib and ReportLab, which are pure Python, with pypdfium2
  rasterising the PDF for `.png`; pypdfium2 is tagged `py3-none-<platform>`, so
  it carries PDFium with it and needs no rebuild for a new interpreter. All four
  packages resolve to wheels on Windows, Linux and macOS for 3.10 through 3.14.

  Both formats survive, and the PDF is still vector: paths and real text, not a
  picture of the drawing. What changed is the typeface. cairosvg asked the
  system for `sans-serif` and got DejaVu Sans on a Linux box and Arial on a
  Windows one; ReportLab draws Helvetica from the PDF base 14, so the lettering
  is now the same everywhere and embeds no font. Geometry is unchanged: with
  every `<text>` removed, the new backend and cairosvg rasterise
  `04_control_loop`, `10_ethanol_pfd` and `11_ethanol_pid` to *pixel-identical*
  images.

  Getting there needed one thing on this side. svglib implements neither `<use>`
  of a `<symbol>` nor `marker-end`, and skips both silently: every unit came out
  at its intrinsic size instead of the size layout gave it, with its process
  lines stopping short of the nozzles, and every flow arrow on a PFD vanished.
  `pandid.render.export.flatten` resolves both into plain geometry before the
  backend sees the file, and refuses to export at all if the renderer ever emits
  some *other* construct the backend would quietly drop. The `.svg` output is
  untouched — flattening happens on the way to the PDF and nowhere else, and no
  golden moves.


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

### Fixed

- **A line number with no run beside the words now carries a leader to it.**
  ([#155](https://github.com/Alpha9463/pandid/issues/155))

  Label placement walked outward from the pipe — 10,5 units, then 23,5, then
  36,5 — until it found paper nothing else had claimed, and wrote the number
  there with nothing joining it to its line. On `11_ethanol_pid`,
  `AE-304-150-80-SS` ended up 1,6 units off D-301's shell and 27 below the lower
  end of the 30-unit stub it names, so it read as an annotation of the drum. The
  avoidance was working; the outcome defeated its purpose, and `validate()` had
  nothing to say about it.

  **ISO 15519-1 §7.2.5** is two *shall*s, and the second names the escape from
  the first: "They shall be oriented along or adjacent to the relevant
  connecting lines. If it is not possible to place the reference designation
  adjacent to the connecting line, it shall be shown elsewhere in the content
  area with a leader line to the actual connecting line." A number the first
  *shall* cannot be met for is now joined to its run by a leader.

  What decides it is whether the line is *there*, beside the words — not how far
  across the paper the number sits. A caption is attached by lying against the
  thing it captions, and a string that has run out past the end of its own line
  is lying against something else. So more than half the number must have its
  own run alongside it, measured against the whole straight length of that run
  rather than one drawn piece of it, since an in-line valve splits a run into
  three pieces and a reader sees one line. Of the 108 numbers on the twelve
  shipped sheets, three have their run beside less than the whole of them, and
  they part into two groups with a wide gap between: `3"-P-1005-A1A` on 09 at
  77 % and `FB-301-200-160-SS` on 11 at 74 % read as their own line's unaided;
  `AE-304-150-80-SS` at 32 % does not.

  The leader follows **§6.4**: it terminates "with an arrowhead if it ends on
  the outline of an object or a connection", it is drawn at the signal weight
  with a head to match, and it is **oblique**, which is what Figure 4 c) draws
  for this exact case and what keeps it from being read as a connection — §12.1
  holds pipelines, conductors and functional connections to horizontal or
  vertical, and a leader is none of those. The head lands on the run itself
  rather than at either end of it, since a run's ends are where it meets the
  equipment it serves.

  A leader is new ink, so it is scored like the label. Its tail is swept along
  the near face of the halo, inset from the corners by half the halo's own
  thickness, and scored on what it cuts, then how near 45° it lands, then how
  near the middle of the words it starts — a halo is measured at 6,2 per
  character plus padding, which over-measures a string as hyphen-heavy as a line
  number, so a tail fired from a bare corner would not touch the words it is
  there to attach. If the leader would run through the vessel the label stepped
  around, the search takes a different spot instead, and the leader is then
  seeded as occupied like everything else, so no later halo deletes the one mark
  saying which line the number belongs to.

  `tests/test_label_invariants.py` pins the property nothing asserted:
  **a line number is written along the line it names, or carries a leader to
  it**, read back off the drawn SVG over the golden corpus, both ethanol sheets
  and a fixture built to need a leader whatever happens to the shipped ones.

  One leader is drawn, on `11_ethanol_pid`. No other sheet carries one and none
  moves for this.

- **A label's halo no longer paints out the symbol underneath it.**

  Every tag and every line number is written on an opaque white plate, emitted
  after the artwork, so wherever it lands it deletes what was there. Neither
  placement pass had ever been told a graphical symbol was on the paper: the
  equipment tag stepped clear of pipe and impulse lines, the line number stepped
  clear of those and of the tags, and a balloon or a square was invisible to
  both. On `11_ethanol_pid`, the sheet the README leads with, D-301's tag ate a
  quadrant of LT-304's balloon and broke its circle in two places, and
  HV-301C's ate the left edge of PIC-301's square. The whole suite passed.

  A symbol is not a worse kind of line. A line broken by a halo is still that
  line and a reader reads across the gap, which is the whole reason writing a
  number *in* its run is a convention; a symbol broken by a halo has stopped
  being the symbol, since its outline is what identifies it. So both passes are
  given the symbols, and both **rank** a symbol above everything else they
  weigh rather than counting it as one more box. Ranking rather than counting is
  what stops the fix from moving the defect: with symbols merely counted,
  D-301's tag stepped off LT-304 onto the one clear strip of paper in that
  corner and displaced `AE-304-150-80-SS` into a stripe through C-301's tube
  bundle.

  That left `AE-304` with no clear spot among its 276 candidates, so the search
  may now walk one band further out, six to seven. It is a bound and not a
  judgement — a clear band wins outright and the bands are walked inward-out —
  and seven is where the answer settles rather than where it first appears,
  since at 8, 10 and 12 that label lands in the same place.

  `tests/test_halo_invariants.py` states the invariant over the whole corpus and
  fails on both of the original defects. Two tags and one line number move on
  `11_ethanol_pid`; no other sheet moves.

- **`examples/12_block_flow_diagram`'s ammonia recycle runs under the row.** It
  left Refrigeration's west face at mid-height, dropped, ran left and came back
  into the Synthesis Loop's south face straight across the purge, needing a line
  hop to say so. A BFD runs a recycle one below the row, from the section that
  produces it to the section that takes it, crossing nothing. One declaration
  changes, `outputs=["E", "W"]` to `["E", "S"]`, and the purge flag moves into
  the gap between the last two boxes: crossings 1 → 0, hop arcs 1 → 0, measured
  segment against segment.

- **`examples/11_ethanol_pid` letters its trips `Z`, not `I`.** ISO 15519-2
  Table 2 gives `Z` for switching, open-loop, safety or protection relevant, and
  `I` for *indicating*, the one thing a trip does not do. Table 2 note 9 is the
  other half: an alarm that acts is `S` or `Z` and does not additionally take
  `A`. The high and low alarms are placed to §5.1.3 Figure 8's quadrants, and
  `PT-318` is a second transmitter on its own tap, so the trip reads a
  measurement independent of the pressure loop and one safety function is drawn
  end to end. The sheet's general notes are rewritten to match. Lettering only:
  a diamond is drawn with its number and never its letters, so no sheet moves.

- **`examples/03_distillation_train` pipes its overheads the way the reference
  sheets pipe theirs.** ([#186](https://github.com/Alpha9463/pandid/issues/186))

  The overhead vapour ran into each condenser's *tube* side. Both reference PFDs
  put cooling water straight across the tubes of all three of their condensers
  and take the vapour up through the shell, which is the fouling rule reaching
  the other answer: the stream that scales goes tube side where a bundle can be
  rodded out, and under a total condenser that is the water, not the process.
  `06_column_reflux` and `10_ethanol_pfd` were already drawn so; only this sheet
  was not, and its comment argued the wrong hand. `E-101` and `E-201` now take
  `shell_in`/`shell_out`, stand on their own towers' axes and are flipped top to
  bottom, so each overhead rises into the underside of its condenser dead
  straight rather than turning into a side nozzle, and the condensate leaves the
  crown, runs over the top and drops onto the drum.

  `V-101` and `V-201` are raised 30 units. A reflux drum feeds reflux *and*
  distillate on the head beneath it, which is why no reference sheet pumps one
  and the P&ID of this same service draws both legs off the one draw through
  control valves and nothing else; drawn low, that head is drawn away. It left
  the take-off no room either: 22 units of draw between the drum and a `Tee`,
  and a `Tee` draws the junction and no symbol, so the pipe either side of it is
  all that says one is there. At 52 the draw runs longer than the drum is tall
  and the reflux parts from the distillate clear of the drum's underside. No
  stream is added, so the table stays 21 columns wide.

- **`examples/03_distillation_train` draws its towers as columns.** `T-100` and
  `T-200` each had a single overhead product, no reflux drum, no reboiler and no
  internal returns, and two towers arranged that way are not columns. Both now
  carry what `06_column_reflux` and `10_ethanol_pfd` already draw: the overhead
  rises into its condenser, which drains into a reflux drum (`V-101` / `V-201`)
  whose single draw parts at a `Tee` into reflux and distillate, and the sump
  drains into a kettle reboiler (`E-102` / `E-202`) whose boilup returns to the
  tower, so `P-100A/B` takes the *net* bottoms. Both loops close on the column
  through `reflux_in` and `boilup_in`, so neither is modelled as a recycle. A
  `Tee` rather than a `Splitter` at the reflux parting, for the reason
  `10_ethanol_pfd` has one there: a junction in the piping is not an item
  somebody buys. This is the largest sheet movement in the release.

- **A flipped condenser no longer reverses its heat-flow arrow.**
  ([#155](https://github.com/Alpha9463/pandid/issues/155))

  draw.io's `Heater` and `Condenser` are one stencil pair: the same circle, the
  same zigzag, the same diagonal, and *only* which end of that diagonal wears
  the arrowhead tells the two apart. `examples/10_ethanol_pfd` pins its
  condenser `mirrored="y"` for a nozzle reason — so the tower overhead rises
  into the shell inlet dead straight — and the flip put the head at the far end.
  `E-201` on `05_reactor_recycle`, the same stencil unflipped, pointed up and
  to the right; `E-301` pointed down and to the right. One drawing, two opposite
  statements about which way the heat goes. The flip also landed the duty
  arrowhead about 15 units from the process inlet's arrowhead, so the two read
  as competing process connections into one corner.

  Not fixed by refusing the flip. **ISO 15519-1 §11.4.2** permits mirroring
  outright — it excepts *turning* only, and only for symbols where gravity is a
  functionality — and what a reader asks for by flipping a condenser is its
  nozzles on the other side. So `Symbol.directional` marks the drawing and the
  renderer holds it still under the flip while the nozzles still move: the flip
  is undone inside the `<defs>` entry and the `<use>` reapplies it, which is
  exactly what `svg.py::_upright_text` already does to keep a symbol's own
  lettering readable. The two cancel exactly, because an axis flip commutes with
  the per-axis scaling that fits the artwork into its box.

  **Which placements reverse a mark, and which carry it**, is `_reflections`'
  answer, and it is *not* "mirrors reverse, turns carry":

  | placement | the mark |
  |---|---|
  | `mirrored="x"` / `"y"` / `"xy"` | reversed — undone |
  | `orientation=180` | reversed — undone. A half turn **is** `mirrored="xy"`, the two flips composed, and it lands the head exactly where the sibling symbol draws it |
  | `orientation=90` / `270` | carried — left alone. A quarter turn puts the head on the *other* diagonal, which no upright drawing of either symbol occupies, and turns the box with it |

  A quarter turn with a mirror on it still has its mirror half undone. That
  split is also the arithmetic one: an axis flip cancels exactly inside the
  definition, a quarter turn cannot on a box that is not square. So a
  directional symbol takes four `<defs>` entries across all sixteen placements.

  Three symbols are marked — `heater/default`, `cooler/default` and
  `hex/condenser`, which is the same drawing as the cooler — with the reasons
  recorded beside `DIRECTIONAL` in `scripts/vendor_symbols.py`, next to the
  `GRAVITY_FIXED` table it is modelled on. Declaring it asks two things of the
  artwork. It decouples the ink from the nozzles, so every port has to stay on
  drawn ink under any flip; and the whole drawing is held still, so it must
  carry no lettering of its own, which the generator refuses and the invariant
  suite checks. `test_a_directional_symbols_arrow_survives_every_placement`
  sweeps all sixteen placements, since both halves of this defect shipped for
  the same reason — nothing on any sheet placed a directional symbol that way.

  **No golden moves**, because no golden scenario flips one; `10_ethanol_pfd`
  changes by two lines of SVG, the definition and the `<use>` that names it, and
  nothing on the sheet is repositioned. `docs/gallery/` is deliberately not
  regenerated.

- **An instrument's link is drawn as the line it is, not as the class of what it
  hangs on.** ([#155](https://github.com/Alpha9463/pandid/issues/155))

  `_draw_taps` chose solid when the host was a unit and dashed when it was a
  balloon, which answers a question about the *host* and draws the answer as
  though it were about the line. On `11_ethanol_pid` the trip square hung on the
  feed's solenoid valve came out **solid** while four identical squares hung on
  balloons and signal lines came out dashed: one logic function, drawn as
  impulse tubing in one place and as a signal in four. On `07_metering_skid` and
  `08_from_data` a control-room controller declared `on` a vessel *for
  placement* was drawn as a length of pipe running from the drum to a DCS
  faceplate.

  The style is a statement about the line, so both its ends are now asked, and
  it is solid only where both answer. An impulse line is a piece of pipe: it
  needs process fluid at one end — a process stream or a unit that is not itself
  a balloon — and a device out in the plant at the other. Only ISA-5.1's bare
  circle is that device. Every other balloon is a location or function symbol
  saying the function is in a panel, in the shared display, in a computer or in
  a logic solver, and no tubing runs from a drum to any of those.

  It subsumes rather than extends the signal-line case added in #171: a tap teed
  off a signal line is dashed because a signal line holds a command, which is
  the same half of the same rule.

  **Two goldens move**, by one attribute on one line each and nothing else:
  `07` and `08`, both of them the panel controller above. Every process tap on
  every sheet stays solid — including `04`'s `LT-101` and `08`'s `LT-201`, the
  two field transmitters that really are piped to their drum. `docs/gallery/` is
  deliberately not regenerated.

- **Examples 04 and 11 stopped drawing loops the standards forbid.** `04`'s
  level loop had no transmitter: `V-101` ran a solid process impulse line
  straight into `LIC-101`, drawing a control-room faceplate with a process tap
  of its own, and with no measurement signal in the loop the interlock had to
  tee off the controller's *output*. `LT-101` now stands between them and the
  trip tees off that measurement, which is what ISO 15519-2 Figure 17 b) draws.
  Both files drew controllers as bare `variant="panel"` circles — a circle on
  its own has no controlling function — and use `variant="shared"` now. `11`'s
  alarms were chained controller → high → low → SIS, against ISO 15519-2 §6.2,
  §7.2.4 and Table 2 note 9; both pairs now fan off their controller onto faces
  of their own, every one a dead end, and both SIS squares sit on a measurement
  signal line. `LIC-304` moves off its row onto the valve it strokes, a fourth
  face not fitting under the cooling-water return. Eight of 123 resolved
  entries change on `11` and 7 of 22 on `04`; `validate()` is clean on both,
  before and after.

- **An instrument's impulse line is orthogonal, and a test says so.** Three
  shipped taps were drawn on the diagonal.
  ([#155](https://github.com/Alpha9463/pandid/issues/155))

  **ISO 15519-1 §12.1**: *"Connecting lines shall be oriented horizontally or
  vertically, except in those cases where oblique lines improve the clarity of
  the diagram"*, and **§12.4**: *"Joining of connecting lines shall be shown
  meeting or intersecting at right angles"* — no exception clause on the second.
  §12.1 names *"conductors, functional connections"* alongside pipelines,
  **ISO 15519-2 §6.1** puts Part 1's rules in force on a P&ID and its **§5.1.1**
  calls an instrument's process tap a *"functional connection line"*, so the rule
  is the tap's and not only the pipe's. The issued reference sheet
  `professional_examples/P&ID_301.pdf` draws 47 dashed signal segments, every one
  exactly horizontal or vertical.

  `test_nothing_is_drawn_diagonally` had asserted this over `fs.streams` since
  #71, and its module docstring said outright that it *"knows nothing about
  instrument attachment, which is the point"*. A tap is drawn by
  `SvgRenderer._draw_taps` and not by the stream pass, so the one line on the
  sheet that says *where* an instrument measures was the one exempt from the
  rule the file is named for. It now sweeps `_tap_lines` as well — the
  renderer's own answer to which taps are drawn at all — and went red on four
  sloping taps: `04_control_loop`'s `LAH-101` and `LAL-101` (`angle=62`/`118`),
  `11_ethanol_pid`'s `PI-315` (`angle=45`), and the `PIC-101` of this file's own
  synthetic fixture.

  The `angle=` default is already 90, straight out of the face, so all four were
  author choices and all four are re-routed rather than exempted. Example 04's
  level cluster is the one that moves visibly: the controller's own impulse line
  arrives at its north face and its output leaves to the east, so a balloon on
  that east face has its tap drawn under the output for the 41px to the output's
  first corner. The two faces left take the high alarm (west) and the low alarm
  (south), and the interlock square takes **no face at all** — it is teed off the
  `LIC-101` → `LV-101` signal line, which is what all four trips on the issued
  sheet do. Every fine line around `LIC-101` now leaves a balloon radially and
  lands square on the next, and the sheet grows 36px taller.

  `11_ethanol_pid`'s `PI-315` reads the tower's feed nozzle, and a unit host taps
  a *face midpoint*: the feed enters the middle of the west wall, so that midpoint
  is the nozzle, and every orthogonal branch off it either runs down the feed line
  or straddles the shell. The tap moves the few pixels back onto the run it
  measures and the gauge stands over it, which is how `FI-314` beside it is
  already drawn. One golden moves, `04_control_loop.svg`, by three tap lines,
  three balloon placements and the canvas height, and by nothing else.

  `_draw_taps` emits a single `<line>` and has no waypoint, so a balloon that is
  not on its tap's own row or column *cannot* be drawn orthogonally, which is
  what forced both of those re-placements. Filed as
  [#170](https://github.com/Alpha9463/pandid/issues/170), with the related
  observation that `_ink` already mis-models a sloping tap as an axis-aligned bar.

- **A balloon teed off a signal line is drawn dashed**, not solid.

  `_draw_taps` chose its dash by `u.host.kind == "instrument"`. A `Stream` host
  answers that with its *stream* kind — `"electric"`, `"material"` — so a balloon
  hung on a signal line fell through to the solid branch and was drawn as a
  process impulse line: tubing on a pipe, which is the wrong statement about the
  wrong medium. It now dashes for `"instrument"` and for any
  `pandid.streams.SIGNAL_KINDS` host, and a tap on the process stays solid.

  Nothing shipped hung a balloon on a signal line, so no existing golden moves;
  the fixture that keeps this covered is example 04's interlock, which is teed
  off `LIC-101`'s output as of the entry above. Hanging it on an alarm instead
  would draw the alarm as driving it, and an alarm that acts is lettered `S` or
  `Z` rather than `A` — **ISO 15519-2 Table 2** note 9: *"Shall only be used for
  separate alarm control functions. If control functions S and Z at time of
  action also trigger an alarm/message, then the A shall not be used in addition
  to the in front letter codes S or Z."* **§7.2.4** is the same rule from the
  line's end: *"Signal lines for different types of control functions should not
  be joined."* Every alarm balloon on `professional_examples/P&ID_301.pdf` is a
  dead end on all four faces, and every trip on it tees off a signal line.

- The four symbol families the generator *reproportions* are drawn with a pen
  centred on the sheet's line weight, instead of one exact along a single axis
  and adrift along the other.
  ([#158](https://github.com/Alpha9463/pandid/issues/158))

  `scripts/vendor_symbols.py` compensates a symbol's line weights once, for the
  scale its artwork is drawn at, by baking a heavier `stroke-width` inside the
  scale group it wraps that artwork in. The divisor was `sx` — a single axis.
  For the 138 families whose `SCALE` entry is a uniform factor there is nothing
  to choose between the two and it was right. For the four whose entry is an
  uneven `(sx, sy)` pair it drew a slightly elliptical pen at **every** box,
  including the symbol's own: `vessel/default` and `separator/default`
  `(0.62, 0.5)` put their shell walls on 2.0 and their heads on 1.61,
  `valve/butterfly_pneumatic` `(24.5/60, 15.0/40)` on 2.0 and 1.84, and
  `column/packed` `(62/14, 200/97)` on 2.0 and 0.93 — the packed tower's bed
  grids and packing at under half the weight of the shell they sit in.

  It is the geometric mean `sqrt(sx*sy)` now, which is what #153 arrived at for
  the same problem one level down, at the placement, and is stated here in the
  same terms rather than as a second vocabulary for one idea: a single
  `stroke-width` cannot express a direction-dependent pen without moving
  geometry, so hold the pen's *area* and split what is left evenly either side
  of the sheet weight. It is exact the moment the two axes agree, which is why
  the other 138 families come out byte-identical.

  What moves is four `stroke-width` values: 3.226 → 3.592 on the vessel and the
  flash drum, 4.898 → 5.111 on the pneumatic butterfly valve, 0.452 → 0.662 on
  the packed tower. Drawn, that is a vessel's walls going 2.00 → 2.23 and its
  heads 1.61 → 1.80, and the packed tower's shell walls 2.00 → 2.93 with its
  grids 0.93 → 1.36. The tower is the one visible change and the one whose axes
  were furthest apart; its worst stroke goes from 2.15x off the sheet weight to
  1.47x, and it is the shell walls that now carry part of the error rather than
  the internals carrying all of it. Five golden sheets move by one
  `stroke-width` value each and by nothing else: blanking every `stroke-width`
  leaves all nine byte-identical to their predecessors, so no geometry, port,
  canvas dimension, label or route moved.

  `tests/test_line_weight.py` gains the check that says so, over every symbol in
  the registry, hand-drawn and vendored alike: the outline pen a definition
  declares has the sheet's line weight as its geometric mean. Nothing already
  there could see this, because every other check in that file measures a
  placement against the definition it draws from, and both sides of that
  comparison come from the same symbol.

- Lettering in the `.pdf` and `.png` exports is drawn at the size the sheet sets
  it in. It came out at three quarters of that. svglib converts a length to
  points twice on the way to a glyph and once on the way to a line: it
  multiplies `font-size` by the 0.75 of px to pt to set the drawn size, and then
  scales the group holding the whole drawing by that same 0.75 to take user
  units to the page's points, so a string is drawn inside a transform that has
  already made the conversion its own size carries. Geometry took the factor
  once and landed right. Measured against a rule of the same declared length in
  the same document, a 100-unit capital drew a cap height 0.752 of the 0.718 em
  Helvetica declares while the rule drew 1.000 of its length — that is every
  stream number, line number, balloon tag, equipment tag, title-block row,
  legend entry and note on every exported sheet, three-quarter size. It arrived
  with the backend change above and was missed for the reason the centring below
  was: the fidelity comparison that vetted that change stripped `<text>` before
  comparing.

  `pandid.render.export` corrects it on the ReportLab drawing, after svglib has
  built it and before the page is written, so nothing but the type size moves
  and the geometry svglib gets right is not touched. The correction is
  *measured* rather than written down: a probe declaring a square and a capital
  at one size states what the backend draws a glyph at against what it draws a
  line of the same length at, and the ratio between the two is applied to every
  string. On an svglib that has stopped converting twice it reads 1.0 and
  nothing is applied.

  Nothing collides at true size, because the room was always reserved for it:
  the layout engine and the title block measure text at its declared size, and
  the `.svg` has always drawn it there. On `11_ethanol_pid` no two labels' ink
  boxes touch, every haloed label is still inside its own halo, and the tightest
  balloon tag clears the circle by 4.5 units. The vertical centring below
  composes with this — its shift is a fraction of the font size, and the font
  size is now the one the file states — and its residual, the gap between the
  x-height middle `middle` names and the middle of an all-capitals ink box, is
  now the full 0.1 em it is in a browser instead of three quarters of it.

  The `.svg` output is untouched and no golden moves.

- Lettering the renderer centres vertically is centred in the `.pdf` and `.png`
  exports too. svglib maps `text-anchor` and nothing else about how a string
  sets: `dominant-baseline` appears nowhere in it, so every `<text>` was drawn
  with its *alphabetic baseline* on the `y` it was given, and anything centred
  on a point came out about a quarter of its type size above that point. That is
  every stream number, both lines inside every instrument balloon, and every
  equipment tag not set above its unit — each of them struck on a white halo
  drawn round the same centre, so the halo and the lettering in it came apart.
  Measured on the raster, a stream number sat 2.7 px high in a 13 px halo, half
  the height of its own ink; in a balloon the tag and loop number rode up
  against the top of the circle with the gap below them. This arrived with the
  backend change above and was missed because the fidelity comparison that
  vetted it stripped `<text>` before comparing.

  `pandid.render.export.flatten`, which exists to resolve exactly this — it
  already stands in for the `<use>` and `marker-end` the backend drops — now
  resolves the alignment as well, working the offset out from the drawing face's
  own ascent and descent (ReportLab's, which are the metrics the backend letters
  with) and folding it into the text's `y`, so what svglib is handed is the
  plain baseline it does read. Because the shift is a fraction of the font size
  it is written in the same units as the text it moves, and a symbol's own
  lettering is shifted by the placement that scales the symbol.

  The values the renderer emits are `middle`, on everything it centres, and
  `baseline`, on a label set above a unit, whose `y` is a baseline already;
  `auto`, `alphabetic` and `central` resolve alongside them. Any other value —
  `hanging` is the likeliest — is refused rather than placed on a guess, the way
  an unsupported construct already is, since a browser reads that one out of a
  font's own baseline table and ReportLab's base-14 metrics do not carry it.

  The `.svg` output is untouched and no golden moves: the SVG was right, and
  this is what makes the exports agree with it.

- A unit given a `width`/`height` of its own is drawn at the sheet's line
  weight. It was not, and the error was the whole of the resize: a symbol's
  weights are compensated once, at generation time, for the scale its artwork is
  drawn at — `scripts/vendor_symbols.py` bakes `2/sx` inside the scale group, so
  a valve's `8.0` lands on `2.0` under `scale(0.25)` — and the `<use>` then
  scales the `<symbol>`'s viewport, ink and all, with nothing scaling it back.
  The `90 × 140` surge vessel of `examples/07` and `09` drew its shell at `2.9`,
  `08`'s `150 × 48` reflux drum at `3.28`, and the `40 × 68` relief valve fixed
  in [#152](https://github.com/Alpha9463/pandid/issues/152) at `5.8`, where it
  merged into a blob. Every other line on those sheets is drawn at `2.0`.
  ([#153](https://github.com/Alpha9463/pandid/issues/153))

  A placement that resizes its symbol now gets a `<defs>` entry of its own, with
  every weight in it divided by the scale the box applies — the same arrangement
  a built-to-measure symbol already had, and it costs one entry per *resized*
  unit, 28 bytes across the nine golden sheets. Nothing else about the drawing
  moves: goldens 06, 07, 08 and 09 differ from their predecessors in symbol ids
  and `stroke-width` values and in nothing else, and a unit left to size itself
  renders byte-identically.

  A box that also *reshapes* the artwork is corrected as far as SVG allows.
  Stroking sweeps a circular pen, a viewport that scales the axes differently
  sweeps an elliptical one, and no `stroke-width` — one number — can undo a
  weight that depends on the direction the line runs in. The compensation is
  therefore the geometric mean, which holds the pen's area to the circle's and
  is exact the moment the two axes agree; what is left is the aspect change the
  box itself asked for, which on the sheets above is under 4%, and
  `tests/test_line_weight.py` bounds it there.

- The three valve symbols drawn off `valves.xml`'s own module come out at the
  size the rest of the family is drawn at. `SCALE["valve"] = 0.25` is calibrated
  to that file's ~98-unit module — it is what puts a Gate Valve's `98 × 60`
  bowtie in the `24.5 × 15.0` box the reference sheet is cut to — and three
  shapes are not on it, with nothing making up the difference. `valve`/`psv`
  shipped `13.9 × 23.6`, `valve`/`relief` `10.0 × 14.8` and
  `valve`/`butterfly_pneumatic` `15.0 × 20.0`: 57%, 41% and 61% of a gate
  valve's length. A PSV's spring hatching closed into a solid wedge, a relief
  PRV's bonnet into a dot, and the butterfly carried its run 5.0 above the
  bottom of its box where every other straight-through valve carries it at 7.5.
  This has been so since 0.1.0 and is not a regression.

  What the family is drawn to is not its box — these are upright devices, and
  the box holds whatever rides above the body — it is the *seat*. Every valve
  body in `valves.xml` is the same pair of triangles, 60 across the run under a
  49 apex, drawn `15.0 × 12.25` at 0.25; Gate Valve sets them base to base and
  Angle folds them into an L, both at that one factor. Each of the three now
  takes a factor that puts its own body on that: `15.0/42` → `19.8 × 33.8` for
  the PSV, whose lower `19.8 × 19.8` is `valve`/`angle`'s box exactly, with the
  spring bonnet above it; `15.0/40` → `15.0 × 22.1` for the relief PRV;
  `(24.5/60, 15.0/40)` → `24.5 × 30.0` for the butterfly, a `24.5 × 15.0` body
  with its run back on 7.5.

  A sheet that sized its PSV by hand to compensate should drop the override:
  `examples/07_metering_skid.py` and `examples/09_line_numbers.py` did, and
  their `width=40, height=68` is gone. Goldens 04, 07 and 09 move, and the
  gallery images with them; nothing in any of them changes but the two symbol
  definitions, the two placements, and the lines and labels that follow them.

- Curved equipment heads are drawn on the ellipse the stencil asked for. The
  stencil converter splits an arc whose chord is about its own diameter into
  quarter-turn pieces, because cairosvg strokes such an arc visibly thick. It
  cut those pieces on the ellipse the SVG spec's radius correction gives
  (§F.6.6: radii too small to span their chord are scaled up until they exactly
  span it) but labelled each piece with the stencil's *uncorrected* radii, so
  every piece was too small for its own, shorter chord and the reader corrected
  it a second time — separately, against a different chord, onto a different
  ellipse per piece.

  The endpoints were computed from the true ellipse and stayed exact, which is
  why this was only ever a curve defect: no nozzle, box or canvas dimension is
  affected, and none moves here. Seventeen symbols are redrawn — `hex`/`kettle`,
  `hex`/`hairpin`, `hex`/`u_tube`, `column`/`packed`, `reactor`/`default`,
  `reactor`/`plain`, `separator`/`horizontal`, `separator`/`knockout`,
  `vessel`/`horizontal` and the eight dished-end `vessel` variants. On the
  40-wide vessel shells the two halves of a dished head met in a visible cusp
  instead of a crown; on the rest the head was drawn shallower than the stencil
  drew it. The `50 × 15` "Pressurized Vessel" family (`vessel`/`default`,
  `column`/`default`, `separator`/`default`) and every `tank` variant already
  spanned their chords and are byte-identical.

  Goldens 01, 05, 06 and 08 move, and gallery images 01, 05, 06, 08, 10 and 11
  with them. Every changed line is an `A` command's two radii inside a `<defs>`
  `<symbol>`; nothing else in any of them differs.


- A label's opaque halo no longer deletes a line that is not its own. Every
  label is written on a white rect and drawn after the lines, so one in the
  wrong place does not sit *over* a line, it erases a length of it and the sheet
  then says the run stops there. Placement seeded the symbols and the equipment
  tags as occupied and **not one routed segment**, so a line number parked beside
  its own run cut whatever pipe passed behind it, and an equipment tag, which is
  drawn last of everything, cut the impulse line running from a tap to the
  balloon reading it. Both now dodge the ink: every routed segment and every
  impulse line is seeded, padded by a stroke width so a halo cannot shave a line
  it merely touches, and the one line a halo may still cover is the run whose
  number is written in it, a break in the line being the convention that puts it
  there (ISO 15519-1 §7.2.5). Where a sheet leaves nothing clear, the least
  damaging spot wins rather than whichever the search reached first, and because
  the spots on the line come first, that makes the label's own run the last
  resort instead of a neighbour's. An equipment tag steps *along* its face
  first, the move the `NC` and fail-position letters already make around it, and
  only then tries another free face; it gives way to an impulse line before a
  pipe, since the impulse line is the only mark saying where a transmitter
  measures. Four line numbers and one tag move on example 11, and one tag each
  on 04 (two, with `FE-101`), 06 and 07, along with the goldens and gallery
  images for those. `tests/test_render.py` pins the invariant over every sheet
  the repo ships: no halo covers a line that is not the run it names.
- A `Column`'s feed family is centred between its two duty arrows, so every feed
  lands on the trayed section however many there are. It was centred on 130 in
  the tower's 200-unit shell and spread over half of it, while the band it was
  documented to stay inside is 65..145: the second feed of two came out at 147.5,
  past `reboiler_duty`, the third of three at 165, and the fourth of four at 180,
  below `boilup_in`. It is now centred on 105, the middle of that band, and
  spread over 0.35 of the shell (70 units, two 35-unit pitches), which leaves the
  outermost feeds on 70 and 140 with 5 units clear of each arrow. Both column
  variants had it, `packed` restating the same numbers in its own 97-unit shell,
  and both are fixed. One, two or three feeds keep the declared 35 pitch; a
  fourth is where the run is squeezed into the band instead of running off it.
  The single-feed nozzle moves 25 up as a result, so examples 03, 06, 10 and 11
  move with it, along with the goldens for 03 and 06. `T-301`'s local pressure
  gauge in 11 is branched off its west wall at 45 rather than square, since the
  middle of that wall is now the feed.
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

[0.1.1]: https://github.com/Alpha9463/pandid/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

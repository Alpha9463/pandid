# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Changed

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

### Fixed

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
  feed's solenoid valve came out **solid** while three identical squares hung on
  balloons came out dashed: one logic function, drawn as impulse tubing in one
  place and as a signal in three. On `08_from_data`, `04_control_loop` and
  `07_metering_skid` a control-room controller declared `on` a vessel *for
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

  **Three goldens move**, by one attribute on one line each and nothing else:
  `04`, `07` and `08`, all of them the panel controller above. Every process tap
  on every sheet stays solid. `docs/gallery/` is deliberately not regenerated.

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

### Added

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
- Python 3.14 is supported and tested. The trove classifier is declared and
  CI runs the suite on 3.14 alongside 3.10 to 3.13. The floor is unchanged
  at 3.10: this widens the supported range at the top and nothing else. No
  package code had to change to get there, since `pandid/` imports only the
  standard library and none of what it imports is touched by 3.14's
  removals; the suite passes unchanged and no golden moves. The optional
  `pdf` extra works on 3.14 too, `cairosvg` and its C-extension dependency
  `cffi` both resolving to wheels rather than a source build.

### Fixed

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

[0.1.0]: https://github.com/Alpha9463/pandid/releases/tag/v0.1.0

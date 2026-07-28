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
  same flowsheet, one stream per port, and signal against process. A port whose
  role is `signal` (`Valve.actuator`, `Instrument.pv` / `sig_in` / `sig_out`)
  joins another signal connection and takes a signal `kind`; a process nozzle
  joins another process nozzle and takes `material` or `energy`. Neither pairing
  is drawable as the other, so a pipe into a valve stem and a pneumatic line
  between two pumps are both rejected by name.
- Heat-exchanger nozzles name the *side of the equipment* rather than the duty:
  `shell_in`, `shell_out`, `tube_in`, `tube_out` in place of `hot_in`,
  `hot_out`, `cold_in`, `cold_out`. Which fluid runs in the shell and which in
  the tubes is a design decision the drawing has to record, while which side is
  hot inverts between operating cases without the nozzle moving — and the old
  names did not even land on the same face from one variant to the next.
  Variants with no shell or no tubes name what they do have: `air_cooled` is
  `tube_*` and `air_*`, `plate` and `spiral` letter their two interchangeable
  circuits `side_a_*` / `side_b_*`, and `thin_film` is `jacket_*` and
  `product_*`. `Heater` and `Cooler` take `utility_in` / `utility_out` in place
  of `duty` on the same principle. Nothing is published, so the old names are
  removed rather than aliased; a unit that names one raises the existing "no
  attribute or port" error, which lists the real ports.
- Two exchanger symbols had their sides mapped wrongly and are corrected with
  the rename. `u_tube` put one tube nozzle on the shell's far dished head; a
  U-tube bundle turns round inside the shell, so both tube connections now sit
  on the channel head, one either side of the pass partition the stencil draws.
  `plate` paired each circuit along one edge of the symbol, across the two
  diagonals the stencil draws; each side now follows the diagonal it is drawn
  on. No other port moved.
- Typed `Unit` classes declaring named ports: `Feed`, `Product`, `Pump`,
  `Compressor`, `Blower`, `Valve`, `Vessel`, `Tank`, `HeatExchanger`, `Heater`,
  `Cooler`, `Reactor`, `Separator`, `Column`, `Mixer`, `Splitter`, `Tee`,
  `Reducer`, `Fitting`, `Ejector`, `Vent`, `Funnel`, `Furnace`, `Turbine`,
  `Filter`, `Dryer`, `Conveyor` and `Instrument`. Ports are reachable both as
  `unit.ports[name]` and as attributes (`pump.suction`), and a typo raises an
  error naming the real ports.
- Custom equipment. A `Unit` subclass declaring its own `kind` and `PORTS`, with
  a `Symbol` registered under that kind, is validated, laid out, routed and drawn
  like a shipped class, and draws a generic box where no symbol is registered.
  The declaration is `PORTS`: it was `_PORTS`, whose underscore said "private"
  about the one attribute a unit type of your own has to set. `docs/api.md`
  documents the workflow (ports, symbol coordinates, the rule that a port must
  land on drawn ink, and `variant=`), and `tests/test_custom_units.py` runs it
  end to end, so the page cannot drift from the engine. The spec layer is the
  one thing custom equipment does not reach: `pandid.spec` builds units from the
  shipped classes by name, so `to_dict()` raises `SpecError` naming the class
  rather than writing a spec that cannot be read back, and a `kind:` naming a
  custom class is refused the same way.
- `Feed(header=True)` / `Product(header=True)`, the utility header flag. A
  boundary flag is an off-page connector rather than a piece of plant, and a
  header — cooling water, steam, flare, plant air — is a service tapped wherever
  it is wanted and labelled the same way at every tap. The reference sheet this
  project reproduces brings cooling water on twice and sends it back twice, all
  four flags reading `CWSH` / `CWRH`. `add()` accepts such a repeat and gives it
  a name of its own (`CWSH`, `CWSH (2)`), exactly as it does an interlock
  square, so each tap is still one unit for a stream endpoint or a spec entry to
  address while the flag drawn stays `CWSH`. Both taps are drawn at the same
  size, get their own stream and line numbers, and the pair is written to a spec
  and read back as the same two taps.
  - Opt-in, because two flags accidentally sharing a name are two services the
    reader cannot tell apart, and only the author knows which case it is. A flag
    without the word still raises, as does equipment, and both drawings have to
    be of the same thing: a `Feed` and a `Product` under one label, or two flags
    naming different `reference` drawings, clash.
- `Conveyor(length=…)`, a belt conveyor drawn to the length the drawing gives
  it. The symbol is built to the belt run rather than scaled to it, so a longer
  conveyor grows only the straight bar between its two rollers and the rollers
  stay the same circles at every length. `length` is its whole size and its only
  one: `width=` and `height=` would set the drawn box independently and stretch
  the rollers, so they are refused and name `length` in their place, and a
  quarter turn makes the length the unit's height. `feed` is the tail end, also
  offered on the top face, since material is dropped onto a belt rather than
  piped into it; `discharge` is the head end, also offered underneath. Below two
  roller diameters the rollers overlap, which is refused with the minimum in the
  message. It is scheduled on the equipment list like other major plant.
- `Valve(normal_position="closed")`, the normally closed valve, drawn with its
  body darkened solid. The source is **PIP PIC001 clause 4.2.2.7**: "normally
  closed manual valves shall be shown using a darkened solid symbol". It is
  **not** an ISA-5.1 or ISO 10628 convention. ISA-5.1 says nothing about valve
  fill and hands manual block valve depiction to the piping group, and ISO 10628
  has no such symbol. Because it is an extension rather than a standard symbol,
  ISA-5.1 clauses 2.8.1(b)(1), 2.8.2 and 5.2.5 oblige a sheet that draws one to
  declare it on a legend or cover sheet; `pandid.document.legend` builds the box
  and the entry is the author's to add.
  - The rule is one-sided. Normally open is not marked at all, so `"open"` is
    the default and draws exactly what a `Valve` without the argument draws; the
    fill is the whole of what `"closed"` adds. The symbol's box, nozzles and
    alternate faces are untouched, so declaring a valve closed never moves a
    line already drawn.
  - `normal_position` rather than a boolean, because the position is what the
    *plant* is in, and the designations a P&ID draws it with are an enumeration
    (NC now, PIC001's locked and car-sealed ones later) rather than a switch. It
    is also readable in a spec, which round-trips it, and only when closed:
    writing `open` down would be writing the default down.
  - Filling a body leaves only its outline, so the fill is used where the
    outline alone still names the device: `default`, `gate`, `globe`, `ball`,
    `needle`, `plug`, `pinch`, `three_way`, `angle`, `bleed`, `manual`, `motor`,
    `solenoid` and `hydraulic`. Where the device is named by something *inside*
    the outline, such as a butterfly's disc, a check valve's flow arrow or a
    knife gate's blade, a filled body would draw a darkened gate valve wearing
    another name, so clause 4.2.2.8's abbreviation `NC` is written beside the
    valve instead, directly below it on a horizontal line and to the right of it
    on a vertical one. A variant added later takes the letters until it is put
    on the list, which is the safe way round: a variant falling through both
    would state its position nowhere.
  - Clause 4.2.2.10, "control valves or relief valves shall not be shown as NC",
    is enforced rather than warned about. `control`, `pneumatic`, `regulator`,
    `relief` and `psv` raise, naming the clause, because a darkened control
    valve on an issued sheet reads as a block valve someone has closed.
  - The one thing the fill costs: darkened, a globe and a ball are the same
    drawing, since the seat that tells them apart is inside the body the fill
    covers. `Valve(variant="globe")` in its normal position is unaffected. Its
    seat is a compact bead inside two conspicuously white triangles and a
    darkened body is black edge to edge, so the device marker and the position
    marker are never read for each other.
- `Fitting(variant="blind")`, the spectacle blind (figure-8 blind): two discs on
  a common tie, one bored through and one solid, bolted between a pair of
  flanges. Which disc is in the line is the whole of what the symbol says, so it
  takes the same `normal_position` a valve does. The run passes through the
  lower disc; `"open"` draws that disc as a ring with the solid one parked
  above, `"closed"` draws it solid with the ring parked above, and the tie hangs
  below the run as the handle it is.
  - The position is a change of *shape*, not a mark applied to one: draw.io's
    P&ID stencils draw both states, so the closed blind is a symbol of its own
    with its own `<defs>` entry. The generator refuses a pair whose boxes,
    nozzles or aspect disagree, or whose artwork does not, so the two differ in
    ink alone and declaring the position cannot move a line already drawn.
  - It needs no legend entry, unlike the darkened valve body. A solid disc
    blanking a line is the device's own convention rather than an extension of
    ISA-5.1.
  - `normal_position` now lives on a base shared with `Valve`, so there is one
    attribute with one vocabulary and one validation. What a sheet draws for it
    is what differs, and each class says separately which of its variants may be
    shown closed: every fitting variant but `blind` is drawn a single way, so
    declaring one closed raises rather than setting a position nothing draws.
  - Three more open/closed stencil pairs were considered and left out.
    fittings.xml's `Open Disc` / `Blind Disc` is a single disc on a handle
    filling 71% of a 40 x 140 box, and carries no connection points at all,
    which is an overlay to drop on a line rather than a device in one, so any
    scale that makes the disc read hangs a centimetre of plain line off the run,
    where a P&ID reads plain line as a branch. Its `Interchangeable Disc` pair
    is the figure-8 again at other proportions, and two mappings a reader cannot
    tell apart are one mapping and a trap.
- Variable-port `Mixer(n_inlets=…)`, `Splitter(n_outlets=…)` and
  `Column(n_feeds=…)` / `Reactor(n_feeds=…)`. A tower fed more than once, as in
  extractive distillation where the solvent enters above the feed tray, spreads
  `feed_1` … `feed_n` down the shell wall between the two duty arrows, so no
  count can reach the reflux and boilup returns opposite. One feed keeps the
  singular `feed` and the nozzle it always had.
- `Column.reflux_in` / `Column.boilup_in` return nozzles and `Reactor.vent`, so
  an overhead or reboiler loop closes on the column instead of being modelled as
  a recycle to some upstream unit.
- `Tee`, the pipe tee, so a line can branch. A bypass leg around a control
  valve, a drain off the underside of a run, a vent off the top, a sample point
  and a PSV takeoff are all one line splitting in two, and none of them could be
  drawn: `Mixer` and `Splitter` were the only branch primitives, and both are
  plant — a tagged unit drawn as a solid triangle and scheduled on the equipment
  list. A bypass drawn with one puts equipment on the sheet that the plant does
  not contain.

  A tee is not that. It is a bulk piping item, bought by the line and specified
  by the piping class like the valves and reducers around it, and an issued
  sheet draws **nothing at all** where one sits: three lines meeting, the run
  passing straight through and the branch leaving it at a right angle, at the
  same line weight. So the symbol is those two segments and no more, its two run
  nozzles share one centreline — which is what stops the run kinking through the
  junction, as it did through a splitter's fixed port pitch — and it draws no
  tag. Nothing reaches the equipment list either: `"tee"` is not major
  equipment, and `include=` still schedules one by name where a piping schedule
  wants it.

  The flowsheet needs a handle even where the drawing has no tag, so the name
  defaults to `TEE` and any two tees may share it, `Tee.repeats()` saying so on
  the same footing as a repeated interlock square or a tapped utility header;
  `add()` hands out `TEE (2)`, `TEE (3)`. It may not take a name that already
  means something else, since that handle is what a stream and a spec entry
  reach it by.

  `branch="outlet"` (the default) takes flow off the run and `branch="inlet"`
  returns it, which is the two ends of a bypass. The branch leaves the south
  face as drawn, so `pin(mirrored="y")` sends it north and `pin(orientation=90)`
  / `270` stand the run on end with the branch west or east.

  The run carries one stream or line number straight through a tee, as it does
  through a valve or a reducer, and each branch takes a number of its own;
  `significant` breaks the run's number at the junction where the piping class
  changes there.
- `HeatExchanger(variant="kettle").bottoms` is the liquid draw at the weir end
  of a kettle reboiler. A tower's bottoms product physically leaves from there,
  so it no longer has to be taken off a splitter in the sump line, which puts a
  piece of equipment that does not exist on the sheet and in the equipment list.
- `Valve.actuator`, the signal connection on the valve, so a controller output
  terminates on the final control element. It sits on the top of the symbol on
  every one of the 22 valve variants, so the signal stops where it meets the
  valve instead of running on into the body, and a valve flipped top to bottom
  carries its operator over with it.
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
- `Flowsheet.route()` places attached instruments and re-routes until the two
  agree, rather than trading a fixed two passes. A balloon is placed on its
  host's *routed* path and the box it lands in is an obstacle the next pass
  routes around, which can bend that same path and move the balloon again, so
  the two chase each other to a fixed point. Left at two passes, a dense sheet
  ended with its balloons in one place and its signal lines drawn to where they
  had been, which is a line leaving one balloon's edge and reaching diagonally
  past the other. Capped at `pandid.layout.attach.MAX_PLACEMENT_PASSES`, since a
  sheet can trade between two arrangements indefinitely; every pass ends on a
  route, so running out of passes still leaves each line drawn to the balloon it
  belongs to. Whether the last run settled is on `Flowsheet.route_converged`.

#### Rendering

- SVG output with no runtime dependencies. `Flowsheet.to_svg()` returns the
  string, `Flowsheet.render(path)` infers the format from the extension, and
  `.pdf`/`.png` go through the optional `cairosvg` backend.
- `Flowsheet.show()` opens the drawing in a browser, and a flowsheet renders
  inline in Jupyter via `_repr_svg_`.
- `diagram=` on `to_svg()` / `render()` (and `--diagram` on `pandid draw`) says
  which of the two drawings the sheet is: `"pfd"` (the default) or `"p&id"`,
  also spelled `"pid"` and matched case-insensitively, so the drawing's own
  name is what an engineer may type. **A P&ID draws its process lines without
  arrowheads**, since flow direction on one is read off the equipment and the
  line list rather than off an arrow on every run; the arrowhead is a PFD
  convention. Nothing else about the sheet changes, and a signal line carried
  none on either drawing. It is deliberately separate from `border=`: the frame
  is sheet furniture and a PFD carries the zone-ruled one as readily as a P&ID
  does, so neither option implies the other.
- Canvas fitted to content, with no letterboxing, no clipping and uniform 2 px
  symbol strokes.
- A unit given an explicit `width`/`height` is drawn *at* that box. Where the
  symbol may be reshaped — every equipment symbol, since each draw.io stencil
  they come from declares `aspect="variable"` — the artwork fills the box, so a
  `Column(width=110, height=250)` is a column of exactly that size and its
  distillate and bottoms lines meet its heads instead of stopping 15 px short of
  them. Where the shape carries meaning it may not be: an ISA-5.1 balloon is a
  circle at every box it is given and is centred in whatever room is left over,
  with its taps on the circle rather than out on the box edge.
  `Symbol.stretchable` is the switch, and the vendored symbols take it from the
  stencil's own declaration.
- A stream number or line number drawn parallel to the line it names, on a wipe
  so no line strikes through the text. It sits on the line only where the run
  can still show pipe past the wipe at each end, and steps beside the line where
  it cannot, which is the usual answer for a line number a dozen characters
  wide. On a vertical run it is turned to read bottom to top, so the sheet is
  read from the bottom or the right the way ISO 5457 §4.1 fixes for the drawing
  as a whole, and wherever it lands it slides along its own run until it clears
  the equipment, tags, balloons and other numbers already on the sheet.
- `page_size="A4"`..`"A0"` draws a sheet of exactly that size instead: the border
  and title strip rule to the page edges and the drawing is fitted into what they
  leave, scaled down uniformly if it is too big and never enlarged if it is not.
  A page too small for its own furniture raises rather than clip it. Fixing the
  page also fixes the zone grid, so a note referring to zone D-4 still means D-4
  after the next revision grows the drawing. The sizes are ISO 216 in
  millimetres, and a named sheet declares that physical size on the `<svg>`
  element, so it prints and exports to PDF at exactly its ISO size.
- `jump_direction="vertical" | "horizontal"` on `to_svg()` / `render()` selects
  which of two crossing lines gets the semicircle hop.
- 137 registered `(kind, variant)` symbols, generated from the draw.io /
  diagrams.net P&ID stencils (Apache-2.0) by `scripts/vendor_symbols.py` and
  matched to ISO 10628-2 symbols where one exists. Feed/Product flags, Mixer,
  Splitter and the ANSI/ISA-5.1 instrument balloons are hand-drawn originals.
- Every symbol draws the thing it is named after. Two did not, and neither was
  diagnosable from the output, which is why both are called out rather than
  folded away silently.
  - `Tank(variant="floating_roof")` came out as a solid black rectangle. The
    converter read mxGraph's `<fill>` as "paint this in the stroke colour",
    but a paint op names the operation and the *fill colour* names the colour;
    a bare `<fill>` is a background wash, and on a monochrome sheet whose
    outlines are transparent it washes in nothing. The converter now keeps the
    fill colour as canvas state, which `<fillcolor>` sets and `<save>`/
    `<restore>` bracket — so it can still draw a solid shape, and draws one
    exactly where a stencil asks for it. That also restores four details the
    converter had been dropping: the pivot dot on `Fitting(variant="damper")`
    and the flow arrowheads inside `Separator(variant=…)` `cyclone`, `gravity`
    and `scrubber`, all of which the stencils mark solid.
  - `Valve(variant="globe")` and `Valve(variant="ball")` were one drawing.
    draw.io ships "Globe Valve" as a byte-for-byte copy of "Ball Valve", and
    both draw the bowtie pinched around an *open* seat, which is the ball
    valve (ISO 10628-2 X8071). A globe valve (X8068) is that same seat drawn
    solid, and the contrast is the whole of what tells a reader which valve is
    in the line. The globe's seat is now filled. Its body — the two triangles —
    keeps its white interiors, so it stays clear of the fully darkened body
    that means *normally closed* (PIP PIC001 4.2.2.7). The correction is
    recorded in `STENCIL_PATCHES` in `scripts/vendor_symbols.py`, in the
    stencil's own drawing language, so `scripts/vendor_data/` stays an
    unmodified mirror of upstream and the generator refuses to run if a patch
    ever stops matching its shape.
- Two more nozzles that were never on the ink, both hidden by the drawing rather
  than by the geometry. `Tank(variant="floating_roof")`'s inlet sat 5 units above
  the roof plate, in the gap the roof floats in — invisible while the tank was
  painted as a solid block — and `Tank(variant="sphere")`'s sat 5 units above the
  sphere's crown, in the gap between the two lines its legs are drawn against.
  Both now land on the drawing, as the dished and conical roofs already did. The
  invariant suite could not see either, because its path flattener counted a
  `moveto` as a drawn segment and so ruled a phantom stroke straight across the
  gap; it no longer does.
- Twelve of those fill gaps a sheet runs into early. `Column(variant="packed")`
  is the first column symbol that draws an internal, two beds of packing between
  their support grids, so an absorber or a stripper is no longer a bare shell; it
  carries the default column's nozzles at the heights they already sit at, so
  nothing already drawn moves. `HeatExchanger` gains `air_cooled` (a fin-fan,
  with the bundle piped and the air drawn in under it and out through the fan),
  `finned`, `double_pipe`, `hairpin`, and `thin_film`, the first evaporator in
  the set. `Vessel` gains `jacketed`, whose process nozzles sit on the jacket's
  outer wall so no line is drawn across the jacket, and `skirted`. `Pump` gains
  `peristaltic` and `submersible`, `Filter` gains `ion_exchange` for water
  treatment, and `Valve` gains `bleed`, the small drain valve piped down the
  page.
- A metered line is drawable end to end. Twenty-two more symbols come from two
  stencil files the project had never taken, `flow_sensors.xml` and
  `piping.xml`. `Fitting(variant="venturi")` is the primary element an FE
  balloon is drawn against most often — a converging throat and a diverging
  recovery cone, closed by a flange face at each end — and it arrives with
  `flow_nozzle`, `coriolis`, `vortex`, `ultrasonic`, `turbine_meter`,
  `positive_displacement`, `v_cone`, `wedge`, `target`, `pitot` and
  `averaging_pitot`. From the piping file: `strainer_y`, `strainer_basket` and
  `strainer_duplex`, which lie in the run rather than standing across it the way
  the two existing strainers do; `bellows`, the expansion joint a piping drawing
  draws; `damper`; and `spool`, the length of pipe taken out to break a line.
  `Reducer` gains `concentric`, a trapezoid where the default is a cone tapering
  to a point, and `eccentric`, flat on top with its small end on a lowered
  centreline — the reducer a pump suction is drawn with, and one the library
  could not draw at all. `Vent` gains `exhaust_head` and `breather`. All of them
  are drawn to the in-line family's sheet size: both stencils lay their devices
  out on a 50-unit module where `valves.xml` uses about 100, so they are scaled
  by half rather than by a quarter and a venturi comes out 25 x 20 beside a
  24.5 x 15 valve.
- The in-line families are drawn at the size a real sheet draws them. draw.io
  cuts its stencils for a diagram rather than for a drawing, and at the scale
  they were first vendored at a gate valve came out 49 units — 13 mm on an A3
  sheet, against the 6 mm an issued P&ID draws one at — so a station with
  isolation valves either side of a control valve took the width that five
  valves, a flow element and an instrument square occupy on a real sheet. The
  bowtie is now 24.5 x 15 units, 6.5 x 4.0 mm. Everything that shares a pipe
  with it moves with it, since one line size is what makes them read as one
  family: strainers, orifice plates, sight glasses, couplings and the rest of
  the `Fitting` variants, the open `Vent` and `Funnel`, and `Reducer`, which is
  the same `fittings` stencil as the others and only had a kind of its own.
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
- `TitleBlock.client` and `.project` rule a row each above the drawing title.
  Neither is a standard field: ISO 5457 specifies no title-block data fields and
  defers them to ISO 7200, whose "legal owner" is the issuing organisation, i.e.
  `TitleBlock.company`. A block naming neither is ruled no row for them.
- `TitleBlock.scale` fills the scale cell, alongside the drawing number and the
  revision index, which is common drafting practice rather than a standard
  requirement: ISO 7200 §4 puts scale outside the block. Left blank it reports
  the ratio the drawing was actually placed at, which is a real number once
  `page_size` fixes the page, and nothing at all on a sheet sized to fit its
  drawing, where no scale exists to state.
- Every cell on the sheet is measured before it is written into, and a cell that
  cannot hold what it was given either grows or says so. The title strip is
  fixed geometry, so it abbreviates with an ellipsis and reports the field and
  the full text on `fs.warnings`; the drawing title, subtitle, client, project,
  status, drawing number, scale, date and every revision cell are all covered.
  Silently drawing text across a rule and into the value beside it is gone: a
  plant designation losing its last two characters is exactly the error that
  survives to issue-for-construction, and it used to leave `fs.warnings` empty.
- How much of a drawing title survives no longer depends on how many sheets the
  set has. The `SHEET n of m` string shares the title band, and its measured
  width used to come out of the title's own budget, so the same title was
  abbreviated differently on a one-sheet drawing and a hundred-sheet one. The
  count now has a slot of its own.
- The revision table's `DATE` column holds a full ISO 8601 date. At the width it
  was, the date every sheet is stamped with ran 3px past its own rule.
- A company name too long to wrap into the company cell, and a sheet count too
  long for its slot, are drawn whole and reported rather than trimmed:
  hyphenating a company name invents a break point, and half a sheet count reads
  as a different sheet.
- An `Annotation` given an explicit `width` smaller than its own rows need is
  reported. A box left to size itself is sized from its rows and always fits.
- Sheet furniture docked flush to the frame on a nine-point `align` grid, or
  hand-placed with `position=(x, y)`: `Annotation`, `TableBox`, and the
  `equipment_list()` / `notes()` / `legend()` constructors. Like the title
  strip, a box added to the flowsheet is drawn on the sheet whatever the border.
- `equipment_list()` schedules major equipment only: vessels, columns, tanks,
  reactors, separators, exchangers, heaters, coolers, furnaces, pumps,
  compressors, blowers, turbines, ejectors, filters and dryers. Valves,
  fittings, reducers, vents and funnels are bulk items bought by the line and
  covered by the piping class, and a mixer or splitter is a junction in that
  line, so none of them is plant to schedule. Each row says what the unit is
  (`E-101` reads `Heat Exchanger`, not the `hex` dict key). `include=[...]`
  names the rows explicitly instead and takes whatever it names, which is how a
  valve schedule is built from the same flowsheet.
- An unknown `border=`, `diagram=` or `styling=` raises, naming the spellings
  that work, rather than silently drawing the plain sheet.
- Optional stream property table (`show_stream_table=True`) with section headers
  injected via `Flowsheet.stream_table_sections`. Property values are supplied
  by the caller as strings; the engine does not compute them.
- The stream table's columns are sized to everything drawn in them: the row
  labels, the stream numbers heading each column, the values under them, and any
  section header spanning the width. The row label column was a hard-coded 122px
  and the value columns were measured from the stream *names* alone, so a row
  label like `Vapour Fraction (mass)` and a value like `0.0441 kg/kg total` both
  overflowed into the cell beside them. The table's width is a layout output
  rather than a fixed constraint, so it grows: a stream table that cannot show
  its own value is not a stream table.
- A fixed `page_size` too small for its furniture names the widest piece in the
  error, since a table honestly sized to its contents is usually what pushed the
  sheet over and "the furniture does not fit" does not say which furniture.
- Off-page connectors: a `Feed`/`Product` flag's `reference` is drawn as its
  second line. A flag is the only thing with a second line, so `reference=` on
  equipment raises and names the boundary to put it on.

#### Instrumentation (ISA-5.1)

- `Flowsheet.add_instrument(type, number, …)` and the `Instrument` unit, drawing
  the functional letters over a bare loop number the way a real sheet does.
  Balloon variants: `default` (field), `panel`, `aux`, `shared` (a circle in a
  square: shared display and shared control), `computer` (hexagon).
- The two trip squares, which ANSI/ISA-5.1-2009 draws as two different symbols:
  `interlock`, a **plain diamond** (Table 5.1.2 items 3-5, the generic interlock
  logic function), and `sis`, a **diamond inscribed in a square** (Table 5.1.1
  column B, the safety-instrumented-system / alternate-choice symbol, and what
  an issued sheet draws a trip with). Both carry the interlock number in the
  lower half of the diamond, and both repeat: a trip is a logic function, so the
  same tag may be drawn at each place it acts. `sis` is also spelled `logic`,
  which is the name the package shipped and what every drawing already authored
  uses; the two names are one symbol and one `Symbol` object. A *bare* square is
  neither of them — that is `shared` with its balloon left off, which is what
  `logic` used to be drawn as.
- `Instrument.attach(on=…, at=…, offset=…, angle=…)` anchors a balloon to the
  stream or the equipment it reads, with an impulse line drawn to the tap.
  `angle` is measured from the flow direction at the tap, so a re-route cannot
  spin it, and `offset=0` leaves an in-line primary element sitting on the line.
  Attached balloons take no part in layout ranking.
- Typed signal lines through `connect(kind=…)`: `electric` (dashed),
  `pneumatic` (slash ticks), `data`/`software` and `capillary`, all with no
  arrowheads and no stream numbers, and all of them legal only between two
  signal connections. A pneumatic line is drawn *solid* and marked
  with double cross-hatches, so the hatch is the only thing distinguishing it
  from process pipe. Every run long enough to hold a mark gets one, however
  short.
- A balloon's signal connections may be taken on any face, since a circle has no
  natural side.
- An interlock square repeats. A tag names one item, so `add()` refuses one
  already on the sheet, and a second `P-101` or a second `LT-101` still raises.
  An `Instrument(variant="logic")` is a logic function rather than a device and
  is drawn at every place it acts, carrying the same tag each time, so a repeat
  is accepted and given a name of its own: `I-1`, `I-1 (2)`, `I-1 (3)`. The tag
  is what the sheet draws; the name is what a stream endpoint, a spec entry and
  an equipment-list row address, and it stays unique. `Instrument.tag` reads the
  drawn tag back.
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
- `text-truncated` and `text-overruns-cell` are the renderer's own findings,
  raised where a piece of sheet furniture could not hold the text it was given.
  Each names the field and quotes what it was asked to draw. They are rebuilt on
  every render, so shortening a title and rendering again clears the finding.
- `route-not-settled` warns when routing and instrument placement never agreed
  and `route()` ran out of passes. The drawing is still coherent, but which of
  the arrangements it caught is arbitrary, so the sheet is not reproducible
  until the balloon-carrying lines are pinned with `via()`.

#### Command line

- A `pandid` command, installed with the distribution, so a spec file becomes a
  drawing without anyone opening Python. `pandid draw plant.yaml -o plant.pdf
  --page-size A3 --border zone` renders a YAML or JSON spec with the render
  options that matter, `pandid validate plant.yaml` reports what the engine makes
  of one without drawing it, and `pandid symbols --kind valve` lists the
  registered `(kind, variant)` pairs, so the variant names are in front of
  whoever is writing the spec. `python -m pandid` is the same entry point from a
  checkout. Built on `argparse`: the package still has no runtime dependencies.
- Exit codes a build script can gate on rather than one number for everything:
  `0` done, `1` the flowsheet was rejected (a spec that could not be read, a
  validation error, a request the engine refused), `2` the command line was
  wrong, `3` an optional extra the request needs is not installed. `validate`
  fails on an error and passes on warnings, which is exactly when a render would.
- Every failure a user can provoke is one line on stderr. A missing file, a typo
  in the spec, an unknown page size, an output extension the engine cannot write,
  and a missing PyYAML or cairosvg all come back as the message the library
  already wrote to be read, rather than as a traceback.

#### Tooling, tests and packaging

- Golden-SVG visual regression suite over a fixed corpus of scenarios
  (`tests/test_golden.py`, fixtures in `tests/golden/`), regenerated with
  `PANDID_UPDATE_GOLDEN=1`.
- Symbol-invariant suite over every registered `(kind, variant)`: well-formed
  SVG, ports inside the bounding box, ports on drawn ink, no two ports
  coinciding — and the same, on a rendered sheet, at box shapes nothing is drawn
  at, which is where a resolved port and the artwork it belongs to can drift
  apart.
- Route-invariant suite (`tests/test_route_invariants.py`) over the whole shipped
  corpus, the golden scenarios and both ethanol sheets: every routed stream
  begins and ends on its own port anchors, and nothing is drawn diagonally.
  Neither invariant knows anything about instrument attachment, which is the
  point; both catch a routing result that nothing re-checked.
- GitHub Actions CI: `ruff check`, `ruff format --check tests`, `mypy pandid`
  (blocking), and `pytest` on Python 3.10, 3.11, 3.12 and 3.13.
- `pre-commit` configuration mirroring the CI lint gates.
- Eleven runnable examples in `examples/`, each usable from the repository root
  or from `examples/` itself, and rendered into `docs/gallery/`. The last of
  them, `11_ethanol_pid.py`, is a whole issued P&ID on a fixed A3 sheet: line
  numbers on every line, four control valve stations drawn in full — isolation
  valves, reducer, a bypass over the top on its own normally closed valve and a
  drain off the underside either side of the control valve, every branch a
  `Tee` and so drawn as nothing and scheduled nowhere — tapped utility headers
  labelled the same way at every tap, five loops closing on an actuator with one
  cascade, alarm pairs and a repeated interlock square. Its PFD counterpart,
  `10_ethanol_pfd.py`, draws the reflux and filter-press partings as tees for
  the same reason.
- Packaged as **`pandid`**, how "P&ID" is said out loud, and the import name as
  well as the distribution name. Plain `pfd` is taken on PyPI by an unrelated
  project.
- Licensed under the **PolyForm Small Business License 1.0.0**: free for
  individuals, research, teaching, and companies under 100 people and
  1,000,000 USD revenue; a commercial licence is required above either
  threshold. Source-available rather than OSI open source. The vendored draw.io
  symbol geometry remains **Apache-2.0**, as that licence requires. The stencil
  artwork carries one additional field-of-use restriction on top of that grant,
  naming Atlassian products and marketplace distribution and excluding diagram
  output; `NOTICE` reproduces it in full. `NOTICE` also lists exactly which
  files fall under which licence, and both texts ship in the distribution.
- `pandid/py.typed`, the PEP 561 marker, so an installing project's type checker
  reads the annotations instead of treating the whole package as `Any`.
- `pandid.__version__` is the only place the version is written; the build backend
  reads it from there, so the distribution metadata cannot disagree with it.
- Release workflow (`.github/workflows/release.yml`): pushing a `v*` tag re-runs
  the four gates, checks the tag against `pandid.__version__`, builds the sdist and
  wheel, and uploads to PyPI over Trusted Publishing (OIDC, no API token).

### Deprecated

- `styling=` on `to_svg()` / `render()`. Use `border="zone"` and
  `diagram="p&id"`, which name the two things it asks for now that the title
  strip and the docked boxes follow the furniture the flowsheet carries rather
  than this option. `styling="p&id"` still means both together, `"pid"` is
  still accepted for it, and asking for either half separately and disagreeing
  raises. The canonical spelling is now `"p&id"`, the way this package writes
  the drawing's name everywhere else.
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
- `Unit._PORTS`. Use `Unit.PORTS`, which is the same list of
  `(name, direction, role)` tuples under a name that does not tell the one
  attribute a subclass must set that it is private. `_PORTS` is still read, so
  no unit loses its nozzles: whichever spelling is declared nearest in the class
  hierarchy wins, and a class using the old one warns where it is defined.

# pandid: P&ID and process flow diagram engine

`pandid` is a zero-dependency, pure-Python engine that turns a topological
flowsheet definition into a publication-quality, orthogonal **PFD / P&ID** as
SVG. You describe *what connects to what*. The engine lays out the equipment,
routes every stream, and draws industry-standard symbols.

The distribution is **`pandid`**, how "P&ID" is said out loud. It imports as
**`pandid`**.

[![Distillation train](https://raw.githubusercontent.com/Alpha9463/pandid/main/docs/gallery/03_distillation_train.png)](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md)

<sub>[`examples/03_distillation_train.py`](https://github.com/Alpha9463/pandid/blob/main/examples/03_distillation_train.py). See the [gallery](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md) for all eleven.</sub>

## Install

Requires Python 3.10+. No runtime dependencies. Fully type-hinted and marked
[PEP 561](https://peps.python.org/pep-0561/), so `mypy` and `pyright` read the
annotations straight out of the wheel.

```bash
pip install pandid
pip install 'pandid[pdf]'    # optional PDF/PNG export backend (cairosvg)
pip install 'pandid[yaml]'   # optional YAML spec reader (Flowsheet.from_yaml)
```

From a checkout:

```bash
pip install -e .
pip install -e '.[dev]'       # pytest, ruff, mypy
```

## Quick start

```python
from pandid import Flowsheet, units

fs = Flowsheet("Flash Separation")
feed   = fs.add(units.Feed("Crude"))
heater = fs.add(units.Heater("E-101"))
drum   = fs.add(units.Separator("V-101"))
gas    = fs.add(units.Product("Off-Gas"))
liquid = fs.add(units.Product("Condensate"))

fs.connect(feed.outlet,   heater.inlet)
fs.connect(heater.outlet, drum.feed)
fs.connect(drum.vapor,    gas.inlet)
fs.connect(drum.liquid,   liquid.inlet)

fs.render("flash.svg")        # layout + routing run automatically
```

No coordinates anywhere. `render()` infers the format from the extension
(`.svg`, or `.pdf`/`.png` with the optional backend). `fs.to_svg()` returns the
SVG string, `fs.show()` opens it in a browser, and a flowsheet renders inline in
Jupyter.

## What it does

- **Topology-first API.** Declare typed units (pumps, columns, reactors,
  heat exchangers, …) and connect their named ports; streams are created for you.
- **Automatic layout.** Sugiyama-style layering, crossing reduction, and a
  center-aligned flow spine; recycles are detected and routed around the sheet.
  Ports that a symbol authors on more than one face are put on the face the
  peer is actually on, so a drum under its condenser is fed from the top.
- **Orthogonal A\* routing.** Clean right-angle streams with crossing jump-gaps
  and parallel-segment separation. Never emits a disconnected stream.
- **Industry-standard symbol library.** 137 registered symbols with style
  **variants** (a heat exchanger can be shell-&-tube, plate, kettle, U-tube…),
  derived from the Apache-2.0 draw.io P&ID stencils (see `NOTICE`). Equipment
  shapes follow the conventions of ISO 10628-2 and instrument symbols follow
  ANSI/ISA-5.1; see [Standards](#standards) for what that does and does not
  claim.
- **Pixel-perfect overrides.** `pin()` equipment to exact coordinates and
  `.via()` a stream through explicit waypoints; the engine honors them and
  auto-routes the rest.
- **Line numbers.** A line is labelled the way the line list has it
  (`6"-P-1001-A1A`: size, service, sequence, spec), not `S1`. The sequence is
  filled automatically, the number carries through in-line fittings and breaks
  at a spec break, and the convention is a format string you can replace. It is
  drawn parallel to its pipe: on the line where the run has room for it, beside
  the line where it has not, and turned to read bottom to top on a riser.
- **Instrumentation (ISA-5.1).** Instrument balloons anchored to the line or
  the equipment they read (with impulse lines), tags drawn inside, location
  variants, alarms and interlock squares, typed signal lines (electric /
  pneumatic / data), and controller outputs landing on a valve's actuator.
- **PFD or P&ID.** `diagram="p&id"` draws the sheet by the P&ID's own
  conventions, starting with the one every engineer notices: a process line
  carries no arrowhead, because direction is read off the equipment and the
  line list. `diagram="pfd"` is the default and keeps them.
- **Engineering sheet framing.** A full-width title strip (integrated revision
  history, company/logo cell, client and project, status / drawing-number /
  two-line title / scale / date / rev), generic titled boxes docked to the
  corners (auto **equipment list**, **notes**, **legend**, or any `Annotation` /
  `TableBox`), and a sectioned stream-property table, with an optional
  zone-ruled drawing border (ASME-style letter/number grid) around the lot.
  Off-page connectors carry a drawing reference.
- **Declare it as data.** A round-trippable spec format (`dict`, JSON, or
  YAML) covering everything above, so an equipment list and a stream table go
  straight to a drawing without anyone writing Python. Validated, not
  interpreted: a typo names the entry and lists what would have worked.
- **A command line.** `pandid draw plant.yaml -o plant.pdf` for the drawing,
  `pandid validate` for a check a build script can gate on, `pandid symbols` for
  what can be drawn. Built on `argparse`, so still no dependencies.
- **Validation.** `fs.validate()` flags overlapping pins, off-sheet
  coordinates (errors) and routes crossing equipment or big detours (warnings).
- **Zero runtime dependencies.** The package uses only the Python standard
  library. (SVG symbols are pre-converted and inlined; `cairosvg` is optional,
  only for PDF/PNG export, and `PyYAML` only for reading a YAML spec.)

**It does not do mass or energy balances.** Stream properties are strings you
supply; nothing is calculated from them. This is a drawing engine.

## Standards

`pandid` draws in the idiom of the process-industry drawing standards. It does
not claim conformance to any of them, and nothing it produces has been certified
against one. What it follows, feature by feature:

- **Equipment symbols** follow the conventions of **ISO 10628-2**. They are
  derived from the draw.io / diagrams.net P&ID stencil set, which makes no
  standards claim of its own, so a shape is matched to the ISO 10628-2 symbol
  where one exists rather than reproduced from the standard itself.
- **Instrument balloons, signal lines and tag letters** follow **ANSI/ISA-5.1**.
  ISO does not speak with one voice here. ISO 10628-1 §4.1 calls for
  instrumentation to IEC 62424. **ISO 15519-2:2015** is ISO's own standard for
  measurement and control on a process diagram, from the same subcommittee a
  year later, and it sends symbols to ISO 14617 and identification to IEC 81346;
  IEC 62424 and ISA 5.1 appear in its bibliography only. `pandid` takes neither
  ISO route, because ISA-5.1 is what North American practice draws and what the
  reference sheets this package was built against use. ISO 15519-1 §7.1 is the
  permission it stands on: *"Other reference designation principles may be used
  as long as they are agreed upon between involved parties."* ISA-5.1 §2.8.1(b)
  asks for the same agreement from its own side, that each exception be
  documented in the user's standard and on the drawing. `legend()` is where a
  sheet records it.
- **The gap to ISO 15519-2 is structural**, not a letter table. Its §5.1.1 says
  the symbol *"consists of a circle or extended circle"*, and its Table 1 draws
  only circles and stadiums, so the `shared` square, the `computer` hexagon and
  the `sis` and `interlock` diamonds have no ISO counterpart at all. Table 1
  codes location in three states, field / central / subsidiary, with no dashed
  line and no operator-accessibility axis. Table 2 has no `T` for transmitter
  and no `V` in any role: a transmitter is a symbol (Annex A.4.04), vibration
  falls under `S` and viscosity under `Q`. `FT-101` therefore has no reading in
  ISO 15519-2's terms at all.
- **Tag numbering** is therefore the ISA-5.1 **loop number** (`FIC-101`), not
  the IEC 81346 reference designation (`LAB01BP01`) that **ISO 15519-2** §5.3
  requires on the lower line of a symbol. A reader coming from ISO should expect
  the tags to look like this, and read it as the same documented exception.
  One ISO 15519-2 rule is enforced regardless, because it is about the letters
  and not the numbering: §5.2.4 orders the control-function letters
  I, R, C, S, M, Z, A, so `FIC` is right and `FCI` earns a `letter-sequence`
  warning on `fs.warnings`.
- **Sheet sizes** are the **ISO 216** A series, declared in millimetres on the
  SVG root so a sheet prints at its physical size.
- **The zone grid** is a drawing-frame zone reference in the ASME idiom: letters
  run bottom to top, numerals right to left. It is **not** an ISO 5457 grid.
  ISO 5457 §4.4 runs letters top down and numerals left to right at a fixed
  50 mm pitch with the field counts of its Table 2, and §4.2, §4.3 and §4.5 add
  a 20 mm filing margin and centring and trimming marks, none of which `pandid`
  draws. ISO 15519-1 §5.1.2 asks for the centring marks only on a document
  prepared for microfilming. The interval and the field count here are chosen to
  suit the sheet.
- **The title block** carries the data fields **ISO 7200** specifies, which
  ISO 10628-1 §5.1.2 requires on a process diagram: identification number, date
  of issue, sheet number, title, approval person, creator, and legal owner,
  which is the issuing organisation and so is the `company` cell. `client` is
  not an ISO 7200 field; it is there because issued sheets carry one. ISO 7200's
  eighth mandatory field, **document type**, has no cell yet.
- **Relative line weights** follow **ISO 15519-1 §6.2**, *"if two or more widths
  of line are used, the ratio between any two widths shall be at least 2:1"*,
  spent as **ISO 15519-2 Annex A.1** spends it: a pipeline (A.1.01) at twice the
  weight of an instrument connection, control connection, pilot line or signal
  line (A.1.02, A.1.03). Process piping and equipment outlines are the heavy
  class; every signal kind, the instrument taps and the pneumatic cross-hatch
  are the fine one. On A3 at 1:1 that is 0,53 mm against 0,26 mm, which is the
  standard's 0,5 / 0,25 pair. See
  [Signal lines](https://github.com/Alpha9463/pandid/blob/main/docs/api.md#signal-lines).
- **Where a label sits on a pipe** follows **ISO 15519-1 §7.2.5**, which puts a
  connection's designation *"above the connection with horizontal connecting
  lines and to the left of vertical connecting lines"*. That is where `pandid`
  puts a line number beside its run, turned to read bottom to top on a riser,
  which is one of the two reading directions §5.1.5 allows. §5.1.5's second
  sentence, holding a reference designation horizontal *"independent of symbol
  orientation"*, is a rule about a symbol's own designation and does not reach a
  connection. `pandid` also draws the number **on** the line where the run is
  long enough to carry it, which §7.2.5 words as a `should`, so that one is a
  divergence rather than a breach. See [Line numbers](#line-numbers).
- **Off-page connector text** is composed by **ISO 15519-1 §9**, which reserves a
  solidus for the sheet and a full stop for the zone and fixes the sequence:
  *"The location reference shall be presented in following sequence: document —
  sheet — column, row or zone."* `location_reference()` spells it, reproducing
  all seven rows of the standard's Table 2 (`7569/12.B3`, `/12.B3`, `/.B3`). A
  `reference` is still a plain string, because a document number on its own is
  what an issued sheet's flags actually carry: the three reference drawings this
  package was built against name `PFD-201`, `PFD-302`, `PCD-302` and `PFD-501`,
  and not one of them names a sheet or a zone. §12.6's placement rule, that the
  references *"shall be placed in the outer grid zone of the content area"*, is
  left to `pin()`, so the flag goes where the author puts it. Reciprocal
  references between the two ends of an interrupted line are outside the model,
  a `Flowsheet` being one sheet with no peer end to read a zone from.
- **Symbols where gravity is a functionality** are not turned. **ISO 15519-1
  §11.4.2** excepts them from the general permission to turn and mirror: *"for
  example symbol 2061: Open tank or symbol X 2618: Cyclone separator … Such
  symbols must not be turned."* 27 registered symbols carry
  `Symbol.gravity_fixed`: the separators, tanks, vessels, columns, reactors,
  vents, the funnel, the spray and fluidised-bed driers and the bag filter.
  Turning one earns a `gravity-turned` warning on `fs.warnings`. A warning rather
  than a refusal, because the sheet still draws correctly and only what it says
  about the plant is wrong. Where the equipment really is installed lying down,
  the answer is the variant drawn that way (`Vessel(variant="horizontal")`),
  which is the same clause's own advice that *"a new symbol should be created to
  the actual orientation"*.

The largest remaining gap against ISO 10628-1 is §5.3.1 and §5.4.2, and against
ISO 15519-1 is §11.1.3 (*"when the size of a symbol is changed, the line width
shall be unchanged"*): line widths and character heights are in drawing units
and are scaled with the drawing, so the weights above hold their *ratio* at any
sheet size but no physical width or height in millimetres is controlled.

## Documentation

| Where | What |
|---|---|
| [Example gallery](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md) | all ten examples rendered, with what each one demonstrates |
| [API reference](https://github.com/Alpha9463/pandid/blob/main/docs/api.md) | every public class, port and option, verified against the source |
| [Contributing](https://github.com/Alpha9463/pandid/blob/main/CONTRIBUTING.md) | setup, the four gates, and the conventions that are easy to get wrong |
| [Changelog](https://github.com/Alpha9463/pandid/blob/main/CHANGELOG.md) | what is in this release |

---

## Equipment & variants

A **class** is a functional equipment type, defined by its ports. A **variant**
is a visual style within it, picked with `variant=`. Each kind's `"default"` is
listed first below, with the shape it draws in brackets. Those brackets are
descriptions, not names. An unknown variant raises `ValueError` listing the ones
that kind does have.

```python
fs.add(units.HeatExchanger("E-1", variant="plate"))    # default, shell_tube, straight_tubes, finned, plate, kettle, u_tube, hairpin, double_pipe, condenser, air_cooled, spiral, thin_film
fs.add(units.Valve("FV-1", variant="control"))         # default (gate), gate, globe, ball, butterfly, check, needle, three_way, control, relief, bleed
fs.add(units.Pump("P-1", variant="gear"))              # default (centrifugal), gear, screw, vacuum, peristaltic, submersible
fs.add(units.Tank("TK-1", variant="floating_roof"))    # default (dished roof), conical, floating_roof, sphere
fs.add(units.Separator("V-2", variant="cyclone"))      # default (knock-out drum), horizontal, cyclone, gravity, scrubber, electrostatic
fs.add(units.Vessel("V-3", variant="jacketed"))        # default, dished, jacketed, skirted, dome, horizontal
fs.add(units.Column("T-1", variant="packed"))          # default (plain shell), packed
fs.add(units.Filter("F-1", variant="ion_exchange"))    # default, gas, press, rotary, ion_exchange
fs.add(units.Reducer("RE-1", variant="eccentric"))     # default, concentric, eccentric
fs.add(units.Vent("VT-1", variant="exhaust_head"))     # default, exhaust_head, breather
fs.add(units.Fitting("ST-1", variant="strainer"))      # see "In-line fittings" below
```

`Column(variant="packed")` is the one column symbol that draws an internal, two
beds of packing between their support grids, so an absorber or a stripper stops
coming out as a bare drum. It carries the default column's nozzles at exactly
the heights they already sit at, so switching to it moves nothing.

Classes include: `Feed`, `Product`, `Pump`, `Compressor`, `Blower`, `Valve`,
`Vessel`, `Tank`, `HeatExchanger`, `Heater`, `Cooler`, `Reactor`, `Separator`,
`Column`, `Mixer`, `Splitter`, `Tee`, `Reducer`, `Fitting`, `Ejector`, `Vent`,
`Funnel`, `Furnace`, `Turbine`, `Filter`, `Dryer`, `Conveyor`, and
`Instrument`. `Conveyor` is sized by `length=` rather than `width=`: its belt
grows and its rollers stay round. The
[API reference](https://github.com/Alpha9463/pandid/blob/main/docs/api.md#units-and-ports) lists every class's ports and every
registered variant.

**Equipment the catalogue does not have.** A `units.Unit` subclass declaring its
own `kind` and `PORTS`, with a `Symbol` registered for that kind, is laid out,
routed and drawn like any shipped class:
[Custom equipment](https://github.com/Alpha9463/pandid/blob/main/docs/api.md#custom-equipment).
It is for genuinely custom plant. Anything standard is better asked for as a
stencil mapping, so it ships for everyone and stays visually consistent.

**Valve operators.** Most valve variants draw the body only, with `actuator` on
the top of the symbol where an operator would be mounted. These also draw the
operator, and put `actuator` on its crown, so a signal lands where it physically
goes.

```python
fs.add(units.Valve("XV-1", variant="solenoid"))    # motor, solenoid, hydraulic (lettered boxes)
fs.add(units.Valve("PV-1", variant="pneumatic"))   # diaphragm actuator dome
fs.add(units.Valve("HV-1", variant="manual"))      # manual, knife (handwheel), butterfly_pneumatic
fs.add(units.Valve("PCV-1", variant="regulator"))  # self-acting, with its external sense line
```

Bodies without an operator: `plug`, `pinch`, `angle` (piped from below, out to
the side), `psv` (spring-loaded angle safety valve) and `bleed`, the small drain
valve tapped off a header, which is piped down the page (`inlet` on N, `outlet`
on S).

**Normally closed valves.** `normal_position` is where a valve sits with the
plant running. A closed one is drawn with its body darkened solid, which is how
every drain and bypass on an issued sheet is marked:

```python
fs.add(units.Valve("HV-301", variant="gate", normal_position="closed"))  # drain
fs.add(units.Valve("HV-302", variant="gate"))                            # isolation
```

The source is **PIP PIC001 clause 4.2.2.7**, "normally closed manual valves
shall be shown using a darkened solid symbol". It is **not** an ISA-5.1,
ISO 10628 or ISO 15519 convention. ISA-5.1 says nothing about valve fill and
leaves manual block valve depiction to the piping group, which is why ISA-5.1
clauses 2.8.1(b)(1), 2.8.2 and 5.2.5 oblige a sheet drawing one to declare it on
a legend. **ISO 15519-1 §11.4.5** does rule on the question, and prescribes a
different answer: letters, not fill. Add the legend entry yourself; nothing adds
it for you.

The rule is one-sided: normally open is not marked at all, so `"open"` is the
default and draws exactly what leaving the argument out draws. A body that
cannot carry the fill legibly (`butterfly`, `butterfly_pneumatic`, `check`,
`knife`) writes the abbreviation `NC` beside the valve instead, above it and to
the right, which is the placement ISO 15519-1 §11.4.5 and its Figure 28 give.
PIP PIC001 clause 4.2.2.10 forbids showing a control or relief valve as NC, so
`control`, `pneumatic`, `regulator`, `relief` and `psv` raise rather than draw
one. See the
[API reference](https://github.com/Alpha9463/pandid/blob/main/docs/api.md#normally-closed-valves).

**More than one of the same nozzle.** `Mixer(n_inlets=…)` and
`Splitter(n_outlets=…)` spread their connections along the triangle's flat face.
`Column(n_feeds=…)` and `Reactor(n_feeds=…)` do the same down the shell wall, for
the extractive tower that has to take its solvent above the feed tray. They are
`feed_1` … `feed_n`, top to bottom, once there is more than one. A single feed
keeps the plain `feed` on the nozzle it always had, and stays clear of the
`reflux_in` / `boilup_in` returns however many there are.

```python
tower = fs.add(units.Column("T-302", n_feeds=2))
fs.connect(solvent.outlet, tower.feed_1)   # above the feed tray
fs.connect(crude.outlet, tower.feed_2)
```

**An exchanger's nozzles name the side, not the duty.** They are `shell_in`,
`shell_out`, `tube_in` and `tube_out`, because which fluid runs in the shell and
which in the tubes is a design decision the drawing has to record — fouling
service goes tube side, since tubes can be rodded out — while which side is the
hot one inverts between operating cases without the nozzle moving. The variants
that have no shell and no tubes say what they do have: `air_cooled` is
`tube_*` and `air_*`, `plate` and `spiral` letter their two interchangeable
circuits `side_a_*` / `side_b_*`, and `thin_film` is `jacket_*` and `product_*`.
`Heater` and `Cooler` take a `utility_in` / `utility_out` on the same principle.

```python
fs.connect(overhead.outlet, cond.shell_in)   # condensing vapour, shell side
fs.connect(cw.outlet, cond.tube_in)          # cooling water through the tubes
```

**A kettle reboiler draws its own bottoms.** `HeatExchanger(variant="kettle")`
has a fifth nozzle, `bottoms`, at the weir end of the shell. What does not boil
overflows and leaves there as the tower's bottoms product, so the sump line
needs no splitter that the plant does not have.

**Branching a line.** A P&ID branches constantly — a bypass leg around a control
valve, a drain off the underside of a run, a vent off the top, a sample point, a
PSV takeoff — and every one of those is a line splitting in two rather than a
piece of plant. `Tee` is the fitting that splits it. It is drawn as an issued
sheet draws one: three lines meeting, the run passing straight through and the
branch leaving at a right angle, at the same line weight, with **nothing** at
the junction. No tag, no symbol, no arrowhead even on a PFD, and no row on the
equipment list. An arrowhead marks where a line arrives somewhere, and a junction
is a point on a line where the line divides, with the run carrying on past it.

`branch="outlet"` (the default) takes flow off the run; `branch="inlet"` returns
it, which is how a bypass rejoins. The branch leaves the south face as drawn, so
the side it comes off is the tee's placement:

```python
takeoff = fs.add(units.Tee().pin(mirrored="y"))   # branch north, over the top
rejoin  = fs.add(units.Tee(branch="inlet").pin(mirrored="y"))
drain   = fs.add(units.Tee())                     # branch south, off the underside

fs.connect(upstream.outlet, takeoff.inlet)        # the run, straight through
fs.connect(takeoff.outlet, hv_a.inlet)
fs.connect(takeoff.branch, bypass_valve.inlet)    # the leg, off the run
fs.connect(bypass_valve.outlet, rejoin.branch)
```

`pin(orientation=90)` and `pin(orientation=270)` stand the run on end with the
branch west and east. A tee needs no name: it defaults to `TEE` and the
flowsheet tells repeats apart as `TEE (2)`, `TEE (3)`, the way it does for a
repeated interlock square. The run keeps one stream or line number through a
tee, as it does through a valve, and each branch takes a number of its own.

Reach for `Mixer` or `Splitter` only where the branch really is plant: both are
tagged equipment drawn as a triangle and scheduled on the equipment list.

**In-line fittings.** Every in-line device is a pair of faces on a line, so
`Fitting` is one class and the variant picks the device: `strainer`, `strainer_cone`, `strainer_y`,
`strainer_basket`, `strainer_duplex`, `orifice`, `rotameter`, `rupture_disc`,
`sight_glass`, `sight_glass_lit`, `silencer`, `expansion_joint`, `bellows`,
`blind`, `damper`, `spool`, `static_mixer`,
`hose`, `coupling`, `clamped_coupling`, `flange` (the default), and the flame
arrestors (`flame_arrestor` plus `_explosion_proof` / `_detonation_proof` /
`_fire_resistant`).

**Spectacle blinds.** `Fitting(variant="blind")` is the figure-8 blind: two
discs on a common tie, one bored through and one solid, bolted between a pair
of flanges. Which of them is in the line is the whole of what the symbol says,
so a blind takes the same `normal_position` a valve does:

```python
fs.add(units.Fitting("SB-101", variant="blind"))                            # line through
fs.add(units.Fitting("SB-102", variant="blind", normal_position="closed"))  # line blanked
```

The line runs through the lower disc. Open draws it as a ring, with the solid
disc parked above; closed draws it solid, with the ring parked above. That is a
change of shape rather than a mark added to one, because the stencil set draws
both, and it is the device's own convention rather than an extension of a
standard, so it needs no legend entry. No other fitting variant takes a
position: a strainer is a strainer whatever the plant is doing, and asking for
one raises.

**Primary flow elements.** The device an FE balloon reads is in the run like any
other fitting, so it is a `Fitting` variant too: `venturi`, `flow_nozzle`,
`coriolis`, `vortex`, `ultrasonic`, `turbine_meter`, `positive_displacement`,
`v_cone`, `wedge`, `target`, `pitot` and `averaging_pitot`. Attach the balloon
to the element with `offset=0` to draw it sitting on the line.

```python
fe = fs.add(units.Fitting("FE-101", variant="venturi"))
ft = fs.add_instrument("FT", 101, on=fe, at="N", offset=70)
```

`Reducer` is the fitting that changes a line's size, and its variants are the
body style: `concentric` (the default) is the trapezoid a piping drawing draws,
symmetric about the run; `eccentric` is flat on top, so the two ends share a
roof and the small one's centreline is the higher of the two. That is what goes
on a pump suction, where a concentric body would leave a pocket for vapour to
collect in against the roof of the line. `pin(mirrored="y")` rolls it over, flat
on the bottom, for a line that has to drain.

Which way the cone points is `large_end`, not the variant. A reducer's wide face
is its `inlet` by default, which reduces the line; `large_end="outlet"` is the
same fitting piped the other way round, which expands it. A control valve
station has both.

```python
rd = fs.add(units.Reducer("RD-306A"))                        # into the valve
ex = fs.add(units.Reducer("RD-306B", large_end="outlet"))    # back out of it
```

`Ejector` is separate because it has three connections (`motive`, `suction`,
`discharge`). `Vent` and `Funnel` have one each: `Vent` is a stack open to
atmosphere that a PSV tailpipe or a tank breather terminates on, and `Funnel` is
a manual charging point feeding the line. `Vent(variant="exhaust_head")` is the
silencing hood on a steam or relief vent and `Vent(variant="breather")` is the
tank conservation vent.

## Automatic layout and recycles

Given only the topology, the engine layers the units, orders them to reduce
crossings, aligns the main process line onto one axis, and detects feedback
loops itself. You never declare a stream to be a recycle.

```python
from pandid import Flowsheet, units

fs = Flowsheet("Ammonia Loop")

feed     = fs.add(units.Feed("Natural Gas"))
mixer    = fs.add(units.Mixer("M-101"))
reformer = fs.add(units.Reactor("R-101"))
hx       = fs.add(units.HeatExchanger("E-101"))
sep      = fs.add(units.Separator("V-101"))
comp     = fs.add(units.Compressor("K-101"))
prod     = fs.add(units.Product("Ammonia"))

fs.connect(feed.outlet,     mixer.in_1)
fs.connect(mixer.outlet,    reformer.feed)
fs.connect(reformer.outlet, hx.shell_in)
fs.connect(hx.shell_out,    sep.feed)
fs.connect(sep.vapor,       comp.suction)
fs.connect(comp.discharge,  mixer.in_2)   # detected as the recycle
fs.connect(sep.liquid,      prod.inlet)

fs.render("ammonia_loop.svg")
```

## Manual layout

```python
# Pin equipment to exact SVG coordinates (top-left corner):
hx = fs.add(units.HeatExchanger("E-1")).pin(x=100, y=50)
# ...or to a grid cell, mirrored:
fv = fs.add(units.Valve("FV-1")).pin(col=2, row=1, mirrored=True)

# Force a stream through explicit orthogonal waypoints:
fs.connect(feed.outlet, hx.tube_in).via([(130, 65), (130, 110)])
```

**Orientation and mirroring.** `orientation` is a clockwise quarter turn in
degrees (`0`/`90`/`180`/`270`) and swaps the unit's width and height. `mirrored`
flips it: `True` or `"x"` is left↔right (swapping the E and W faces), `"y"` is
top↔bottom (swapping N and S), `"xy"` both. Ports follow the placement, so a
stream never detaches from its nozzle.

```python
fs.add(units.Pump("P-1")).pin(x=200, y=100, orientation=90)      # discharge now faces S
fs.add(units.Pump("P-2")).pin(x=400, y=100, mirrored="y")        # flipped top-to-bottom
```

**Choosing a port's face.** Many vessels can be piped from more than one side,
and the engine picks which one: it scores every face the symbol authored against
where the unit at the other end of the stream actually landed, and takes the
shortest run. A reflux drum sitting under its condenser is fed from the top
without being told. Nozzles fixed by physics (a column's bottoms, a drum's
liquid draw-off) offer one face and are never moved.

`nozzle()` overrides the choice where the sheet wants a particular convention,
naming the compass point **as drawn** so mirroring cannot invert it;
`Flowsheet(..., auto_faces=False)` turns the whole thing off:

```python
drum = fs.add(units.Separator("V-1", variant="horizontal"))
drum.nozzle("feed", "N")        # always from above, however the header is laid in
```

Pinned and auto-placed units mix freely. A port sits at a fixed *fraction* of
its symbol's box, so lining two items up means matching those fractions rather
than their corners. See [example 06](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md#06--column-reflux-and-reboiler).

## Instrumentation & signals

```python
ft  = fs.add_instrument("FT", 101)                             # field flow transmitter
fic = fs.add_instrument("FIC", 101, variant="panel")           # panel-mounted controller
fy  = fs.add_instrument("FY", 101, variant="computer")         # computing relay
# variants: default (field balloon), panel, aux, shared (circle in a square),
#           computer (hexagon), sis (diamond in a square; also spelled
#           "logic"), interlock (plain diamond)

fs.connect(ft.sig_out, fic.sig_in, kind="electric")        # dashed
fs.connect(fic.sig_out, fy.sig_in, kind="pneumatic")       # slash-ticks
```

`type` and `number` make the tag. `instrument.tag` is `"FT-101"` for equipment
lists and cross-references, while the balloon draws the letters over the
**bare** number, as a real sheet does. (`units.Instrument("FT-101")` is still
accepted and split.) The signal `kind`s are `electric`, `pneumatic`,
`data`/`software` and `capillary`, each with its own line style, no arrowheads
and no stream numbers.

### Declaring the loop

`add_loop()` types the loop number once and hands it to every member:

```python
loop = fs.add_loop("F", 303)                     # the pair (F, 303) is the identity
fe  = fs.add(units.Fitting(loop.tag("FE"), variant="venturi"))   # primary element
ft  = fs.add_instrument("FT",  loop, on=fe, at="N", offset=90)
fic = fs.add_instrument("FIC", loop, on=ft, at="E", offset=70, variant="shared")
cv  = fs.add(units.Valve(loop.tag("CV"), variant="control"))     # final element
fs.connect(fic.sig_out, cv.actuator, kind="pneumatic")

fs.add_instrument("TT", loop)     # ValueError: loop F-303 measures 'F'...
```

The loop replaces the **number**, not the letters. Each balloon still types its
own functional letters and the loop checks the first of them, at the line that
wrote it rather than as a finding three hundred lines later. That one letter of
redundancy is the whole point: a loop that supplied the letter would have every
balloon agreeing by construction, and an `FIC` reading a `TT` would become
unrepresentable rather than detected.

- **A loop is `(variable, number)`.** `add_loop("F", 101)` and
  `add_loop("L", 101)` are two loops on one sheet, which is what
  [example 04](https://github.com/Alpha9463/pandid/blob/main/examples/04_control_loop.py)
  draws. Nothing recovers loops by grouping tags on the number alone.
- **`loop.tag(letters)`** returns a plain tag string, so a `Fitting`, a `Valve`
  or anything else joins on the same terms as a balloon. It composes and does
  not judge: a final control element is not tagged from the measured variable,
  and `CV-303` on the flow loop is the ordinary spelling.
- **`fs.loops`** lists what has been declared. A loop draws nothing, is never in
  `fs.units`, and reaches no equipment list.
- **A loop number is allocated once and never renumbered.** A stream number is
  engine output and is re-derived on every `connect()`; a loop number is author
  intent that leaves the drawing for the DCS.
- **The loop-less form is not legacy.** `add_instrument("TI", 325)` is the right
  spelling for an indicator that is nobody's loop, and a repeated interlock
  square has no measured variable to declare one with.

**A tag names one item**, so `add()` refuses one already on the sheet: two
`P-101`s, or two `LT-101`s, are a mistake in the drawing. Two symbols are the
exception, because each stands for one thing shown in several places. A trip
square is a logic function rather than a device and is drawn at every place it
acts:

```python
squares = [fs.add_instrument("I", 1, variant="logic") for _ in range(4)]
[s.tag for s in squares]     # ['I-1', 'I-1', 'I-1', 'I-1']   drawn four times
[s.name for s in squares]    # ['I-1', 'I-1 (2)', 'I-1 (3)', 'I-1 (4)']
```

A utility header flag — `Feed`/`Product` with `header=True` — is one service
drawn at every place it is tapped, which is how cooling water reaches two
coolers under the one label:

```python
cws = [fs.add(units.Feed("CWSH", header=True)) for _ in range(2)]
[f.tag for f in cws]         # ['CWSH', 'CWSH']       drawn twice
[f.name for f in cws]        # ['CWSH', 'CWSH (2)']
```

The tag repeats; the name does not, so a stream endpoint, a spec entry or an
equipment-list row still means exactly one square, and one tap.

A balloon's `pv`, `sig_in` and `sig_out`, and a valve's `actuator`, are **signal
connections**: nothing flows through them, so they take a signal `kind` and
refuse process fluid, and a process nozzle refuses a signal `kind` in return.
`connect()` raises on either, naming both ports, rather than drawing a pipe into
a valve stem or a control signal down a pipe run.

**Attaching a balloon.** A bubble measures something, so anchor it to that thing
with `on=`.

```python
s   = fs.connect(feed.outlet, fv.inlet)
fs.add_instrument("FE", 101, on=s, at=0.4, offset=0)             # element sits ON the line
ft  = fs.add_instrument("FT", 101, on=s, at=0.4, offset=60)      # transmitter above the tap
lic = fs.add_instrument("LIC", 101, on=drum, at="E", variant="panel")   # mounted on the drum
fs.add_instrument("LAH", 101, on=lic, at="N", offset=48)         # alarm, same loop number
fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")   # interlock square
```

- `on=` a **stream** taps the line, or a **unit** mounts on equipment.
- `at=` is a fraction `0..1` along the host stream's routed path, or a face
  (`"N"`/`"S"`/`"E"`/`"W"`) of a host unit's box.
- `offset=` is the distance from the tap to the balloon centre. `offset=0`
  leaves an in-line primary element sitting on the line.
- `angle=` is the branch direction in degrees from the **flow direction at the
  tap**, counter-clockwise positive (default `90`, i.e. perpendicular). Measured
  from the flow, so a tap keeps its orientation when the line is re-routed.

An impulse line runs from the tap to the balloon: fine and solid to a process
host, dashed where a balloon hangs off another balloon. Attached balloons take
no part in layout ranking and are drawn over the lines, so neither an in-line
element nor a stream number is lost underneath one.

**Final control element.** `Valve.actuator` is the signal connection on top of
the valve, so a controller output terminates on real equipment, at the point
where the line meets the valve.

```python
fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
```

A relief valve is an ordinary `Valve` with `variant="relief"`. Its tag is drawn
as plain text beside the symbol (`PSV-308`), not in a balloon.

Inline fittings (valves, reducers, `Fitting`s) carry the stream number
**through** them. Set `unit.significant = True` to break the number at an
important valve. `connect()` returns the number that gets drawn, so `s.name` is
safe to quote in a report or a stream table of your own.

## Line numbers

A P&ID identifies a line the way the line list does, by size, service, sequence
and spec, because that is what ties the drawing to the stress calculation and the
isometric. Give `connect()` the components and the line is named that way
instead of `S1`:

```python
s = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
s.name        # '6"-P-1001-A1A'
s.sequence    # '1001' filled by auto-numbering, from line_number_start
```

You supply `size`, `service`, `spec` and `insulation`; auto-numbering fills
`sequence`, unless you set it to tie into a line that already exists. The number
carries **through** an in-line valve or strainer and breaks at a unit marked
`significant`, which is exactly where the spec breaks. A component left unset
drops out, so a line with no spec issued yet reads `6"-P-1001`.

The convention is a format string (or a callable), so a site that spells it
differently says so once:

```python
fs = Flowsheet("U100", line_numbering_scheme="{service}-{size}-{sequence:0>6}-{insulation}",
               line_number_start=1)
```

Under `show_stream_table=True` each column is headed by its line number, so a
column ties to a line without a second lookup. A stream with no components set
is numbered exactly as before.

## PFD or P&ID

The two drawings are read by different conventions, so the sheet is told which
one it is:

```python
fs.render("sheet.svg", page_size="A3", border="zone", diagram="p&id")
```

**A P&ID draws no arrowhead on a process line.** Flow direction on one is read
off the equipment and the line list, not off an arrow on every run; the
arrowhead is a PFD convention, where showing where the material goes is the
whole job of the line. `diagram="pfd"` is the default and keeps them. Signal
lines never carried one on either drawing, and neither does a line ending at a
[`Tee`](#equipment--variants) on either: an arrowhead marks where a line arrives
somewhere, and a junction is a point on a line where the line divides.

`"P&ID"`, `"p&id"` and `"pid"` are all accepted. `styling="p&id"` is the
one-word way to ask for a P&ID on the engineering frame, and is the older
spelling of the option.

The frame is a separate choice: `border="zone"` is sheet furniture, and a PFD
carries it as readily as a P&ID does ([example
10](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md#10--ethanol-purification-pfd)
is one), so neither option implies the other.

## Engineering title block & sheet furniture

Give a flowsheet a title block and the sheet is drawn with a full-width
engineering title strip. A PFD carries one as readily as a P&ID does, so no
option turns it on: `border="zone"` is a separate choice, and adds the
zone-ruled drawing frame around whatever furniture the sheet carries.

`title`/`subtitle` are the two title lines, `client` and `project` rule a row
each above them, `company` fills the logo cell and `status` the issue-status
cell. Each `Revision` carries its own `by`/`checked`/`approved` initials, and
the block-level `drawn_by`/`checked_by`/`approved_by` backfill the newest row.

```python
from pandid.document import TitleBlock, Revision

fs.title_block = TitleBlock(
    title="Aromatics Recovery A100", subtitle="Process Flow Diagram 1",
    drawing_number="PFD-1001", company="THE UNIVERSITY OF QUEENSLAND",
    client="Aromatics Australia Pty Ltd", project="Aromatics Recovery Unit",
    status="ISSUED FOR REVIEW", sheet="1", of_sheets="3",
    revisions=[
        Revision("B", "2026-07-01", "Issued for design", "AA", "JS", "RL"),
        Revision("C", "2026-07-12", "Added recycle loop", "AA", "JS", "RL"),
    ],
)
```

`scale` states the scale cell. Left blank it reports the ratio the drawing was
actually placed at, which is a real number once `page_size` fixes the page and
nothing at all on a sheet sized to fit its drawing, where there is no scale to
state.

**Generic titled boxes** dock **flush to the sheet frame**, as on a real
drawing. `align=` is a nine-point grid
(`top-left`/`top`/`top-right`/`left`/`center`/`right`/`bottom-left`/`bottom`/
`bottom-right`) that pins the box's matching corner or edge to the frame's,
inset by an optional `margin=`. `position=(x, y)` instead pins the box's
**top-left corner** at absolute sheet coordinates. Equipment lists, notes and
legends are thin wrappers over `Annotation`, and `TableBox` is a bordered grid
for anything else. Add them with `fs.add_annotation(...)`.

`equipment_list()` schedules **major equipment**: vessels, columns, tanks,
reactors, separators, exchangers, heaters, coolers, furnaces, pumps,
compressors, blowers, turbines, ejectors, filters, dryers and conveyors. Valves, fittings,
reducers, tees, vents and funnels are bulk items bought by the line and covered by the
piping class; mixers and splitters are junctions in that line; feeds, products
and instruments are not equipment. `include=[...]` names the rows explicitly
instead, in the order given, which is how a valve schedule is built from the
same flowsheet.

```python
from pandid.document import equipment_list, notes, legend, Annotation, TableBox

fs.add(units.Column("T-101", description="Beer Column"))   # feeds the equipment list
fs.add_annotation(equipment_list(fs, align="top-right"))
fs.add_annotation(equipment_list(fs, title="VALVE SCHEDULE", align="right",
                                 include=["FV-101", "PSV-101"]))   # a list of its own
fs.add_annotation(notes(["Sampling point on every product line."], align="top"))
fs.add_annotation(legend({"SS": "Stainless Steel 316L"}, align="top-left"))
fs.add_annotation(Annotation(title="HOLD", rows=["Awaiting vendor data"],
                             position=(1200, 90)))          # absolute placement
```

(`anchor=` is still accepted as a deprecated alias for `align=`.)

**Off-page connectors.** A boundary flag's `reference` is drawn as its second
line, naming the drawing the stream comes from or goes to. Only a flag has that
line, so `reference=` on equipment raises rather than being kept and never
drawn.

```python
fs.add(units.Feed("Fermentation Broth", reference="PFD-201"))
```

`location_reference()` composes one that names a sheet or a zone as well, in the
grammar ISO 15519-1 §9 gives (`document`, then `/sheet`, then `.zone`). It
returns a plain string, so `reference=` is unchanged:

```python
from pandid.document import location_reference

units.Product("Azeotropic Ethanol",
              reference=location_reference("PFD-302", sheet="12", zone="B3"))
#                                                          -> "PFD-302/12.B3"
```

**Stream table.** Property rows render in first-seen key order. Values are the
strings you supply and carry their own units. Inject section headers with
`stream_table_sections`.

```python
fs.stream_table_sections = [("Ethanol", "Mass Fraction")]   # header before "Ethanol"
fs.render("sheet.svg", border="zone", show_stream_table=True)
```

## Building a flowsheet from data

An equipment list and a stream table are data, and usually already exist in a
spreadsheet, a YAML file, or a simulator export. Declare the flowsheet as a
plain mapping and hand it to the engine instead of retyping it as Python.

```python
from pandid import Flowsheet

fs   = Flowsheet.from_dict(spec)         # a plain dict, from anywhere
fs   = Flowsheet.from_json("bfw.json")   # standard library only
fs   = Flowsheet.from_yaml("bfw.yaml")   # pip install 'pandid[yaml]'
spec = fs.to_dict()                      # writes the same spec back out

fs.render("bfw.svg", border="zone", show_stream_table=True)
```

`to_dict()` **round-trips**. `Flowsheet.from_dict(fs.to_dict())` rebuilds an
equivalent flowsheet with the same equipment, nozzles, placement and drawing.
Only intent is written, never the engine's results (resolved frames, routed
paths, computed stream numbers), so the file stays short and re-lays out
cleanly. YAML is the one optional extra. `from_dict` and `from_json` need
nothing, and asking for YAML without PyYAML installed says exactly that.

A complete sheet:

```yaml
name: Feed Metering Skid          # the only required field
stream_naming_scheme: "S{n}"
line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
line_number_start: 1001
components: [Water, {name: Ethanol, formula: C2H6O}]

units:
  - {kind: Feed, name: Raw Feed, reference: PFD-100, pin: {x: 60, y: 275}}
  - {kind: Fitting, name: ST-101, variant: strainer, description: Suction Strainer}
  - {kind: Mixer, name: M-101, n_inlets: 3, description: Suction Header}
  - {kind: Pump, name: P-101, description: Feed Pump}
  - {kind: Splitter, name: SP-101, n_outlets: 2, description: Minimum-Flow Tee}
  - {kind: Valve, name: FV-101, variant: control, significant: true,
     description: Spillback Valve}
  - {kind: Vessel, name: V-101, variant: horizontal, width: 130, height: 42,
     description: Surge Drum, port_faces: {inlet: N}}
  - {kind: Product, name: To Unit 200, reference: PFD-200}

loops:
  - {variable: L, number: 101}

instruments:
  - {type: LIC, number: 101, variant: panel, on: V-101, at: S, offset: 110,
     port_faces: {sig_out: W}}

streams:
  - {from: [Raw Feed, outlet], to: [ST-101, inlet]}
  - {from: [ST-101, outlet], to: [M-101, in_1]}
  - {from: [M-101, outlet], to: [P-101, suction]}
  - from: [P-101, discharge]
    to:   [SP-101, inlet]
    size: '6"'
    service: P
    spec: A1A
    properties: {Temperature: 25 C, Pressure: 4.0 barg, Ethanol: "0.92"}
  - {from: [SP-101, out_1], to: [V-101, inlet]}
  - {from: [SP-101, out_2], to: [FV-101, inlet]}
  - {from: [FV-101, outlet], to: [M-101, in_3], tear_hint: true}
  - {from: [V-101, outlet], to: [To Unit 200, inlet]}
  - {from: [LIC-101, sig_out], to: [FV-101, actuator], kind: electric}

stream_table_sections: [[Ethanol, Mass Fraction]]

title_block:
  title: Utilities U200
  subtitle: Process Flow Diagram 1
  drawing_number: PFD-2001
  company: THE UNIVERSITY OF QUEENSLAND
  status: ISSUED FOR REVIEW
  sheet: "1"
  of_sheets: "2"
  revisions:
    - {rev: A, date: 2026-05-18, description: Issued for review, by: AA}
    - {rev: B, date: 2026-07-02, description: Added spillback, by: AA,
       checked: JS, approved: RL}

annotations:
  - {type: equipment_list, align: top-right}
  - {type: notes, align: top, items: [Sampling point on every product line.]}
  - {type: legend, align: top-left, margin: 6, entries: {SS: Stainless Steel 316L}}
  - {type: annotation, title: HOLD, rows: [Awaiting vendor data], position: [1200, 90]}
  - {type: table, title: TIE-INS, headers: [Tag, Line], rows: [[TI-1, 6-P-101]]}
```

**`units`**: `kind` (required) is the equipment class from the list above, in
any spelling you would reasonably write: `HeatExchanger`, `heat_exchanger` or
`hex`. `name` (required) is the tag. Then `variant`, `description` (feeds the
equipment list), `reference` (a boundary flag's off-page drawing), explicit
`width`/`height`, `label_pos`, `significant` (break the stream or line number at
this inline item), `n_inlets` / `n_outlets` for `Mixer` / `Splitter`,
`n_feeds` for `Column` / `Reactor`, `length` for `Conveyor`, `branch`
(`outlet` / `inlet`) for `Tee`, `large_end` (`inlet` / `outlet`) for `Reducer`,
and `normal_position` (`open` / `closed`) for `Valve` and for `Fitting`'s
`blind`.

**`pin` / `port_faces`**: `pin` mirrors `pin()` with `x`/`y` (absolute), `col`/`row`
(grid), `orientation` (`0`/`90`/`180`/`270`) and `mirrored` (`x`/`y`/`xy`).
`port_faces` maps a port to the face it leaves from **as drawn**, so a
mirrored or turned unit takes the face the reader sees. It is an override:
without it the engine picks the face itself, and the top-level `auto_faces:
false` is how you stop it.

**`loops`.** Declared control loops, `{variable: F, number: 303}`, matching
`add_loop()`. Members carry their whole tag, so the section only records that
the loop exists; a sheet that declares none writes no section at all.

**`instruments`.** `type` (required) and `number` make the tag, so
`{type: LIC, number: 101}` is `LIC-101` elsewhere. `on` names the host: a unit,
a named stream, or `[unit, port]` for the line leaving that nozzle. `to_dict()`
writes that last form, since auto-numbered stream names are rewritten at render
time. `at` / `offset` / `angle` / `variant` / `port_faces` behave as in
`add_instrument()`. An instrument with no `on` is laid out like any other unit.

**`streams`.** `from` and `to` are `[unit, port]` pairs (or
`{unit: ..., port: ...}`). `kind` makes a signal line (`electric`, `pneumatic`,
`data`, …), `name` overrides the auto number, `tear_hint` nominates the recycle
to cut, `via` forces waypoints, and `properties` is that line's stream-table
column. `size` / `service` / `spec` / `insulation` are the line-number
components, and `sequence` overrides the one auto-numbering would assign,
which is why `to_dict()` writes the components but never the computed
sequence.

**Sheet furniture.** `title_block` takes the `TitleBlock` fields plus
`revisions`. Each `annotations` entry is one box, typed `equipment_list`,
`notes`, `legend`, `annotation` or `table`, placed with `align` / `position` /
`margin` exactly as above.

**Errors name the entry and what would have worked**, so a typo cannot silently
drop a nozzle off the drawing:

```
units[3] 'P-101': unknown key 'varient' (did you mean 'variant'?); allowed keys:
['description', 'height', 'kind', 'label_pos', 'name', 'pin', 'port_faces', ...]

streams[6].from: Pump 'P-101' has no port 'dischrge' (did you mean 'discharge'?);
available ports: ['discharge', 'suction']
```

Every failure raises `pandid.SpecError`, a `ValueError`.

## Command line

Installing the package installs a `pandid` command, so a spec file becomes a
drawing without opening Python. `python -m pandid` runs the same thing from a
checkout.

```bash
pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone --stream-table
pandid validate plant.yaml
pandid symbols --kind valve
```

`draw` reads a `.yaml`, `.yml` or `.json` spec and writes the format `-o` names:
`.svg`, or `.pdf` / `.png` with the `pdf` extra. Without `-o` it writes the
spec's own name with `.svg`. `--page-size`, `--border`, `--diagram`,
`--stream-table` and `--jump-direction` are the render options, and mean what
they mean in `render()`.

`validate` lays the sheet out and reports what the engine found, errors first
and then warnings. It draws nothing.

```
$ pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone
wrote plant.pdf  (A3, 14 units, 14 streams)

$ pandid validate overlap.yaml
error: unit-overlap: P-101 and FV-101 overlap
warning: route-detour: stream S2 routes 225px for a 55px span (4.1x)
overlap.yaml: 1 error, 1 warning
```

`symbols` lists every registered `(kind, variant)`, grouped by kind, so the
variant names are in front of you while you write the spec. `--kind` takes any
spelling the spec takes (`Valve`, `HeatExchanger`, `hex`).

The exit codes are meant to be gated on: `0` done, `1` the flowsheet was
rejected, `2` the command line was wrong, `3` an optional extra the request
needs is not installed. Nothing prints a traceback at a mistyped file name, an
unknown page size or a typo in the spec; each is one line on stderr saying what
to do instead.

```bash
pandid validate plant.yaml && pandid draw plant.yaml -o plant.pdf
```

## Examples

Runnable scripts in `examples/`, each usable from the repo root or from
`examples/` itself. All eleven are rendered in the
[gallery](https://github.com/Alpha9463/pandid/blob/main/docs/gallery/README.md).

| Script | Demonstrates |
|---|---|
| `01_ammonia_loop.py` | fully automatic layout, layering, recycle detection |
| `02_manual_layout.py` | `pin()` + `.via()` overrides |
| `03_distillation_train.py` | two-column train, recycle, stream table, P&ID title block with revision history, equipment list / notes / legend |
| `04_control_loop.py` | ISA balloons attached to the line and to equipment, alarms, an interlock, a PSV, and both loops closing on a valve actuator |
| `05_reactor_recycle.py` | automatic recycle + purge split, straightened process spine |
| `06_column_reflux.py` | fractionation sheet: overhead condenser, reflux drum, kettle reboiler taking bottoms off its own draw, both loops closing on the column's return nozzles |
| `07_metering_skid.py` | in-line fittings and actuated valves on one spine, PSV to flare, level controller on the valve operator |
| `08_from_data.py` | the whole flowsheet declared as data and built with `Flowsheet.from_dict()` |
| `09_line_numbers.py` | full line numbers (`8"-P-1001-A1A`) carried through in-line fittings and broken at two spec breaks, with the stream table headed by them |
| `10_ethanol_pfd.py` | a whole issue-ready sheet on a real `page_size="A3"` page: beer column with condenser, reflux drum and kettle reboiler, filter-press dewatering, six off-page connectors, equipment list, utilities summary and sectioned stream table |
| `11_ethanol_pid.py` | a whole issued P&ID on a fixed A3 sheet: line numbers on every line, hand-isolated control valve stations, five loops closing on an actuator with one cascade, alarm pairs and a repeated interlock square |

## Architecture

1. **Topology** (`pandid/flowsheet.py`, `pandid/units.py`, `pandid/ports.py`,
   `pandid/streams.py`) holds units, ports, and stream connectivity.
2. **Geometry.** `pandid/layout/` (Sugiyama layering → ordering → coordinates,
   emitting each unit's resolved `Frame`, then port-face selection and label
   placement), `pandid/portgeom.py` (single source of truth for port geometry),
   `pandid/routing/` (visibility graph + A\*).
3. **Render** (`pandid/render/`) produces SVG output, the symbol registry, and
   `pandid/validate.py` / `pandid/document.py`.

Geometry separates *intent* (`Pin`, from `pin()`) from *result* (`Frame`,
computed by the layout engine), so layout is idempotent.

`scripts/vendor_symbols.py` generates the symbol library into
`pandid/render/_vendored_symbols.py`, converting mxGraph stencil XML to SVG via
`scripts/mxgraph_to_svg.py`. `scripts/symbol_sheet.py` renders a catalogue.

## Contributing

See [CONTRIBUTING.md](https://github.com/Alpha9463/pandid/blob/main/CONTRIBUTING.md). The gates are `pytest`, `ruff check .`,
`ruff format --check tests` and `mypy pandid`.

## Licence & attribution

`pandid` is **free for individuals, for research and teaching, and for small
companies**, under the [PolyForm Small Business License 1.0.0](https://polyformproject.org/licenses/small-business/1.0.0).

You may use it at no cost if your company has **fewer than 100 people** and
**under 1,000,000 USD** (2019, inflation adjusted) of revenue in its prior tax
year. Students, academics, hobbyists and small consultancies are covered. A
company above either threshold needs a commercial licence. Contact
`alexandersonxii+pandid@gmail.com`.

This is a source-available licence, not an OSI-approved open-source one, which
matters if your organisation screens dependencies.

**Equipment symbols are Apache-2.0 and stay that way.** They derive from the
draw.io / diagrams.net P&ID stencils, so `pandid/render/_vendored_symbols.py` and
`scripts/vendor_data/drawio/` carry the original licence rather than the one
above, as does the conveyor symbol in `pandid/render/symbols.py`, which is adapted
from a stencil rather than generated from one. The stencil artwork carries one
additional field-of-use restriction on top of Apache-2.0, naming Atlassian
products and marketplace distribution; it does not reach a drawing you make with
`pandid`, and `NOTICE` reproduces it in full for anyone redistributing the
symbols themselves.
[`NOTICE`](https://github.com/Alpha9463/pandid/blob/main/NOTICE)
says exactly which files are which. The full texts are in
[`LICENSE`](https://github.com/Alpha9463/pandid/blob/main/LICENSE) and
[`LICENSE-APACHE`](https://github.com/Alpha9463/pandid/blob/main/LICENSE-APACHE).

# Example gallery

Every script in [`examples/`](../../examples) rendered to SVG and PNG. The PNG is
shown inline (raster, 1600 px wide); the SVG beside each heading is the real
output: vector, searchable text, and what `fs.render("…svg")` actually writes.

These are **generated, not hand-drawn**. To rebuild them, run the examples and
copy their output:

```bash
for f in examples/0*.py; do python "$f"; done
```

Each script writes its SVG next to itself in `examples/` (gitignored); the
gallery copies are those files, with the PNGs rasterized from them by
`cairosvg` at `output_width=1600`. Note that `03` leaves its `TitleBlock.date`
blank, so the renderer stamps the current date and that image changes whenever
it is regenerated.

---

## 01 · Ammonia loop

[`examples/01_ammonia_loop.py`](../../examples/01_ammonia_loop.py) ·
[SVG](01_ammonia_loop.svg)

![Ammonia loop](01_ammonia_loop.png)

Fully automatic: no coordinates anywhere. Seven units and their connections go
in, and the engine assigns layers, orders them, places them on a common flow
axis and routes every stream. The compressor discharge back to the mixer is
detected as the recycle and carried across the top of the sheet, and the streams
are numbered `S1`…`S7` in creation order.

## 02 · Manual layout

[`examples/02_manual_layout.py`](../../examples/02_manual_layout.py) ·
[SVG](02_manual_layout.svg)

![Manual layout](02_manual_layout.png)

The two pixel-level escape hatches. Every unit is `pin(x=…, y=…)`ed, with the
port heights matched so three of the four runs come out dead straight. The
fourth uses `via([...])` to force the stream down, along and back up, an
explicit detour the auto-router would never choose but honours verbatim.

## 03 · Distillation train

[`examples/03_distillation_train.py`](../../examples/03_distillation_train.py) ·
[SVG](03_distillation_train.svg)

![Distillation train](03_distillation_train.png)

The full engineering sheet: `styling="pid"` draws the zone-ruled ASME-style
border and the full-width title strip with its revision history, company cell
and issue status. Around it, furniture docked flush to the frame: an auto
`equipment_list()` built from each unit's `description`, numbered `notes()`, and
a `legend()`. Along the bottom, the stream property table with a "Mass Fraction"
section header injected via `stream_table_sections`. Two columns, their
overheads and bottoms pumps, a bottoms splitter, and a recycle through FV-200
back to the feed mixer. Boundary flags carry off-page `reference`s.

## 04 · Control loop

[`examples/04_control_loop.py`](../../examples/04_control_loop.py) ·
[SVG](04_control_loop.svg)

![Control loop](04_control_loop.png)

ISA-5.1 instrumentation. Two loops, each closing on a real final control
element: FIC-101 drives FV-101's actuator over a pneumatic line, LIC-101 drives
LV-101 over an electric one. FE-101 sits *on* the line (`offset=0`) with
FT-101 above it on the same tap; LIC-101 mounts on the drum's south face with
its high/low alarms alongside on the same loop number and an interlock square
hung underneath on a dashed line. PSV-101 is an ordinary `Valve(variant="relief")`,
tagged as plain text beside the symbol rather than in a balloon.

## 05 · Reactor recycle

[`examples/05_reactor_recycle.py`](../../examples/05_reactor_recycle.py) ·
[SVG](05_reactor_recycle.svg)

![Reactor recycle](05_reactor_recycle.png)

Automatic again, and the clearest demonstration of the straightened spine: feed
→ mixer → compressor → cooler → separator → splitter all land on one horizontal
axis. The splitter purges one outlet to a product flag and recycles
the other back to the mixer; `tear_hint=True` tells the cycle breaker which edge
to tear, and the recycle is routed clear across the top.

## 06 · Column reflux and reboiler

[`examples/06_column_reflux.py`](../../examples/06_column_reflux.py) ·
[SVG](06_column_reflux.svg)

![Column reflux](06_column_reflux.png)

A fractionation sheet drawn the way one actually is: tower on the left,
condenser high and right with the reflux drum beneath it, kettle reboiler off
the bottom. Both loops close on the column itself through its `reflux_in` and
`boilup_in` return nozzles rather than being faked as recycles to an upstream
unit. The sump drains into the kettle and the bottoms product leaves from the
reboiler's own draw at the weir end, so nothing on the sheet is there to make
the topology work. The drum's inlet is authored on three faces and the engine
takes the top one, since the condenser drains straight down onto it, and the
condenser is `mirrored="x"` so it drains toward the drum. Equipment is pinned by
nozzle fraction, which is what makes every run either straight or a single
corner.

## 07 · Metering skid

[`examples/07_metering_skid.py`](../../examples/07_metering_skid.py) ·
[SVG](07_metering_skid.svg)

![Metering skid](07_metering_skid.png)

The in-line fitting and actuated-valve families on one spine: a suction
`strainer`, pump, `rotameter`, a `motor`-operated throttle valve, a surge vessel
with a spring `psv` to flare, and a `sight_glass` on the way out. The valve is
`mirrored="y"` so its operator faces down toward the controller instead of
making the signal climb over the vessel, and LIC-101 takes its output on its
west face because that is the side the valve is on. The only rise on the sheet
is across the pump, whose discharge nozzle really is above its suction.

## 08 · Built from data

[`examples/08_from_data.py`](../../examples/08_from_data.py) ·
[SVG](08_from_data.svg)

![Built from data](08_from_data.png)

The only example that writes no flowsheet code at all: one plain mapping, the
kind you would keep in a YAML file beside the equipment list it came from,
handed to `Flowsheet.from_dict`. Layout, routing and stream numbering run
exactly as they do for the hand-written sheets, and `to_dict()` writes the same
spec back out.

The process is a boiler feedwater package, and it carries a complete ISA-5.1
level loop: `LT-201` on the deaerator measures, `LIC-201` in the control room
decides, and `LY-201` on the valve acts. An electric signal goes into the
controller, an electric signal comes out of it, and a pneumatic line (solid,
double cross-hatched) strokes the actuator. `M-201` is a three-inlet header, which is
the case that used to have nowhere to put its third stream.

## 09 · Line numbers

[`examples/09_line_numbers.py`](../../examples/09_line_numbers.py) ·
[SVG](09_line_numbers.svg)

![Line numbers](09_line_numbers.png)

Every line is labelled the way the line list has it, `8"-P-1001-A1A` for size,
service, sequence and spec, instead of `S1`. The components go in on
`connect()`; the sequence is filled by the same numbering that hands out stream
numbers, so nothing has to be kept unique by hand. The suction line keeps one
number through HV-101 and ST-101, and breaks at the two units marked
`significant`: the spec changes A1A → D1B across FV-101, and the size changes
3" → 4" across PSV-101, which is what a spec break is. The tail-pipe to flare
takes its `sequence` by hand, for a line that already exists on someone else's
list. The stream table underneath is headed by the same line numbers, so a
column ties to a line without a second lookup.

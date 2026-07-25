# Example gallery

Every script in [`examples/`](../../examples) rendered to SVG and PNG. The PNG is
shown inline (raster, 1600 px wide); the SVG beside each heading is the real
output — vector, searchable text, and what `fs.render("…svg")` actually writes.

These are **generated, not hand-drawn**. To rebuild them, run the examples and
copy their output:

```bash
for f in examples/0*.py; do python "$f"; done
```

Each script writes its SVG next to itself in `examples/` (gitignored); the
gallery copies are those files, with the PNGs rasterized from them by
`cairosvg` at `output_width=1600`. Note that `03` leaves its `TitleBlock.date`
blank, so the renderer stamps the current date — that image changes whenever it
is regenerated.

---

## 01 — Ammonia loop

[`examples/01_ammonia_loop.py`](../../examples/01_ammonia_loop.py) ·
[SVG](01_ammonia_loop.svg)

![Ammonia loop](01_ammonia_loop.png)

Fully automatic: no coordinates anywhere. Seven units and their connections go
in, and the engine assigns layers, orders them, places them on a common flow
axis and routes every stream. The compressor discharge back to the mixer is
detected as the recycle and carried across the top of the sheet, and the streams
are numbered `S1`…`S7` in creation order.

## 02 — Manual layout

[`examples/02_manual_layout.py`](../../examples/02_manual_layout.py) ·
[SVG](02_manual_layout.svg)

![Manual layout](02_manual_layout.png)

The two pixel-level escape hatches. Every unit is `pin(x=…, y=…)`ed, with the
port heights matched so three of the four runs come out dead straight. The
fourth uses `via([...])` to force the stream down, along and back up — an
explicit detour the auto-router would never choose, honoured verbatim.

## 03 — Distillation train

[`examples/03_distillation_train.py`](../../examples/03_distillation_train.py) ·
[SVG](03_distillation_train.svg)

![Distillation train](03_distillation_train.png)

The full engineering sheet: `styling="pid"` draws the zone-ruled ASME-style
border and the full-width title strip with its revision history, company cell
and issue status. Around it, furniture docked flush to the frame — an auto
`equipment_list()` built from each unit's `description`, numbered `notes()`, and
a `legend()`. Along the bottom, the stream property table with a "Mass Fraction"
section header injected via `stream_table_sections`. Two columns, their
overheads and bottoms pumps, a bottoms splitter, and a recycle through FV-200
back to the feed mixer. Boundary flags carry off-page `reference`s.

## 04 — Control loop

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

## 05 — Reactor recycle

[`examples/05_reactor_recycle.py`](../../examples/05_reactor_recycle.py) ·
[SVG](05_reactor_recycle.svg)

![Reactor recycle](05_reactor_recycle.png)

Automatic again, and the clearest demonstration of the straightened spine: feed
→ mixer → compressor → cooler → separator → splitter all land on one horizontal
axis. The splitter purges one outlet to a product flag and recycles
the other back to the mixer; `tear_hint=True` tells the cycle breaker which edge
to tear, and the recycle is routed clear across the top.

## 06 — Column reflux and reboiler

[`examples/06_column_reflux.py`](../../examples/06_column_reflux.py) ·
[SVG](06_column_reflux.svg)

![Column reflux](06_column_reflux.png)

A fractionation sheet drawn the way one actually is: tower on the left,
condenser high and right with the reflux drum beneath it, kettle reboiler off
the bottom. Both loops close on the column itself through its `reflux_in` and
`boilup_in` return nozzles rather than being faked as recycles to an upstream
unit. The drum's inlet is moved to its top face with `nozzle("inlet", "N")`
so the condenser drains straight down into it, and the condenser is
`mirrored="x"` so it drains toward the drum. Equipment is pinned by nozzle
fraction, which is what makes every run either straight or a single corner.

## 07 — Metering skid

[`examples/07_metering_skid.py`](../../examples/07_metering_skid.py) ·
[SVG](07_metering_skid.svg)

![Metering skid](07_metering_skid.png)

The in-line fitting and actuated-valve families on one spine: a suction
`strainer`, pump, `rotameter`, a `motor`-operated throttle valve, a surge vessel
with a spring `psv` to flare, and a `sight_glass` on the way out. The valve is
`mirrored="y"` so its operator faces down toward the controller instead of
making the signal climb over the vessel, and LIC-101 takes its output on the
west face via `nozzle("sig_out", "W")`. The only rise on the sheet is across
the pump, whose discharge nozzle really is above its suction.

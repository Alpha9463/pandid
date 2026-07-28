"""Golden-file SVG regression over a fixed corpus: the first nine examples'
flowsheets, three of which (03, 08 and 09) also exercise ``border="zone"`` with
the stream table and sheet furniture (title block, equipment list, notes,
legend).

The flowsheets are rebuilt here rather than by importing examples/*.py: those
scripts render straight to a file under examples/ (a side effect a test suite
shouldn't have), and 03's and 08's TitleBlocks leave ``date`` empty, which
SvgRenderer fills in with ``datetime.now()`` -- fine for a real render, but it
would make the golden change every day. Every other input is copied verbatim
from the matching example script; for 08, whose example *is* data, the copied
input is its spec mapping. See tests/golden/README.md for how to regenerate.
"""

import os
from pathlib import Path

import pytest

from pandid import Flowsheet, units
from pandid.document import Revision, TitleBlock, equipment_list, legend, notes

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("PANDID_UPDATE_GOLDEN") == "1"


# --- scenarios, one per example -----------------------------------------------


def _ammonia_loop() -> Flowsheet:
    fs = Flowsheet("Ammonia Loop Auto")
    feed = fs.add(units.Feed("Natural Gas"))
    mix = fs.add(units.Mixer("M-101"))
    reformer = fs.add(units.Reactor("R-101"))
    hx = fs.add(units.HeatExchanger("E-101"))
    sep = fs.add(units.Separator("V-101"))
    comp = fs.add(units.Compressor("K-101"))
    prod = fs.add(units.Product("Ammonia"))
    fs.connect(feed.outlet, mix.in_2)
    fs.connect(mix.outlet, reformer.feed)
    fs.connect(reformer.outlet, hx.shell_in)
    fs.connect(hx.shell_out, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.connect(comp.discharge, mix.in_1)
    fs.connect(sep.liquid, prod.inlet)
    return fs


def _manual_layout() -> Flowsheet:
    fs = Flowsheet("Manual Override Example")
    f1 = fs.add(units.Feed("F-1")).pin(x=60, y=105)
    e1 = fs.add(units.HeatExchanger("E-1")).pin(x=210, y=100)
    p1 = fs.add(units.Product("P-1")).pin(x=430, y=105)
    f2 = fs.add(units.Feed("F-2")).pin(x=60, y=305)
    e2 = fs.add(units.HeatExchanger("E-2")).pin(x=210, y=300)
    p2 = fs.add(units.Product("P-2")).pin(x=430, y=305)
    fs.connect(f1.outlet, e1.tube_in)
    fs.connect(e1.tube_out, p1.inlet)
    fs.connect(f2.outlet, e2.tube_in)
    fs.connect(e2.tube_out, p2.inlet).via(
        [
            (360, 330),
            (360, 380),
            (410, 380),
            (410, 330),
        ]
    )
    return fs


def _distillation_train() -> Flowsheet:
    fs = Flowsheet("Distillation Train")
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-1000"))
    mixer = fs.add(units.Mixer("M-100", n_inlets=2, description="Feed Mixer Drum"))
    feed_valve = fs.add(units.Valve("FV-100"))
    preheater = fs.add(units.HeatExchanger("E-100", description="Feed Preheater"))
    col1 = fs.add(units.Column("T-100", description="Light Ends Column"))
    c1_ovhd = fs.add(units.HeatExchanger("E-101", description="T-100 Overhead Condenser"))
    c1_prod = fs.add(units.Product("Light Product", reference="PFD-1002"))
    pump1 = fs.add(units.Pump("P-100A/B", description="T-100 Bottoms Pump"))
    col2 = fs.add(units.Column("T-200", description="Product Column"))
    c2_ovhd = fs.add(units.HeatExchanger("E-201", description="T-200 Overhead Condenser"))
    c2_prod = fs.add(units.Product("Med Product", reference="PFD-1002"))
    pump2 = fs.add(units.Pump("P-200A/B", description="T-200 Bottoms Pump"))
    splitter = fs.add(units.Splitter("SP-200", n_outlets=2, description="Bottoms Splitter"))
    c2_bot = fs.add(units.Product("Heavy Product", reference="PFD-1003"))
    recycle_valve = fs.add(units.Valve("FV-200"))

    col_y = 420
    mixer_y = col_y + 105 - 25
    feed_y = mixer_y - 10
    valve_y = col_y + 105 - 15
    hx_y = col_y + 105 - 30

    feed.pin(x=160, y=feed_y)
    mixer.pin(x=290, y=mixer_y)
    feed_valve.pin(x=410, y=valve_y)
    preheater.pin(x=520, y=hx_y)
    col1.pin(x=690, y=col_y)
    ovhd_y = col_y - 80
    c1_ovhd.pin(x=820, y=ovhd_y)
    c1_prod.pin(x=980, y=ovhd_y + 5)
    bot_y = col_y + 205 + 30
    pump1.pin(x=820, y=bot_y)
    col2.pin(x=1100, y=col_y)
    c2_ovhd.pin(x=1230, y=ovhd_y)
    c2_prod.pin(x=1390, y=ovhd_y + 5)
    pump2.pin(x=1230, y=bot_y)
    splitter.pin(x=1360, y=bot_y - 100)
    c2_bot.pin(x=1480, y=bot_y - 110)
    recycle_valve.pin(x=590, y=bot_y + 100, mirrored=True)

    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, feed_valve.inlet)
    fs.connect(feed_valve.outlet, preheater.tube_in)
    fs.connect(preheater.tube_out, col1.feed)
    fs.connect(col1.distillate, c1_ovhd.tube_in)
    fs.connect(c1_ovhd.tube_out, c1_prod.inlet)
    fs.connect(col1.bottoms, pump1.suction)
    fs.connect(pump1.discharge, col2.feed)
    fs.connect(col2.distillate, c2_ovhd.tube_in)
    fs.connect(c2_ovhd.tube_out, c2_prod.inlet)
    fs.connect(col2.bottoms, pump2.suction)
    fs.connect(pump2.discharge, splitter.inlet)
    fs.connect(splitter.out_1, c2_bot.inlet)
    fs.connect(splitter.out_2, recycle_valve.inlet)
    fs.connect(recycle_valve.outlet, mixer.in_2, tear_hint=True)

    for i, s in enumerate(fs.streams):
        s.properties = {
            "Temperature (°C)": f"{25 + i * 5} C",
            "Pressure (bar)": f"{1.0 + i * 0.1:.1f} bar",
            "Total Flow (kg/h)": f"{1000 - i * 10}",
            "Benzene": f"{0.90 - i * 0.02:.2f}",
            "Toluene": f"{0.10 + i * 0.02:.2f}",
        }
    fs.stream_table_sections = [("Benzene", "Mass Fraction")]

    # date is fixed (not left blank) so the golden never drifts with today's date.
    fs.title_block = TitleBlock(
        title="Aromatics Recovery A100",
        subtitle="Process Flow Diagram 1",
        drawing_number="PFD-1001",
        project="Aromatics Recovery Unit",
        client="Aromatics Australia Pty Ltd",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="3",
        scale="NTS",
        drawn_by="A. Anderson",
        checked_by="J. Smith",
        approved_by="R. Lee",
        date="2026-01-01",
        revisions=[
            Revision("A", "2026-06-01", "Issued for internal review", "AA"),
            Revision("B", "2026-07-01", "Issued for design", "AA", "JS", "RL"),
            Revision("C", "2026-07-12", "Added FV-200 recycle loop", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(equipment_list(fs, align="top-right"))
    fs.add_annotation(
        notes(
            [
                "Sampling point on every product line.",
                "All instruments field-mounted unless noted.",
                "Recycle valve FV-200 fails open.",
            ],
            align="top-right",
        )
    )
    fs.add_annotation(
        legend(
            {
                "PFD": "Process Flow Diagram",
                "FV": "Flow Control Valve",
                "NTS": "Not To Scale",
            },
            align="top-left",
        )
    )
    return fs


def _control_loop() -> Flowsheet:
    fs = Flowsheet("Flow Control Loop")
    # Two declared loops, both numbered 101: the identity is the pair. The tags
    # they mint are the literal ones this fixture was drawn with, so the golden
    # is the proof that declaring a loop moves nothing on the sheet.
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(units.Valve(flow.tag("FV"), variant="control")).pin(x=270, y=180)
    drum = fs.add(units.Vessel("V-101", description="Surge Drum")).pin(x=420, y=145)
    lv = fs.add(units.Valve(level.tag("LV"), variant="control")).pin(x=640, y=180)
    prod = fs.add(units.Product("Product")).pin(x=790, y=170)
    psv = fs.add(units.Valve("PSV-101", variant="relief")).pin(x=441, y=55)
    flare = fs.add(units.Product("To Flare", reference="P&ID-902")).pin(x=630, y=5)

    line = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    fs.add_instrument("FE", flow, on=line, at=0.5, offset=0)
    ft = fs.add_instrument("FT", flow, on=line, at=0.5, offset=62)
    fic = fs.add_instrument("FIC", flow, on=ft, at="N", offset=125, angle=35, variant="panel")
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    lic = fs.add_instrument("LIC", level, on=drum, at="S", offset=90, variant="panel")
    lah = fs.add_instrument("LAH", level, on=lic, at="W", offset=50)
    fs.add_instrument("LAL", level, on=lah, at="W", offset=50)
    # In no loop and with no measured variable: a repeatable logic function
    # takes a literal number, and has to keep being able to.
    fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")
    return fs


def _reactor_recycle() -> Flowsheet:
    fs = Flowsheet("Reactor Recycle Loop")
    feed = fs.add(units.Feed("Syngas Feed"))
    mix = fs.add(units.Mixer("M-201", n_inlets=2))
    comp = fs.add(units.Compressor("K-201"))
    rx = fs.add(units.Reactor("R-201"))
    cool = fs.add(units.Cooler("E-201"))
    sep = fs.add(units.Separator("V-201"))
    split = fs.add(units.Splitter("SP-201", n_outlets=2))
    prod = fs.add(units.Product("Liquid Product"))
    purge = fs.add(units.Product("Purge Gas"))
    fs.connect(feed.outlet, mix.in_2)
    fs.connect(mix.outlet, comp.suction)
    fs.connect(comp.discharge, rx.feed)
    fs.connect(rx.outlet, cool.inlet)
    fs.connect(cool.outlet, sep.feed)
    fs.connect(sep.liquid, prod.inlet)
    fs.connect(sep.vapor, split.inlet)
    fs.connect(split.out_2, purge.inlet)
    fs.connect(split.out_1, mix.in_1, tear_hint=True)
    return fs


def _column_reflux() -> Flowsheet:
    fs = Flowsheet("Column Overhead System")
    feed = fs.add(units.Feed("Feed", reference="PFD-100"))
    col = fs.add(units.Column("T-701", description="Main Fractionator"))
    cond = fs.add(
        units.HeatExchanger(
            "E-701",
            variant="straight_tubes",
            width=120,
            height=36,
            description="Overhead Condenser",
        )
    )
    drum = fs.add(
        units.Vessel("V-701", variant="horizontal", width=130, height=42, description="Reflux Drum")
    )
    vent = fs.add(units.Product("Vent Gas", reference="PFD-900"))
    split = fs.add(units.Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(units.Product("Distillate", reference="PFD-200"))
    reb = fs.add(
        units.HeatExchanger(
            "E-702", variant="kettle", width=120, height=44, description="Kettle Reboiler"
        )
    )
    bot = fs.add(units.Product("Bottoms", reference="PFD-300"))

    col_x, col_y = 300, 260
    col.pin(x=col_x, y=col_y)
    feed.pin(x=90, y=col_y + 105)
    cond_x, cond_y, cond_w = 560, 70, 120
    cond.pin(x=cond_x, y=cond_y, mirrored="x")
    cond_drain_x = cond_x + 0.75 * cond_w
    drum_w, drum_y = 130, 170
    drum.pin(x=cond_drain_x - (20 / 91.5) * drum_w, y=drum_y)
    drum_x = cond_drain_x - (20 / 91.5) * drum_w
    drum_draw_x = drum_x + (68 / 91.5) * drum_w
    vent.pin(x=880, y=100)
    split.pin(x=drum_draw_x - 25, y=240, orientation=90)
    dist.pin(x=900, y=315)
    reb.pin(x=660, y=512)
    bot.pin(x=900, y=620)

    fs.connect(feed.outlet, col.feed)
    fs.connect(col.distillate, cond.shell_in)
    fs.connect(cond.shell_out, drum.inlet)
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.outlet, split.inlet)
    fs.connect(split.out_1, dist.inlet)
    fs.connect(split.out_2, col.reflux_in, tear_hint=True)
    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, tear_hint=True)
    fs.connect(reb.bottoms, bot.inlet)
    return fs


def _metering_skid() -> Flowsheet:
    fs = Flowsheet("Feed Metering Skid")
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-100"))
    strainer = fs.add(units.Fitting("ST-101", variant="strainer", description="Suction Strainer"))
    pump = fs.add(units.Pump("P-101", description="Feed Pump"))
    meter = fs.add(
        units.Fitting("FI-101", variant="rotameter", description="Variable-Area Flow Meter")
    )
    fv = fs.add(units.Valve("FV-101", variant="motor", description="Motor-Operated Throttle Valve"))
    surge = fs.add(units.Vessel("V-101", width=90, height=140, description="Surge Vessel"))
    psv = fs.add(
        units.Valve(
            "PSV-101", variant="psv", width=40, height=68, description="Vessel Relief Valve"
        )
    )
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    glass = fs.add(units.Fitting("SG-101", variant="sight_glass", description="Sight Glass"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    feed.pin(x=60, y=275)
    strainer.pin(x=190, y=280)
    pump.pin(x=280, y=270)
    meter.pin(x=430, y=265)
    fv.pin(x=540, y=265.3, mirrored="y")
    surge.pin(x=680, y=210)
    glass.pin(x=850, y=267.5)
    prod.pin(x=980, y=255)
    surge_vent_x = 680 + (31 / 62) * 90
    psv.pin(x=surge_vent_x - (10.5 / 27.8) * 40, y=110)
    flare.pin(x=900, y=110 + (30.2 / 47.2) * 68 - 25)

    fs.connect(feed.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)
    fs.connect(pump.discharge, meter.inlet)
    fs.connect(meter.outlet, fv.inlet)
    fs.connect(fv.outlet, surge.inlet)
    fs.connect(surge.outlet, glass.inlet)
    fs.connect(glass.outlet, prod.inlet)
    fs.connect(surge.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    lic = fs.add_instrument("LIC", 101, on=surge, at="S", offset=115, variant="panel")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    return fs


def _from_data() -> Flowsheet:
    """Example 08 -- the whole flowsheet declared as data, not as code.

    Its input *is* a mapping, so this reads the example's own ``SPEC`` instead
    of keeping a second copy of it in step by hand. A local copy drifts silently
    -- an edit to the example never reaches it -- leaving the golden guarding a
    sheet nobody draws.

    Importing the module does not render anything -- the example guards that
    behind ``__main__`` -- but it does leave the title block's date blank for
    SvgRenderer to fill in with today's, which would move the golden every day.
    That one field is pinned here.
    """
    import copy
    import importlib.util
    import sys

    examples = Path(__file__).resolve().parent.parent / "examples"
    sys.path.insert(0, str(examples))  # the example's own _bootstrap
    try:
        spec = importlib.util.spec_from_file_location(
            "_golden_example_08", examples / "08_from_data.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(examples))

    data = copy.deepcopy(module.SPEC)
    data["title_block"]["date"] = "2026-01-01"
    return Flowsheet.from_dict(data)


def _line_numbers() -> Flowsheet:
    fs = Flowsheet("Transfer and Relief")
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-100"))
    hv = fs.add(units.Valve("HV-101", description="Suction Isolation Valve"))
    strainer = fs.add(units.Fitting("ST-101", variant="strainer", description="Suction Strainer"))
    pump = fs.add(units.Pump("P-101", description="Transfer Pump"))
    fv = fs.add(units.Valve("FV-101", variant="control", description="Discharge Control Valve"))
    surge = fs.add(units.Vessel("V-101", width=90, height=140, description="Surge Vessel"))
    psv = fs.add(
        units.Valve(
            "PSV-101", variant="psv", width=40, height=68, description="Vessel Relief Valve"
        )
    )
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    fv.significant = True
    psv.significant = True

    feed.pin(x=60, y=275)
    hv.pin(x=235, y=285)
    strainer.pin(x=335, y=280)
    pump.pin(x=425, y=270)
    fv.pin(x=575, y=265)
    surge.pin(x=725, y=210)
    prod.pin(x=925, y=255)
    surge_vent_x = 725 + (31 / 62) * 90
    psv.pin(x=surge_vent_x - (10.5 / 27.8) * 40, y=110)
    flare.pin(x=945, y=110 + (30.2 / 47.2) * 68 - 25)

    suction = fs.connect(feed.outlet, hv.inlet, size='8"', service="P", spec="A1A")
    fs.connect(hv.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)
    discharge = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
    downstream = fs.connect(fv.outlet, surge.inlet, size='6"', service="P", spec="D1B")
    to_unit = fs.connect(surge.outlet, prod.inlet, size='6"', service="P", spec="D1B")
    relief = fs.connect(surge.vent, psv.inlet, size='3"', service="P", spec="A1A")
    tail = fs.connect(psv.outlet, flare.inlet, size='4"', service="FL", sequence=2740, spec="A1A")

    conditions = [
        (suction, "25 C", "1.2 bara", "42000"),
        (discharge, "26 C", "9.5 bara", "42000"),
        (downstream, "26 C", "4.0 bara", "42000"),
        (to_unit, "26 C", "3.6 bara", "42000"),
        (relief, "26 C", "4.0 bara", "0"),
        (tail, "26 C", "1.1 bara", "0"),
    ]
    for stream, temperature, pressure, flow in conditions:
        stream.properties = {
            "Temperature": temperature,
            "Pressure": pressure,
            "Mass Flow (kg/h)": flow,
        }

    fs.title_block = TitleBlock(
        title="Transfer and Relief U100",
        subtitle="Piping and Instrumentation Diagram",
        drawing_number="P&ID-1009",
        project="Feed Transfer Package",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        drawn_by="A. Anderson",
        checked_by="J. Smith",
        date="2026-07-15",
        revisions=[
            Revision("A", "2026-06-20", "Issued for internal review", "AA"),
            Revision("B", "2026-07-15", "Line numbers added", "AA", "JS"),
        ],
    )
    return fs


SCENARIOS = {
    "01_ammonia_loop": (_ammonia_loop, {}),
    "02_manual_layout": (_manual_layout, {}),
    "03_distillation_train": (_distillation_train, {"show_stream_table": True, "border": "zone"}),
    "04_control_loop": (_control_loop, {}),
    "05_reactor_recycle": (_reactor_recycle, {}),
    "06_column_reflux": (_column_reflux, {}),
    "07_metering_skid": (_metering_skid, {}),
    "08_from_data": (_from_data, {"show_stream_table": True, "border": "zone"}),
    # 09 is issued as a P&ID -- line numbers, "P&ID-1009" -- and is the one
    # scenario drawn as one, so it is also what guards the arrowless process
    # line. Every other scenario is a PFD and keeps its arrowheads.
    "09_line_numbers": (
        _line_numbers,
        {"show_stream_table": True, "border": "zone", "diagram": "p&id"},
    ),
}


# --- normalization + comparison -----------------------------------------------


def _normalize(svg: str) -> str:
    """Canonicalize ordering the renderer itself does not guarantee.

    ``SvgRenderer._defs()`` builds its marker/symbol defs from Python ``set``s
    (``used_colors``, ``used_symbols``), so their order in the output depends
    on the process's string-hash seed, not on anything about the diagram --
    confirmed by rendering one flowsheet under several ``PYTHONHASHSEED``
    values and diffing the result. Sorting each group canonicalizes that away
    so two renders of an identical flowsheet always compare equal; every other
    line is left untouched so a real regression still shows up.
    """
    lines = svg.split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<defs>")
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</defs>")
    except StopIteration:
        return svg
    body = lines[start + 1 : end]
    markers = []
    j = 0
    while j < len(body) and body[j].strip().startswith("<marker "):
        markers.append(tuple(body[j : j + 3]))
        j += 3
    symbols = sorted(body[j:])
    markers.sort()
    new_body = [line for group in markers for line in group] + symbols
    return "\n".join(lines[: start + 1] + new_body + lines[end:])


def _diff_message(name: str, golden: str, actual: str) -> str:
    """First differing line with a little context -- not a 40KB dump."""
    exp = golden.split("\n")
    act = actual.split("\n")
    for i, (e, a) in enumerate(zip(exp, act)):
        if e == a:
            continue
        lo, hi = max(0, i - 2), min(max(len(exp), len(act)), i + 3)
        ctx = []
        for k in range(lo, hi):
            ek = exp[k] if k < len(exp) else "<no line>"
            ak = act[k] if k < len(act) else "<no line>"
            mark = ">>" if k == i else "  "
            ctx.append(f"{mark} [{k}] golden: {ek}")
            ctx.append(f"{mark} [{k}] actual: {ak}")
        return f"{name}: first mismatch at line {i} of {max(len(exp), len(act))}\n" + "\n".join(ctx)
    return f"{name}: identical prefix but line counts differ (golden {len(exp)}, actual {len(act)})"


def _check_golden(name: str, svg: str) -> None:
    path = GOLDEN_DIR / f"{name}.svg"
    normalized = _normalize(svg)
    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"no golden at {path}; regenerate with PANDID_UPDATE_GOLDEN=1", pytrace=False)
    golden = _normalize(path.read_text(encoding="utf-8"))
    if golden != normalized:
        pytest.fail(_diff_message(name, golden, normalized), pytrace=False)


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_golden_svg(name):
    build, kwargs = SCENARIOS[name]
    fs = build()
    svg = fs.to_svg(**kwargs)
    _check_golden(name, svg)


def test_the_fractionator_schedules_only_equipment_that_exists():
    """The bottoms product leaves over the reboiler's weir, off the kettle's own
    draw. Splitting the sump line instead needs a piece of equipment that is not
    in the plant, and the sheet would then carry a tag for it."""
    fs = _column_reflux()
    col = next(u for u in fs.units if u.name == "T-701")
    reb = next(u for u in fs.units if u.name == "E-702")
    assert col.bottoms.stream.dest.owner is reb  # nothing invented in the sump
    assert reb.bottoms.stream is not None
    assert reb.bottoms.stream.dest.owner.name == "Bottoms"
    assert [tag for tag, _ in equipment_list(fs).rows] == [
        "T-701",
        "E-701",
        "V-701",
        "E-702",
    ]

"""Golden-file SVG regression over a fixed corpus: one scenario per example.

Five of them (03, 08, 09, 10 and 11) draw the zone-ruled border and the sheet
furniture -- title block, equipment list, notes, legend -- with a stream table
on all but 11. 09 and 11 are the two issued as P&IDs, and 10 and 11 the two on
a fixed A3 page.

The flowsheets are rebuilt here rather than by importing examples/*.py: those
scripts render straight to a file under examples/ (a side effect a test suite
shouldn't have), and 03's and 08's TitleBlocks leave ``date`` empty, which
SvgRenderer fills in with ``datetime.now()`` -- fine for a real render, but it
would make the golden change every day. 10's and 11's title blocks state their
own dates, so those two need no pinning. Every other input is copied verbatim
from the matching example script; for 08, whose example *is* data, the copied
input is its spec mapping. See tests/golden/README.md for how to regenerate.
"""

import os
from pathlib import Path

import pytest

from pandid import Flowsheet, units
from pandid.document import (
    Annotation,
    Revision,
    TableBox,
    TitleBlock,
    equipment_list,
    legend,
    notes,
)
from pandid.portgeom import port_offset, resolve_size

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
    c1_drum = fs.add(
        units.Vessel(
            "V-101", variant="horizontal", width=130, height=42, description="T-100 Reflux Drum"
        )
    )
    c1_tee = fs.add(units.Tee())
    c1_reb = fs.add(
        units.HeatExchanger(
            "E-102", variant="kettle", width=120, height=44, description="T-100 Kettle Reboiler"
        )
    )
    c1_prod = fs.add(units.Product("Light Product", reference="PFD-1002"))
    pump1 = fs.add(units.Pump("P-100A/B", description="T-100 Bottoms Pump"))
    col2 = fs.add(units.Column("T-200", description="Product Column"))
    c2_ovhd = fs.add(units.HeatExchanger("E-201", description="T-200 Overhead Condenser"))
    c2_drum = fs.add(
        units.Vessel(
            "V-201", variant="horizontal", width=130, height=42, description="T-200 Reflux Drum"
        )
    )
    c2_tee = fs.add(units.Tee())
    c2_reb = fs.add(
        units.HeatExchanger(
            "E-202", variant="kettle", width=120, height=44, description="T-200 Kettle Reboiler"
        )
    )
    c2_prod = fs.add(units.Product("Med Product", reference="PFD-1002"))
    pump2 = fs.add(units.Pump("P-200A/B", description="T-200 Bottoms Pump"))
    splitter = fs.add(units.Splitter("SP-200", n_outlets=2, description="Bottoms Splitter"))
    c2_bot = fs.add(units.Product("Heavy Product", reference="PFD-1003"))
    recycle_valve = fs.add(units.Valve("FV-200"))

    col_y = 420
    col1.pin(x=690, y=col_y)

    feed_run_y = col_y + port_offset(col1, "feed")[1]
    mixer.pin(x=290).pin(port="outlet", y=feed_run_y)
    feed.pin(port="outlet", x=210, y=mixer.pin_.y + port_offset(mixer, "in_1")[1])
    feed_valve.pin(x=410, port="inlet", y=feed_run_y)
    preheater.pin(x=520, port="tube_in", y=feed_run_y)

    col2.pin(x=1260, y=col_y)
    ovhd_run_y = col_y - 130
    drum_y = col_y - 105
    tee_y = col_y - 5
    bot_y = col_y + 225
    pump_y = bot_y + 85

    c1_axis = col1.pin_.x + port_offset(col1, "distillate")[0]
    c2_axis = col2.pin_.x + port_offset(col2, "distillate")[0]

    c1_ovhd.pin(mirrored="y").pin(x=c1_axis, port="shell_in", y=ovhd_run_y)
    c2_ovhd.pin(mirrored="y").pin(x=c2_axis, port="shell_in", y=ovhd_run_y)

    c1_drum.nozzle("inlet", "N").pin(port="inlet", x=c1_axis + 200, y=drum_y)
    c2_drum.nozzle("inlet", "N").pin(port="inlet", x=c2_axis + 200, y=drum_y)

    for tee, drum, prod, prod_x in (
        (c1_tee, c1_drum, c1_prod, 1070),
        (c2_tee, c2_drum, c2_prod, 1640),
    ):
        tee.pin(orientation=90, mirrored="y")
        tee.pin(port="inlet", x=drum.pin_.x + port_offset(drum, "outlet")[0])
        tee.pin(port="branch", y=tee_y)
        prod.pin(x=prod_x, port="inlet", y=tee_y)

    c1_reb.pin(x=c1_axis + 90, y=bot_y)
    c2_reb.pin(x=c2_axis + 90, y=bot_y)
    pump1.pin(x=1010, port="suction", y=pump_y)
    pump2.pin(x=1580, port="suction", y=pump_y)

    splitter.pin(x=1710, y=bot_y - 40)
    c2_bot.pin(x=1830, port="inlet", y=splitter.pin_.y + port_offset(splitter, "out_1")[1])
    recycle_valve.pin(x=590, y=pump_y + 110, mirrored=True)

    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, feed_valve.inlet)
    fs.connect(feed_valve.outlet, preheater.tube_in)
    fs.connect(preheater.tube_out, col1.feed)

    fs.connect(col1.distillate, c1_ovhd.shell_in)
    fs.connect(c1_ovhd.shell_out, c1_drum.inlet)
    fs.connect(c1_drum.outlet, c1_tee.inlet)
    fs.connect(c1_tee.outlet, col1.reflux_in, draw_as_recycle=True)
    fs.connect(c1_tee.branch, c1_prod.inlet)

    fs.connect(col1.bottoms, c1_reb.shell_in)
    fs.connect(c1_reb.shell_out, col1.boilup_in, draw_as_recycle=True)
    fs.connect(c1_reb.bottoms, pump1.suction)
    fs.connect(pump1.discharge, col2.feed)

    fs.connect(col2.distillate, c2_ovhd.shell_in)
    fs.connect(c2_ovhd.shell_out, c2_drum.inlet)
    fs.connect(c2_drum.outlet, c2_tee.inlet)
    fs.connect(c2_tee.outlet, col2.reflux_in, draw_as_recycle=True)
    fs.connect(c2_tee.branch, c2_prod.inlet)

    fs.connect(col2.bottoms, c2_reb.shell_in)
    fs.connect(c2_reb.shell_out, col2.boilup_in, draw_as_recycle=True)
    fs.connect(c2_reb.bottoms, pump2.suction)
    fs.connect(pump2.discharge, splitter.inlet)

    fs.connect(splitter.out_1, c2_bot.inlet)
    fs.connect(splitter.out_2, recycle_valve.inlet)
    fs.connect(recycle_valve.outlet, mixer.in_2, draw_as_recycle=True)

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
        company="PANDID",
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
            Revision("D", "2026-07-28", "Reflux and reboiler added", "AA", "JS", "RL"),
            Revision("E", "2026-08-01", "Reflux drums raised", "AA", "JS", "RL"),
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
    run_y = 195
    feed = fs.add(units.Feed("Feed")).pin(port="outlet", x=110, y=run_y)
    fv = fs.add(units.Valve(flow.tag("FV"), variant="control")).pin(x=270, port="inlet", y=run_y)
    drum = fs.add(units.Vessel("V-101", description="Surge Drum")).pin(x=420, port="inlet", y=run_y)
    fe = fs.add(
        units.Fitting(flow.tag("FE"), variant="orifice", description="Feed Orifice Plate")
    ).pin(x=180, port="inlet", y=run_y)
    lv = fs.add(units.Valve(level.tag("LV"), variant="control")).pin(
        x=640, port="inlet", y=run_y, mirrored="y"
    )
    prod = fs.add(units.Product("Product")).pin(port="inlet", x=790, y=run_y)
    psv = (
        fs.add(units.Valve("PSV-101", variant="relief"))
        .pin(y=55)
        .pin(port="inlet", x=420 + port_offset(drum, "vent")[0])
    )
    flare = fs.add(units.Product("To Flare", reference="P&ID-902")).pin(x=630, y=5)

    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Both controllers are circle-in-square, ISA-5.1's shared display and shared
    # control; the bare circle of "panel" says the instrument only reads.
    ft = fs.add_instrument("FT", flow, on=fe, at="N", offset=62)
    fic = fs.add_instrument("FIC", flow, on=ft, at="N", offset=125, angle=35, variant="shared")
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Element -> transmitter -> controller on the level as well as on the flow:
    # the impulse line off the drum reaches LT-101 and the controller reads it.
    lt = fs.add_instrument("LT", level, on=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", level, on=lt, at="S", offset=95, variant="shared")
    # One face each, at the default angle, so every impulse line runs square,
    # and squared like the controller because the square is the DCS point:
    # see the comment on the same four balloons in examples/04_control_loop.py.
    fs.add_instrument("LAH", level, on=lic, at="W", offset=78, variant="shared")
    fs.add_instrument("LAL", level, on=lic, at="S", offset=78, variant="shared")
    # In no loop and with no measured variable: a repeatable logic function
    # takes a literal number, and has to keep being able to. Teed off the
    # measurement signal line rather than off a balloon face, which is also the
    # fixture that keeps a stream-hosted tap in the golden corpus -- it is drawn
    # dashed, and the two process taps above it are not.
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("I", 1, on=measurement, at=0.5, offset=44, angle=90, variant="logic")
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
    fs.connect(split.out_1, mix.in_1, draw_as_recycle=True)
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
    feed.pin(x=90, y=col_y + port_offset(col, "feed")[1] - 25)
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
    fs.connect(split.out_2, col.reflux_in, draw_as_recycle=True)
    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, draw_as_recycle=True)
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
    psv = fs.add(units.Valve("PSV-101", variant="psv", description="Vessel Relief Valve"))
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    glass = fs.add(units.Fitting("SG-101", variant="sight_glass", description="Sight Glass"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    suction_y = 300
    discharge_y = 280
    feed.pin(port="outlet", x=110, y=suction_y)
    strainer.pin(port="inlet", x=190, y=suction_y)
    pump.pin(port="suction", x=280, y=suction_y)
    meter.pin(port="inlet", x=430, y=discharge_y)
    fv.pin(port="inlet", x=540, y=discharge_y, mirrored="y")
    surge.pin(port="inlet", x=680, y=discharge_y)
    glass.pin(port="inlet", x=850, y=discharge_y)
    prod.pin(port="inlet", x=980, y=discharge_y)
    psv.pin(y=110).pin(port="inlet", x=680 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=900, y=110 + port_offset(psv, "outlet")[1])

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
    psv = fs.add(units.Valve("PSV-101", variant="psv", description="Vessel Relief Valve"))
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    fv.new_line_number = True
    psv.new_line_number = True

    suction_y = 300
    discharge_y = 280
    feed.pin(port="outlet", x=110, y=suction_y)
    hv.pin(port="inlet", x=235, y=suction_y)
    strainer.pin(port="inlet", x=335, y=suction_y)
    pump.pin(port="suction", x=425, y=suction_y)
    fv.pin(port="inlet", x=575, y=discharge_y)
    surge.pin(port="inlet", x=725, y=discharge_y)
    prod.pin(port="inlet", x=925, y=discharge_y)
    psv.pin(y=110).pin(port="inlet", x=725 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=945, y=110 + port_offset(psv, "outlet")[1])

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
        company="PANDID",
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


_PFD_PROPERTY_ROWS = (
    "Temperature (C)",
    "Pressure (bar)",
    "Vapour Fraction",
    "Total Flow (kg/s)",
    "Ethanol",
    "Water",
    "CO2",
    "Biosolids",
    "Monosaccharides",
    "SO4",
    "MEG",
    "Flocculant",
)

# Rows render in first-seen key order, so every stream carries the same keys in
# the same order. An empty value renders as "-".
_PFD_PROPERTIES = {
    "S-301": (
        "35",
        "1",
        "0",
        "38.93",
        "0.047",
        "0.887",
        "3.08E-05",
        "0.060",
        "3.73E-03",
        "2.00E-03",
        "",
        "",
    ),
    "S-303": ("25", "1", "0", "0.0088", "", "", "", "", "", "", "", "1.000"),
    "S-304": ("25", "1", "0", "0.167", "", "1.000", "", "", "", "", "", ""),
    "S-305": ("68", "1", "0", "2.01", "0.916", "0.084", "5.96E-04", "", "", "", "", ""),
    "S-306": (
        "100",
        "1",
        "0.044",
        "36.93",
        "trace",
        "0.930",
        "",
        "0.064",
        "3.93E-03",
        "2.11E-03",
        "",
        "",
    ),
    "S-307": (
        "35",
        "1",
        "0",
        "36.93",
        "trace",
        "0.930",
        "",
        "0.064",
        "3.93E-03",
        "2.11E-03",
        "",
        "",
    ),
    "S-308": ("25", "1", "0", "0.175", "", "0.950", "", "", "", "", "", "0.050"),
    "S-309": (
        "35",
        "1",
        "0",
        "37.10",
        "trace",
        "0.930",
        "",
        "0.063",
        "3.91E-03",
        "2.10E-03",
        "",
        "2.36E-04",
    ),
    "S-310": (
        "35",
        "1",
        "0",
        "34.30",
        "trace",
        "0.990",
        "",
        "3.86E-03",
        "4.16E-03",
        "2.23E-03",
        "",
        "1.28E-05",
    ),
    "S-501": (
        "35",
        "1",
        "0",
        "2.80",
        "",
        "0.199",
        "",
        "0.797",
        "8.35E-04",
        "4.49E-04",
        "",
        "0.003",
    ),
}


def _ethanol_pfd() -> Flowsheet:
    """Example 10 -- a whole issue-ready PFD on a fixed A3 page.

    The title block states its own date, so unlike 03 and 08 there is nothing
    here to pin: the sheet renders the same today as it did at issue.
    """
    fs = Flowsheet("Ethanol Purification A300")

    broth = fs.add(units.Feed("Fermentation Broth", reference="PFD-201"))
    floc = fs.add(units.Feed("Flocculant", reference="PCD-301"))
    water = fs.add(units.Feed("RO Water", reference="PCD-301"))

    col = fs.add(
        units.Column("T-301", width=110, height=250, label_pos="center", description="Beer Column")
    )
    cond = fs.add(
        units.HeatExchanger(
            "E-301",
            variant="condenser",
            width=64,
            height=64,
            description="T-301 Overhead Condenser",
        )
    )
    drum = fs.add(
        units.Vessel(
            "V-301", variant="horizontal", width=110, height=36, description="T-301 Reflux Drum"
        )
    )
    # Where the drum's single draw parts into reflux and distillate: one fluid,
    # two destinations, so a junction in the piping and not a piece of plant. A
    # tee is drawn as nothing at all and carries no tag, so it puts nothing on
    # the drawing and no row in the equipment list.
    refl = fs.add(units.Tee())
    reb = fs.add(
        units.HeatExchanger(
            "E-302", variant="kettle", width=120, height=44, description="T-301 Kettle Reboiler"
        )
    )
    hx = fs.add(
        units.HeatExchanger(
            "HX-301",
            variant="straight_tubes",
            width=150,
            height=45,
            description="Beer Column Bottoms Cooling",
        )
    )
    mix1 = fs.add(
        units.Reactor(
            "M-301", n_feeds=2, width=80, height=100, description="Flocculant Activation Mixer Tank"
        )
    )
    mix2 = fs.add(units.Mixer("M-302", n_inlets=2, description="Beer Flocculant Mixer Tank"))
    press = fs.add(
        units.Filter(
            "F-301",
            variant="press",
            width=120,
            height=60,
            description="Membrane Pressure Filter Press",
        )
    )
    # The press's discharge parts the same way, but the size and the service
    # both change across it, so this one breaks the run's line number.
    disch = fs.add(units.Tee())
    disch.new_line_number = True
    belt = fs.add(units.Conveyor("BC-301", length=120, description="Filter Cake Conveyor Belt"))
    belt.nozzle("feed", "N")  # cake is dropped onto the belt, not piped

    ethanol = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    effluent = fs.add(units.Product("Wastewater", reference="PCD-302"))
    cake = fs.add(units.Product("Biomass Filter Cake", reference="PFD-501"))

    # Equipment is positioned by nozzle, not by its top-left corner. A tee is a
    # 12-unit square with a port on the middle of each face it uses, so half its
    # width is the whole of the offset from a junction to the corner it is
    # pinned by.
    tee_w = 12.0
    col_x, col_y, col_w = 430.0, 180.0, 110.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + col_w / 2  # distillate / bottoms line
    col_feed_y = col_y + port_offset(col, "feed")[1]
    col_reflux_y = col_y + port_offset(col, "reflux_in")[1]

    broth.pin(x=140, y=col_feed_y - 25)  # flag tip meets the feed nozzle

    cond_w = 64.0
    cond.pin(x=col_axis - cond_w / 2, y=56, mirrored="y")

    drum_x, drum_y, drum_w = 700.0, 100.0, 110.0
    drum.pin(x=drum_x, y=drum_y)
    drum_draw_x = drum_x + (68 / 91.5) * drum_w  # liquid draw down the shell
    refl.pin(x=drum_draw_x - tee_w / 2, y=col_reflux_y - tee_w / 2, orientation=90)
    ethanol.pin(x=1330, y=250)

    reb.pin(x=640, y=420)

    hx_y, hx_h = 510.0, 45.0
    hx.pin(x=900, y=hx_y)
    hx_axis_y = hx_y + hx_h / 2  # the dewatering train runs on it

    mix1_y, mix1_h = 620.0, 100.0
    mix1.pin(x=560, y=mix1_y)
    floc.pin(x=140, y=545)  # every flag tip on one line
    water.pin(x=140, y=mix1_y + 0.573 * mix1_h - 25)

    mix2.pin(x=1120, y=hx_axis_y - 15)  # in_1 level with the cooler
    press_h = 60.0
    press.pin(x=1250, y=hx_axis_y - 20)
    press_out_y = hx_axis_y - 20 + press_h / 2  # discharge, mid-shell
    disch.pin(x=1400, y=press_out_y - tee_w / 2)
    effluent.pin(x=1540, y=press_out_y - 25)  # flag tip on the filtrate leg
    belt_y, belt_tail = 715.0, 10.0  # tail nozzle, in from the end
    belt.pin(x=disch.pin_.x + tee_w / 2 - belt_tail, y=belt_y)
    cake.pin(x=1546, y=belt_y + belt_tail - 25)

    # Declared in stream-number order, which is the order the table reads. The
    # overhead and the reboiler circuit are each one service, so every segment
    # of one carries the same number; a number is drawn once, on the first
    # segment declared, so each group starts with the run it belongs on.
    fs.connect(broth.outlet, col.feed, name="S-301")
    fs.connect(floc.outlet, mix1.feed_1, name="S-303")
    fs.connect(water.outlet, mix1.feed_2, name="S-304")

    fs.connect(refl.outlet, ethanol.inlet, name="S-305")
    fs.connect(col.distillate, cond.shell_in, name="S-305")
    fs.connect(cond.shell_out, drum.inlet, name="S-305")
    fs.connect(drum.outlet, refl.inlet, name="S-305")
    fs.connect(refl.branch, col.reflux_in, name="S-305", draw_as_recycle=True)

    fs.connect(col.bottoms, reb.shell_in, name="S-306")
    fs.connect(reb.shell_out, col.boilup_in, name="S-306", draw_as_recycle=True)
    fs.connect(reb.bottoms, hx.tube_in, name="S-306")

    fs.connect(hx.tube_out, mix2.in_1, name="S-307")
    fs.connect(mix1.outlet, mix2.in_2, name="S-308")

    fs.connect(mix2.outlet, press.inlet, name="S-309")
    fs.connect(press.outlet, disch.inlet, name="S-309")
    fs.connect(disch.outlet, effluent.inlet, name="S-310")
    fs.connect(disch.branch, belt.feed, name="S-501")
    fs.connect(belt.discharge, cake.inlet, name="S-501")

    for s in fs.streams:
        values = _PFD_PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(_PFD_PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]

    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process Flow Diagram 1",
        drawing_number="PFD-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        date="30/08/25",
        drawn_by="AA",
        checked_by="RG",
        approved_by="HVL",
        revisions=[
            Revision("A", "30/07/25", "Issued for internal review", "AA"),
            Revision("B", "20/08/25", "Flocculation package added", "AA"),
            Revision("C", "30/08/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # The list is named row by row: the two junctions are tees, bulk piping
    # bought by the line, and carry no tag to schedule.
    fs.add_annotation(
        equipment_list(
            fs,
            align="top",
            include=[
                "T-301",
                "E-301",
                "V-301",
                "E-302",
                "HX-301",
                "M-301",
                "M-302",
                "F-301",
                "BC-301",
            ],
        )
    )
    fs.add_annotation(
        TableBox(
            title="UTILITIES SUMMARY",
            headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in", "T_out"],
            rows=[
                ["Cold Water", "HX-301", "-13161", "630.7", "25 C", "30 C"],
                ["Cold Water", "E-301", "-5645", "270.5", "25 C", "30 C"],
                ["High Pressure Steam", "E-302", "19112", "11.116", "250 C", "249 C"],
            ],
            col_align=["l", "l", "r", "r", "c", "c"],
            align="bottom-right",
        )
    )
    return fs


def _ethanol_pid() -> Flowsheet:
    """Example 11 -- the P&ID of 10's unit, and the densest sheet in the repo.

    Its title block states its own date too, so nothing here is pinned either.
    """
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=301,
    )

    col = fs.add(units.Column("T-301", label_pos="center", description="Beer Column"))
    cond = fs.add(
        units.HeatExchanger(
            "C-301",
            variant="straight_tubes",
            width=130,
            height=40,
            description="Overhead Condenser",
        )
    )
    drum = fs.add(
        units.Vessel("D-301", variant="horizontal", width=130, height=42, description="Reflux Drum")
    )
    reb = fs.add(
        units.HeatExchanger(
            "RB-301", variant="kettle", width=140, height=50, description="U-tube Kettle Reboiler"
        )
    )
    cooler = fs.add(
        units.HeatExchanger(
            "HX-301",
            variant="straight_tubes",
            width=130,
            height=40,
            description="Beer Bottoms Cooler",
        )
    )

    # The cooling water and the steam are utility headers, not lines leaving the
    # sheet once, so both tie-ins on each carry the one tag the legend explains.
    fb_feed = fs.add(units.Feed("Fermentation Broth", reference="P&ID-201"))
    cws_cond = fs.add(units.Feed("CWSH", header=True))
    cwr_cond = fs.add(units.Product("CWRH", header=True))
    cws_cool = fs.add(units.Feed("CWSH", header=True))
    cwr_cool = fs.add(units.Product("CWRH", header=True))
    steam = fs.add(units.Feed("HPSSH", header=True))
    condensate = fs.add(units.Product("HPSRH", header=True))
    ae_prod = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    bottoms_prod = fs.add(units.Product("Cooled Bottoms", reference="F-301"))

    xv = fs.add(units.Valve("XV-301", variant="solenoid", description="Feed Trip Valve"))
    meter = fs.add(units.Fitting("FE-313", variant="rotameter", description="Feed Flow Element"))
    cv306 = fs.add(units.Valve("CV-306", variant="control", description="Bottoms Control Valve"))
    nrv306 = fs.add(units.Valve("NRV-306", variant="check", description="Bottoms Non-Return Valve"))
    hv311 = fs.add(units.Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(units.Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    fe303 = fs.add(
        units.Fitting(
            "FE-303", variant="venturi", label_pos="bottom", description="Reflux Flow Element"
        )
    )
    # The size steps down 100 -> 40 across it, so the run's number breaks here.
    t_draw = fs.add(units.Tee())
    t_draw.new_line_number = True

    # Pinned by nozzle, not by corner: every device is placed with pin(port=...),
    # which asks the symbol where its own nozzle sits, so no rescaling of the
    # artwork can leave a valve off its run.
    col_x, col_y = 470.0, 300.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + resolve_size(col)[0] / 2
    feed_y = col_y + port_offset(col, "feed")[1]
    boilup_y = col_y + port_offset(col, "boilup_in")[1]

    fb_feed.pin(port="outlet", x=200, y=feed_y)
    xv.pin(mirrored="y").pin(port="inlet", x=250, y=feed_y)
    meter.pin(port="inlet", x=350, y=feed_y)

    overhead_y = 130.0
    cond_x, cond_y = 1010.0, 210.0
    cond.pin(x=cond_x, y=cond_y)
    cond_shell_in_x = cond_x + port_offset(cond, "shell_in")[0]
    cw_cond_y = cond_y + port_offset(cond, "tube_in")[1]
    st301 = fs.add_valve_station(
        "CV-301-1",
        x=677.5,
        y=overhead_y,
        number=301,
        bypass_over="reduction",
        description="Overhead",
        service="AE",
        sequence=302,
        size=300,
        schedule=80,
        spec="SS",
    )
    cws_cond.pin(port="outlet", x=200, y=cw_cond_y)
    hv311.pin(port="inlet", x=320, y=cw_cond_y)
    cwr_cond.pin(port="inlet", x=1540, y=cw_cond_y)

    # The inlet is authored on more than one face and the top one is named here,
    # so the nozzle the drum is positioned by is the one the condensate arrives
    # at, and the run from the condenser's drain is a straight drop.
    drum.nozzle("inlet", "N")
    drum_x = cond_x + port_offset(cond, "shell_out")[0] - port_offset(drum, "inlet")[0]
    drum.pin(x=drum_x, y=280)
    drum_draw_x = drum_x + port_offset(drum, "outlet")[0]

    reflux_run_y = 440.0
    st303 = fs.add_valve_station(
        "CV-303",
        x=672.5,
        y=reflux_run_y,
        mirrored=True,
        bypass_over="reduction",
        description="Reflux",
        service="AE",
        sequence=303,
        size=80,
        schedule=80,
        spec="SS",
    )
    fe303.pin(mirrored=True).pin(port="outlet", x=617.5, y=reflux_run_y)

    t_draw.pin(orientation=90)
    t_draw.pin(port="inlet", x=drum_draw_x).pin(port="branch", y=reflux_run_y)

    dist_y = 510.0
    st305 = fs.add_valve_station(
        "CV-305",
        x=1147,
        y=dist_y,
        gap=26,
        bypass_over="reduction",
        description="Distillate",
        service="AE",
        sequence=305,
        size=40,
        schedule=80,
        spec="SS",
    )
    ae_prod.pin(port="inlet", x=1540, y=dist_y)

    reb.pin(x=700, y=580)
    steam_y = 580 + port_offset(reb, "tube_in")[1]
    steam.pin(port="outlet", x=200, y=steam_y)
    st308 = fs.add_valve_station(
        "CV-308",
        x=217.5,
        y=steam_y,
        bypass_over="downstream_isolation",
        description="Steam",
        service="HPS",
        sequence=308,
        size=100,
        schedule=80,
        spec="CS",
    )
    condensate.pin(port="inlet", x=1540, y=580 + port_offset(reb, "tube_out")[1])

    bottoms_y = 660.0
    cv306.pin(mirrored="y").pin(port="inlet", x=900, y=bottoms_y)
    nrv306.pin(port="inlet", x=1000, y=bottoms_y)
    cooler.pin(x=1100, y=720)
    cooler_shell_in_x = 1100 + port_offset(cooler, "shell_in")[0]
    cooler_shell_out_x = 1100 + port_offset(cooler, "shell_out")[0]
    cw_cool_y = 720 + port_offset(cooler, "tube_in")[1]
    cooled_y = 805.0
    cws_cool.pin(port="outlet", x=200, y=cw_cool_y)
    hv315.pin(port="inlet", x=320, y=cw_cool_y)
    cwr_cool.pin(port="inlet", x=1540, y=cw_cool_y)
    bottoms_prod.pin(port="inlet", x=1540, y=cooled_y)

    # A station is one line, and so are its bypass and its drains, so all three
    # branches take the station's number and only the run carries it.
    fs.connect(
        fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200, schedule=160, spec="SS"
    )
    fs.connect(xv.outlet, meter.inlet)
    col_feed = fs.connect(meter.outlet, col.feed)

    # A line that carries a balloon is routed by hand with via(): an attached
    # instrument hangs off the *routed* path, so a line the router is free to
    # re-bend carries its instrumentation somewhere else with it.
    vapour = fs.connect(
        col.distillate, st301.inlet, service="AE", sequence=302, size=300, schedule=80, spec="SS"
    ).via([(col_axis, overhead_y)])
    fs.connect(st301.outlet, cond.shell_in).via([(cond_shell_in_x, overhead_y)])

    fs.connect(
        cond.shell_out, drum.inlet, service="AE", sequence=304, size=150, schedule=80, spec="SS"
    )
    fs.connect(
        cws_cond.outlet, hv311.inlet, service="CWS", sequence=311, size=150, schedule=40, spec="CS"
    )
    fs.connect(hv311.outlet, cond.tube_in)
    cw_return = fs.connect(
        cond.tube_out, cwr_cond.inlet, service="CWR", sequence=312, size=150, schedule=40, spec="CS"
    ).via([(1300, cw_cond_y)])

    fs.connect(
        drum.outlet, t_draw.inlet, service="AE", sequence=309, size=100, schedule=80, spec="SS"
    )
    fs.connect(
        t_draw.branch, st303.inlet, service="AE", sequence=303, size=80, schedule=80, spec="SS"
    )
    fs.connect(st303.outlet, fe303.inlet)
    fs.connect(fe303.outlet, col.reflux_in, draw_as_recycle=True)

    fs.connect(
        t_draw.outlet, st305.inlet, service="AE", sequence=305, size=40, schedule=80, spec="SS"
    )
    fs.connect(st305.outlet, ae_prod.inlet)

    sump_x = 700 + port_offset(reb, "shell_in")[0]
    boilup_x = 700 + port_offset(reb, "shell_out")[0]
    sump = fs.connect(
        col.bottoms, reb.shell_in, service="FB", sequence=307, size=250, schedule=160, spec="SS"
    ).via([(col_axis, 655), (sump_x, 655)])
    boilup = fs.connect(
        reb.shell_out,
        col.boilup_in,
        service="FB",
        sequence=310,
        size=300,
        schedule=160,
        spec="SS",
        draw_as_recycle=True,
    ).via([(boilup_x, 535), (595, 535), (595, boilup_y)])
    fs.connect(
        steam.outlet, st308.inlet, service="HPS", sequence=308, size=100, schedule=80, spec="CS"
    )
    fs.connect(st308.outlet, reb.tube_in)
    fs.connect(
        reb.tube_out, condensate.inlet, service="HPR", sequence=317, size=80, schedule=80, spec="CS"
    )

    fs.connect(
        reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100, schedule=160, spec="SS"
    )
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.shell_in).via([(cooler_shell_in_x, bottoms_y)])
    fs.connect(
        cooler.shell_out,
        bottoms_prod.inlet,
        service="FB",
        sequence=314,
        size=100,
        schedule=160,
        spec="SS",
    ).via([(cooler_shell_out_x, cooled_y)])
    fs.connect(
        cws_cool.outlet, hv315.inlet, service="CWS", sequence=315, size=100, schedule=40, spec="CS"
    )
    fs.connect(hv315.outlet, cooler.tube_in)
    fs.connect(
        cooler.tube_out,
        cwr_cool.inlet,
        service="CWR",
        sequence=316,
        size=100,
        schedule=40,
        spec="CS",
    )

    # The trip square is logic rather than a device, so it is drawn at each place
    # the trip acts and carries the same tag every time. Z, not I: a function
    # that acts is lettered S or Z.
    fs.add_instrument("Z", 2, on=xv, at="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, on=meter, at="S", offset=36)
    fs.add_instrument("PI", 315, on=col_feed, at=0.45, offset=58)
    fs.add_instrument("TI", 325, on=cw_return, at=0.3, offset=55)

    # Loop 301: tower overhead pressure. The faceplate is mounted on the valve it
    # drives, so its output drops straight onto the actuator. Both alarms read
    # the controller and each takes a face of its own, high above low.
    balloon_row_y = 45.0
    cv3011_top = overhead_y - port_offset(st301.control, "inlet")[1]
    pt301 = fs.add_instrument("PT", 301, on=vapour, at=0.75, offset=overhead_y - balloon_row_y)
    pic301 = fs.add_instrument(
        "PIC", 301, on=st301.control, at="N", variant="shared", offset=cv3011_top - balloon_row_y
    )
    pic301.nozzle("sig_out", "S")
    fs.add_instrument("PAH", 301, on=pic301, at="N", offset=46, variant="shared")
    fs.add_instrument("PAL", 301, on=pic301, at="E", offset=46, variant="shared")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, st301.control.actuator, kind="pneumatic")

    # The high pressure trip, on a measurement of its own: PT-318 taps the
    # overhead west of PT-301 and drives Z-2 alone.
    pt318 = fs.add_instrument("PT", 318, on=vapour, at=0.55, offset=overhead_y - balloon_row_y)
    fs.add_instrument("Z", 2, on=pt318, at="N", offset=40, variant="sis")

    # Loops 302/303: tower top temperature cascaded onto the reflux flow. A
    # cascade sets a setpoint, so it lands on the flow controller's pv.
    tt302 = fs.add_instrument("TT", 302, on=vapour, at=0.13, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", 302, on=tt302, at="E", offset=78, variant="shared")
    tic302.nozzle("sig_out", "S")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    ft303 = fs.add_instrument("FT", 303, on=fe303, at="N", offset=90)
    fic303 = fs.add_instrument("FIC", 303, on=ft303, at="E", offset=70, variant="shared")
    fic303.nozzle("sig_out", "E")  # the valve it strokes stands below and right
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, st303.control.actuator, kind="pneumatic")

    # Loop 304: reflux drum level on the distillate valve. Four lines reach this
    # controller, so it needs four faces: the high alarm takes the north, the
    # measurement comes in from the west, the output leaves south onto the
    # actuator and the low alarm takes the east.
    lt304 = fs.add_instrument("LT", 304, on=drum, at="E", offset=60)
    lic304_row_y = 403.0
    cv305_top = dist_y - port_offset(st305.control, "inlet")[1]
    lic304 = fs.add_instrument(
        "LIC", 304, on=st305.control, at="N", variant="shared", offset=cv305_top - lic304_row_y
    )
    lic304.nozzle("sig_in", "W")
    lic304.nozzle("sig_out", "S")
    fs.add_instrument("LAH", 304, on=lic304, at="N", offset=46, variant="shared")
    fs.add_instrument("LAL", 304, on=lic304, at="E", offset=46, variant="shared")
    # Teed off the measurement rather than hung on an alarm: an alarm host would
    # draw the alarm as driving the trip.
    level = fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.add_instrument("Z", 1, on=level, at=0.6, offset=40, angle=-90, variant="sis")
    fs.connect(lic304.sig_out, st305.control.actuator, kind="pneumatic")

    # Loop 307: reboiler return temperature on the steam valve. The trip goes on
    # the transmitter, which keeps working when the loop is put on manual.
    tt307 = fs.add_instrument("TT", 307, on=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", 307, on=tt307, at="W", offset=96, variant="shared")
    tic307.nozzle("sig_out", "S")
    fs.add_instrument("TI", 321, on=boilup, at=0.05, offset=70, angle=-90)
    fs.add_instrument("Z", 1, on=tt307, at="N", offset=40, variant="sis")
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")
    fs.connect(tic307.sig_out, st308.control.actuator, kind="pneumatic")

    # Loop 306: kettle level on the bottoms draw.
    lt306 = fs.add_instrument("LT", 306, on=reb, at="S", offset=68)
    lic306 = fs.add_instrument("LIC", 306, on=lt306, at="E", offset=56, variant="shared")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("Z", 1, on=lt306, at="W", offset=44, variant="sis")
    fs.connect(lt306.sig_out, lic306.sig_in, kind="electric")
    fs.connect(lic306.sig_out, cv306.actuator, kind="pneumatic")

    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        date="30/10/25",
        drawn_by="AA",
        checked_by="RG",
        approved_by="HVL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # Written out rather than generated, so the rows keep the order the issued
    # sheet schedules them in.
    fs.add_annotation(
        Annotation(
            title="EQUIPMENT LIST",
            rows=[
                ("D-301", "Reflux Drum"),
                ("T-301", "Beer Column"),
                ("HX-301", "Beer Bottoms Cooler"),
                ("C-301", "Overhead Condenser"),
                ("RB-301", "U-tube Kettle Reboiler"),
            ],
            align="top-right",
        )
    )
    fs.add_annotation(
        notes(
            [
                "Diamond in square: safety instrumented system logic, code Z.",
                "One trip is one tag, drawn at every point the trip acts.",
                "Z-2: high pressure trip. PT-318 is its own measurement point.",
                "Z-1: process shutdown logic, reading three measurements.",
                "Alarms are lettered A and trips S or Z; H is drawn above L.",
            ],
            title="GENERAL NOTES",
            numbered=False,
            align="bottom-left",
        )
    )
    fs.add_annotation(
        legend(
            {
                "SS": "Stainless Steel 316L",
                "CS": "Carbon Steel A106-B",
                "AE": "Azeotropic Ethanol",
                "FB": "Fermentation Broth",
                "CWSH": "Cooling Water Supply Header",
                "CWRH": "Cooling Water Return Header",
                "HPSSH": "High Pressure Steam Supply Header",
                "HPSRH": "High Pressure Steam Return Header",
                "NC": "Normally Closed (darkened valve body)",
            },
            align="top-left",
        )
    )
    return fs


def _block_flow_diagram() -> Flowsheet:
    fs = Flowsheet("Ammonia Plant - Block Flow Diagram")
    reforming = fs.add(units.Block("Reforming", inputs=["W", "N", "N"], outputs=["E"])).pin(
        x=260, y=340
    )
    shift = fs.add(units.Block("Shift & CO2 Removal", inputs=1, outputs=["E", "N"])).pin(
        x=520, y=340
    )
    synthesis = fs.add(units.Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"])).pin(
        x=830, y=340
    )
    synthesis.order_on("S", [synthesis.out_2, synthesis.in_2])
    refrigeration = fs.add(units.Block("Refrigeration", inputs=1, outputs=["E", "S"])).pin(
        x=1080, y=340
    )
    natural_gas = fs.add(units.Feed("Natural Gas")).pin(x=60, y=355)
    air = fs.add(units.Feed("Air")).pin(x=180, y=180)
    steam = fs.add(units.Feed("Steam")).pin(x=330, y=180)
    co2 = fs.add(units.Product("CO2 to Urea")).pin(x=560, y=170)
    ammonia = fs.add(units.Product("Liquid NH3")).pin(x=1300, y=355)
    purge = fs.add(units.Product("Purge Gas")).pin(x=975, y=490)
    fs.connect(natural_gas.outlet, reforming.in_1)
    fs.connect(air.outlet, reforming.in_2)
    fs.connect(steam.outlet, reforming.in_3)
    fs.connect(reforming.out_1, shift.in_1)
    fs.connect(shift.out_2, co2.inlet)
    fs.connect(shift.out_1, synthesis.in_1)
    fs.connect(synthesis.out_1, refrigeration.in_1)
    fs.connect(refrigeration.out_1, ammonia.inlet)
    fs.connect(refrigeration.out_2, synthesis.in_2)
    fs.connect(synthesis.out_2, purge.inlet)
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
    # 10 and 11 are the two flagship sheets: the same unit as a PFD and as the
    # P&ID of it, both on a fixed A3 page, and between them the widest coverage
    # in the corpus -- valve stations, five control loops, a repeated interlock
    # square, utility headers, a conveyor, off-page connectors, a utilities
    # summary and a sectioned stream table. Both state their own title-block
    # date, so neither needs the pinning 03 and 08 do.
    "10_ethanol_pfd": (
        _ethanol_pfd,
        {"show_stream_table": True, "border": "zone", "page_size": "A3"},
    ),
    "11_ethanol_pid": (_ethanol_pid, {"border": "zone", "page_size": "A3", "diagram": "p&id"}),
    # 12 is the block flow diagram, the one drawing a level above the PFD and
    # the only scenario with process connections on the north and south faces.
    # It is what guards the sizing rule as a *drawing* rather than as an
    # arithmetic claim: the boxes here are as wide as their own names and as
    # tall as their walls need, so a change to the pitch, the minimum box or the
    # label allowance moves this file and nothing else.
    "12_block_flow_diagram": (_block_flow_diagram, {}),
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

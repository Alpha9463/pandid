"""Golden-file SVG regression over a fixed corpus: one scenario per example.

Five of them (03, 08, 09, 10 and 11) draw the zone-ruled border and the sheet
furniture -- title block, equipment list, notes, legend -- with a stream table
on all but 11. 09 and 11 are the two issued as P&IDs, and 10 and 11 the two on
a fixed A3 page.

Each golden is built twice, from two independent sources, and both are compared
against it.

**From a fixture in this file.** Each scenario below is a rebuilt copy of the
matching example: the example scripts render straight to a file under examples/
(a side effect a test suite shouldn't have), and 03's and 08's TitleBlocks leave
``date`` empty, which SvgRenderer fills in with ``datetime.now()`` -- fine for a
real render, but it would make the golden change every day. 10's and 11's title
blocks state their own dates, so those two need no pinning. Every other input is
copied verbatim from the matching example script; for 08, whose example *is*
data, the copied input is its spec mapping.

**From the example itself.** A copy drifts from what it copied, and this one
did: #230 corrected real people's initials in examples/13_mineral_dewatering.py
and the golden went on reading the old ones, because the golden is built from
the fixture. So every example is also imported, rendered and compared against
the same golden -- see ``test_the_example_draws_the_same_sheet_as_its_fixture``
-- which is what turns that class of drift from something a screenshot catches
into something the next test run catches.

See tests/golden/README.md for how to regenerate.
"""

import functools
import importlib.util
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
from pandid.render.svg import PROVENANCE_CLOSE, PROVENANCE_OPEN

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
    run_y = 330
    f2 = fs.add(units.Feed("F-2")).pin(x=60).pin(port="outlet", y=run_y)
    e2 = fs.add(units.HeatExchanger("E-2")).pin(x=210).pin(port="tube_in", y=run_y)
    p2 = fs.add(units.Product("P-2")).pin(x=430).pin(port="inlet", y=run_y)
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
    col1 = fs.add(
        units.Column("T-100", internals="valve_tray", trays=14, description="Light Ends Column")
    )
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
    col2 = fs.add(
        units.Column("T-200", internals="sieve_tray", trays=18, description="Product Column")
    )
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
        units.Fitting(flow.element("FE"), variant="orifice", description="Feed Orifice Plate")
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

    # The one fixture carrying a primary element's balloon: the plate's tag
    # moves into it, the fitting is left unlettered, and FT-101 stacks on top.
    fe_b = fs.add_balloon(fe, at="N", offset=38)
    ft = fs.add_instrument("FT", flow, near=fe_b, at="N", offset=23)
    # Both controllers are circle-in-square, ISA-5.1's shared display and shared
    # control; a bare circle with display="central" says the instrument only
    # reads.
    fic = fs.add_instrument("FIC", flow, near=ft, at="N", offset=110, angle=35, variant="shared")
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Element -> transmitter -> controller on the level as well as on the flow:
    # the impulse line off the drum reaches LT-101 and the controller reads it.
    lt = fs.add_instrument("LT", level, sensing=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", level, near=lt, at="S", offset=95, variant="shared")
    # The alarms are lettering in the controller's own quadrants, which is what
    # keeps a quadrant pair in the golden corpus; see the same two codes in
    # examples/04_control_loop.py.
    lic.annotate(high="LAH", low="LAL")
    # In no loop and with no measured variable: a repeatable logic function
    # takes a literal number, and has to keep being able to. Teed off the
    # measurement signal line rather than off a balloon face, which is also the
    # fixture that keeps a stream-hosted tap in the golden corpus -- it is drawn
    # dashed, and the two process taps above it are not.
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("I", 1, sensing=measurement, at=0.5, offset=44, angle=90, variant="logic")
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
    col = fs.add(
        units.Column("T-701", internals="baffle_tray", trays=10, description="Main Fractionator")
    )
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

    lic = fs.add_instrument("LIC", 101, sensing=surge, at="S", offset=115, display="central")
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
        units.Column(
            "T-301",
            internals="sieve_tray",
            trays=18,
            width=110,
            height=250,
            label_pos="center",
            description="Beer Column",
        )
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
        scale="NTS",
        date="30/08/25",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "30/07/25", "Issued for internal review", "AA"),
            Revision("B", "20/08/25", "Flocculation package added", "AA"),
            Revision("C", "30/08/25", "Issued For Review", "AA", "JS", "RL"),
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

    # Eight loops, each number declared once. A loop is the measured variable and
    # the number together, so the 301 on line FB-301 and in CV-301-1's suffix is
    # not the pressure loop; and the balloons in no loop -- the indicators, the
    # trip's own transmitter and the Z squares -- keep literal numbers.
    press301 = fs.add_loop("P", 301)
    temp302 = fs.add_loop("T", 302)
    flow303 = fs.add_loop("F", 303)
    level304 = fs.add_loop("L", 304)
    flow305 = fs.add_loop("F", 305)
    level306 = fs.add_loop("L", 306)
    temp307 = fs.add_loop("T", 307)
    flow308 = fs.add_loop("F", 308)

    col = fs.add(
        units.Column(
            "T-301",
            internals="sieve_tray",
            trays=18,
            label_pos="center",
            description="Beer Column",
        )
    )
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
    cv306 = fs.add(
        units.Valve(level306.tag("CV"), variant="control", description="Bottoms Control Valve")
    )
    nrv306 = fs.add(units.Valve("NRV-306", variant="check", description="Bottoms Non-Return Valve"))
    hv311 = fs.add(units.Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(units.Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    fe303 = fs.add(
        units.Fitting(
            flow303.element("FE"),
            variant="venturi",
            description="Reflux Flow Element",
        )
    )
    fe305 = fs.add(
        units.Fitting(
            flow305.element("FE"),
            variant="venturi",
            description="Distillate Flow Element",
        )
    )
    fe308 = fs.add(
        units.Fitting(
            flow308.element("FE"),
            variant="venturi",
            description="Steam Flow Element",
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
        flow303.tag("CV"),
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
        flow305.tag("CV"),
        x=1147,
        y=dist_y,
        gap=22,
        bypass_over="reduction",
        description="Distillate",
        service="AE",
        sequence=305,
        size=40,
        schedule=80,
        spec="SS",
    )
    fe305.pin(port="inlet", x=1495, y=dist_y)
    ae_prod.pin(port="inlet", x=1540, y=dist_y)

    reb.pin(x=700, y=580)
    steam_y = 580 + port_offset(reb, "tube_in")[1]
    # The header steps back to 130 so FE-308 stands ahead of the station: the run
    # behind it is the reboiler's, and the paper over it belongs to the bypass.
    steam.pin(port="outlet", x=130, y=steam_y)
    fe308.pin(port="inlet", x=150, y=steam_y)
    st308 = fs.add_valve_station(
        flow308.tag("CV"),
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
    fs.connect(st305.outlet, fe305.inlet)
    fs.connect(fe305.outlet, ae_prod.inlet)

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
        steam.outlet, fe308.inlet, service="HPS", sequence=308, size=100, schedule=80, spec="CS"
    )
    fs.connect(fe308.outlet, st308.inlet)
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
    fs.add_instrument("Z", 2, acting_on=xv, at="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, sensing=meter, at="S", offset=36)
    fs.add_instrument("PI", 315, sensing=col_feed, at=0.45, offset=58)
    fs.add_instrument("TI", 325, sensing=cw_return, at=0.3, offset=55)

    # Loop 301: tower overhead pressure. The faceplate stands over the valve it
    # drives -- near=, so nothing is drawn between the two and the output is the
    # connect() below -- and its alarms are lettering in its own quadrants.
    balloon_row_y = 45.0
    cv3011_top = overhead_y - port_offset(st301.control, "inlet")[1]
    pt301 = fs.add_instrument(
        "PT", press301, sensing=vapour, at=0.75, offset=overhead_y - balloon_row_y
    )
    pic301 = fs.add_instrument(
        "PIC",
        press301,
        near=st301.control,
        at="N",
        variant="shared",
        offset=cv3011_top - balloon_row_y,
    )
    pic301.nozzle("sig_out", "S")
    pic301.annotate(high="PAH", low="PAL")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, st301.control.actuator, kind="pneumatic")

    # The high pressure trip, on a measurement of its own: PT-318 taps the
    # overhead west of PT-301 and drives Z-2 alone.
    pt318 = fs.add_instrument("PT", 318, sensing=vapour, at=0.55, offset=overhead_y - balloon_row_y)
    fs.add_instrument("Z", 2, sensing=pt318, at="N", offset=40, variant="sis")

    # Loops 302/303: tower top temperature cascaded onto the reflux flow. A
    # cascade sets a setpoint, so it lands on the flow controller's pv.
    tt302 = fs.add_instrument("TT", temp302, sensing=vapour, at=0.13, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", temp302, near=tt302, at="E", offset=78, variant="shared")
    tic302.nozzle("sig_out", "S")
    tic302.annotate(high="TAH", low="TAL")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    # The venturi's tag moves into a balloon on its impulse line and FT-303
    # stacks on that, edge to edge: two touching balloons need no line.
    fe303_b = fs.add_balloon(fe303, at="N", offset=38)
    ft303 = fs.add_instrument("FT", flow303, near=fe303_b, at="N", offset=23)
    fic303 = fs.add_instrument("FIC", flow303, near=ft303, at="E", offset=70, variant="shared")
    fic303.nozzle("sig_out", "E")  # the valve it strokes stands below and right
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, st303.control.actuator, kind="pneumatic")

    # Loops 304/305: reflux drum level cascaded onto the distillate flow. Both
    # faceplates stand over the valve, master above slave.
    lt304 = fs.add_instrument("LT", level304, sensing=drum, at="E", offset=60)
    lic304_row_y = 325.0
    fic305_row_y = 417.0  # FT-305's row, so the measurement runs straight
    cv305_top = dist_y - port_offset(st305.control, "inlet")[1]
    fic305 = fs.add_instrument(
        "FIC",
        flow305,
        near=st305.control,
        at="N",
        variant="shared",
        offset=cv305_top - fic305_row_y,
    )
    lic304 = fs.add_instrument(
        "LIC",
        level304,
        near=st305.control,
        at="N",
        variant="shared",
        offset=cv305_top - lic304_row_y,
    )
    lic304.nozzle("sig_out", "S")
    lic304.annotate(high="LAH", low="LAL")
    fic305.nozzle("pv", "E")
    fic305.nozzle("sig_out", "S")
    fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    # On the transmitter and not teed off its run: two faceplates over the valve
    # leave that run too short to tee off.
    fs.add_instrument("Z", 1, sensing=lt304, at="S", offset=44, variant="sis")
    fe305_b = fs.add_balloon(fe305, at="N", offset=38)
    ft305 = fs.add_instrument("FT", flow305, near=fe305_b, at="N", offset=23)
    fs.connect(ft305.sig_out, fic305.pv, kind="electric")
    fs.connect(lic304.sig_out, fic305.sig_in, kind="software")
    fs.connect(fic305.sig_out, st305.control.actuator, kind="pneumatic")

    # Loops 307/308: reboiler return temperature cascaded onto the steam flow.
    # The trip goes on the transmitter, which keeps working on manual.
    tt307 = fs.add_instrument("TT", temp307, sensing=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", temp307, near=tt307, at="W", offset=96, variant="shared")
    tic307.nozzle("sig_out", "W")
    fs.add_instrument("TI", 321, sensing=boilup, at=0.05, offset=70, angle=-90)
    fs.add_instrument("Z", 1, sensing=tt307, at="N", offset=40, variant="sis")
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")

    fe308_b = fs.add_balloon(fe308, at="N", offset=38)
    ft308 = fs.add_instrument("FT", flow308, near=fe308_b, at="N", offset=23)
    fic308 = fs.add_instrument("FIC", flow308, near=ft308, at="E", offset=60, variant="shared")
    fic308.nozzle("sig_out", "S")
    fs.connect(ft308.sig_out, fic308.pv, kind="electric")
    fs.connect(tic307.sig_out, fic308.sig_in, kind="software")
    fs.connect(fic308.sig_out, st308.control.actuator, kind="pneumatic")

    # Loop 306: kettle level on the bottoms draw.
    lt306 = fs.add_instrument("LT", level306, sensing=reb, at="S", offset=68)
    lic306 = fs.add_instrument("LIC", level306, near=lt306, at="E", offset=56, variant="shared")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("Z", 1, sensing=lt306, at="W", offset=44, variant="sis")
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
        scale="NTS",
        date="30/10/25",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "JS", "RL"),
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


_MD_PROPERTY_ROWS = (
    "Temperature (C)",
    "Pressure (bara)",
    "Total Flow (t/h)",
    "Solids (% w/w)",
    "Water",
    "Concentrate",
    "Tramp Metal",
    "Flocculant",
    "Air / Flue Gas",
    "Fuel Gas",
)

_MD_PROPERTIES = {
    "S-401": ("28", "1.4", "224.0", "28.0", "0.720", "0.2800", "2.2E-05", "", "", ""),
    "S-402": ("20", "3.0", "0.630", "", "1.000", "", "", "", "", ""),
    "S-403": ("20", "1.0", "0.002", "100.0", "", "", "", "1.000", "", ""),
    "S-404": ("20", "1.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "", ""),
    "S-405": ("20", "2.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "", ""),
    "S-406": ("28", "1.2", "224.63", "27.9", "0.721", "0.2792", "2.2E-05", "8.9E-06", "", ""),
    "S-407": ("28", "1.0", "120.1", "0.01", "1.000", "1.0E-04", "", "", "", ""),
    "S-408": ("28", "1.2", "104.5", "60.0", "0.400", "0.5998", "4.8E-05", "1.9E-05", "", ""),
    "S-409": ("28", "2.5", "104.5", "60.0", "0.400", "0.5998", "4.8E-05", "1.9E-05", "", ""),
    "S-410": ("28", "1.0", "35.6", "0.10", "0.999", "1.0E-03", "", "5.6E-05", "", ""),
    "S-411": ("28", "1.0", "68.9", "91.0", "0.090", "0.9099", "7.3E-05", "", "", ""),
    "S-412": ("15", "1.0", "30.5", "", "", "", "", "", "1.000", ""),
    "S-413": ("15", "2.0", "0.43", "", "", "", "", "", "", "1.000"),
    "S-414": ("650", "0.99", "30.93", "", "0.031", "", "", "", "0.969", ""),
    # No temperature. The cake and the burner gas arrive at the breeching and
    # start drying in the same instant, so there is no equilibrium the two
    # reach and nothing an adiabatic mixing sum would be true of. A dryer
    # datasheet quotes the two inlets it has -- 650 C of gas onto 28 C of cake
    # -- and so does this table, one column each side of this one.
    "S-415": ("", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "", "0.300", ""),
    "S-416": ("115", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "", "0.300", ""),
    "S-417": ("115", "0.97", "37.03", "0.35", "0.187", "3.5E-03", "", "", "0.809", ""),
    "S-418": ("28", "3.0", "41.5", "", "1.000", "", "", "", "", ""),
    "S-419": ("62", "0.96", "78.53", "0.17", "0.616", "1.7E-03", "", "", "0.382", ""),
    "S-420": ("62", "1.0", "35.08", "", "0.146", "trace", "", "", "0.854", ""),
    "S-421": ("62", "1.0", "43.45", "0.30", "0.997", "3.0E-03", "", "", "", ""),
    "S-422": ("110", "1.0", "62.80", "99.5", "0.005", "0.9949", "8.0E-05", "", "", ""),
    "S-423": ("110", "1.0", "62.79", "99.5", "0.005", "0.995", "", "", "", ""),
    "S-424": ("110", "1.0", "0.005", "100.0", "", "", "1.000", "", "", ""),
}


def _mineral_dewatering() -> Flowsheet:
    """Example 13 -- the solids circuit, and the only sheet that is not a fluids plant.

    A concentrate slurry thickened, filtered, dried and cleaned of tramp iron. It
    states its own title-block date, so like 10, 11 and 14 there is nothing here to
    pin, and it is the widest fixture in the corpus: twenty-four streams side by
    side is more than an A3 page carries beside a utilities summary, so unlike
    those three it is sized to its drawing rather than to a page. That makes it the
    one fixture whose *furniture* rather than whose diagram sets the sheet width.

    Its four ``branch="inlet"`` tees are what it adds that nothing else in the
    corpus has: junctions where a second stream *joins* a run rather than leaving
    it. It is also the only fixture drawing a dryer, a furnace, a blower or a
    funnel.
    """
    fs = Flowsheet("Mineral Concentrate Dewatering A400")

    water = fs.add(units.Feed("Raw Water", reference="PCD-402"))
    funnel = fs.add(units.Funnel("FN-401", description="Flocculant Charging Funnel"))
    charge = fs.add(units.Tee(branch="inlet"))
    tank = fs.add(
        units.Tank("TK-401", variant="conical_bottom", description="Flocculant Make-up Tank")
    )
    dose = fs.add(units.Pump("P-402", variant="peristaltic", description="Flocculant Dosing Pump"))

    concentrate = fs.add(units.Feed("Flotation Concentrate", reference="PFD-302"))
    floc = fs.add(units.Tee(branch="inlet"))
    # ``characteristic="gravity"``, not the retired ``variant="gravity"``:
    # the same drawing to the character, so this golden does not move.
    thickener = fs.add(
        units.Separator("TH-401", characteristic="gravity", description="Concentrate Thickener")
    )
    overflow = fs.add(units.Product("Recovered Water", reference="PCD-402"))

    underflow_pump = fs.add(
        units.Pump("P-401", variant="screw", description="Thickener Underflow Pump")
    )
    suction_red = fs.add(
        units.Reducer("RD-401", variant="eccentric", description="P-401 Suction Reducer")
    )
    disch_red = fs.add(
        units.Reducer(
            "RD-402",
            variant="concentric",
            large_end="outlet",
            description="P-401 Discharge Expander",
        )
    )
    belt_filter = fs.add(
        units.Filter(
            "FL-401", variant="belt", width=60, height=110, description="Concentrate Belt Filter"
        )
    )
    cake_tee = fs.add(units.Tee())
    filtrate = fs.add(units.Product("Filtrate", reference="PCD-402"))
    conveyor = fs.add(units.Conveyor("CV-401", length=150, description="Filter Cake Conveyor"))
    conveyor.nozzle("feed", "N")

    air = fs.add(units.Feed("Ambient Air"))
    gas = fs.add(units.Feed("Natural Gas", reference="PCD-403"))
    heater = fs.add(units.Furnace("FH-401", description="Dryer Air Heater"))
    breeching = fs.add(units.Tee(branch="inlet"))
    dryer = fs.add(units.Dryer("DR-401", description="Concentrate Rotary Dryer"))

    cyclone = fs.add(
        units.Separator("CY-401", variant="cyclone", description="Product Recovery Cyclone")
    )
    scrub_water = fs.add(units.Feed("Scrubbing Water", reference="PCD-402"))
    scrub_tee = fs.add(units.Tee(branch="inlet"))
    scrubber = fs.add(
        units.Separator("SC-401", variant="scrubber", description="Dryer Exhaust Scrubber")
    )
    effluent = fs.add(units.Product("Scrubber Effluent", reference="PCD-402"))
    fan = fs.add(units.Blower("BL-401", description="Dryer Exhaust Fan"))
    stack = fs.add(
        units.Vent(
            "VE-401", variant="exhaust_head", width=45, height=36, description="Dryer Exhaust Head"
        )
    )

    magnet = fs.add(
        units.Separator(
            "MS-401", variant="permanent_magnet", description="Product Magnetic Separator"
        )
    )
    product = fs.add(units.Product("Dry Concentrate", reference="PFD-402"))
    tramp = fs.add(units.Product("Tramp Metal"))

    tee_w = 12.0
    feed_y = 140.0  # the concentrate feed line
    water_y = 230.0  # the make-up water line, below it
    dose_x = 336.0  # the flocculant riser

    concentrate.pin(port="outlet", x=90, y=feed_y)
    water.pin(port="outlet", x=90, y=water_y)

    charge.pin(mirrored="y").pin(port="inlet", x=130, y=water_y)
    funnel.pin(port="outlet", x=charge.pin_.x + tee_w / 2, y=water_y - 20)

    tank.pin(port="inlet", x=200, y=260)
    dose.pin(port="discharge", x=dose_x, y=430)

    floc.pin(port="branch", x=dose_x, y=feed_y + tee_w / 2)
    thickener.pin(port="feed", x=380, y=feed_y)
    overflow.pin(port="inlet", x=520, y=feed_y)  # dead level off the launder

    suction_y = 330.0
    underflow_pump.pin(port="suction", x=520.7, y=suction_y)
    suction_red.pin(port="outlet", x=478, y=suction_y)
    disch_red.pin(port="inlet", x=624, y=suction_y)
    belt_filter.pin(port="inlet", x=670, y=suction_y)

    cake_tee.pin(port="inlet", x=740, y=suction_y)
    filtrate.pin(port="inlet", x=770, y=560)

    belt_y, dryer_y = 480.0, 490.0
    conveyor.pin(port="feed", x=cake_tee.pin_.x + tee_w + 38, y=belt_y)
    breeching.pin(port="inlet", x=950, y=dryer_y)
    dryer.pin(port="feed", x=1000, y=dryer_y)

    heater.pin(port="inlet", x=860, y=654.5)
    air.pin(port="outlet", x=790, y=654.5)  # clear of the burner wall
    gas.pin(port="outlet", x=750, y=740)
    hot_gas_x = breeching.pin_.x + tee_w / 2

    cyclone.pin(port="feed", x=1180, y=322)
    scrub_tee.pin(mirrored="y").pin(port="inlet", x=1255, y=132)
    scrub_water.pin(port="outlet", x=1180, y=85)
    scrubber.pin(port="feed", x=1300, y=132)
    effluent.pin(port="inlet", x=1400, y=280)
    fan.pin(port="suction", x=1440, y=132)
    stack.pin(port="inlet", x=fan.pin_.x + port_offset(fan, "discharge")[0], y=60)

    magnet.pin(port="feed", x=1300, y=532)
    product.pin(port="inlet", x=1430, y=532)
    tramp.pin(port="inlet", x=1430, y=680)

    fs.connect(concentrate.outlet, floc.inlet, name="S-401")

    fs.connect(water.outlet, charge.inlet, name="S-402")
    fs.connect(funnel.outlet, charge.branch, name="S-403")
    fs.connect(charge.outlet, tank.inlet, name="S-404")

    fs.connect(tank.outlet, dose.suction, name="S-405")
    fs.connect(dose.discharge, floc.branch, name="S-405")
    fs.connect(floc.outlet, thickener.feed, name="S-406")

    fs.connect(thickener.port("overflow"), overflow.inlet, name="S-407")

    fs.connect(thickener.port("underflow"), suction_red.inlet, name="S-408").via([(420, 332.4)])
    fs.connect(suction_red.outlet, underflow_pump.suction, name="S-408")

    fs.connect(underflow_pump.discharge, disch_red.inlet, name="S-409")
    fs.connect(disch_red.outlet, belt_filter.inlet, name="S-409")
    fs.connect(belt_filter.outlet, cake_tee.inlet, name="S-409")

    fs.connect(cake_tee.branch, filtrate.inlet, name="S-410")

    fs.connect(cake_tee.outlet, conveyor.feed, name="S-411")
    fs.connect(conveyor.discharge, breeching.inlet, name="S-411")

    fs.connect(air.outlet, heater.inlet, name="S-412")
    fs.connect(gas.outlet, heater.fuel, name="S-413").via([(900, 740)])
    fs.connect(heater.outlet, breeching.branch, name="S-414").via([(hot_gas_x, 654.5 + 25)])

    fs.connect(breeching.outlet, dryer.feed, name="S-415")
    fs.connect(dryer.product, cyclone.feed, name="S-416")

    fs.connect(cyclone.port("overflow"), scrub_tee.inlet, name="S-417")
    fs.connect(scrub_water.outlet, scrub_tee.branch, name="S-418")
    fs.connect(scrub_tee.outlet, scrubber.feed, name="S-419")

    fs.connect(scrubber.port("vapor"), fan.suction, name="S-420")
    fs.connect(fan.discharge, stack.inlet, name="S-420")
    fs.connect(scrubber.port("liquid"), effluent.inlet, name="S-421")

    fs.connect(cyclone.port("underflow"), magnet.feed, name="S-422")
    fs.connect(magnet.port("overflow"), product.inlet, name="S-423")
    fs.connect(magnet.port("underflow"), tramp.inlet, name="S-424")

    for s in fs.streams:
        values = _MD_PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(_MD_PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    fs.title_block = TitleBlock(
        title="Mineral Dewatering",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        date="12/09/25",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "22/08/25", "Issued for internal review", "AA"),
            Revision("B", "05/09/25", "Dryer exhaust scrubber added", "AA"),
            Revision("C", "12/09/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    fs.add_annotation(
        equipment_list(
            fs,
            align="top",
            include=[
                "TK-401",
                "P-402",
                "TH-401",
                "P-401",
                "FL-401",
                "CV-401",
                "FH-401",
                "DR-401",
                "CY-401",
                "MS-401",
                "SC-401",
                "BL-401",
            ],
        )
    )
    fs.add_annotation(
        TableBox(
            title="UTILITIES SUMMARY",
            headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in", "T_out"],
            rows=[
                ["Natural Gas", "FH-401", "5972", "0.119", "15 C", "-"],
                ["Ambient Air", "FH-401", "-", "8.47", "15 C", "650 C"],
                ["Raw Water", "TK-401", "-", "0.175", "20 C", "-"],
                ["Scrubbing Water", "SC-401", "-1638", "11.53", "28 C", "62 C"],
            ],
            col_align=["l", "l", "r", "r", "c", "c"],
            align="bottom-right",
        )
    )

    return fs


def _tank_farm() -> Flowsheet:
    """Example 14 -- a bulk liquid storage tank farm and its road loading rack.

    The corpus's only sheet whose loop numbers are *allocated* rather than typed:
    ``add_loop("L")`` with no number takes the next from ``loop_number_start``, so
    the golden is what pins the allocated series to the drawing. Its title block
    states its own date, so nothing here is pinned.
    """
    fs = Flowsheet(
        "Product Storage and Road Loading A600",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=601,
        loop_number_start=601,
    )

    ms_level = fs.add_loop("L")  # L-601, TK-601 level
    eth_level = fs.add_loop("L")  # L-602, TK-602 level
    lpg_press = fs.add_loop("P")  # P-603, V-603 pressure
    load_flow = fs.add_loop("F")  # F-604, loading rate
    blend_flow = fs.add_loop("F")  # F-605, ethanol blend ratio

    tk601 = fs.add(
        units.Tank(
            "TK-601",
            variant="floating_roof",
            width=190,
            height=140,
            label_pos="center",
            description="Motor Spirit Storage Tank",
        )
    )
    tk602 = fs.add(
        units.Tank(
            "TK-602",
            width=180,
            height=150,
            label_pos="center",
            description="Denatured Ethanol Storage Tank",
        )
    )
    v603 = fs.add(
        units.Tank(
            "V-603",
            variant="sphere",
            width=140,
            height=185,
            label_pos="center",
            description="Butane Storage Sphere",
        )
    )
    v604 = fs.add(
        units.Vessel(
            "V-604",
            supports="leg",
            width=60,
            height=120,
            description="Loading Vapour Knock-Out Drum",
        )
    )

    p601 = fs.add(units.Pump("P-601", description="Motor Spirit Transfer Pump"))
    p602 = fs.add(
        units.Pump("P-602", variant="gear", width=48, height=76, description="Ethanol Blend Pump")
    )

    ms_in = fs.add(units.Feed("Motor Spirit", reference="P&ID-501"))
    eth_in = fs.add(units.Feed("Denatured Ethanol", reference="PFD-302"))
    lpg_in = fs.add(units.Feed("Butane", reference="P&ID-503"))
    e10_out = fs.add(units.Product("E10 Road Tanker", reference="P&ID-611"))
    lpg_out = fs.add(units.Product("LPG Road Tanker", reference="P&ID-612"))
    vap_in = fs.add(units.Feed("Tanker Vapour Return", reference="P&ID-611"))
    vru_out = fs.add(units.Product("Vapour Recovery Unit", reference="P&ID-609"))

    xv601 = fs.add(
        units.Valve(
            "XV-601", variant="solenoid", fail="closed", description="MS Receipt Trip Valve"
        )
    )
    xv602 = fs.add(
        units.Valve(
            "XV-602", variant="solenoid", fail="closed", description="Ethanol Receipt Trip Valve"
        )
    )
    hv601 = fs.add(units.Valve("HV-601", variant="gate", description="TK-601 Root Valve"))
    ej601 = fs.add(
        units.Fitting("EJ-601", variant="expansion_joint", description="TK-601 Nozzle Compensator")
    )
    st601 = fs.add(
        units.Fitting("ST-601", variant="strainer_basket", description="P-601 Suction Strainer")
    )
    rd601 = fs.add(
        units.Reducer("RD-601", variant="eccentric", description="P-601 Suction Reducer")
    )
    rd602 = fs.add(
        units.Reducer(
            "RD-602",
            variant="concentric",
            large_end="outlet",
            description="P-601 Discharge Expander",
        )
    )
    nrv601 = fs.add(units.Valve("NRV-601", variant="check", description="P-601 Non-Return Valve"))

    hv603 = fs.add(units.Valve("HV-603", variant="gate", description="TK-602 Root Valve"))
    sb601 = fs.add(units.Fitting("SB-601", variant="blind", description="TK-602 Spectacle Blind"))
    t_rec = fs.add(units.Tee(branch="inlet"))
    st602 = fs.add(
        units.Fitting("ST-602", variant="strainer_y", description="P-602 Suction Strainer")
    )
    t_psv = fs.add(units.Tee())
    psv602 = fs.add(units.Valve("PSV-602", variant="relief", description="P-602 Relief Valve"))
    fe605 = fs.add(
        units.Fitting(
            blend_flow.element("FE"), variant="coriolis", description="Ethanol Blend Meter"
        )
    )
    cv605 = fs.add(
        units.Valve(blend_flow.tag("CV"), variant="control", description="Ethanol Blend Valve")
    )
    nrv602 = fs.add(units.Valve("NRV-602", variant="check", description="P-602 Non-Return Valve"))

    hv605 = fs.add(units.Valve("HV-605", variant="gate", description="V-603 Root Valve"))
    pcv606 = fs.add(
        units.Valve("PCV-606", variant="regulator", description="Butane Let-Down Regulator")
    )
    hv608 = fs.add(units.Valve("HV-608", variant="ball", description="LPG Loading Arm Valve"))

    t_blend = fs.add(units.Tee(branch="inlet"))
    t_blend.new_line_number = True
    fe604 = fs.add(
        units.Fitting(
            load_flow.element("FE"),
            variant="positive_displacement",
            label_pos="bottom",
            description="Loading Meter",
        )
    )
    cv604 = fs.add(
        units.Valve(load_flow.tag("CV"), variant="control", description="Loading Rate Valve")
    )
    hv604 = fs.add(units.Valve("HV-604", variant="ball", description="E10 Loading Arm Valve"))
    hos601 = fs.add(units.Fitting("HOS-601", variant="hose", description="E10 Loading Hose"))

    fa602 = fs.add(
        units.Fitting(
            "FA-602",
            variant="flame_arrestor_detonation_proof",
            description="Vapour Return Flame Arrestor",
        )
    )
    hv607 = fs.add(units.Valve("HV-607", variant="butterfly", description="Vapour Header Valve"))
    fa601 = fs.add(
        units.Fitting("FA-601", variant="flame_arrestor", description="V-604 Vent Flame Arrestor")
    )
    vt601 = fs.add(units.Vent("VT-601", variant="breather", description="V-604 Conservation Vent"))

    tk601.pin(x=360, y=215)
    tk602.pin(x=680, y=205)
    v603.pin(x=1090, y=180)

    tk602.nozzle("inlet", "N")

    ms_drop_x = 340.0
    ms_fill_y = 215 + port_offset(tk601, "inlet")[1]
    ms_draw_x = 360 + port_offset(tk601, "outlet")[0]
    eth_fill_x = 680 + port_offset(tk602, "inlet")[0]
    eth_draw_x = 680 + port_offset(tk602, "outlet")[0]
    lpg_fill_y = 180 + port_offset(v603, "inlet")[1]
    lpg_draw_x = 1090 + port_offset(v603, "outlet")[0]

    ms_recv_y, eth_recv_y, lpg_recv_y = 170.0, 110.0, 50.0
    ms_in.pin(port="outlet", x=200, y=ms_recv_y)
    xv601.pin(port="inlet", x=250, y=ms_recv_y)
    eth_in.pin(port="outlet", x=200, y=eth_recv_y)
    xv602.pin(port="inlet", x=500, y=eth_recv_y)
    lpg_in.pin(port="outlet", x=200, y=lpg_recv_y)

    lpg_run_y, eth_run_y, ms_run_y = 390.0, 550.0, 665.0
    lpg_drop_x = 1040.0
    balloon_row_y, low_row_y, psv_run_y = 462.0, 564.0, 620.0
    cascade_y = 422.0

    hv601.pin(port="inlet", x=495, y=ms_run_y)
    ej601.pin(port="inlet", x=560, y=ms_run_y)
    st601.pin(port="inlet", x=605, y=ms_run_y)
    rd601.pin(port="inlet", x=665, y=ms_run_y)
    ms_suction_y = ms_run_y + port_offset(rd601, "outlet")[1] - port_offset(rd601, "inlet")[1]
    p601.pin(port="suction", x=705, y=ms_suction_y)
    ms_disch_y = ms_suction_y + port_offset(p601, "discharge")[1] - port_offset(p601, "suction")[1]
    rd602.pin(port="inlet", x=795, y=ms_disch_y)
    nrv601.pin(port="inlet", x=875, y=ms_disch_y)

    hv603.pin(port="inlet", x=785, y=eth_run_y)
    sb601.pin(port="inlet", x=845, y=eth_run_y)
    t_rec.pin(port="inlet", x=870, y=eth_run_y)
    st602.pin(port="inlet", x=896, y=eth_run_y)
    p602.pin(port="suction", x=940, y=eth_run_y)
    t_psv.pin(port="inlet", x=1060, y=eth_run_y)
    fe605.pin(port="inlet", x=1080, y=eth_run_y)
    cv605.pin(port="inlet", x=1140, y=eth_run_y)
    nrv602.pin(port="inlet", x=1180, y=eth_run_y)
    psv_branch_x = t_psv.pin_.x + port_offset(t_psv, "branch")[0]
    rec_branch_x = t_rec.pin_.x + port_offset(t_rec, "branch")[0]
    psv602.pin(port="inlet", x=rec_branch_x, y=psv_run_y)

    hv605.pin(port="inlet", x=1250, y=lpg_run_y)
    pcv606.pin(port="inlet", x=1310, y=lpg_run_y)
    hv608.pin(port="inlet", x=1390, y=lpg_run_y)
    lpg_out.pin(port="inlet", x=1560, y=lpg_run_y)

    blend_y = ms_disch_y
    t_blend.pin(mirrored="y").pin(port="inlet", x=1220, y=blend_y)
    blend_branch_x = t_blend.pin_.x + port_offset(t_blend, "branch")[0]
    fe604.pin(port="inlet", x=1340, y=blend_y)
    cv604.pin(port="inlet", x=1400, y=blend_y)
    hv604.pin(port="inlet", x=1460, y=blend_y)
    hos601.pin(port="inlet", x=1505, y=blend_y)
    e10_out.pin(port="inlet", x=1560, y=blend_y)

    vap_y = 830.0
    drum_x, vap_gap = 1255.0, 52.0
    fa602_x = drum_x - vap_gap - port_offset(fa602, "outlet")[0]
    hv607_x = fa602_x - vap_gap - port_offset(hv607, "outlet")[0]
    vap_in.pin(port="outlet", x=200, y=vap_y)
    hv607.pin(port="inlet", x=hv607_x, y=vap_y)
    fa602.pin(port="inlet", x=fa602_x, y=vap_y)
    v604.pin(port="inlet", x=drum_x, y=vap_y)
    vent_x = v604.pin_.x + port_offset(v604, "vent")[0]
    vent_y = v604.pin_.y + port_offset(v604, "vent")[1]
    fa601.pin(orientation=270).pin(port="inlet", x=vent_x, y=vent_y - 22)
    vt601.pin(port="inlet", x=vent_x, y=vent_y - 68)
    vru_out.pin(port="inlet", x=1560, y=vap_y)

    fs.connect(
        ms_in.outlet, xv601.inlet, service="MS", sequence=601, size=200, schedule=40, spec="CS"
    )
    fs.connect(xv601.outlet, tk601.inlet).via([(ms_drop_x, ms_recv_y), (ms_drop_x, ms_fill_y)])
    fs.connect(
        eth_in.outlet, xv602.inlet, service="ETH", sequence=602, size=150, schedule=40, spec="SS"
    )
    fs.connect(xv602.outlet, tk602.inlet).via([(eth_fill_x, eth_recv_y)])
    fs.connect(
        lpg_in.outlet, v603.inlet, service="LPG", sequence=603, size=100, schedule=80, spec="CS"
    ).via([(lpg_drop_x, lpg_recv_y), (lpg_drop_x, lpg_fill_y)])

    fs.connect(
        tk601.outlet, hv601.inlet, service="MS", sequence=604, size=250, schedule=40, spec="CS"
    ).via([(ms_draw_x, ms_run_y)])
    fs.connect(hv601.outlet, ej601.inlet)
    fs.connect(ej601.outlet, st601.inlet)
    fs.connect(st601.outlet, rd601.inlet)
    fs.connect(rd601.outlet, p601.suction)
    fs.connect(
        p601.discharge, rd602.inlet, service="MS", sequence=605, size=200, schedule=40, spec="CS"
    )
    fs.connect(rd602.outlet, nrv601.inlet)
    fs.connect(nrv601.outlet, t_blend.inlet)

    fs.connect(
        tk602.outlet, hv603.inlet, service="ETH", sequence=606, size=100, schedule=40, spec="SS"
    ).via([(eth_draw_x, eth_run_y)])
    fs.connect(hv603.outlet, sb601.inlet)
    fs.connect(sb601.outlet, t_rec.inlet)
    fs.connect(t_rec.outlet, st602.inlet)
    fs.connect(st602.outlet, p602.suction)
    fs.connect(
        p602.discharge, t_psv.inlet, service="ETH", sequence=607, size=80, schedule=40, spec="SS"
    )
    fs.connect(t_psv.outlet, fe605.inlet)
    fs.connect(fe605.outlet, cv605.inlet)
    fs.connect(cv605.outlet, nrv602.inlet)
    fs.connect(nrv602.outlet, t_blend.branch).via([(blend_branch_x, eth_run_y)])
    fs.connect(
        t_psv.branch, psv602.inlet, service="ETH", sequence=613, size=40, schedule=40, spec="SS"
    ).via([(psv_branch_x, psv_run_y)])
    fs.connect(psv602.outlet, t_rec.branch)

    fs.connect(
        v603.outlet, hv605.inlet, service="LPG", sequence=608, size=80, schedule=80, spec="CS"
    ).via([(lpg_draw_x, lpg_run_y)])
    fs.connect(hv605.outlet, pcv606.inlet)
    fs.connect(pcv606.outlet, hv608.inlet)
    fs.connect(hv608.outlet, lpg_out.inlet)

    fs.connect(
        t_blend.outlet, fe604.inlet, service="E10", sequence=609, size=200, schedule=40, spec="CS"
    )
    fs.connect(fe604.outlet, cv604.inlet)
    fs.connect(cv604.outlet, hv604.inlet)
    fs.connect(hv604.outlet, hos601.inlet)
    fs.connect(hos601.outlet, e10_out.inlet)

    fs.connect(
        vap_in.outlet, hv607.inlet, service="VAP", sequence=610, size=150, schedule=40, spec="CS"
    )
    fs.connect(hv607.outlet, fa602.inlet)
    fs.connect(fa602.outlet, v604.inlet)
    fs.connect(
        v604.outlet, vru_out.inlet, service="VAP", sequence=612, size=150, schedule=40, spec="CS"
    )
    fs.connect(
        v604.vent, fa601.inlet, service="VAP", sequence=611, size=150, schedule=40, spec="CS"
    )
    fs.connect(fa601.outlet, vt601.inlet)

    lt601 = fs.add_instrument("LT", ms_level, sensing=tk601, at="W", offset=62)
    fs.add_instrument("LI", ms_level, near=lt601, at="S", offset=50, variant="shared").annotate(
        high="LAH", low="LAL"
    )
    lt602 = fs.add_instrument("LT", eth_level, sensing=tk602, at="W", offset=32)
    fs.add_instrument("LI", eth_level, near=lt602, at="S", offset=50, variant="shared").annotate(
        high="LAH", low="LAL"
    )

    lsh611 = fs.add_instrument("LSHH", 611, sensing=tk601, at="E", offset=32)
    lsh612 = fs.add_instrument("LSHH", 612, sensing=tk602, at="E", offset=40)
    fs.add_instrument("Z", 1, sensing=lsh611, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, sensing=lsh612, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv601, at="S", offset=46, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv602, at="S", offset=46, variant="sis")

    pt603 = fs.add_instrument("PT", lpg_press, sensing=v603, at="E", offset=30)
    fs.add_instrument("PI", lpg_press, near=pt603, at="N", offset=40, variant="shared").annotate(
        high="PAH"
    )

    cv604_axis = 1400 + resolve_size(cv604)[0] / 2
    cv605_axis = 1140 + resolve_size(cv605)[0] / 2
    fe604_top = blend_y - port_offset(fe604, "inlet")[1]
    cv604_top = blend_y - port_offset(cv604, "inlet")[1]
    fe605_top = eth_run_y - port_offset(fe605, "inlet")[1]
    cv605_top = eth_run_y - port_offset(cv605, "inlet")[1]

    fe604_b = fs.add_balloon(fe604, at="N", offset=fe604_top - low_row_y - 45)
    ft604 = fs.add_instrument("FT", load_flow, near=fe604_b, at="N", offset=23)
    fic604 = fs.add_instrument(
        "FIC", load_flow, near=cv604, at="N", variant="shared", offset=cv604_top - balloon_row_y
    )
    fic604.nozzle("sig_out", "S")
    fs.connect(ft604.sig_out, fic604.sig_in, kind="electric")
    fs.connect(fic604.sig_out, cv604.actuator, kind="pneumatic")

    fe605_b = fs.add_balloon(fe605, at="N", offset=fe605_top - balloon_row_y - 45)
    ft605 = fs.add_instrument("FT", blend_flow, near=fe605_b, at="N", offset=23)
    fic605 = fs.add_instrument(
        "FIC", blend_flow, near=cv605, at="N", variant="shared", offset=cv605_top - balloon_row_y
    )
    fic605.nozzle("sig_out", "S")
    fic605.nozzle("sig_in", "N")
    fs.connect(ft605.sig_out, fic605.pv, kind="electric")
    fs.connect(fic604.sig_out, fic605.sig_in, kind="software").via(
        [(cv604_axis, cascade_y), (cv605_axis, cascade_y)]
    )
    fs.connect(fic605.sig_out, cv605.actuator, kind="pneumatic")

    fs.title_block = TitleBlock(
        title="Tank Farm and Loading",
        subtitle="A600 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-601",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        date="12/12/25",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "28/11/25", "Issued for internal review", "AA"),
            Revision("B", "12/12/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(
        Annotation(
            title="EQUIPMENT LIST",
            rows=[
                ("TK-601", "Motor Spirit Storage Tank"),
                ("TK-602", "Denatured Ethanol Storage Tank"),
                ("V-603", "Butane Storage Sphere"),
                ("V-604", "Loading Vapour Knock-Out Drum"),
                ("P-601", "Motor Spirit Transfer Pump"),
                ("P-602", "Ethanol Blend Pump"),
            ],
            align="top-right",
        )
    )
    fs.add_annotation(
        notes(
            [
                "Z-1: receipt shutdown on tank high-high level.",
                "LSHH-611/612 are independent of the gauging transmitters they back up.",
                "FA-601 is deflagration rated; FA-602, on the rack return, is detonation",
                "rated. VT-601 is the vapour system's only opening to atmosphere.",
                "SB-601 gives TK-602 positive isolation from the blend header.",
                "TK-602 is filled through an internal downcomer carried to the floor.",
            ],
            title="GENERAL NOTES",
            numbered=False,
            align="bottom-left",
        )
    )
    fs.add_annotation(
        legend(
            {
                "MS": "Motor Spirit",
                "ETH": "Denatured Ethanol",
                "LPG": "Liquefied Petroleum Gas",
                "E10": "Ethanol Blended Motor Spirit",
                "VAP": "Loading Vapour",
                "CS": "Carbon Steel A106-B",
                "SS": "Stainless Steel 316L",
            },
            align="top-left",
        )
    )
    return fs


def _condensing_turbine() -> Flowsheet:
    fs = Flowsheet("Condensing Turbine and Vacuum System")

    hp_steam = fs.add(units.Feed("HP Steam", reference="PFD-700"))
    s701 = fs.add(units.Separator("S-701", variant="knockout", description="HP Steam Separator"))
    gv701 = fs.add(units.Valve("GV-701", variant="globe", description="MP Steam Isolation Valve"))
    trap = fs.add(units.Product("Steam Trap Drain", reference="PFD-800"))
    tv701 = fs.add(
        units.Valve(
            "TV-701",
            variant="hydraulic",
            fail="closed",
            description="Turbine Trip and Throttle Valve",
        )
    )
    st701 = fs.add(units.Turbine("ST-701", description="Condensing Steam Turbine"))
    e701 = fs.add(
        units.HeatExchanger("E-701", variant="air_cooled", description="Air-Cooled Condenser")
    )

    ej701 = fs.add(units.Ejector("EJ-701", description="Condenser Air Ejector"))
    v701 = fs.add(units.Vessel("V-701", variant="dished", description="Condensate Receiver"))
    sp701 = fs.add(units.Splitter("SP-701", n_outlets=2))
    vt701 = fs.add(units.Vent("VT-701", description="Non-Condensibles Vent"))

    p701 = fs.add(units.Pump("P-701A/B", description="Condensate Pump"))
    e702 = fs.add(units.Heater("E-702", description="LP Feedwater Heater"))
    mp_steam = fs.add(units.Feed("MP Steam", reference="PFD-700"))

    level = fs.add_loop("L", 701)
    lv701 = fs.add(
        units.Valve(
            level.tag("LV"),
            variant="control",
            fail="open",
            description="Receiver Level Control Valve",
        )
    )
    xv701 = fs.add(
        units.Valve(
            "XV-701",
            variant="butterfly_pneumatic",
            fail="closed",
            description="Low-Level Trip Valve",
        )
    )
    deaerator = fs.add(units.Product("To Deaerator", reference="PFD-800"))

    fs.connect(hp_steam.outlet, s701.feed)
    fs.connect(s701.liquid, trap.inlet)
    fs.connect(s701.vapor, tv701.inlet)
    fs.connect(tv701.outlet, st701.inlet)
    exhaust = fs.connect(st701.outlet, e701.tube_in)
    fs.connect(e701.tube_out, v701.inlet)

    fs.connect(v701.vent, ej701.suction)
    fs.connect(sp701.out_1, ej701.motive)
    fs.connect(ej701.discharge, vt701.inlet)

    fs.connect(v701.outlet, p701.suction)
    fs.connect(p701.discharge, e702.inlet)
    fs.connect(mp_steam.outlet, gv701.inlet)
    fs.connect(gv701.outlet, sp701.inlet)
    fs.connect(sp701.out_2, e702.utility_in)
    fs.connect(e702.outlet, lv701.inlet)
    fs.connect(lv701.outlet, xv701.inlet)
    fs.connect(xv701.outlet, deaerator.inlet)

    lt701 = fs.add_instrument("LT", level, sensing=v701, at="S", offset=55)
    lic701 = fs.add_instrument("LIC", level, near=lv701, at="N", offset=110, variant="shared")
    trip = fs.add_instrument(
        "ZSL",
        701,
        near=lic701,
        at="N",
        offset=70,
        variant="interlock",
        description="Low-Level Trip",
    )
    fs.connect(lt701.sig_out, lic701.pv, kind="electric")
    fs.connect(lic701.sig_out, lv701.actuator, kind="pneumatic")
    fs.connect(lic701.sig_out, trip.sig_in, kind="electric")
    fs.connect(trip.sig_out, xv701.actuator, kind="electric")

    vacuum = fs.add_loop("P", 702)
    pt702 = fs.add_instrument("PT", vacuum, sensing=exhaust, at=0.5, offset=60)
    pi702 = fs.add_instrument(
        "PI",
        vacuum,
        near=pt702,
        at="N",
        offset=65,
        display="subsidiary",
        description="Local Gauge Board",
    )
    fs.connect(pt702.sig_out, pi702.sig_in, kind="electric")
    return fs


def _demineralised_water() -> Flowsheet:
    fs = Flowsheet("Demineralised Water Plant")

    raw = fs.add(units.Feed("Raw Water", reference="PFD-100"))
    t801 = fs.add(
        units.Tank("T-801", variant="dished_roof_conical_bottom", description="Raw Water Tank")
    )
    st801 = fs.add(
        units.Fitting(
            "ST-801", variant="strainer_duplex", description="Transfer Pump Suction Strainer"
        )
    )
    p801 = fs.add(units.Pump("P-801A/B", description="Raw Water Transfer Pump"))
    f801 = fs.add(units.Filter("F-801", description="Multimedia Filter"))
    f802 = fs.add(units.Filter("F-802", variant="fixed_bed", description="Activated Carbon Filter"))
    ix801 = fs.add(units.Filter("IX-801", variant="ion_exchange", description="Cation Exchanger"))

    d801 = fs.add(units.Column("D-801", variant="packed", description="Degasser Tower"))
    air = fs.add(units.Feed("Stripping Air"))
    b801 = fs.add(units.Blower("B-801", description="Degasser Air Blower"))
    vt801 = fs.add(units.Vent("VT-801", description="Degasser Vent"))

    p802 = fs.add(units.Pump("P-802A/B", description="Degassed Water Pump"))
    ix802 = fs.add(units.Filter("IX-802", variant="ion_exchange", description="Anion Exchanger"))
    ix803 = fs.add(units.Filter("IX-803", variant="ion_exchange", description="Mixed Bed Polisher"))
    t802 = fs.add(units.Tank("T-802", variant="conical", description="Demineralised Water Tank"))
    hv801 = fs.add(units.Valve("HV-801", variant="manual", description="Demin Water Outlet Valve"))
    header = fs.add(units.Product("To Demin Water Header", reference="PFD-200"))

    fs.connect(raw.outlet, t801.inlet)
    fs.connect(t801.outlet, st801.inlet)
    fs.connect(st801.outlet, p801.suction)
    fs.connect(p801.discharge, f801.inlet)
    fs.connect(f801.outlet, f802.inlet)
    fs.connect(f802.outlet, ix801.inlet)

    fs.connect(ix801.outlet, d801.feed)
    fs.connect(air.outlet, b801.suction)
    fs.connect(b801.discharge, d801.boilup_in)
    fs.connect(d801.distillate, vt801.inlet)
    fs.connect(d801.bottoms, p802.suction)

    fs.connect(p802.discharge, ix802.inlet)
    fs.connect(ix802.outlet, ix803.inlet)
    fs.connect(ix803.outlet, t802.inlet)
    fs.connect(t802.outlet, hv801.inlet)
    fs.connect(hv801.outlet, header.inlet)

    fs.title_block = TitleBlock(
        title="Demineralised Water",
        subtitle="U800 Process Flow Diagram",
        drawing_number="PFD-801",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        date="03/08/26",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "24/07/26", "Issued for internal review", "AA"),
            Revision("B", "03/08/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(
        equipment_list(
            fs,
            align="top",
            include=[
                "T-801",
                "P-801A/B",
                "F-801",
                "F-802",
                "IX-801",
                "D-801",
                "B-801",
                "P-802A/B",
                "IX-802",
                "IX-803",
                "T-802",
            ],
        )
    )
    return fs


_AMINE_PROPERTY_ROWS = (
    "Temperature (C)",
    "Pressure (bara)",
    "Vapour Fraction",
    "Total Flow (kg/s)",
    "Methane",
    "Ethane",
    "CO2",
    "H2S",
    "MDEA",
    "Water",
)

_AMINE_PROPERTIES = {
    "S-401": ("40", "66.0", "1.000", "30.00", "0.900", "0.040", "0.050", "0.010", "", ""),
    "S-402": ("46", "65.4", "1.000", "28.31", "0.953", "0.042", "0.003", "2.0E-06", "", "0.002"),
    "S-403": ("45", "68.0", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04", "0.449", "0.550"),
    "S-404": ("62", "65.8", "0.000", "121.7", "", "", "0.0136", "2.55E-03", "0.443", "0.542"),
    "S-405": ("97", "1.90", "0.012", "121.7", "", "", "0.0136", "2.55E-03", "0.443", "0.542"),
    "S-406": ("104", "1.85", "1.000", "6.02", "", "", "0.276", "0.052", "", "0.672"),
    "S-407": ("50", "1.80", "0.286", "6.02", "", "", "0.276", "0.052", "", "0.672"),
    "S-408": ("50", "1.75", "1.000", "1.72", "", "", "0.850", "0.110", "", "0.040"),
    "S-409": ("50", "1.80", "0.000", "4.30", "", "", "0.047", "0.029", "", "0.924"),
    "S-410": ("122", "2.00", "0.000", "148.5", "", "", "1.42E-03", "1.2E-04", "0.363", "0.636"),
    "S-411": ("124", "2.02", "1.000", "28.5", "", "", "5.0E-03", "4.0E-04", "", "0.995"),
    "S-412": ("122", "2.00", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04", "0.449", "0.550"),
    "S-413": ("75", "1.60", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04", "0.449", "0.550"),
    "S-414": ("76", "70.0", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04", "0.449", "0.550"),
    "S-415": ("152", "5.00", "1.000", "11.30", "", "", "", "", "", "1.000"),
    "S-416": ("151", "4.90", "0.000", "11.30", "", "", "", "", "", "1.000"),
    "S-417": ("25", "4.00", "0.000", "72.4", "", "", "", "", "", "1.000"),
    "S-418": ("40", "3.40", "0.000", "72.4", "", "", "", "", "", "1.000"),
    "S-419": ("25", "4.00", "0.000", "196.3", "", "", "", "", "", "1.000"),
    "S-420": ("40", "3.40", "0.000", "196.3", "", "", "", "", "", "1.000"),
}


def _stirred_reactor_train() -> Flowsheet:
    """Example 17 -- the jacketed CSTR, and the composition layer drawn as plant.

    The only scenario with an agitator, a drive motor or a jacketed body on it,
    and the one that pins ISO items 28.4 and 20.6 composed onto a vessel. Its
    title block states its own date, so nothing here is pinned.
    """
    fs = Flowsheet("Propylene Glycol Reaction A200", line_number_start=201)

    flow201 = fs.add_loop("F", 201)
    temp202 = fs.add_loop("T", 202)
    level203 = fs.add_loop("L", 203)
    press204 = fs.add_loop("P", 204)
    flow205 = fs.add_loop("F", 205)

    rx = fs.add(
        units.Reactor(
            "R-101",
            variant="jacketed",
            agitator="turbine",
            width=130,
            height=360,
            description="Propylene Glycol Reactor",
        )
    )
    cooler = fs.add(
        units.HeatExchanger(
            "E-201", variant="straight_tubes", width=130, height=40, description="Product Cooler"
        )
    )
    pump = fs.add(units.Pump("P-201A/B", description="Propylene Oxide Charge Pump"))

    po_feed = fs.add(units.Feed("Propylene Oxide", reference="P&ID-101"))
    water = fs.add(units.Feed("Process Water", reference="P&ID-101"))
    quench = fs.add(units.Feed("QWSH", header=True))
    cws_jkt = fs.add(units.Feed("CWSH", header=True))
    cws_cool = fs.add(units.Feed("CWSH", header=True))
    cwr_cool = fs.add(units.Product("CWRH", header=True))
    vent_gas = fs.add(units.Product("To Vent Scrubber", reference="P&ID-902"))
    glycol = fs.add(units.Product("Crude Propylene Glycol", reference="P&ID-301"))

    xv201 = fs.add(
        units.Valve(
            "XV-201", variant="solenoid", fail="closed", description="Reactor Feed Trip Valve"
        )
    )
    fe201 = fs.add(
        units.Fitting(
            flow201.element("FE"), variant="venturi", description="Propylene Oxide Flow Element"
        )
    )
    cv201 = fs.add(
        units.Valve(
            flow201.tag("CV"),
            variant="control",
            fail="closed",
            description="Propylene Oxide Control Valve",
        )
    )
    hv202 = fs.add(units.Valve("HV-202", description="Process Water Block Valve"))
    charge = fs.add(units.Tee(branch="inlet"))
    mixer = fs.add(
        units.Fitting("M-201", variant="static_mixer", description="Reactor Charge Static Mixer")
    )
    dump = fs.add(units.Tee(branch="inlet"))
    xv206 = fs.add(
        units.Valve("XV-206", variant="solenoid", fail="open", description="Reactor Quench Valve")
    )
    cv204 = fs.add(
        units.Valve(
            press204.tag("CV"),
            variant="control",
            fail="open",
            description="Reactor Vent Control Valve",
        )
    )
    cv203 = fs.add(
        units.Valve(
            level203.tag("CV"),
            variant="control",
            fail="closed",
            description="Product Draw Control Valve",
        )
    )
    hv205 = fs.add(units.Valve("HV-205", description="Jacket Cooling Water Block Valve"))
    fe205 = fs.add(
        units.Fitting(
            flow205.element("FE"),
            variant="venturi",
            description="Jacket Cooling Water Flow Element",
        )
    )
    cv205 = fs.add(
        units.Valve(
            flow205.tag("CV"),
            variant="control",
            fail="open",
            description="Jacket Cooling Water Control Valve",
        )
    )
    hv207 = fs.add(units.Valve("HV-207", description="E-201 Cooling Water Block Valve"))

    rx_x, rx_y = 640.0, 230.0
    rx.pin(x=rx_x, y=rx_y)
    charge_y = rx_y + port_offset(rx, "feed")[1]
    jacket_y = rx_y + port_offset(rx, "duty")[1]
    vent_y = rx_y + port_offset(rx, "vent")[1]
    draw_x = rx_x + port_offset(rx, "outlet")[0]

    pump.pin(x=150).pin(port="discharge", y=charge_y)
    po_feed.pin(port="outlet", x=80, y=pump.pin_.y + port_offset(pump, "suction")[1])
    xv201.pin(mirrored="y").pin(port="inlet", x=340, y=charge_y)
    fe201.pin(port="inlet", x=410, y=charge_y)
    cv201.pin(port="inlet", x=470, y=charge_y)
    charge.pin(port="inlet", x=520, y=charge_y)
    mixer.pin(port="inlet", x=545, y=charge_y)
    dump.pin(port="inlet", x=590, y=charge_y)

    water_run_y = 620.0
    water.pin(port="outlet", x=80, y=water_run_y)
    hv202.pin(port="inlet", x=300, y=water_run_y)

    quench_run_y = 740.0
    quench.pin(port="outlet", x=80, y=quench_run_y)
    xv206.pin(mirrored="y").pin(port="inlet", x=340, y=quench_run_y)

    vent_run_y = 120.0
    vent_riser_x = 1000.0
    cv204.pin(port="inlet", x=1150, y=vent_run_y)
    vent_gas.pin(port="inlet", x=1540, y=vent_run_y)

    cws_jkt.pin(mirrored=True).pin(port="outlet", x=1540, y=jacket_y)
    hv205.pin(mirrored=True).pin(port="inlet", x=1420, y=jacket_y)
    fe205.pin(mirrored=True).pin(port="inlet", x=1300, y=jacket_y)
    cv205.pin(mirrored=True).pin(port="inlet", x=1150, y=jacket_y)

    product_y = 720.0
    cv203.pin(port="inlet", x=880, y=product_y)
    cooler.pin(x=1040).pin(port="tube_in", y=product_y)
    shell_in_x = cooler.pin_.x + port_offset(cooler, "shell_in")[0]
    shell_out_x = cooler.pin_.x + port_offset(cooler, "shell_out")[0]
    cws_cool.pin(port="outlet", x=shell_in_x, y=590)
    hv207.pin(orientation=90).pin(port="inlet", x=shell_in_x, y=640)
    cwr_cool.pin(port="inlet", x=shell_out_x, y=850)
    glycol.pin(port="inlet", x=1540, y=product_y)

    fs.connect(po_feed.outlet, pump.suction, size=80, service="PO", sequence=201, spec="SS")
    fs.connect(pump.discharge, xv201.inlet, size=50, service="PO", sequence=202, spec="SS")
    fs.connect(xv201.outlet, fe201.inlet)
    fs.connect(fe201.outlet, cv201.inlet)
    fs.connect(cv201.outlet, charge.inlet)
    fs.connect(water.outlet, hv202.inlet, size=50, service="PW", sequence=203, spec="CS")
    fs.connect(hv202.outlet, charge.branch)
    fs.connect(charge.outlet, mixer.inlet, size=80, service="RC", sequence=204, spec="SS")
    fs.connect(mixer.outlet, dump.inlet)
    fs.connect(dump.outlet, rx.feed)

    fs.connect(quench.outlet, xv206.inlet, size=80, service="QWS", sequence=205, spec="CS")
    fs.connect(xv206.outlet, dump.branch)

    off_gas = fs.connect(rx.vent, cv204.inlet, size=100, service="VG", sequence=206, spec="SS").via(
        [(vent_riser_x, vent_y), (vent_riser_x, vent_run_y)]
    )
    fs.connect(cv204.outlet, vent_gas.inlet)

    fs.connect(cws_jkt.outlet, hv205.inlet, size=150, service="CWS", sequence=207, spec="CS")
    fs.connect(hv205.outlet, fe205.inlet)
    fs.connect(fe205.outlet, cv205.inlet)
    fs.connect(cv205.outlet, rx.duty)

    draw = fs.connect(rx.outlet, cv203.inlet, size=100, service="PG", sequence=208, spec="SS").via(
        [(draw_x, product_y)]
    )
    fs.connect(cv203.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, glycol.inlet, size=100, service="PG", sequence=211, spec="SS")
    fs.connect(cws_cool.outlet, hv207.inlet, size=100, service="CWS", sequence=209, spec="CS")
    fs.connect(hv207.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr_cool.inlet, size=100, service="CWR", sequence=210, spec="CS")

    fe201_b = fs.add_balloon(fe201, at="N", offset=38)
    ft201 = fs.add_instrument("FT", flow201, near=fe201_b, at="N", offset=23)
    fic201 = fs.add_instrument("FIC", flow201, near=ft201, at="N", offset=60, variant="shared")
    fic201.nozzle("sig_out", "E")
    fs.connect(ft201.sig_out, fic201.pv, kind="electric")
    fs.connect(fic201.sig_out, cv201.actuator, kind="pneumatic")

    tt202 = fs.add_instrument("TT", temp202, sensing=rx, at="E", offset=80)
    tic202 = fs.add_instrument("TIC", temp202, near=tt202, at="S", offset=130, variant="shared")
    tic202.nozzle("sig_out", "E")
    tic202.annotate(high="TAH", low="TAL")
    fs.connect(tt202.sig_out, tic202.sig_in, kind="electric")

    fe205_b = fs.add_balloon(fe205, at="N", offset=38)
    ft205 = fs.add_instrument("FT", flow205, near=fe205_b, at="N", offset=23)
    fic205 = fs.add_instrument("FIC", flow205, near=ft205, at="W", offset=90, variant="shared")
    fic205.nozzle("sig_out", "S")
    fs.connect(ft205.sig_out, fic205.pv, kind="electric")
    fs.connect(tic202.sig_out, fic205.sig_in, kind="software")
    fs.connect(fic205.sig_out, cv205.actuator, kind="pneumatic")

    lt203 = fs.add_instrument("LT", level203, sensing=rx, at="W", offset=90)
    lic203 = fs.add_instrument("LIC", level203, near=lt203, at="N", offset=90, variant="shared")
    lic203.nozzle("sig_out", "E")
    lic203.annotate(high="LAH", low="LAL")
    fs.connect(lt203.sig_out, lic203.sig_in, kind="electric")
    fs.connect(lic203.sig_out, cv203.actuator, kind="pneumatic")

    pt204 = fs.add_instrument("PT", press204, sensing=off_gas, at=0.6, offset=70, angle=-90)
    pic204 = fs.add_instrument("PIC", press204, near=pt204, at="E", offset=90, variant="shared")
    pic204.nozzle("sig_out", "E")
    pic204.annotate(high="PAH")
    fs.connect(pt204.sig_out, pic204.sig_in, kind="electric")
    fs.connect(pic204.sig_out, cv204.actuator, kind="pneumatic")

    tt207 = fs.add_instrument("TT", 207, sensing=draw, at=0.12, offset=90)
    si208 = fs.add_instrument("ST", 208, sensing=rx, at="N", offset=70)
    fs.add_instrument("Z", 1, sensing=tt207, at="E", offset=44, variant="sis")
    fs.add_instrument("Z", 1, sensing=si208, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv201, at="N", offset=34, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv206, at="N", offset=34, variant="sis")

    fs.title_block = TitleBlock(
        title="Propylene Glycol Reaction",
        subtitle="A200 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-201",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        date="04/02/26",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "16/01/26", "Issued for internal review", "AA"),
            Revision("B", "04/02/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(
        equipment_list(
            fs,
            align="top-right",
            include=[
                "R-101",
                "P-201A/B",
                "E-201",
            ],
        )
    )
    fs.add_annotation(
        notes(
            [
                "Z-1: reactor runaway trip. TT-207 and ST-208 are its own "
                "measurements, independent of TIC-202.",
                "Z-1 shuts XV-201 and opens XV-206 together; the quench is sized "
                "for the full reactor inventory.",
                "R-101 jacket cooling water return is on P&ID-202.",
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
                "PO": "Propylene Oxide",
                "PW": "Process Water",
                "RC": "Reactor Charge",
                "PG": "Propylene Glycol",
                "VG": "Reactor Vent Gas",
                "CWSH": "Cooling Water Supply Header",
                "CWRH": "Cooling Water Return Header",
                "QWSH": "Quench Water Supply Header",
            },
            align="top-left",
        )
    )
    return fs


def _fixed_bed_recycle() -> Flowsheet:
    """Example 18 -- a packed catalytic converter in a synthesis loop.

    The only scenario drawing ISO item 27.8's bed in a reactor, and so what
    holds ``internals=`` to leaving the default agitator out. Laid out end to
    end by the engine, with the recycle torn and drawn as a lane across the
    sheet; it states its own title-block date.
    """
    fs = Flowsheet("Methanol Synthesis Loop A300", line_number_start=301)

    flow301 = fs.add_loop("F", 301)
    temp302 = fs.add_loop("T", 302)
    flow303 = fs.add_loop("F", 303)
    press304 = fs.add_loop("P", 304)
    level305 = fs.add_loop("L", 305)

    rx = fs.add(
        units.Reactor(
            "R-301", internals="packing", width=90, height=200, description="Methanol Converter"
        )
    )
    fehe = fs.add(
        units.HeatExchanger(
            "E-301",
            variant="straight_tubes",
            width=120,
            height=36,
            description="Feed / Effluent Exchanger",
        )
    )
    heater = fs.add(units.Furnace("H-301", description="Converter Fired Heater"))
    cooler = fs.add(
        units.HeatExchanger(
            "E-302", variant="straight_tubes", width=120, height=36, description="Product Condenser"
        )
    )
    sep = fs.add(
        units.Separator("V-301", variant="knockout", description="Crude Methanol Separator")
    )
    makeup_k = fs.add(units.Compressor("K-301", description="Make-up Gas Compressor"))
    recycle_k = fs.add(units.Compressor("K-302", description="Recycle Gas Compressor"))

    syngas = fs.add(units.Feed("Synthesis Gas", reference="P&ID-201"))
    fuel = fs.add(units.Feed("FGSH", header=True))
    cws = fs.add(units.Feed("CWSH", header=True))
    cwr = fs.add(units.Product("CWRH", header=True))
    purge_gas = fs.add(units.Product("Purge to Fuel Gas", reference="P&ID-901"))
    crude = fs.add(units.Product("Crude Methanol", reference="P&ID-401"))

    mix = fs.add(units.Tee(branch="inlet"))
    purge_tee = fs.add(units.Tee())

    fe301 = fs.add(
        units.Fitting(
            flow301.element("FE"), variant="orifice", description="Make-up Gas Flow Element"
        )
    )
    cv301 = fs.add(
        units.Valve(
            flow301.tag("CV"),
            variant="control",
            fail="closed",
            description="Make-up Gas Control Valve",
        )
    )
    fe303 = fs.add(
        units.Fitting(flow303.element("FE"), variant="orifice", description="Fuel Gas Flow Element")
    )
    xv307 = fs.add(
        units.Valve(
            "XV-307", variant="solenoid", fail="closed", description="Fired Heater Fuel Trip Valve"
        )
    )
    cv303 = fs.add(
        units.Valve(
            flow303.tag("CV"),
            variant="control",
            fail="closed",
            description="Fuel Gas Control Valve",
        )
    )
    cv304 = fs.add(
        units.Valve(
            press304.tag("CV"),
            variant="control",
            fail="open",
            description="Loop Purge Control Valve",
        )
    )
    cv305 = fs.add(
        units.Valve(
            level305.tag("CV"),
            variant="control",
            fail="closed",
            description="Crude Methanol Control Valve",
        )
    )

    fs.connect(syngas.outlet, fe301.inlet, size=300, service="SG", sequence=301, spec="CS")
    fs.connect(fe301.outlet, cv301.inlet)
    fs.connect(cv301.outlet, makeup_k.suction)
    fs.connect(makeup_k.discharge, mix.inlet, size=200, service="SG", sequence=302, spec="CS")

    fs.connect(mix.outlet, fehe.tube_in, size=350, service="LG", sequence=303, spec="CS")
    fs.connect(fehe.tube_out, heater.inlet, size=350, service="LG", sequence=314, spec="CS")
    inlet_line = fs.connect(heater.outlet, rx.feed, size=350, service="LG", sequence=304, spec="LT")
    fs.connect(rx.outlet, fehe.shell_in, size=350, service="LG", sequence=305, spec="LT")
    fs.connect(fehe.shell_out, cooler.tube_in, size=350, service="LG", sequence=306, spec="CS")
    fs.connect(cooler.tube_out, sep.feed, size=350, service="LG", sequence=315, spec="CS")

    fs.connect(sep.liquid, cv305.inlet, size=100, service="CM", sequence=307, spec="SS")
    fs.connect(cv305.outlet, crude.inlet)

    loop_gas = fs.connect(
        sep.vapor, purge_tee.inlet, size=350, service="LG", sequence=308, spec="CS"
    )
    fs.connect(purge_tee.outlet, cv304.inlet, size=80, service="PG", sequence=309, spec="CS")
    fs.connect(cv304.outlet, purge_gas.inlet)
    fs.connect(purge_tee.branch, recycle_k.suction, size=350, service="LG", sequence=316, spec="CS")
    fs.connect(
        recycle_k.discharge,
        mix.branch,
        size=350,
        service="LG",
        sequence=310,
        spec="CS",
        draw_as_recycle=True,
    )

    fs.connect(fuel.outlet, fe303.inlet, size=80, service="FG", sequence=311, spec="CS")
    fs.connect(fe303.outlet, xv307.inlet)
    fs.connect(xv307.outlet, cv303.inlet)
    fs.connect(cv303.outlet, heater.fuel)

    fs.connect(cws.outlet, cooler.shell_in, size=250, service="CWS", sequence=312, spec="CS")
    fs.connect(cooler.shell_out, cwr.inlet, size=250, service="CWR", sequence=313, spec="CS")

    fe301_b = fs.add_balloon(fe301, at="N", offset=38)
    ft301 = fs.add_instrument("FT", flow301, near=fe301_b, at="N", offset=23)
    fic301 = fs.add_instrument("FIC", flow301, near=ft301, at="N", offset=60, variant="shared")
    fs.connect(ft301.sig_out, fic301.pv, kind="electric")
    fs.connect(fic301.sig_out, cv301.actuator, kind="pneumatic")

    tt302 = fs.add_instrument("TT", temp302, sensing=inlet_line, at=0.5, offset=60)
    tic302 = fs.add_instrument("TIC", temp302, near=tt302, at="N", offset=70, variant="shared")
    tic302.annotate(high="TAH")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    fe303_b = fs.add_balloon(fe303, at="N", offset=38)
    ft303 = fs.add_instrument("FT", flow303, near=fe303_b, at="N", offset=23)
    fic303 = fs.add_instrument("FIC", flow303, near=ft303, at="N", offset=60, variant="shared")
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    pt304 = fs.add_instrument("PT", press304, sensing=loop_gas, at=0.4, offset=60)
    pic304 = fs.add_instrument("PIC", press304, near=pt304, at="N", offset=70, variant="shared")
    pic304.annotate(high="PAH", low="PAL")
    fs.connect(pt304.sig_out, pic304.sig_in, kind="electric")
    fs.connect(pic304.sig_out, cv304.actuator, kind="pneumatic")

    lt305 = fs.add_instrument("LT", level305, sensing=sep, at="E", offset=60)
    lic305 = fs.add_instrument("LIC", level305, near=lt305, at="S", offset=70, variant="shared")
    lic305.annotate(high="LAH", low="LAL")
    fs.connect(lt305.sig_out, lic305.sig_in, kind="electric")
    fs.connect(lic305.sig_out, cv305.actuator, kind="pneumatic")

    fs.add_instrument("TI", 306, sensing=rx, at="W", offset=60)
    tt307 = fs.add_instrument("TT", 307, sensing=rx, at="E", offset=60)
    fs.add_instrument("Z", 1, sensing=tt307, at="E", offset=44, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv307, at="N", offset=34, variant="sis")

    fs.title_block = TitleBlock(
        title="Methanol Synthesis Loop",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        date="18/02/26",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "29/01/26", "Issued for internal review", "AA"),
            Revision("B", "18/02/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(
        equipment_list(
            fs,
            align="top-right",
            include=[
                "K-301",
                "E-301",
                "H-301",
                "R-301",
                "E-302",
                "V-301",
                "K-302",
            ],
        )
    )
    fs.add_annotation(
        notes(
            [
                "Z-1: converter high bed temperature. TT-307 is its own "
                "measurement, independent of TIC-302.",
                "H-301 flue gas and combustion air are on P&ID-302.",
                "Per-pass conversion is 5 to 7 %; the recycle ratio is 5:1 on molar flow.",
            ],
            title="GENERAL NOTES",
            numbered=False,
            align="bottom-left",
        )
    )
    fs.add_annotation(
        legend(
            {
                "CS": "Carbon Steel A106-B",
                "LT": "Low Temperature Carbon Steel A333-6",
                "SS": "Stainless Steel 316L",
                "SG": "Make-up Synthesis Gas",
                "LG": "Loop Gas",
                "PG": "Purge Gas",
                "CM": "Crude Methanol",
                "FGSH": "Fuel Gas Supply Header",
                "CWSH": "Cooling Water Supply Header",
                "CWRH": "Cooling Water Return Header",
            },
            align="top-left",
        )
    )
    return fs


def _absorber_stripper() -> Flowsheet:
    """Example 19 -- two columns on one PFD, with different internals.

    An absorber on valve trays and its regenerator on packing, which is what
    pins two group-27 internals against each other on one sheet. It is also the
    only scenario with a plain kettle reboiler feeding a lean/rich exchanger,
    and it states its own title-block date.
    """
    fs = Flowsheet("Amine Sweetening A400")

    contactor = fs.add(
        units.Column(
            "T-401",
            internals="valve_tray",
            trays=20,
            width=110,
            height=340,
            label_pos="center",
            description="Amine Contactor",
        )
    ).pin(mirrored=True)
    regen = fs.add(
        units.Column(
            "T-402",
            internals="packing",
            trays=2,
            width=110,
            height=300,
            label_pos="center",
            description="Amine Regenerator",
        )
    )

    cross = fs.add(
        units.HeatExchanger(
            "E-401",
            variant="straight_tubes",
            width=140,
            height=44,
            description="Lean / Rich Exchanger",
        )
    )
    ovhd = fs.add(
        units.HeatExchanger(
            "E-402",
            variant="condenser",
            width=70,
            height=70,
            description="Regenerator Overhead Condenser",
        )
    )
    drum = fs.add(
        units.Vessel("V-401", variant="horizontal", width=120, height=40, description="Reflux Drum")
    )
    reboiler = fs.add(
        units.HeatExchanger(
            "E-403", variant="kettle", width=130, height=46, description="Regenerator Reboiler"
        )
    )
    trim = fs.add(
        units.HeatExchanger(
            "E-404", variant="straight_tubes", width=130, height=40, description="Lean Amine Cooler"
        )
    )
    lean_pump = fs.add(units.Pump("P-401A/B", description="Lean Solvent Pump"))
    reflux_pump = fs.add(units.Pump("P-402A/B", description="Reflux Pump"))

    letdown = fs.add(
        units.Valve("LV-401", variant="control", description="Rich Amine Level Control Valve")
    )

    sour = fs.add(units.Feed("Sour Gas", reference="PFD-301"))
    steam = fs.add(units.Feed("LP Steam", reference="PFD-901"))
    cws_ovhd = fs.add(units.Feed("CWS", header=True))
    cws_trim = fs.add(units.Feed("CWS", header=True))
    sweet = fs.add(units.Product("Sweet Gas", reference="PFD-501"))
    acid = fs.add(units.Product("Acid Gas to SRU", reference="PFD-601"))
    condensate = fs.add(units.Product("Steam Condensate", reference="PFD-901"))
    cwr_ovhd = fs.add(units.Product("CWR", header=True))
    cwr_trim = fs.add(units.Product("CWR", header=True))

    contactor.pin(x=300, y=250)
    lean_in_y = 250 + port_offset(contactor, "reflux_in")[1]
    gas_in_y = 250 + port_offset(contactor, "boilup_in")[1]
    contactor_axis = 300 + port_offset(contactor, "distillate")[0]
    sour.pin(port="outlet", x=120, y=gas_in_y)
    sweet.pin(port="inlet", x=contactor_axis, y=140)

    rich_y = 822.0
    letdown.pin(port="inlet", x=460, y=rich_y)
    cross.pin(x=620).pin(port="tube_in", y=rich_y)
    cross_shell_in_x = cross.pin_.x + port_offset(cross, "shell_in")[0]
    cross_shell_out_x = cross.pin_.x + port_offset(cross, "shell_out")[0]
    rich_riser_x = 880.0

    regen.pin(x=980, y=290)
    regen_axis = 980 + port_offset(regen, "distillate")[0]
    regen_feed_y = 290 + port_offset(regen, "feed")[1]
    reflux_in_y = 290 + port_offset(regen, "reflux_in")[1]
    boilup_in_y = 290 + port_offset(regen, "boilup_in")[1]

    ovhd.pin(mirrored="y").pin(port="shell_in", x=regen_axis, y=201)
    ovhd_drain_y = ovhd.pin_.y + port_offset(ovhd, "shell_out")[1]
    cw_ovhd_y = ovhd.pin_.y + port_offset(ovhd, "tube_in")[1]
    drum.pin(port="inlet", x=1200, y=ovhd_drain_y)
    drum_draw_x = drum.pin_.x + port_offset(drum, "outlet")[0]
    drum_vent_x = drum.pin_.x + port_offset(drum, "vent")[0]
    reflux_run_y = 240.0
    reflux_pump.pin(x=1350).pin(port="suction", y=reflux_run_y)
    reflux_riser_x = 1480.0

    reboiler.pin(x=1400, y=640)
    sump_x = 1400 + port_offset(reboiler, "shell_in")[0]
    boilup_x = 1400 + port_offset(reboiler, "shell_out")[0]
    lean_draw_x = 1400 + port_offset(reboiler, "bottoms")[0]
    steam_y = 640 + port_offset(reboiler, "tube_in")[1]
    condensate_y = 640 + port_offset(reboiler, "tube_out")[1]
    sump_run_y = 730.0
    lean_run_y = 770.0

    steam.pin(port="outlet", x=1230, y=steam_y)
    condensate.pin(port="inlet", x=1700, y=condensate_y)
    cws_ovhd.pin(port="outlet", x=880, y=cw_ovhd_y)
    cwr_ovhd.pin(port="inlet", x=1700, y=cw_ovhd_y)
    acid.pin(port="inlet", x=1700, y=60)

    return_y = 900.0
    lean_pump.pin(mirrored=True).pin(port="suction", x=600, y=return_y)
    pump_out_y = lean_pump.pin_.y + port_offset(lean_pump, "discharge")[1]
    trim.pin(x=370, y=960)
    trim_shell_in_x = trim.pin_.x + port_offset(trim, "shell_in")[0]
    trim_shell_out_x = trim.pin_.x + port_offset(trim, "shell_out")[0]
    cw_trim_y = trim.pin_.y + port_offset(trim, "tube_in")[1]
    cws_trim.pin(port="outlet", x=250, y=cw_trim_y)
    cwr_trim.pin(port="inlet", x=760, y=cw_trim_y)
    lean_riser_x = 150.0
    lean_return_y = 1040.0

    fs.connect(sour.outlet, contactor.boilup_in, name="S-401")
    fs.connect(contactor.distillate, sweet.inlet, name="S-402")

    fs.connect(contactor.bottoms, letdown.inlet, name="S-404").via([(contactor_axis, rich_y)])
    fs.connect(letdown.outlet, cross.tube_in, name="S-404")
    fs.connect(cross.tube_out, regen.feed, name="S-405").via(
        [(rich_riser_x, rich_y), (rich_riser_x, regen_feed_y)]
    )

    fs.connect(regen.distillate, ovhd.shell_in, name="S-406")
    fs.connect(ovhd.shell_out, drum.inlet, name="S-407").via([(regen_axis, ovhd_drain_y)])
    fs.connect(drum.vent, acid.inlet, name="S-408").via([(drum_vent_x, 60)])
    fs.connect(drum.outlet, reflux_pump.suction, name="S-409").via([(drum_draw_x, reflux_run_y)])
    fs.connect(reflux_pump.discharge, regen.reflux_in, name="S-409", draw_as_recycle=True).via(
        [
            (reflux_riser_x, reflux_pump.pin_.y + port_offset(reflux_pump, "discharge")[1]),
            (reflux_riser_x, reflux_in_y),
        ]
    )

    fs.connect(regen.bottoms, reboiler.shell_in, name="S-410").via(
        [(regen_axis, sump_run_y), (sump_x, sump_run_y)]
    )
    fs.connect(reboiler.shell_out, regen.boilup_in, name="S-411", draw_as_recycle=True).via(
        [(boilup_x, boilup_in_y)]
    )

    fs.connect(reboiler.bottoms, cross.shell_in, name="S-412").via(
        [(lean_draw_x, lean_run_y), (cross_shell_in_x, lean_run_y)]
    )
    fs.connect(cross.shell_out, lean_pump.suction, name="S-413").via(
        [(cross_shell_out_x, return_y)]
    )
    fs.connect(lean_pump.discharge, trim.shell_in, name="S-414").via(
        [(trim_shell_in_x, pump_out_y)]
    )
    fs.connect(trim.shell_out, contactor.reflux_in, name="S-403", draw_as_recycle=True).via(
        [
            (trim_shell_out_x, lean_return_y),
            (lean_riser_x, lean_return_y),
            (lean_riser_x, lean_in_y),
        ]
    )

    fs.connect(steam.outlet, reboiler.tube_in, name="S-415")
    fs.connect(reboiler.tube_out, condensate.inlet, name="S-416")
    fs.connect(cws_ovhd.outlet, ovhd.tube_in, name="S-417")
    fs.connect(ovhd.tube_out, cwr_ovhd.inlet, name="S-418")
    fs.connect(cws_trim.outlet, trim.tube_in, name="S-419")
    fs.connect(trim.tube_out, cwr_trim.inlet, name="S-420")

    for s in fs.streams:
        values = _AMINE_PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(_AMINE_PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Methane", "Mass Fraction")]

    fs.title_block = TitleBlock(
        title="Amine Sweetening",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        date="03/03/26",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "12/02/26", "Issued for internal review", "AA"),
            Revision("B", "03/03/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    fs.add_annotation(
        equipment_list(
            fs,
            align="top",
            include=[
                "T-401",
                "E-401",
                "T-402",
                "E-402",
                "V-401",
                "P-402A/B",
                "E-403",
                "P-401A/B",
                "E-404",
            ],
        )
    )
    fs.add_annotation(
        TableBox(
            title="UTILITIES SUMMARY",
            headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in", "T_out"],
            rows=[
                ["LP Steam", "E-403", "24700", "11.30", "152 C", "151 C"],
                ["Cooling Water", "E-402", "-4540", "72.4", "25 C", "40 C"],
                ["Cooling Water", "E-404", "-12310", "196.3", "25 C", "40 C"],
            ],
            col_align=["l", "l", "r", "r", "c", "c"],
            align="bottom-right",
        )
    )
    return fs


def _molecular_sieve_dryer() -> Flowsheet:
    """Example 20 -- two identical adsorbers and the valves that switch them.

    The same shell and the same group-27 bed as example 18's converter, drawn
    twice and told apart by its tag, with eight solenoid switching valves and
    the one repeated logic square in the corpus. It states its own title-block
    date.
    """
    fs = Flowsheet("Gas Dehydration A500", line_number_start=501)

    temp503 = fs.add_loop("T", 503)
    level504 = fs.add_loop("L", 504)

    bed_a = fs.add(
        units.Column(
            "V-501A",
            internals="packing",
            trays=1,
            width=90,
            height=200,
            label_pos="center",
            description="Molecular Sieve Drier A",
        )
    )
    bed_b = fs.add(
        units.Column(
            "V-501B",
            internals="packing",
            trays=1,
            width=90,
            height=200,
            label_pos="center",
            description="Molecular Sieve Drier B",
        )
    )

    heater = fs.add(units.Furnace("H-501", description="Regeneration Gas Heater"))
    regen_cooler = fs.add(
        units.HeatExchanger("E-501", variant="air_cooled", description="Regeneration Gas Cooler")
    )
    regen_sep = fs.add(
        units.Separator("V-502", variant="knockout", description="Regeneration Gas Separator")
    )
    regen_k = fs.add(units.Compressor("K-501", description="Regeneration Gas Blower"))

    wet_gas = fs.add(units.Feed("Wet Feed Gas", reference="P&ID-401"))
    fuel = fs.add(units.Feed("FGSH", header=True))
    dry_gas = fs.add(units.Product("Dry Gas to NGL Recovery", reference="P&ID-601"))
    water = fs.add(units.Product("Free Water to Disposal", reference="P&ID-902"))

    xv501a = fs.add(
        units.Valve(
            "XV-501A", variant="solenoid", fail="closed", description="V-501A Wet Gas Inlet Valve"
        )
    )
    xv501b = fs.add(
        units.Valve(
            "XV-501B", variant="solenoid", fail="closed", description="V-501B Wet Gas Inlet Valve"
        )
    )
    xv502a = fs.add(
        units.Valve(
            "XV-502A", variant="solenoid", fail="closed", description="V-501A Dry Gas Outlet Valve"
        )
    )
    xv502b = fs.add(
        units.Valve(
            "XV-502B", variant="solenoid", fail="closed", description="V-501B Dry Gas Outlet Valve"
        )
    )
    xv503a = fs.add(
        units.Valve(
            "XV-503A",
            variant="solenoid",
            fail="closed",
            description="V-501A Regeneration Gas Inlet Valve",
        )
    )
    xv503b = fs.add(
        units.Valve(
            "XV-503B",
            variant="solenoid",
            fail="closed",
            description="V-501B Regeneration Gas Inlet Valve",
        )
    )
    xv504a = fs.add(
        units.Valve(
            "XV-504A",
            variant="solenoid",
            fail="closed",
            description="V-501A Regeneration Gas Outlet Valve",
        )
    )
    xv504b = fs.add(
        units.Valve(
            "XV-504B",
            variant="solenoid",
            fail="closed",
            description="V-501B Regeneration Gas Outlet Valve",
        )
    )

    cv503 = fs.add(
        units.Valve(
            temp503.tag("CV"),
            variant="control",
            fail="closed",
            description="H-501 Fuel Gas Control Valve",
        )
    )
    cv504 = fs.add(
        units.Valve(
            level504.tag("CV"),
            variant="control",
            fail="closed",
            description="V-502 Water Draw Control Valve",
        )
    )

    t_wet_in = fs.add(units.Tee(branch="inlet"))
    t_wet_a = fs.add(units.Tee())
    t_dry = fs.add(units.Tee(branch="inlet"))
    t_regen_out = fs.add(units.Tee(branch="inlet"))
    t_regen_in = fs.add(units.Tee())
    t_slip = fs.add(units.Tee())

    regen_out_y = 130.0
    wet_y = 220.0
    bed_y = 300.0
    regen_in_y = 590.0
    dry_y = 700.0
    regen_run_y = 900.0

    bed_a.pin(mirrored=True).pin(x=460, y=bed_y)
    bed_b.pin(x=940, y=bed_y)
    a_axis = 460 + port_offset(bed_a, "distillate")[0]
    b_axis = 940 + port_offset(bed_b, "distillate")[0]
    top_in_y = bed_y + port_offset(bed_a, "reflux_in")[1]
    bot_in_y = bed_y + port_offset(bed_a, "boilup_in")[1]
    a_leg_x, b_leg_x = 380.0, 1110.0

    wet_gas.pin(port="outlet", x=120, y=wet_y)
    t_wet_in.pin(mirrored="y").pin(port="branch", x=250).pin(port="outlet", y=wet_y)
    t_wet_a.pin(port="inlet", x=a_leg_x - 6, y=wet_y)
    xv501a.pin(port="inlet", x=400, y=top_in_y)
    xv501b.pin(mirrored=True).pin(port="inlet", x=1090, y=top_in_y)

    xv502a.pin(orientation=90).pin(port="inlet", x=a_axis, y=640)
    xv502b.pin(orientation=90).pin(port="inlet", x=b_axis, y=640)
    xv504a.pin(orientation=270).pin(port="inlet", x=a_axis, y=190)
    xv504b.pin(orientation=270).pin(port="inlet", x=b_axis, y=190)
    xv503a.pin(port="inlet", x=400, y=bot_in_y)
    xv503b.pin(mirrored=True).pin(port="inlet", x=1090, y=bot_in_y)

    t_dry.pin(mirrored="y").pin(port="branch", x=b_axis).pin(port="outlet", y=dry_y)
    t_regen_out.pin(port="branch", x=b_axis).pin(port="outlet", y=regen_out_y)
    t_regen_in.pin(mirrored="y").pin(port="branch", x=a_leg_x).pin(port="outlet", y=regen_in_y)
    t_slip.pin(port="inlet", x=1250, y=dry_y)
    dry_gas.pin(port="inlet", x=1560, y=dry_y)

    heater.pin(mirrored=True).pin(port="inlet", x=420, y=regen_run_y)
    heater_out_y = heater.pin_.y + port_offset(heater, "outlet")[1]
    fuel_x = heater.pin_.x + port_offset(heater, "fuel")[0]
    fuel.pin(port="outlet", x=140, y=1030)
    cv503.pin(port="inlet", x=250, y=1030)

    regen_cooler.pin(port="tube_in", x=1250, y=regen_out_y)
    regen_sep.pin(port="feed", x=1440, y=regen_out_y)
    sep_vapor_x = regen_sep.pin_.x + port_offset(regen_sep, "vapor")[0]
    sep_liquid_x = regen_sep.pin_.x + port_offset(regen_sep, "liquid")[0]
    regen_k.pin(port="suction", x=1620, y=60)
    cv504.pin(port="inlet", x=1520, y=310)
    water.pin(port="inlet", x=1700, y=310)

    fs.connect(wet_gas.outlet, t_wet_in.inlet, size=400, service="WG", sequence=501, spec="CS")
    fs.connect(t_wet_in.outlet, t_wet_a.inlet, size=400, service="WG", sequence=502, spec="CS")
    fs.connect(t_wet_a.branch, xv501a.inlet, size=400, service="WG", sequence=516, spec="CS").via(
        [(a_leg_x, wet_y), (a_leg_x, top_in_y)]
    )
    fs.connect(xv501a.outlet, bed_a.reflux_in)
    fs.connect(t_wet_a.outlet, xv501b.inlet, size=400, service="WG", sequence=517, spec="CS").via(
        [(b_leg_x, wet_y), (b_leg_x, top_in_y)]
    )
    fs.connect(xv501b.outlet, bed_b.reflux_in)

    fs.connect(bed_a.bottoms, xv502a.inlet, size=400, service="DG", sequence=503, spec="CS")
    fs.connect(xv502a.outlet, t_dry.inlet).via([(a_axis, dry_y)])
    fs.connect(bed_b.bottoms, xv502b.inlet, size=400, service="DG", sequence=504, spec="CS")
    fs.connect(xv502b.outlet, t_dry.branch)
    dry_header = fs.connect(
        t_dry.outlet, t_slip.inlet, size=400, service="DG", sequence=505, spec="CS"
    )
    fs.connect(t_slip.outlet, dry_gas.inlet, size=400, service="DG", sequence=520, spec="CS")

    fs.connect(t_slip.branch, heater.inlet, size=200, service="RG", sequence=506, spec="CS").via(
        [(1256, regen_run_y), (420, regen_run_y)]
    )
    fs.connect(fuel.outlet, cv503.inlet, size=50, service="FG", sequence=507, spec="CS")
    fs.connect(cv503.outlet, heater.fuel).via([(fuel_x, 1030)])

    hot_regen = fs.connect(
        heater.outlet, t_regen_in.inlet, size=200, service="RG", sequence=508, spec="LT"
    ).via([(200, heater_out_y), (200, regen_in_y)])
    fs.connect(
        t_regen_in.branch, xv503a.inlet, size=200, service="RG", sequence=518, spec="LT"
    ).via([(a_leg_x, bot_in_y)])
    fs.connect(xv503a.outlet, bed_a.boilup_in)
    fs.connect(
        t_regen_in.outlet, xv503b.inlet, size=200, service="RG", sequence=519, spec="LT"
    ).via([(b_leg_x, regen_in_y), (b_leg_x, bot_in_y)])
    fs.connect(xv503b.outlet, bed_b.boilup_in)

    fs.connect(bed_a.distillate, xv504a.inlet, size=200, service="RG", sequence=509, spec="LT")
    fs.connect(xv504a.outlet, t_regen_out.inlet).via([(a_axis, regen_out_y)])
    fs.connect(bed_b.distillate, xv504b.inlet, size=200, service="RG", sequence=510, spec="LT")
    fs.connect(xv504b.outlet, t_regen_out.branch)
    fs.connect(
        t_regen_out.outlet, regen_cooler.tube_in, size=200, service="RG", sequence=511, spec="LT"
    )

    fs.connect(
        regen_cooler.tube_out, regen_sep.feed, size=200, service="RG", sequence=512, spec="CS"
    )
    fs.connect(regen_sep.liquid, cv504.inlet, size=50, service="PW", sequence=513, spec="CS").via(
        [(sep_liquid_x, 310)]
    )
    fs.connect(cv504.outlet, water.inlet)
    fs.connect(
        regen_sep.vapor, regen_k.suction, size=200, service="RG", sequence=514, spec="CS"
    ).via([(sep_vapor_x, 60)])
    fs.connect(
        regen_k.discharge,
        t_wet_in.branch,
        size=200,
        service="RG",
        sequence=515,
        spec="CS",
        draw_as_recycle=True,
    ).via([(1690, 20), (250, 20)])

    kc501 = fs.add_instrument(
        "KC",
        501,
        near=bed_a,
        at="W",
        offset=170,
        variant="shared",
        description="Drier Switching Sequence",
    )
    kc501.annotate(high="KAH")
    for valve, face in (
        (xv501a, "N"),
        (xv501b, "N"),
        (xv502a, "W"),
        (xv502b, "W"),
        (xv503a, "N"),
        (xv503b, "N"),
        (xv504a, "W"),
        (xv504b, "W"),
    ):
        fs.add_instrument("KY", 501, acting_on=valve, at=face, offset=34, variant="logic")

    tt503 = fs.add_instrument("TT", temp503, sensing=hot_regen, at=0.5, offset=70)
    tic503 = fs.add_instrument("TIC", temp503, near=tt503, at="S", offset=70, variant="shared")
    tic503.annotate(high="TAH")
    fs.connect(tt503.sig_out, tic503.sig_in, kind="electric")
    fs.connect(tic503.sig_out, cv503.actuator, kind="pneumatic")

    lt504 = fs.add_instrument("LT", level504, sensing=regen_sep, at="E", offset=60)
    lic504 = fs.add_instrument("LIC", level504, near=lt504, at="S", offset=70, variant="shared")
    lic504.annotate(high="LAH", low="LAL")
    fs.connect(lt504.sig_out, lic504.sig_in, kind="electric")
    fs.connect(lic504.sig_out, cv504.actuator, kind="pneumatic")

    at502 = fs.add_instrument("AT", 502, sensing=dry_header, at=0.4, offset=60, angle=-90)
    ai502 = fs.add_instrument(
        "AI",
        502,
        near=at502,
        at="S",
        offset=60,
        variant="shared",
        description="Dry Gas Moisture Analyser",
    )
    ai502.annotate(high="AAH")
    fs.connect(at502.sig_out, ai502.sig_in, kind="electric")

    fs.title_block = TitleBlock(
        title="Gas Dehydration",
        subtitle="A500 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-501",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        date="24/03/26",
        drawn_by="AA",
        checked_by="JS",
        approved_by="RL",
        revisions=[
            Revision("A", "05/03/26", "Issued for internal review", "AA"),
            Revision("B", "24/03/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(
        equipment_list(
            fs,
            align="top-right",
            include=[
                "V-501A",
                "V-501B",
                "H-501",
                "E-501",
                "V-502",
                "K-501",
            ],
        )
    )
    fs.add_annotation(
        notes(
            [
                "KY-501 is one logic function drawn at each valve it strokes; "
                "the sequence is KC-501.",
                "Cycle: 8 h adsorption, 5 h heating, 2 h cooling, 1 h standby. "
                "AAH-502 shortens the adsorption step.",
                "V-501A and V-501B are identical vessels. Neither drawing says "
                "which is on line; the sequence does.",
            ],
            title="GENERAL NOTES",
            numbered=False,
            align="bottom-left",
        )
    )
    fs.add_annotation(
        legend(
            {
                "CS": "Carbon Steel A106-B",
                "LT": "Low Temperature Carbon Steel A333-6",
                "WG": "Wet Feed Gas",
                "DG": "Dry Gas",
                "RG": "Regeneration Gas",
                "FG": "Fuel Gas",
                "PW": "Produced Water",
                "FGSH": "Fuel Gas Supply Header",
            },
            align="top-left",
        )
    )
    return fs


SCENARIOS = {
    "01_ammonia_loop": (_ammonia_loop, {}),
    # 02 is the manual-placement example and is the one sheet drawn with the
    # coordinate overlay on, which is what its example demonstrates. It is
    # therefore also what pins the overlay: the grid, the numbers written on it,
    # the anchor markers and the port markers all land in this fixture, so a
    # change to any of them shows up here as a drawing rather than as a claim in
    # a unit test. Every other scenario draws with it off, which is what holds
    # the rest of the corpus to being byte for byte what it was before the
    # feature existed.
    "02_manual_layout": (_manual_layout, {"debug": True}),
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
    "11_ethanol_pid": (
        _ethanol_pid,
        {"border": "zone", "page_size": "A3", "diagram": "p&id", "connections": "flanged"},
    ),
    # 12 is the block flow diagram, the one drawing a level above the PFD and
    # the only scenario with process connections on the north and south faces.
    # It is what guards the sizing rule as a *drawing* rather than as an
    # arithmetic claim: the boxes here are as wide as their own names and as
    # tall as their walls need, so a change to the pitch, the minimum box or the
    # label allowance moves this file and nothing else.
    "12_block_flow_diagram": (_block_flow_diagram, {}),
    # 13 is the solids circuit: a mineral concentrate thickened, filtered, dried and
    # magnetically cleaned. It is the only scenario drawing a dryer, a furnace, a
    # blower or a funnel, the only one with a tee that *combines* rather than
    # splits, and the widest stream table in the corpus. It states its own
    # title-block date, so nothing here is pinned; it takes no ``page_size``, so it
    # is also what guards a stream table wider than the drawing it belongs to, on a
    # sheet sized to fit them both.
    "13_mineral_dewatering": (
        _mineral_dewatering,
        {"show_stream_table": True, "border": "zone"},
    ),
    # 14 is the tank farm: three storage vessels, the transfer system that draws
    # them down and the rack that loads road tankers off it. It is the third A3
    # P&ID and the one that pins the storage, containment and line-fitting
    # families -- floating roof, fixed roof, sphere, conservation vent, two flame
    # arrestors, a spectacle blind, a compensator, both strainer bodies and the
    # eccentric/concentric reducer pair around one pump. It is also the only
    # scenario whose loop numbers are allocated rather than typed, so it is what
    # holds add_loop()'s counter to a drawing rather than to a unit test.
    "14_tank_farm": (
        _tank_farm,
        {"border": "zone", "page_size": "A3", "diagram": "p&id"},
    ),
    # 15 and 16 are the two sheets the engine lays out end to end: no
    # pin() anywhere on either. 15 is the first auto-laid-out scenario
    # carrying instrumentation -- two loops, a shared-display controller,
    # an auxiliary-location gauge and an interlock diamond, every balloon
    # placed off a host and routed after the boxes settled. It is also the
    # only scenario drawing a turbine, an ejector, a heater or an
    # air-cooled exchanger.
    "15_condensing_turbine": (_condensing_turbine, {"diagram": "p&id"}),
    # 16 is the ion-exchange train: the only scenario drawing a packed
    # column, a plain or fixed-bed filter or an ion exchanger, and the
    # only auto-laid-out sheet carrying a title strip and an equipment
    # list. It states its own title-block date, so nothing here is pinned.
    "16_demineralised_water": (_demineralised_water, {"border": "zone"}),
    # 17 is the jacketed stirred reactor: the composition layer drawn as plant,
    # and the only scenario carrying an agitator, a drive motor or a jacketed
    # body. It is the fourth sheet on a fixed A3 page.
    "17_stirred_reactor_train": (
        _stirred_reactor_train,
        {"border": "zone", "page_size": "A3", "diagram": "p&id"},
    ),
    # 18 is the synthesis loop: a packed catalytic converter, a fired heater and
    # a recycle the engine tears and draws as a lane. It is the third sheet laid
    # out end to end with no pin() on it, and the first of those to carry line
    # numbers.
    "18_fixed_bed_recycle": (_fixed_bed_recycle, {"border": "zone", "diagram": "p&id"}),
    # 19 is the amine pair: two columns on one PFD with a different group-27
    # internal in each, which is what holds "an absorber and a regenerator are
    # not the same service" to a drawing rather than to a docstring.
    "19_absorber_stripper": (
        _absorber_stripper,
        {"show_stream_table": True, "border": "zone"},
    ),
    # 20 is the molecular sieve pair: the same shell and the same bed as 18's
    # converter, drawn twice, and the only scenario with eight on/off valves on
    # one switching sequence or a repeated logic square.
    "20_molecular_sieve_dryer": (
        _molecular_sieve_dryer,
        {"border": "zone", "diagram": "p&id"},
    ),
}


# --- normalization + comparison -----------------------------------------------


def _normalize(svg: str) -> str:
    """Canonicalize what the renderer does not promise to hold still.

    Two things, and nothing else. Every other line is left untouched so a real
    regression still shows up.

    **Defs ordering.** ``SvgRenderer._defs()`` builds its marker/symbol defs
    from Python ``set``s (``used_colors``, ``used_symbols``), so their order in
    the output depends on the process's string-hash seed, not on anything about
    the diagram -- confirmed by rendering one flowsheet under several
    ``PYTHONHASHSEED`` values and diffing the result. Sorting each group
    canonicalizes that away so two renders of an identical flowsheet always
    compare equal.

    **The provenance block.** Every sheet says what drew it, version included,
    which means every release would otherwise rewrite all twenty fixtures --
    and the gallery with them -- for a reason that is not about any drawing. The
    contents of the block are dropped here, which is why the renderer fences it
    between two marker comments: this is a slice between two known lines, not a
    version pattern hunted across the document. The fences themselves are kept,
    so a fixture still records that the block exists and where it sits, and
    ``<title>`` is deliberately outside them -- it is the sheet's own name and
    carries no version, so it stays in the comparison.
    """
    lines = svg.split("\n")
    open_i = next((i for i, ln in enumerate(lines) if ln.strip() == PROVENANCE_OPEN.strip()), None)
    close_i = next(
        (i for i, ln in enumerate(lines) if ln.strip() == PROVENANCE_CLOSE.strip()), None
    )
    if open_i is not None and close_i is not None and close_i > open_i:
        del lines[open_i + 1 : close_i]
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<defs>")
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</defs>")
    except StopIteration:
        return "\n".join(lines)  # no defs to sort; the provenance edit still stands
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


def test_a_version_bump_does_not_move_a_fixture(monkeypatch):
    """Cutting a release must not be a diff of every artefact in the repo.

    Every sheet now says what drew it, version included, so without
    :func:`_normalize`'s rule a one-line change to ``pandid.__version__`` would
    rewrite all twenty fixtures for a reason that is about none of the
    drawings. This is that rule, checked rather than asserted in a comment.

    Three claims, and the first is what stops the other two being vacuous: the
    version really is in the file, so the raw renders differ; normalized they
    are the same text; and the fixture on disk still passes at a version it was
    never generated under. One scenario is enough -- the block is emitted
    identically for every sheet -- and a furnished one is used so the ``<title>``
    and ``dc:title`` that sit either side of the fence are both in play.
    """
    import pandid

    name = "03_distillation_train"
    build, kwargs = SCENARIOS[name]
    at_this_version = build().to_svg(**kwargs)
    monkeypatch.setattr(pandid, "__version__", "99.99.99")
    at_another = build().to_svg(**kwargs)

    assert at_this_version != at_another, "the version is not in the rendered file at all"
    assert _normalize(at_this_version) == _normalize(at_another)
    _check_golden(name, at_another)


# --- the examples, against the same goldens -----------------------------------
#
# Everything above rebuilds each sheet from a fixture in this file, which leaves
# the suite green whenever the fixture matches the golden -- whether or not
# either matches the example it was copied from. That is not hypothetical: #230
# corrected a set of real people's initials in examples/13_mineral_dewatering.py
# and the golden went on reading the old ones, because the golden is built from
# the fixture. Both copies had to be found and edited by hand, and nothing would
# have complained if only one of them had been.
#
# So the examples are rendered here too, and compared against the *same* golden.
# Any divergence now fails on the next run instead of on the next screenshot.
# Merging the two copies -- making the examples the fixtures outright -- is the
# expensive fix and #231 scopes it out; this is what makes it unnecessary.


@functools.lru_cache(maxsize=1)
def _example_capture():
    """``scripts/gallery.py``, loaded by path, once.

    Reused rather than reimplemented, because it already solves the awkward
    half of this: an example is a script, so it writes a file and prints, and
    ``01`` does it at import while the other thirteen do it behind ``main()``.
    ``gallery.flowsheet()`` runs either shape with ``Flowsheet.render`` replaced,
    catching the flowsheet and the keyword arguments the example was about to
    draw it with and writing nothing anywhere. A second copy of that capture
    living here would be one more thing to drift, which is the bug this section
    exists to prevent.

    Loading a dev-only script by path is the convention already: it is what
    ``tests/test_gallery.py`` does with this same file and what
    ``tests/test_devices.py`` does with ``scripts/gen_devices.py``.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / "gallery.py"
    module_spec = importlib.util.spec_from_file_location("_golden_script_gallery", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


# The two examples that leave ``TitleBlock.date`` blank, which ``SvgRenderer``
# fills in with ``datetime.now()``. That is right for a sheet drawn today and
# impossible for one committed to a repository, so both the fixture and the
# gallery pin it -- and they pin it *differently*: the fixture to a constant
# (2026-01-01), the gallery to the newest revision's date, which is the date the
# sheet was in fact issued at. Neither is wrong and there is no drift here; the
# field simply has no value in the example for the two to agree on.
#
# So the guard takes the fixture's, since the fixture's golden is what it is
# comparing against. It is read off the fixture rather than written out again
# here, so the constant still lives in exactly one place. Everything else on the
# sheet is compared as the example draws it, this one field included the moment
# an example starts stating its own date.
_DATE_LEFT_TO_THE_RENDERER = ("03_distillation_train", "08_from_data")


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_example_draws_the_same_sheet_as_its_fixture(name):
    if UPDATE:
        pytest.skip("the goldens are being rewritten from the fixtures; compare on the next run")
    fs, kwargs = _example_capture().flowsheet(name)
    if name in _DATE_LEFT_TO_THE_RENDERER:
        fs.title_block.date = SCENARIOS[name][0]().title_block.date
    drawn = _normalize(fs.to_svg(**kwargs))
    golden = _normalize((GOLDEN_DIR / f"{name}.svg").read_text(encoding="utf-8"))
    if drawn != golden:
        pytest.fail(
            f"examples/{name}.py does not draw tests/golden/{name}.svg.\n"
            "The golden is built from the fixture in this file, so the two have drifted: "
            "either the example was edited and the fixture was not, or the reverse. Fix "
            "whichever is wrong -- do not regenerate the golden until they agree.\n\n"
            + _diff_message(name, golden, drawn),
            pytrace=False,
        )


def test_every_example_has_a_fixture():
    """A new example with no scenario beside it is unguarded, and silently so:
    the suite would stay green while nothing at all held the new sheet to
    anything. #231 asks for this before the corpus grows again."""
    assert sorted(SCENARIOS) == _example_capture().sheets()


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

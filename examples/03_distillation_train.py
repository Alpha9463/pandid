"""
Example 3: Advanced distillation train

Routing across a complex flowsheet: tall equipment, multiple outlets and
recycle loops. Equipment shapes follow ISO 10628-2.

Two towers, each with a condenser onto a reflux drum whose single draw
parts into reflux and distillate, and a kettle reboiler off the sump
returning boilup, with the net bottoms taken over the weir. Both loops
close on the column's ``reflux_in`` and ``boilup_in`` nozzles.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Column,
    Feed,
    Flowsheet,
    HeatExchanger,
    KettleReboiler,
    Mixer,
    Product,
    Pump,
    Splitter,
    Tee,
    Valve,
    Vessel,
)
from pandid.portgeom import port_offset

def main():
    fs = Flowsheet("Distillation Train")

    # reference= puts an off-page drawing number on a boundary flag.
    feed = fs.add(Feed("Raw Feed", reference="PFD-1000"))
    mixer = fs.add(Mixer("M-100", n_inlets=2, description="Feed Mixer Drum"))
    feed_valve = fs.add(Valve("FV-100"))
    preheater = fs.add(HeatExchanger("E-100", description="Feed Preheater"))

    # Column 1. The tee carries no tag and no equipment-list row.
    # Valve trays: light ends are clean, so nothing here needs a deck
    # that resists fouling -- but the cut swings with the upstream
    # unit's rate, and a movable valve holds its efficiency down to the
    # low vapour load a sieve deck would weep at.
    col1 = fs.add(Column("T-100", internals="valve_tray", trays=14,
                         description="Light Ends Column"))
    c1_ovhd = fs.add(HeatExchanger("E-101", description="T-100 Overhead Condenser"))
    c1_drum = fs.add(Vessel("V-101", variant="horizontal", width=130, height=42,
                            description="T-100 Reflux Drum"))
    c1_tee = fs.add(Tee())
    c1_reb = fs.add(KettleReboiler("E-102", width=120, height=44,
                                   description="T-100 Kettle Reboiler"))
    c1_prod = fs.add(Product("Light Product", reference="PFD-1002"))

    pump1 = fs.add(Pump("P-100A/B", description="T-100 Bottoms Pump"))

    # Column 2, with the same two circuits on it.
    # Sieve trays: this one is base-loaded off T-100's bottoms at a
    # steady rate on a clean feed, so the turndown a valve deck is
    # bought for is never used and the perforated deck is the cheapest
    # way to the capacity.
    col2 = fs.add(Column("T-200", internals="sieve_tray", trays=18,
                         description="Product Column"))
    c2_ovhd = fs.add(HeatExchanger("E-201", description="T-200 Overhead Condenser"))
    c2_drum = fs.add(Vessel("V-201", variant="horizontal", width=130, height=42,
                            description="T-200 Reflux Drum"))
    c2_tee = fs.add(Tee())
    c2_reb = fs.add(KettleReboiler("E-202", width=120, height=44,
                                   description="T-200 Kettle Reboiler"))
    c2_prod = fs.add(Product("Med Product", reference="PFD-1002"))

    # Bottoms split and recycle
    pump2 = fs.add(Pump("P-200A/B", description="T-200 Bottoms Pump"))
    splitter = fs.add(Splitter("SP-200", n_outlets=2, description="Bottoms Splitter"))
    c2_bot = fs.add(Product("Heavy Product", reference="PFD-1003"))
    recycle_valve = fs.add(Valve("FV-200"))

    # --- Pinned coordinates (Manual Grid) -----------------------------
    # pin(port=...) asks each symbol where its own nozzle sits, so no
    # half-height is written down here.
    col_y = 420
    col1.pin(x=690, y=col_y)

    # Feed row: every device on the column's own feed elevation.
    feed_run_y = col_y + port_offset(col1, "feed")[1]
    mixer.pin(x=290).pin(port="outlet", y=feed_run_y)
    # A boundary flag is pinned at the tip of its arrow, and this one's
    # line lands on in_1, above the outlet the run is pinned on.
    feed.pin(port="outlet", x=210, y=mixer.pin_.y + port_offset(mixer, "in_1")[1])
    feed_valve.pin(x=410, port="inlet", y=feed_run_y)
    preheater.pin(x=520, port="tube_in", y=feed_run_y)

    # Both towers carry the same rows, so each row is named once here.
    col2.pin(x=1260, y=col_y)
    ovhd_run_y = col_y - 130    # where each tower's overhead enters its condenser
    drum_y = col_y - 105        # reflux drum, hung under the condenser it drains
    tee_y = col_y - 5           # where each drum's draw parts into two lines
    bot_y = col_y + 225         # kettle reboiler row, below both towers
    pump_y = bot_y + 85         # pump suctions, on the run the weir draw falls to

    # Asked of the symbol rather than measured off the drawing. The two
    # return elevations are never written down: reflux_in and boilup_in
    # sit at fixed fractions of whatever height the column is drawn at.
    c1_axis = col1.pin_.x + port_offset(col1, "distillate")[0]
    c2_axis = col2.pin_.x + port_offset(col2, "distillate")[0]

    # Condenser over its own tower on the same axis, flipped top to
    # bottom so the vapour rises into its underside dead straight.
    c1_ovhd.pin(mirrored="y").pin(x=c1_axis, port="shell_in", y=ovhd_run_y)
    c2_ovhd.pin(mirrored="y").pin(x=c2_axis, port="shell_in", y=ovhd_run_y)

    # nozzle() moves the inlet to the top face: left alone the engine
    # reaches for the head, which would hook the drop off the condenser
    # back on itself. drum_y also buys the draw its room -- a Tee draws
    # no symbol, so the pipe either side of it is the only thing saying
    # one is there.
    c1_drum.nozzle("inlet", "N").pin(port="inlet", x=c1_axis + 200, y=drum_y)
    c2_drum.nozzle("inlet", "N").pin(port="inlet", x=c2_axis + 200, y=drum_y)

    # The quarter turn puts each tee's run down the page, the flip its
    # branch out east.
    for tee, drum, prod, prod_x in ((c1_tee, c1_drum, c1_prod, 1070),
                                    (c2_tee, c2_drum, c2_prod, 1640)):
        tee.pin(orientation=90, mirrored="y")
        tee.pin(port="inlet", x=drum.pin_.x + port_offset(drum, "outlet")[0])
        tee.pin(port="branch", y=tee_y)
        prod.pin(x=prod_x, port="inlet", y=tee_y)

    # Kettle offset east of each tower so the sump line climbs into its
    # underside rather than running through the shell.
    c1_reb.pin(x=c1_axis + 90, y=bot_y)
    c2_reb.pin(x=c2_axis + 90, y=bot_y)
    pump1.pin(x=1010, port="suction", y=pump_y)
    pump2.pin(x=1580, port="suction", y=pump_y)

    # Bottoms split, above T-200's pump discharge run.
    splitter.pin(x=1710, y=bot_y - 40)
    c2_bot.pin(x=1830, port="inlet",
               y=splitter.pin_.y + port_offset(splitter, "out_1")[1])

    # Recycle valve below the pump row (receives flow from the right)
    recycle_valve.pin(x=590, y=pump_y + 110, mirrored=True)

    # --- Connections --------------------------------------------------
    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, feed_valve.inlet)
    fs.connect(feed_valve.outlet, preheater.tube_in)
    fs.connect(preheater.tube_out, col1.feed)

    # The tee is inline, so the drum's draw and the reflux leg carry one
    # number and only the branch takes one of its own.
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

    # Rows render in first-seen key order; values carry their own units.
    for i, s in enumerate(fs.streams):
        s.properties = {
            "Temperature (°C)": f"{25 + i * 5} C",
            "Pressure (bar)": f"{1.0 + i * 0.1:.1f} bar",
            "Total Flow (kg/h)": f"{1000 - i * 10}",
            "Benzene": f"{0.90 - i * 0.02:.2f}",
            "Toluene": f"{0.10 + i * 0.02:.2f}",
        }
    fs.stream_table_sections = [("Benzene", "Mass Fraction")]

    # --- Title block + revision history -------------------------------
    from pandid.document import (TitleBlock, Revision, equipment_list, notes, legend)
    fs.title_block = TitleBlock(
        title="Aromatics Recovery A100",
        subtitle="Process Flow Diagram 1",
        drawing_number="PFD-1001",
        project="Aromatics Recovery Unit",
        client="Aromatics Australia Pty Ltd",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="3", scale="NTS",
        drawn_by="A. Anderson", checked_by="J. Smith", approved_by="R. Lee",
        revisions=[
            Revision("A", "2026-06-01", "Issued for internal review", "AA"),
            Revision("B", "2026-07-01", "Issued for design", "AA", "JS", "RL"),
            Revision("C", "2026-07-12", "Added FV-200 recycle loop", "AA", "JS", "RL"),
            Revision("D", "2026-07-28", "Reflux and reboiler added",
                     "AA", "JS", "RL"),
            Revision("E", "2026-08-01", "Reflux drums raised",
                     "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture: titled boxes docked to the frame ------------
    fs.add_annotation(equipment_list(fs, align="top-right"))
    fs.add_annotation(notes([
        "Sampling point on every product line.",
        "All instruments field-mounted unless noted.",
        "Recycle valve FV-200 fails open.",
    ], align="top-right"))
    fs.add_annotation(legend({
        "PFD": "Process Flow Diagram",
        "FV": "Flow Control Valve",
        "NTS": "Not To Scale",
    }, align="top-left"))

    # --- Render -------------------------------------------------------
    fs.render(out("distillation_train.svg"), show_stream_table=True, border="zone")
    # The same sheet and arguments, as an editable draw.io model.
    fs.render(out("distillation_train.drawio"), show_stream_table=True, border="zone")
    print("Generated distillation_train.svg and distillation_train.drawio")

if __name__ == "__main__":
    main()

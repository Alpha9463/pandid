"""
Example 3: Advanced Distillation Train

This example demonstrates the engine's capability to route streams
across a complex flowsheet with tall equipment (columns), multiple
outlets, and recycled loops. The equipment shapes follow the conventions
of ISO 10628-2.

Both towers carry the overhead and bottoms systems that make them towers: a
condenser onto a reflux drum whose single draw parts into reflux and
distillate, and a kettle reboiler off the sump returning boilup, with the net
bottoms taken over the kettle's weir. Both loops close on the column itself,
through its ``reflux_in`` and ``boilup_in`` nozzles. 06_column_reflux draws one
tower's worth of the same arrangement on its own.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.portgeom import port_offset

def main():
    fs = Flowsheet("Distillation Train")

    # Feed system. Boundary flags carry an off-page reference (the drawing the
    # stream comes from / goes to), drawn as the connector's second line.
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-1000"))
    mixer = fs.add(units.Mixer("M-100", n_inlets=2, description="Feed Mixer Drum"))
    feed_valve = fs.add(units.Valve("FV-100"))
    preheater = fs.add(units.HeatExchanger("E-100", description="Feed Preheater"))

    # Column 1. The drum has one liquid draw and a nozzle takes one stream, so
    # the point where the reflux parts from the distillate is a Tee: a junction
    # in the piping rather than a piece of plant. It draws the junction and
    # nothing else, carries no tag and puts no row in the equipment list, which
    # is how the issued sheet draws it (10_ethanol_pfd spells out the same
    # reasoning, at the same place on its own tower).
    col1 = fs.add(units.Column("T-100", description="Light Ends Column"))
    c1_ovhd = fs.add(units.HeatExchanger("E-101", description="T-100 Overhead Condenser"))
    c1_drum = fs.add(units.Vessel("V-101", variant="horizontal", width=130, height=42,
                                  description="T-100 Reflux Drum"))
    c1_tee = fs.add(units.Tee())
    c1_reb = fs.add(units.HeatExchanger("E-102", variant="kettle", width=120, height=44,
                                        description="T-100 Kettle Reboiler"))
    c1_prod = fs.add(units.Product("Light Product", reference="PFD-1002"))

    # Bottoms transfer, off the reboiler's weir draw rather than off the tower:
    # what boils returns to T-100 as boilup and only the overflow goes to T-200.
    pump1 = fs.add(units.Pump("P-100A/B", description="T-100 Bottoms Pump"))

    # Column 2, with the same two circuits on it.
    col2 = fs.add(units.Column("T-200", description="Product Column"))
    c2_ovhd = fs.add(units.HeatExchanger("E-201", description="T-200 Overhead Condenser"))
    c2_drum = fs.add(units.Vessel("V-201", variant="horizontal", width=130, height=42,
                                  description="T-200 Reflux Drum"))
    c2_tee = fs.add(units.Tee())
    c2_reb = fs.add(units.HeatExchanger("E-202", variant="kettle", width=120, height=44,
                                        description="T-200 Kettle Reboiler"))
    c2_prod = fs.add(units.Product("Med Product", reference="PFD-1002"))

    # Bottoms split and recycle
    pump2 = fs.add(units.Pump("P-200A/B", description="T-200 Bottoms Pump"))
    splitter = fs.add(units.Splitter("SP-200", n_outlets=2, description="Bottoms Splitter"))
    c2_bot = fs.add(units.Product("Heavy Product", reference="PFD-1003"))
    recycle_valve = fs.add(units.Valve("FV-200"))

    # --- Pinned coordinates (Manual Grid) ---
    # Pinned by nozzle, not by corner: pin(port=...) asks each symbol where its
    # own nozzle sits, so a run stays straight whatever size the artwork is
    # drawn at and no half-height is written down here.
    col_y = 420
    col1.pin(x=690, y=col_y)

    # Feed row, left-to-right, every device on the column's own feed elevation.
    feed_run_y = col_y + port_offset(col1, "feed")[1]
    mixer.pin(x=290).pin(port="outlet", y=feed_run_y)
    # A boundary flag is pinned at the tip of its arrow, which is where its line
    # reaches it, and that line lands on the mixer's upper inlet -- which sits
    # above the outlet the run itself is pinned on.
    feed.pin(port="outlet", x=210, y=mixer.pin_.y + port_offset(mixer, "in_1")[1])
    feed_valve.pin(x=410, port="inlet", y=feed_run_y)
    preheater.pin(x=520, port="tube_in", y=feed_run_y)

    # Both towers stand on one elevation and carry the same rows above and below
    # them, so each row is named once here and every device on it is pinned to
    # it by its own nozzle.
    col2.pin(x=1260, y=col_y)
    ovhd_run_y = col_y - 160    # condenser row, clear above both towers
    drum_y = col_y - 75         # reflux drum, hung under the condenser it drains
    tee_y = col_y - 5           # where each drum's draw parts into two lines
    bot_y = col_y + 225         # kettle reboiler row, below both towers
    pump_y = bot_y + 85         # pump suctions, on the run the weir draw falls to

    # Each overhead and bottoms system is hung off its own tower's centreline,
    # asked of the symbol rather than measured off the drawing. The two return
    # elevations are never written down at all: reflux_in and boilup_in sit at
    # fixed fractions of whatever height a column is drawn at, and connecting to
    # them by name is what keeps a fraction copied out of this drawing -- only
    # ever true of this drawing -- out of the script.
    c1_axis = col1.pin_.x + port_offset(col1, "distillate")[0]
    c2_axis = col2.pin_.x + port_offset(col2, "distillate")[0]

    # Overhead: condenser up and to the right, so the tower's overhead leaves
    # the crown, rises and turns once into it. The process takes the exchanger's
    # W-E pair, which is its tube side.
    c1_ovhd.pin(x=c1_axis + 80, port="tube_in", y=ovhd_run_y)
    c2_ovhd.pin(x=c2_axis + 80, port="tube_in", y=ovhd_run_y)

    # Drum hung below the condenser it drains, and piped from the top rather
    # than from the head the engine would otherwise reach for: condensate falls
    # onto a receiver, and nozzle() is how that convention gets stated instead
    # of being left to wherever the peer happened to land.
    c1_drum.nozzle("inlet", "N").pin(
        port="inlet", x=c1_ovhd.pin_.x + port_offset(c1_ovhd, "tube_out")[0] + 60, y=drum_y)
    c2_drum.nozzle("inlet", "N").pin(
        port="inlet", x=c2_ovhd.pin_.x + port_offset(c2_ovhd, "tube_out")[0] + 60, y=drum_y)

    # Each tee sits on its drum's draw. The quarter turn puts the run down the
    # page and the flip puts the branch out east, so the reflux carries straight
    # on down and turns once into the tower, while the distillate leaves level,
    # on the elevation its product flag is pinned to.
    for tee, drum, prod, prod_x in ((c1_tee, c1_drum, c1_prod, 1070),
                                    (c2_tee, c2_drum, c2_prod, 1640)):
        tee.pin(orientation=90, mirrored="y")
        tee.pin(port="inlet", x=drum.pin_.x + port_offset(drum, "outlet")[0])
        tee.pin(port="branch", y=tee_y)
        prod.pin(x=prod_x, port="inlet", y=tee_y)

    # Kettle off each tower bottom, low enough that the boilup rises into the
    # return nozzle instead of dropping back down to it, and offset east so the
    # sump line leaves the tower downward and climbs into the kettle's underside
    # rather than running through its shell. Each pump then stands below and
    # east of its kettle, with its suction on the run the weir draw falls onto.
    c1_reb.pin(x=c1_axis + 90, y=bot_y)
    c2_reb.pin(x=c2_axis + 90, y=bot_y)
    pump1.pin(x=1010, port="suction", y=pump_y)
    pump2.pin(x=1580, port="suction", y=pump_y)

    # Bottoms split, downstream of T-200's pump and above its discharge run.
    splitter.pin(x=1710, y=bot_y - 40)
    c2_bot.pin(x=1830, port="inlet",
               y=splitter.pin_.y + port_offset(splitter, "out_1")[1])

    # Recycle valve below the pump row (receives flow from the right)
    recycle_valve.pin(x=590, y=pump_y + 110, mirrored=True)

    # --- Connections ---
    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, feed_valve.inlet)
    fs.connect(feed_valve.outlet, preheater.tube_in)
    fs.connect(preheater.tube_out, col1.feed)

    # T-100's overhead circuit, then its reboiler circuit. The tee is inline, so
    # the drum's draw and the reflux leg it runs into carry one number and only
    # the distillate branch takes one of its own.
    fs.connect(col1.distillate, c1_ovhd.tube_in)
    fs.connect(c1_ovhd.tube_out, c1_drum.inlet)
    fs.connect(c1_drum.outlet, c1_tee.inlet)
    fs.connect(c1_tee.outlet, col1.reflux_in, draw_as_recycle=True)
    fs.connect(c1_tee.branch, c1_prod.inlet)

    fs.connect(col1.bottoms, c1_reb.shell_in)                       # sump to kettle
    fs.connect(c1_reb.shell_out, col1.boilup_in, draw_as_recycle=True)
    fs.connect(c1_reb.bottoms, pump1.suction)                       # over the weir
    fs.connect(pump1.discharge, col2.feed)

    fs.connect(col2.distillate, c2_ovhd.tube_in)
    fs.connect(c2_ovhd.tube_out, c2_drum.inlet)
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

    # Stream properties. Rows render in first-seen key order; values carry their
    # own units. A "Mass Fraction" section header is injected before benzene.
    for i, s in enumerate(fs.streams):
        s.properties = {
            "Temperature (°C)": f"{25 + i * 5} C",
            "Pressure (bar)": f"{1.0 + i * 0.1:.1f} bar",
            "Total Flow (kg/h)": f"{1000 - i * 10}",
            "Benzene": f"{0.90 - i * 0.02:.2f}",
            "Toluene": f"{0.10 + i * 0.02:.2f}",
        }
    fs.stream_table_sections = [("Benzene", "Mass Fraction")]

    # --- Title block + revision history ---
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
        ],
    )

    # --- Sheet furniture: generic titled boxes docked flush to the frame ---
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

    # --- Render ---
    fs.render(out("distillation_train.svg"), show_stream_table=True, border="zone")
    print("Generated distillation_train.svg")

if __name__ == "__main__":
    main()

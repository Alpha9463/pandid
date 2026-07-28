"""
Example 3: Advanced Distillation Train

This example demonstrates the engine's capability to route streams
across a complex flowsheet with tall equipment (columns), multiple
outlets, and recycled loops. The equipment shapes follow the conventions
of ISO 10628-2.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units

def main():
    fs = Flowsheet("Distillation Train")

    # Feed system. Boundary flags carry an off-page reference (the drawing the
    # stream comes from / goes to), drawn as the connector's second line.
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-1000"))
    mixer = fs.add(units.Mixer("M-100", n_inlets=2, description="Feed Mixer Drum"))
    feed_valve = fs.add(units.Valve("FV-100"))
    preheater = fs.add(units.HeatExchanger("E-100", description="Feed Preheater"))

    # Column 1
    col1 = fs.add(units.Column("T-100", description="Light Ends Column"))
    c1_ovhd = fs.add(units.HeatExchanger("E-101", description="T-100 Overhead Condenser"))
    c1_prod = fs.add(units.Product("Light Product", reference="PFD-1002"))

    # Bottoms transfer
    pump1 = fs.add(units.Pump("P-100A/B", description="T-100 Bottoms Pump"))

    # Column 2
    col2 = fs.add(units.Column("T-200", description="Product Column"))
    c2_ovhd = fs.add(units.HeatExchanger("E-201", description="T-200 Overhead Condenser"))
    c2_prod = fs.add(units.Product("Med Product", reference="PFD-1002"))

    # Bottoms split and recycle
    pump2 = fs.add(units.Pump("P-200A/B", description="T-200 Bottoms Pump"))
    splitter = fs.add(units.Splitter("SP-200", n_outlets=2, description="Bottoms Splitter"))
    c2_bot = fs.add(units.Product("Heavy Product", reference="PFD-1003"))
    recycle_valve = fs.add(units.Valve("FV-200"))
    
    # --- Pinned coordinates (Manual Grid) ---
    col_y = 420
    mixer_y = col_y + 105 - 25  # align mixer outlet (y+25) with col feed (col_y+105)
    feed_y = mixer_y - 10       # align feed outlet (y+25) with mixer in_1 (y+15)
    valve_y = col_y + 105 - 15  # align valve ports (y+15) with col feed line
    hx_y = col_y + 105 - 30     # align HX tube_in (y+30) with col feed line

    # Row positions left-to-right
    feed.pin(x=160, y=feed_y)
    mixer.pin(x=290, y=mixer_y)
    feed_valve.pin(x=410, y=valve_y)
    preheater.pin(x=520, y=hx_y)

    # Column 1
    col1.pin(x=690, y=col_y)

    # Overhead: HX above column, product to the right
    ovhd_y = col_y - 80         # overhead HX row
    c1_ovhd.pin(x=820, y=ovhd_y)
    # HX tube_out is at ovhd_y + 30. Product inlet is at y + 25.
    c1_prod.pin(x=980, y=ovhd_y + 5)

    # Bottoms: pump below column
    bot_y = col_y + 205 + 30    # below column bottom
    pump1.pin(x=820, y=bot_y)

    # Column 2
    col2.pin(x=1100, y=col_y)

    # Column 2 overhead
    c2_ovhd.pin(x=1230, y=ovhd_y)
    c2_prod.pin(x=1390, y=ovhd_y + 5)

    # Column 2 bottoms
    pump2.pin(x=1230, y=bot_y)
    # Move splitter up to align with pump2 discharge routing
    splitter.pin(x=1360, y=bot_y - 100)
    # Splitter out_1 is at bot_y - 85. Product inlet is at y + 25.
    c2_bot.pin(x=1480, y=bot_y - 110)

    # Recycle valve below the pump row (receives flow from the right)
    recycle_valve.pin(x=590, y=bot_y + 100, mirrored=True)
    
    # --- Connections ---
    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, feed_valve.inlet)
    fs.connect(feed_valve.outlet, preheater.tube_in)
    fs.connect(preheater.tube_out, col1.feed)

    # The overhead runs through the tubes, which is the exchanger's W-E pair.
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

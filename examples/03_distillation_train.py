"""
Example 3: Advanced Distillation Train

This example demonstrates the engine's capability to route streams
across a complex flowsheet with tall equipment (columns), multiple 
outlets, and recycled loops.  Uses ISO 10628-2 compliant symbols.
"""

from pfd.flowsheet import Flowsheet
import pfd.units as U

def main():
    fs = Flowsheet("Distillation Train")

    # Feed system
    feed = fs.add(U.Feed("Raw Feed"))
    mixer = fs.add(U.Mixer("M-100", n_inlets=2))
    feed_valve = fs.add(U.Valve("FV-100"))
    preheater = fs.add(U.HeatExchanger("E-100"))
    
    # Column 1
    col1 = fs.add(U.Column("T-100"))
    c1_ovhd = fs.add(U.HeatExchanger("E-101"))
    c1_prod = fs.add(U.Product("Light Product"))
    
    # Bottoms transfer
    pump1 = fs.add(U.Pump("P-100A/B"))
    
    # Column 2
    col2 = fs.add(U.Column("T-200"))
    c2_ovhd = fs.add(U.HeatExchanger("E-201"))
    c2_prod = fs.add(U.Product("Med Product"))
    
    # Bottoms split and recycle
    pump2 = fs.add(U.Pump("P-200A/B"))
    splitter = fs.add(U.Splitter("SP-200", n_outlets=2))
    c2_bot = fs.add(U.Product("Heavy Product"))
    recycle_valve = fs.add(U.Valve("FV-200"))
    
    # --- Pinned coordinates (Manual Grid) ---
    col_y = 420
    mixer_y = col_y + 105 - 25  # align mixer outlet (y+25) with col feed (col_y+105)
    feed_y = mixer_y - 10       # align feed outlet (y+25) with mixer in_1 (y+15)
    valve_y = col_y + 105 - 15  # align valve ports (y+15) with col feed line
    hx_y = col_y + 105 - 30     # align HX cold_in (y+30) with col feed line

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
    # HX cold_out is at ovhd_y + 30. Product inlet is at y + 25.
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
    fs.connect(feed_valve.outlet, preheater.cold_in)
    fs.connect(preheater.cold_out, col1.feed)
    
    # Use cold side of HX for left-to-right routing
    fs.connect(col1.distillate, c1_ovhd.cold_in)
    fs.connect(c1_ovhd.cold_out, c1_prod.inlet)
    
    fs.connect(col1.bottoms, pump1.suction)
    fs.connect(pump1.discharge, col2.feed)
    
    fs.connect(col2.distillate, c2_ovhd.cold_in)
    fs.connect(c2_ovhd.cold_out, c2_prod.inlet)
    
    fs.connect(col2.bottoms, pump2.suction)
    fs.connect(pump2.discharge, splitter.inlet)
    
    fs.connect(splitter.out_1, c2_bot.inlet)
    
    fs.connect(splitter.out_2, recycle_valve.inlet)
    fs.connect(recycle_valve.outlet, mixer.in_2, tear_hint=True)
    
    # Add some mock properties to streams to test the stream table
    for i, s in enumerate(fs.streams):
        s.properties = {
            "T (°C)": f"{25 + i * 5}",
            "P (bar)": f"{1.0 + i * 0.1:.1f}",
            "Flow (kg/h)": f"{1000 - i * 10}",
        }
        
    # --- Title block + revision history (drawn when styling="pid") ---
    from pfd.document import TitleBlock, Revision
    fs.title_block = TitleBlock(
        title="Distillation Train",
        drawing_number="PFD-1001",
        project="Aromatics Recovery Unit",
        sheet="1", of_sheets="3", scale="NTS",
        drawn_by="A. Anderson", checked_by="J. Smith", approved_by="R. Lee",
        revisions=[
            Revision("A", "2026-06-01", "Issued for internal review", "AA"),
            Revision("0", "2026-07-01", "Issued for design", "AA"),
            Revision("1", "2026-07-12", "Added FV-200 recycle loop", "AA"),
        ],
    )

    # --- Render ---
    fs.render("distillation_train.svg", show_stream_table=True, styling="pid")
    print("Generated distillation_train.svg")

if __name__ == "__main__":
    main()

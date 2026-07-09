"""
Example 3: Advanced Distillation Train

This example demonstrates the engine's capability to route streams
across a complex flowsheet with tall equipment (columns), multiple 
outlets, and recycled loops.  Uses ISO 10628-2 compliant symbols.
"""

from pfd.flowsheet import Flowsheet
import pfd.units as U
from pfd.geometry import Placement

def main():
    fs = Flowsheet("Distillation Train")

    # Feed system
    feed = fs.add(U.Feed("Raw Feed"))
    mixer = fs.add(U.Mixer("M-100", n_inlets=2))
    feed_valve = fs.add(U.ControlValve("FV-100"))
    preheater = fs.add(U.ShellAndTube("E-100"))
    
    # Column 1
    col1 = fs.add(U.TrayColumn("T-100"))
    c1_ovhd = fs.add(U.ShellAndTube("E-101"))
    c1_prod = fs.add(U.Product("Light Product"))
    
    # Bottoms transfer
    pump1 = fs.add(U.CentrifugalPump("P-100A/B"))
    
    # Column 2
    col2 = fs.add(U.TrayColumn("T-200"))
    c2_ovhd = fs.add(U.ShellAndTube("E-201"))
    c2_prod = fs.add(U.Product("Med Product"))
    
    # Bottoms split and recycle
    pump2 = fs.add(U.CentrifugalPump("P-200A/B"))
    splitter = fs.add(U.Splitter("SP-200", n_outlets=2))
    c2_bot = fs.add(U.Product("Heavy Product"))
    recycle_valve = fs.add(U.ControlValve("FV-200"))
    
    # --- Placements (Manual Grid) ---
    col_y = 420
    mixer_y = col_y + 105 - 25  # align mixer outlet (y+25) with col feed (col_y+105)
    feed_y = mixer_y - 10       # align feed outlet (y+25) with mixer in_1 (y+15)
    valve_y = col_y + 105 - 25  # align valve ports (y+25) with col feed
    hx_y = col_y + 105 - 30     # align HX cold_in (y+30) with col feed line

    # Row positions left-to-right
    feed.placement = Placement(160, feed_y)
    mixer.placement = Placement(290, mixer_y)
    feed_valve.placement = Placement(410, valve_y)
    preheater.placement = Placement(520, hx_y)

    # Column 1
    col1.placement = Placement(690, col_y)

    # Overhead: HX above column, product to the right
    ovhd_y = col_y - 80         # overhead HX row
    c1_ovhd.placement = Placement(820, ovhd_y)
    # HX cold_out is at ovhd_y + 30. Product inlet is at y + 25.
    c1_prod.placement = Placement(980, ovhd_y + 5)

    # Bottoms: pump below column
    bot_y = col_y + 205 + 30    # below column bottom
    pump1.placement = Placement(820, bot_y)

    # Column 2
    col2.placement = Placement(1100, col_y)

    # Column 2 overhead
    c2_ovhd.placement = Placement(1230, ovhd_y)
    c2_prod.placement = Placement(1390, ovhd_y + 5)

    # Column 2 bottoms
    pump2.placement = Placement(1230, bot_y)
    # Move splitter up to align with pump2 discharge routing
    splitter.placement = Placement(1360, bot_y - 100)
    # Splitter out_1 is at bot_y - 85. Product inlet is at y + 25.
    c2_bot.placement = Placement(1480, bot_y - 110)

    # Recycle valve below the pump row (receives flow from the right)
    recycle_valve.placement = Placement(590, bot_y + 100, mirrored=True)
    
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
        
    # --- Render ---
    fs.render("distillation_train.svg", show_stream_table=True, styling="pid")
    print("Generated distillation_train.svg")

if __name__ == "__main__":
    main()

"""
Example 2: Manual Layout and Routing

This example demonstrates how to use `pin()` and `.via()` to manually
control the placement of units and the routing of streams, overriding
the automatic layout engine.
"""

from pfd.flowsheet import Flowsheet
import pfd.units as U

def main():
    # 1. Create a flowsheet
    fs = Flowsheet("Manual Override Example")
    
    # 2. Add units and PIN their (x, y) coordinates
    # The pin() method accepts absolute SVG coordinates (top-left of the unit)
    feed1 = fs.add(U.Feed("F-1")).pin(x=50, y=50)
    feed2 = fs.add(U.Feed("F-2")).pin(x=50, y=250)
    hx1 = fs.add(U.HeatExchanger("E-1")).pin(x=150, y=100)
    hx2 = fs.add(U.HeatExchanger("E-2")).pin(x=150, y=250)
    prod1 = fs.add(U.Product("P-1")).pin(x=350, y=100)
    prod2 = fs.add(U.Product("P-2")).pin(x=350, y=250)
    
    # 3. Connect streams and use .via() to specify custom routing waypoints
    # The via() method accepts a list of (x, y) coordinates for the orthogonal path
    # If a path isn't perfectly orthogonal, it will still draw straight lines between points.
    
    fs.connect(feed1.outlet, hx1.cold_in).via([
        (130, 65),     # Move horizontally out of feed
        (130, 110),    # Move vertically down
        (150, 110)     # Connect to E-1
    ])
    
    # Let the engine automatically route this one!
    fs.connect(feed2.outlet, hx2.cold_in)
    
    fs.connect(hx1.cold_out, prod1.inlet)
    fs.connect(hx2.cold_out, prod2.inlet)
    
    # 4. Render!
    # Because we used pin() and via(), the engine will respect our coordinates
    # and only auto-route the streams we didn't specify.
    out_file = "manual_layout.svg"
    fs.render(out_file)
    print(f"Flowsheet rendered successfully to {out_file}")

if __name__ == "__main__":
    main()

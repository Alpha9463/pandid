"""
Example 15: Condensing steam turbine, laid out automatically

HP steam is dried, passes a trip-and-throttle valve and expands
through a condensing turbine. The exhaust condenses in an air-cooled
condenser and drains to a receiver that a steam-jet ejector holds
under vacuum; the condensate is pumped through a feedwater heater to
the deaerator. One MP steam header drives the ejector and heats the
condensate. Receiver level throttles the discharge valve, and a
low-level interlock shuts the trip valve downstream of it.

Nothing is pinned. The engine ranks, orders, places and routes the
whole sheet, balloons included; the only placements stated here are
which face a balloon hangs off and how far out.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    AirCooledExchanger,
    ControlValve,
    Ejector,
    Feed,
    Flowsheet,
    Heater,
    KnockoutDrum,
    Product,
    Pump,
    Splitter,
    Turbine,
    Valve,
    Vent,
    Vessel,
)


def main():
    fs = Flowsheet("Condensing Turbine and Vacuum System")

    hp_steam = fs.add(Feed("HP Steam", reference="PFD-700"))
    s701 = fs.add(KnockoutDrum("S-701", description="HP Steam Separator"))
    gv701 = fs.add(Valve("GV-701", variant="globe",
                         description="MP Steam Isolation Valve"))
    trap = fs.add(Product("Steam Trap Drain", reference="PFD-800"))
    tv701 = fs.add(Valve("TV-701", variant="hydraulic", fail="closed",
                         description="Turbine Trip and Throttle Valve"))
    st701 = fs.add(Turbine("ST-701", description="Condensing Steam Turbine"))
    e701 = fs.add(AirCooledExchanger("E-701", description="Air-Cooled Condenser"))

    ej701 = fs.add(Ejector("EJ-701", description="Condenser Air Ejector"))
    v701 = fs.add(Vessel("V-701", variant="dished", description="Condensate Receiver"))
    sp701 = fs.add(Splitter("SP-701", n_outlets=2))
    vt701 = fs.add(Vent("VT-701", description="Non-Condensibles Vent"))

    p701 = fs.add(Pump("P-701A/B", description="Condensate Pump"))
    e702 = fs.add(Heater("E-702", description="LP Feedwater Heater"))
    mp_steam = fs.add(Feed("MP Steam", reference="PFD-700"))

    level = fs.add_loop("L", 701)
    lv701 = fs.add(ControlValve(level.tag("LV"), fail="open",
                                description="Receiver Level Control Valve"))
    xv701 = fs.add(Valve("XV-701", variant="butterfly_pneumatic", fail="closed",
                         description="Low-Level Trip Valve"))
    deaerator = fs.add(Product("To Deaerator", reference="PFD-800"))

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

    # The controller hangs over the valve it strokes, so its output
    # drops straight onto the actuator, and the interlock hangs off the
    # controller so its own output leaves east and turns down.
    lt701 = fs.add_instrument("LT", level, sensing=v701, at="S", offset=55)
    lic701 = fs.add_instrument("LIC", level, near=lv701, at="N", offset=110,
                               variant="shared")
    trip = fs.add_instrument("ZSL", 701, near=lic701, at="N", offset=70,
                             variant="interlock",
                             description="Low-Level Trip")
    fs.connect(lt701.sig_out, lic701.pv, kind="electric")
    fs.connect(lic701.sig_out, lv701.actuator, kind="pneumatic")
    fs.connect(lic701.sig_out, trip.sig_in, kind="electric")
    fs.connect(trip.sig_out, xv701.actuator, kind="electric")

    vacuum = fs.add_loop("P", 702)
    pt702 = fs.add_instrument("PT", vacuum, sensing=exhaust, at=0.5, offset=60)
    pi702 = fs.add_instrument("PI", vacuum, near=pt702, at="N", offset=65,
                              display="subsidiary",
                              description="Local Gauge Board")
    fs.connect(pt702.sig_out, pi702.sig_in, kind="electric")

    fs.render(out("condensing_turbine.svg"), diagram="p&id")
    print("Generated condensing_turbine.svg")


if __name__ == "__main__":
    main()

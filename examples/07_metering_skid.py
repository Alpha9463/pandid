"""
Example 7: Feed conditioning and metering skid

Exercises the inline fittings and actuated valves: feed is strained, pumped,
metered through a rotameter, throttled by a motor-operated valve, held in a
surge vessel protected by a relief valve, and checked through a sight glass on
the way out. Everything sits on one spine, so the runs are straight.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Feed Metering Skid")

    # --- Equipment -------------------------------------------------------
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-100"))
    strainer = fs.add(units.Fitting("ST-101", variant="strainer",
                                    description="Suction Strainer"))
    pump = fs.add(units.Pump("P-101", description="Feed Pump"))
    meter = fs.add(units.Fitting("FI-101", variant="rotameter",
                                 description="Variable-Area Flow Meter"))
    fv = fs.add(units.Valve("FV-101", variant="motor",
                            description="Motor-Operated Throttle Valve"))
    surge = fs.add(units.Vessel("V-101", width=90, height=140,
                                description="Surge Vessel"))
    psv = fs.add(units.Valve("PSV-101", variant="psv",
                             description="Vessel Relief Valve"))
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    glass = fs.add(units.Fitting("SG-101", variant="sight_glass",
                                 description="Sight Glass"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: pin(port=...) asks each symbol where its
    # own nozzle sits, so nothing here writes down half a valve body. A
    # boundary flag is pinned at the tip of its arrow.
    #
    # Two elevations, because the pump's discharge nozzle sits above its
    # suction and lifts the spine with it.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    strainer.pin(port="inlet", x=190, y=suction_y)
    pump.pin(port="suction", x=280, y=suction_y)
    meter.pin(port="inlet", x=430, y=discharge_y)
    # Flipped so the motor operator faces down, on the controller's side of the
    # line. A flip moves the ports within the box and the offset is read after
    # it, so the valve still lands on the run.
    fv.pin(port="inlet", x=540, y=discharge_y, mirrored="y")
    surge.pin(port="inlet", x=680, y=discharge_y)
    glass.pin(port="inlet", x=850, y=discharge_y)
    prod.pin(port="inlet", x=980, y=discharge_y)

    # Two pins: how high the PSV stands is a free choice and stays a corner,
    # while the axis its riser has to land on is read off the vessel's nozzle.
    psv.pin(y=110).pin(port="inlet", x=680 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=900, y=110 + port_offset(psv, "outlet")[1])

    # --- Connections -----------------------------------------------------
    fs.connect(feed.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)
    fs.connect(pump.discharge, meter.inlet)
    fs.connect(meter.outlet, fv.inlet)
    fs.connect(fv.outlet, surge.inlet)
    fs.connect(surge.outlet, glass.inlet)
    fs.connect(glass.outlet, prod.inlet)

    fs.connect(surge.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Hung below the vessel rather than beside it: the east side is the outlet
    # run, and an instrument placed into equipment is a hard validation error.
    # A balloon has no fixed sides, so the engine picks the face itself.
    lic = fs.add_instrument("LIC", 101, on=surge, at="S", offset=115,
                            variant="panel")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")

    fs.render(out("metering_skid.svg"))
    print("Generated metering_skid.svg")


if __name__ == "__main__":
    main()

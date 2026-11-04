"""
Example 6: Feed conditioning and metering skid

Feed is strained, pumped, metered through a rotameter, throttled by a
motor-operated valve, held in a surge vessel with a relief valve, and
checked through a sight glass on the way out.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Fitting, Flowsheet, MotorOperatedValve, Product, Pump, ReliefValve, Vessel
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Feed Metering Skid")

    # --- Equipment ----------------------------------------------------
    feed = fs.add(Feed("Raw Feed", reference="P&ID-100"))
    strainer = fs.add(Fitting("ST-101", variant="strainer",
                              description="Suction Strainer"))
    pump = fs.add(Pump("P-101", description="Feed Pump"))
    meter = fs.add(Fitting("FI-101", variant="rotameter",
                           description="Variable-Area Flow Meter"))
    fv = fs.add(MotorOperatedValve("FV-101",
                                   description="Motor-Operated Throttle Valve"))
    surge = fs.add(Vessel("V-101", width=90, height=140,
                          description="Surge Vessel"))
    psv = fs.add(ReliefValve("PSV-101", variant="psv",
                             description="Vessel Relief Valve"))
    flare = fs.add(Product("To Flare", reference="P&ID-900"))
    glass = fs.add(Fitting("SG-101", variant="sight_glass",
                           description="Sight Glass"))
    prod = fs.add(Product("To Unit 200", reference="P&ID-200"))

    # --- Placement ----------------------------------------------------
    # Pin by nozzle; the pump's discharge sits above its suction.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    strainer.pin(port="inlet", x=190, y=suction_y)
    pump.pin(port="suction", x=280, y=suction_y)
    meter.pin(port="inlet", x=430, y=discharge_y)
    # Flipped so the motor operator faces down, towards the controller.
    fv.pin(port="inlet", x=540, y=discharge_y, mirrored="y")
    surge.pin(port="inlet", x=680, y=discharge_y)
    glass.pin(port="inlet", x=850, y=discharge_y)
    prod.pin(port="inlet", x=980, y=discharge_y)

    # Pin the PSV's height by its corner and its x by its inlet.
    psv.pin(y=110).pin(port="inlet", x=680 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=900, y=110 + port_offset(psv, "outlet")[1])

    # --- Connections --------------------------------------------------
    fs.connect(feed.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)
    fs.connect(pump.discharge, meter.inlet)
    fs.connect(meter.outlet, fv.inlet)
    fs.connect(fv.outlet, surge.inlet)
    fs.connect(surge.outlet, glass.inlet)
    fs.connect(glass.outlet, prod.inlet)

    fs.connect(surge.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Level controller below the vessel, in the central control system.
    lic = fs.add_instrument("LIC", 101, sensing=surge, face="S", offset=115,
                            display="central")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")

    fs.render(out("metering_skid.svg"), diagram="p&id")
    print("Generated metering_skid.svg")


if __name__ == "__main__":
    main()

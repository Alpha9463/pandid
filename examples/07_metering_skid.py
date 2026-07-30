"""
Example 7: Feed conditioning and metering skid

Exercises the inline fittings and actuated valves: feed is strained, pumped,
metered through a rotameter, throttled by a motor-operated valve, held in a
surge vessel protected by a spring relief valve, and checked through a sight
glass on the way out.

Everything sits on one spine so the runs are straight. The only rise is across
the pump, whose discharge nozzle is above its suction, which is what a pump
actually looks like rather than a routing artefact.
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
    # own nozzle sits, so nothing here writes down half a valve body and no
    # in-line device can land off its run. A boundary flag is pinned at the tip
    # of its arrow, which is where its line reaches it.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    strainer.pin(port="inlet", x=190, y=suction_y)
    # The one rise on the sheet, and it is the pump's own: its discharge nozzle
    # really does sit above its suction, which is what lifts the spine.
    pump.pin(port="suction", x=280, y=suction_y)
    meter.pin(port="inlet", x=430, y=discharge_y)
    # Flipped top-to-bottom so the motor operator faces down, on the same side
    # as the controller: otherwise the signal has to climb over the vessel to
    # reach it. A flip moves the ports within the box, and the offset is read
    # after it, so the valve still lands on the run.
    fv.pin(port="inlet", x=540, y=discharge_y, mirrored="y")
    surge.pin(port="inlet", x=680, y=discharge_y)
    glass.pin(port="inlet", x=850, y=discharge_y)
    prod.pin(port="inlet", x=980, y=discharge_y)

    # Relief stack: the PSV takes flow in its base and discharges from its side,
    # so it stands directly over the vessel's relief nozzle.
    # How high it stands is a free choice, so that one is pinned by the corner;
    # only the axis the riser has to land on is read as a nozzle.
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

    # Level controller on the vessel driving the throttle valve's operator.
    # Hung below rather than beside it: the east side is the outlet run, and an
    # instrument placed into equipment is a hard validation error, not a nudge.
    # A balloon has no fixed sides, so the engine takes the signal out on the
    # face the valve is actually on rather than letting the run double back.
    lic = fs.add_instrument("LIC", 101, on=surge, at="S", offset=115,
                            variant="panel")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")

    fs.render(out("metering_skid.svg"))
    print("Generated metering_skid.svg")


if __name__ == "__main__":
    main()

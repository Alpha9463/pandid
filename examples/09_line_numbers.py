"""
Example 9: Line numbers

A line number such as `6"-P-1001-A1A` is size, service, sequence and
spec, given on `connect()`; the sequence is numbered automatically. One
number carries through the hand valve and strainer and breaks at each
unit marked `new_line_number`. The flare tail-pipe sets `sequence` by
hand.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import ControlValve, Feed, Fitting, Flowsheet, Product, Pump, ReliefValve, Valve, Vessel
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Transfer and Relief")

    # --- Equipment ----------------------------------------------------
    feed = fs.add(Feed("Raw Feed", reference="PFD-100"))
    hv = fs.add(Valve("HV-101", description="Suction Isolation Valve"))
    strainer = fs.add(Fitting("ST-101", variant="strainer",
                              description="Suction Strainer"))
    pump = fs.add(Pump("P-101", description="Transfer Pump"))
    fv = fs.add(ControlValve("FV-101",
                             description="Discharge Control Valve"))
    surge = fs.add(Vessel("V-101", width=90, height=140,
                          description="Surge Vessel"))
    psv = fs.add(ReliefValve("PSV-101", variant="psv",
                             description="Vessel Relief Valve"))
    flare = fs.add(Product("To Flare", reference="PFD-900"))
    prod = fs.add(Product("To Unit 200", reference="PFD-200"))

    # The two spec breaks; everything else keeps its run whole.
    fv.new_line_number = True
    psv.new_line_number = True

    # --- Placement ----------------------------------------------------
    # Pin by nozzle, with a long run off the feed for its line number.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    hv.pin(port="inlet", x=235, y=suction_y)
    strainer.pin(port="inlet", x=335, y=suction_y)
    pump.pin(port="suction", x=425, y=suction_y)
    fv.pin(port="inlet", x=575, y=discharge_y)
    surge.pin(port="inlet", x=725, y=discharge_y)
    prod.pin(port="inlet", x=925, y=discharge_y)

    # Pin the PSV's height by its corner and its x by its inlet.
    psv.pin(y=110).pin(port="inlet", x=725 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=945, y=110 + port_offset(psv, "outlet")[1])

    # --- Connections --------------------------------------------------
    # One line number over three segments, set on the first.
    fs.connect(feed.outlet, hv.inlet, size='8"', service="P", spec="A1A")
    fs.connect(hv.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)

    fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
    fs.connect(fv.outlet, surge.inlet, size='6"', service="P", spec="D1B")
    fs.connect(surge.outlet, prod.inlet, size='6"', service="P", spec="D1B")

    fs.connect(surge.vent, psv.inlet, size='3"', service="P", spec="A1A")
    # sequence= set by hand; the automatic sequence runs on regardless.
    fs.connect(psv.outlet, flare.inlet, size='4"', service="FL", sequence=2740, spec="A1A")

    # diagram="p&id" is what drops the arrowheads off the process lines.
    fs.render(out("line_numbers.svg"), diagram="p&id")
    print("Generated line_numbers.svg")
    for stream in fs.streams:
        print(f"  {stream.source.owner.name} -> {stream.dest.owner.name}: {stream.name}")


if __name__ == "__main__":
    main()

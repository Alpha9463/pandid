"""
Example 9: Line numbers

The identifier that ties a line on the sheet to the line list, the stress
calculation and the isometric: `6"-P-1001-A1A` is size, service, sequence, spec.
Each line's components go in on `connect()` and the sequence is filled by the
same numbering that hands out `S1`, `S2`, so nothing has to be kept unique by
hand.

The two rules a line number inherits from the stream number are what make it
match the piping:

- it carries **through** a hand valve and a strainer, so one line keeps one
  number over its whole run;
- it **breaks** at a unit marked `new_line_number`, which is exactly where the
  spec breaks, at the control valve and across the relief valve.

The tail-pipe to flare shows the other half: `sequence` set by hand, for a line
that already exists on someone else's line list.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Fitting, Flowsheet, Product, Pump, Valve, Vessel
from pandid.document import Revision, TitleBlock
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Transfer and Relief")

    # --- Equipment -------------------------------------------------------
    feed = fs.add(Feed("Raw Feed", reference="PFD-100"))
    hv = fs.add(Valve("HV-101", description="Suction Isolation Valve"))
    strainer = fs.add(Fitting("ST-101", variant="strainer",
                              description="Suction Strainer"))
    pump = fs.add(Pump("P-101", description="Transfer Pump"))
    fv = fs.add(Valve("FV-101", variant="control",
                      description="Discharge Control Valve"))
    surge = fs.add(Vessel("V-101", width=90, height=140,
                          description="Surge Vessel"))
    psv = fs.add(Valve("PSV-101", variant="psv",
                       description="Vessel Relief Valve"))
    flare = fs.add(Product("To Flare", reference="PFD-900"))
    prod = fs.add(Product("To Unit 200", reference="PFD-200"))

    # The two spec breaks on this sheet. Everything else in line is left alone
    # and keeps its run whole.
    fv.new_line_number = True
    psv.new_line_number = True

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: pin(port=...) asks each symbol where its
    # own nozzle sits. A boundary flag is pinned at the tip of its arrow.
    #
    # The run off the feed flag is long on purpose: a line number is a dozen
    # characters wide and is labelled on the longest segment it has. The two
    # elevations are the pump's, whose discharge nozzle sits above its suction.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    hv.pin(port="inlet", x=235, y=suction_y)
    strainer.pin(port="inlet", x=335, y=suction_y)
    pump.pin(port="suction", x=425, y=suction_y)
    fv.pin(port="inlet", x=575, y=discharge_y)
    surge.pin(port="inlet", x=725, y=discharge_y)
    prod.pin(port="inlet", x=925, y=discharge_y)

    # Two pins: how high the PSV stands is a free choice and stays a corner,
    # while the axis its riser has to land on is read off the vessel's nozzle.
    psv.pin(y=110).pin(port="inlet", x=725 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=945, y=110 + port_offset(psv, "outlet")[1])

    # --- Connections -----------------------------------------------------
    # One line number over three segments: the components go on the first, and
    # the group takes it from there.
    suction = fs.connect(feed.outlet, hv.inlet, size='8"', service="P", spec="A1A")
    fs.connect(hv.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)

    discharge = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
    downstream = fs.connect(fv.outlet, surge.inlet, size='6"', service="P", spec="D1B")
    to_unit = fs.connect(surge.outlet, prod.inlet, size='6"', service="P", spec="D1B")

    relief = fs.connect(surge.vent, psv.inlet, size='3"', service="P", spec="A1A")
    # sequence= set by hand; the automatic sequence runs on regardless.
    tail = fs.connect(psv.outlet, flare.inlet, size='4"', service="FL",
                      sequence=2740, spec="A1A")

    # --- Line list -------------------------------------------------------
    conditions = [
        (suction, "25 C", "1.2 bara", "42000"),
        (discharge, "26 C", "9.5 bara", "42000"),
        (downstream, "26 C", "4.0 bara", "42000"),
        (to_unit, "26 C", "3.6 bara", "42000"),
        (relief, "26 C", "4.0 bara", "0"),
        (tail, "26 C", "1.1 bara", "0"),
    ]
    for stream, temperature, pressure, flow in conditions:
        stream.properties = {
            "Temperature": temperature,
            "Pressure": pressure,
            "Mass Flow (kg/h)": flow,
        }

    fs.title_block = TitleBlock(
        title="Transfer and Relief U100",
        subtitle="Piping and Instrumentation Diagram",
        drawing_number="P&ID-1009",
        project="Feed Transfer Package",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        drawn_by="A. Anderson",
        checked_by="J. Smith",
        # Fixed rather than left blank, so re-rendering the sheet does not move
        # the drawing by a day.
        date="2026-07-15",
        revisions=[
            Revision("A", "2026-06-20", "Issued for internal review", "AA"),
            Revision("B", "2026-07-15", "Line numbers added", "AA", "JS"),
        ],
    )

    # diagram="p&id" is what drops the arrowheads off the process lines.
    fs.render(out("line_numbers.svg"), border="zone", diagram="p&id",
              show_stream_table=True)
    print("Generated line_numbers.svg")
    for stream in fs.streams:
        print(f"  {stream.source.owner.name} -> {stream.dest.owner.name}: {stream.name}")


if __name__ == "__main__":
    main()

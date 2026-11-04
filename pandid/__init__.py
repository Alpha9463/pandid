"""pandid: draw process flow diagrams and P&IDs from a Python flowsheet.

Before you start:
1. Pass diagram="p&id" to render() for a P&ID ("bfd" for a block flow
   diagram). Without it the sheet is a PFD, which reports
   stream-table-missing until each line crossing the sheet edge has
   properties and render(show_stream_table=True) draws the table.
2. Check in this order: render, then fs.validate(), then look. render()
   raises ValueError listing every error finding; before a render,
   fs.validate() reports only model findings, under PFD rules. Act on
   every finding, warnings too, then open the drawing and look for lines
   through units, crowded labels and balloons on the wrong line. Repeat
   until fs.validate() returns [] and the drawing reads right.

Model: a Flowsheet holds units (equipment, valves, instruments, and the
Feed and Product flags where lines enter and leave the sheet); import
every class from pandid. A unit has named ports; fs.connect(source, dest)
joins an outlet port to an inlet port with a Stream. The sheet places
units and routes streams when drawn; give coordinates only where needed.
help(pandid.Flowsheet) documents every call, help() on a class its options.

Example, a pumped product cooler with a flow control loop::

    from pandid import (ControlValve, Feed, Flowsheet, Product, Pump,
                        ShellAndTubeExchanger)

    fs = Flowsheet("Product cooler")
    feed = fs.add(Feed("Feed"))
    pump = fs.add(Pump("P-101"))
    cooler = fs.add(ShellAndTubeExchanger("E-101"))
    valve = fs.add(ControlValve("FV-101"))
    product = fs.add(Product("Product"))
    cws = fs.add(Feed("CWS"))
    cwr = fs.add(Product("CWR"))

    fs.connect(feed.outlet, pump.suction)
    line = fs.connect(pump.discharge, cooler.tube_in)
    fs.connect(cooler.tube_out, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.connect(cws.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr.inlet)

    fs.add_control_loop("F", 101, measuring=line, acting_on=valve)
    fs.add_instrument("PI", 102, sensing=pump, face="N")

    fs.render("cooler.svg", diagram="p&id")
    print(fs.validate())

Ports:
    Feed / Product              outlet / inlet
    Pump, Compressor            suction, discharge
    Valve, ControlValve         inlet, outlet, actuator (signal)
    HeatExchanger, Condenser,
    ShellAndTubeExchanger       tube_in, tube_out, shell_in, shell_out
    Heater / Cooler             inlet, outlet, utility_in / utility_out
    Vessel, Tank                inlet, outlet, vent, relief, drain
    Separator                   feed, vapor, liquid
    Cyclone                     feed, overflow, underflow
    Column                      feed, overhead, bottoms
    DistillationColumn          as Column, and reflux_in, boilup_in,
                                reboiler_duty, condenser_duty
    Splitter                    inlet, out_1, out_2
    Tee                         inlet, outlet, branch (inlet if branch="inlet")
    Instrument                  pv, sig_in, sig_out
A count (n_feeds=, n_inlets=, n_outlets=, inputs=, outputs=) numbers the
ports: feed_1, feed_2, in_1, out_1. list(unit.ports) lists a unit's ports;
a wrong name raises AttributeError listing them.

Traps:
- Pin a nozzle, not the corner: unit.pin(port="suction", x=..., y=...)
  places that nozzle; unit.pin(x=..., y=...) places the box's top-left
  corner. On a Feed or Product, x and y place the flag's port.
- A class is what the equipment is; variant= is how its base class draws
  it. Use the named class (Cyclone, ControlValve, GearPump), else the base
  class with variant=: Valve("HV-101", variant="gate").
  python -m pandid symbols --kind valve lists a kind's drawings.
- A signal line needs kind= (electric, pneumatic, data, capillary or
  software): fs.connect(ft.sig_out, fic.sig_in, kind="electric"). A process
  line infers material, or energy between two energy or utility ports.
- face= is a side of a unit, "N", "S", "E" or "W"; at= is a fraction 0..1
  along a line: fs.add_instrument("TI", 103, sensing=cooler, face="E"),
  fs.add_instrument("PI", 104, sensing=line, at=0.3),
  fs.add(Valve("HV-102"), on=line, at=0.5).
- Attach an instrument with one of sensing= (what it measures), acting_on=
  (what it drives) or near= (beside it, no line). sensing= and acting_on=
  draw a tap line but add no Stream; join instruments with
  fs.connect(..., kind=...). fs.add_control_loop("F", 101, measuring=line,
  acting_on=valve) adds the transmitter, the controller and both signal
  lines.
- A line keeps its number through a valve or fitting (Feed -> valve -> pump
  -> Product is S1, S1, S2); device.new_line_number = True starts a new one.
- .svg and .drawio need nothing; .pdf and .png need pip install "pandid[pdf]".
"""

__version__ = "0.1.5"

from pandid.components import Component
from pandid.flowsheet import Flowsheet
from pandid import units
from pandid import devices
from pandid.units import *  # noqa: F403
from pandid.devices import *  # noqa: F403
from pandid.spec import SpecError

# Handles the API returns, and the title-block and annotation classes.
from pandid.ports import Port
from pandid.streams import Stream
from pandid.geometry import Pin, Frame, Route
from pandid.loops import Loop, ControlLoop
from pandid.stations import ValveStation
from pandid.validate import Issue
from pandid.document import TitleBlock, Revision, Annotation, TableBox

__all__ = ["Flowsheet", "Component", "units", "devices", "SpecError", "__version__",
           "Port", "Stream", "Pin", "Frame", "Route",
           "Loop", "ControlLoop", "ValveStation", "Issue",
           "TitleBlock", "Revision", "Annotation", "TableBox",
           *units.__all__, *devices.__all__]

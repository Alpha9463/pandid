"""pandid: draw process flow diagrams and P&IDs from a Python flowsheet.

Import every equipment class, and every handle the API returns, from
pandid. help(pandid.Flowsheet) documents every call, and help() on an
equipment class its options.

The model
---------
A Flowsheet holds units: equipment, valves, instruments, and the Feed and
Product flags where lines enter and leave the sheet. A unit has named
ports. fs.connect(source, dest) joins an outlet port to an inlet port with
a Stream. The sheet places its units and routes its streams when it is
drawn; give coordinates only where a drawing needs them.

Example
-------
Draw a pumped product cooler with a flow control loop::

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
    for issue in fs.validate():
        print(issue.severity, issue.code, issue.message)

Port names
----------
    Feed                          outlet
    Product                       inlet
    Pump, Compressor              suction, discharge
    Valve, ControlValve           inlet, outlet, actuator (signal)
    HeatExchanger,
    ShellAndTubeExchanger         tube_in, tube_out, shell_in, shell_out
    Heater                        inlet, outlet, utility_in
    Cooler                        inlet, outlet, utility_out
    Vessel, Tank                  inlet, outlet, vent, relief, drain
    Separator                     feed, vapor, liquid
    Cyclone                       feed, overflow, underflow
    Column                        feed, overhead, bottoms
    DistillationColumn            as Column, and reflux_in, boilup_in,
                                  reboiler_duty, condenser_duty
    Instrument                    pv, sig_in, sig_out

A unit with several feeds, inlets or outlets numbers them instead:
feed_1, feed_2, in_1, in_2, out_1. list(unit.ports) lists a unit's ports,
and a wrong name raises AttributeError listing them.

Traps
-----
Pin a nozzle, not the corner. unit.pin(x=..., y=...) places the top-left
corner of the unit's box; unit.pin(port="suction", x=..., y=...) places
that nozzle. On a Feed or Product, x and y place the flag's port.

A class is what the equipment is; variant= is how its base class draws
it. Use the named class when there is one: Cyclone("S-101"),
ControlValve("FV-101"), GearPump("P-102"). Use the base class with
variant= for a drawing with no class: Valve("HV-101", variant="gate").
python -m pandid symbols --kind valve lists the drawings of a kind.

A signal line needs kind=: fs.connect(ft.sig_out, fic.sig_in,
kind="electric"). The signal kinds are electric, pneumatic, data,
capillary and software. A process line infers material, or energy
between two energy or utility ports.

face= is a side of a unit, "N", "S", "E" or "W"; at= is a fraction 0..1
along a line: fs.add_instrument("TI", 103, sensing=cooler, face="E"),
fs.add_instrument("PI", 104, sensing=line, at=0.3), and
fs.add(Valve("HV-102"), on=line, at=0.5) to put a valve in a line.

Attach an instrument with one of sensing= (what it measures), acting_on=
(what it drives) or near= (placed beside, no line). sensing= and
acting_on= draw a tap line but add no Stream; join instruments with
fs.connect(..., kind=...). fs.add_control_loop("F", 101, measuring=line,
acting_on=valve) adds a whole loop: transmitter, controller and both
signal lines.

A line keeps its number through a valve or fitting, so the lines of
Feed -> valve -> pump -> Product are S1, S1, S2. Set
device.new_line_number = True to start a new number after a device.

.svg and .drawio output need nothing. .pdf and .png need the pdf extra:
pip install "pandid[pdf]".

render() draws a PFD unless given diagram="p&id" or diagram="bfd". A PFD
reports stream-table-missing until the lines crossing the sheet edge have
properties and render(show_stream_table=True) draws the table.

Check your work
---------------
1. Render. render() raises ValueError listing every error finding;
   fix each one and render again.
2. Call fs.validate() after the render and act on every finding,
   warnings too. Before a render it reports only model findings.
3. Open the drawing and look for lines through units, crowded labels
   and balloons on the wrong line.
4. Repeat until fs.validate() returns [] and the drawing reads right.
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

"""
Example 11: Ethanol Purification A300 — the P&ID of example 10's unit

The same beer column, condenser, reflux drum, kettle reboiler and bottoms
cooler as ``10_ethanol_pfd.py``, on the same fixed ``page_size="A3"`` sheet,
drawn as the piping and instrumentation diagram rather than the flow diagram.
The condenser, drum and reboiler carry the tags the P&ID gives them, which the
PFD leaves off.

What a P&ID adds over the PFD of the same unit:

- every line carries its **line number** rather than a stream number, and one
  number runs through the hand valves and the control valve of a station,
  because a valve station is one line and not four;
- the field devices are drawn: hand isolation valves either side of the
  reflux and steam control valves, the flow element sitting *in* the line, a
  check valve on the bottoms and the solenoid trip on the feed;
- five control loops close on a real final control element, each drawn
  measurement -> controller -> actuator, with the tower-top temperature
  cascaded onto the reflux flow controller;
- the interlock square repeats. ``Instrument(variant="logic")`` is the one
  symbol allowed to carry its tag more than once, because a trip is a single
  logic function drawn everywhere it acts.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes


def main():
    # The sheet spells a line number service-sequence-size-spec, and its spec
    # field carries the flange class and the material together.
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{spec}",
        line_number_start=301,
    )

    # --- Equipment -------------------------------------------------------
    col = fs.add(units.Column("T-301", description="Beer Column"))
    cond = fs.add(units.HeatExchanger("C-301", variant="straight_tubes", width=130,
                                      height=40, description="Overhead Condenser"))
    drum = fs.add(units.Vessel("D-301", variant="horizontal", width=130, height=42,
                               description="Reflux Drum"))
    reb = fs.add(units.HeatExchanger("RB-301", variant="kettle", width=140, height=50,
                                     description="U-tube Kettle Reboiler"))
    cooler = fs.add(units.HeatExchanger("HX-301", variant="straight_tubes", width=130,
                                        height=40, description="Beer Bottoms Cooler"))
    split = fs.add(units.Splitter("SP-301", n_outlets=2, width=40, height=40,
                                  description="Reflux Split"))

    # Boundary flags. The two cooling-water tie-ins serve one header but are
    # numbered apart, because a tag names one item on the sheet.
    fb_feed = fs.add(units.Feed("Fermentation Broth", reference="P&ID-201"))
    cws_cond = fs.add(units.Feed("CWSH-1"))
    cwr_cond = fs.add(units.Product("CWRH-1"))
    cws_cool = fs.add(units.Feed("CWSH-2"))
    cwr_cool = fs.add(units.Product("CWRH-2"))
    steam = fs.add(units.Feed("HPSSH"))
    condensate = fs.add(units.Product("HPSRH"))
    ae_prod = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    bottoms_prod = fs.add(units.Product("Cooled Bottoms", reference="F-301"))

    # Valve stations. The reflux and steam control valves sit between hand
    # isolation valves, which is what a P&ID draws where a PFD draws one valve.
    xv = fs.add(units.Valve("XV-301", variant="solenoid",
                            description="Feed Trip Valve"))
    meter = fs.add(units.Fitting("FE-313", variant="rotameter",
                                 description="Feed Flow Element"))
    cv3011 = fs.add(units.Valve("CV-301-1", variant="control",
                                description="Overhead Pressure Control Valve"))
    hv303a = fs.add(units.Valve("HV-303A", description="Reflux Isolation Valve"))
    cv303 = fs.add(units.Valve("CV-303", variant="control",
                               description="Reflux Control Valve"))
    hv303b = fs.add(units.Valve("HV-303B", description="Reflux Isolation Valve"))
    cv305 = fs.add(units.Valve("CV-305", variant="control",
                               description="Distillate Control Valve"))
    cv306 = fs.add(units.Valve("CV-306", variant="control",
                               description="Bottoms Control Valve"))
    nrv306 = fs.add(units.Valve("NRV-306", variant="check",
                                description="Bottoms Non-Return Valve"))
    hv308a = fs.add(units.Valve("HV-308A", description="Steam Isolation Valve"))
    cv308 = fs.add(units.Valve("CV-308", variant="control",
                               description="Steam Control Valve"))
    hv308b = fs.add(units.Valve("HV-308B", description="Steam Isolation Valve"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: a port sits at a fixed fraction of its
    # symbol's box, so matching those fractions is what makes a run straight.
    col.pin(x=470, y=300)                   # feed y+130, reflux y+35, boilup y+175

    # Feed spine at y = 430, the tower's feed nozzle. The trip valve is flipped
    # top-to-bottom so its solenoid faces the interlock square underneath it.
    fb_feed.pin(x=150, y=405)               # flag tip y + 25
    xv.pin(x=250, y=415.3, mirrored="y")    # ports y + 14.7 once flipped
    meter.pin(x=350, y=415)                 # ports y + 15

    # Overhead spine at y = 140, clear above the tower and the condenser.
    cv3011.pin(x=640, y=125)                # ports y + 15
    cond.pin(x=880, y=180)                  # hot_in x+0.75w, hot_out x+0.25w
    cws_cond.pin(x=150, y=175)              # tube-side supply, tip y + 25
    cwr_cond.pin(x=1480, y=175)

    # Drum hung so its top inlet (20/91.5 along the shell) sits under the
    # condenser's drain, which makes that run a straight drop.
    drum_x = 912.5 - (20 / 91.5) * 130
    drum.pin(x=drum_x, y=270)
    drum_draw_x = drum_x + (68 / 91.5) * 130
    split.pin(x=drum_draw_x - 20, y=350, orientation=90)   # inlet up, outlets down

    # Reflux spine at y = 440, running right to left, so its station is
    # mirrored and every valve takes flow on its east face.
    hv303a.pin(x=880, y=425, mirrored=True)
    cv303.pin(x=760, y=425, mirrored=True)
    hv303b.pin(x=650, y=425, mirrored=True)

    cv305.pin(x=1090, y=430)
    ae_prod.pin(x=1480, y=420)

    # Reboiler off the tower sump; steam spine at y = 614.1, its shell inlet.
    reb.pin(x=700, y=580)
    steam.pin(x=150, y=589.1)
    hv308a.pin(x=240, y=599.1)
    cv308.pin(x=330, y=599.1)
    hv308b.pin(x=420, y=599.1)
    condensate.pin(x=1480, y=577.7)

    # Bottoms over the weir, cooled and sent off the sheet. The bottoms valve
    # is flipped so its operator faces the controller standing below it.
    cv306.pin(x=900, y=645, mirrored="y")
    nrv306.pin(x=1000, y=644.5)             # ports y + 15.5
    cooler.pin(x=1100, y=720)
    cws_cool.pin(x=150, y=715)
    cwr_cool.pin(x=1480, y=715)
    bottoms_prod.pin(x=1480, y=780)

    # --- Process lines ---------------------------------------------------
    fs.connect(fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200,
               spec="160-SS")
    fs.connect(xv.outlet, meter.inlet)
    fs.connect(meter.outlet, col.feed)

    # A line that carries a balloon is routed by hand with via(). An attached
    # instrument hangs off the *routed* path, so a line the router is free to
    # re-bend carries its instrumentation somewhere else with it.
    vapour = fs.connect(col.distillate, cv3011.inlet, service="AE", sequence=302,
                        size=300, spec="80-SS").via([(520, 140)])
    fs.connect(cv3011.outlet, cond.hot_in).via([(977.5, 140)])
    fs.connect(cond.hot_out, drum.inlet, service="AE", sequence=304, size=150,
               spec="80-SS")
    fs.connect(cws_cond.outlet, cond.cold_in, service="CWS", sequence=311, size=150,
               spec="150-CS")
    cw_return = fs.connect(cond.cold_out, cwr_cond.inlet, service="CWR",
                           sequence=312, size=150,
                           spec="150-CS").via([(1200, 200)])

    fs.connect(drum.outlet, split.inlet, service="AE", sequence=309, size=100,
               spec="80-SS")
    # The left-hand outlet takes the reflux and the right-hand one the
    # distillate, so the two lines leave the tee without crossing.
    fs.connect(split.out_2, hv303a.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")
    metered_reflux = fs.connect(hv303a.outlet, cv303.inlet).via([(844.5, 440)])
    fs.connect(cv303.outlet, hv303b.inlet)
    fs.connect(hv303b.outlet, col.reflux_in, tear_hint=True)
    fs.connect(split.out_1, cv305.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")
    fs.connect(cv305.outlet, ae_prod.inlet)

    sump = fs.connect(col.bottoms, reb.cold_in, service="FB", sequence=307,
                      size=250, spec="160-SS").via([(520, 655), (770.1, 655)])
    boilup = fs.connect(reb.cold_out, col.boilup_in, service="FB", sequence=310,
                        size=300, spec="160-SS",
                        tear_hint=True).via([(797.9, 535), (595, 535), (595, 475)])
    fs.connect(steam.outlet, hv308a.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(hv308a.outlet, cv308.inlet)
    fs.connect(cv308.outlet, hv308b.inlet)
    fs.connect(hv308b.outlet, reb.hot_in)
    fs.connect(reb.hot_out, condensate.inlet, service="HPR", sequence=317, size=80,
               spec="300-CS")

    fs.connect(reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100,
               spec="160-SS")
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.hot_in).via([(1197.5, 660)])
    fs.connect(cooler.hot_out, bottoms_prod.inlet, service="FB", sequence=314,
               size=100, spec="160-SS").via([(1132.5, 805)])
    fs.connect(cws_cool.outlet, cooler.cold_in, service="CWS", sequence=315, size=100,
               spec="150-CS")
    fs.connect(cooler.cold_out, cwr_cool.inlet, service="CWR", sequence=316, size=100,
               spec="150-CS")

    # --- Feed trip and local indication ----------------------------------
    # The square is the trip logic rather than a device, so it is drawn at each
    # place the trip acts and carries the same tag every time.
    fs.add_instrument("I", 2, on=xv, at="S", offset=26, variant="logic")
    fs.add_instrument("FI", 314, on=meter, at="S", offset=48)
    fs.add_instrument("PI", 315, on=col, at="W", offset=52)
    fs.add_instrument("TI", 325, on=cw_return, at=0.3, offset=55)

    # --- Loop 301: tower overhead pressure -------------------------------
    pt301 = fs.add_instrument("PT", 301, on=vapour, at=0.75, offset=95)
    # Stood directly over the valve it drives: the output then leaves the
    # bottom of the balloon and drops straight onto the actuator.
    pic301 = fs.add_instrument("PIC", 301, on=pt301, at="E", offset=72.5,
                               variant="panel")
    pic301.nozzle("sig_out", "S")
    pah = fs.add_instrument("PAH", 301, on=pic301, at="E", offset=46)
    pal = fs.add_instrument("PAL", 301, on=pah, at="E", offset=46)
    fs.add_instrument("I", 1, on=pal, at="E", offset=40, variant="logic")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, cv3011.actuator, kind="pneumatic")

    # --- Loops 302/303: tower top temperature cascaded onto reflux flow ---
    tt302 = fs.add_instrument("TT", 302, on=vapour, at=0.2, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", 302, on=tt302, at="E", offset=78, variant="panel")
    tic302.nozzle("sig_out", "S")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    fs.add_instrument("FE", 303, on=metered_reflux, at=0.5, offset=0)
    ft303 = fs.add_instrument("FT", 303, on=metered_reflux, at=0.5, offset=95,
                              angle=-90)
    fic303 = fs.add_instrument("FIC", 303, on=ft303, at="W", offset=90, variant="panel")
    fic303.nozzle("sig_out", "S")
    # The measurement lands on the flow controller's pv and the temperature
    # controller sets it: a cascade sets a setpoint, it does not stroke a valve.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    # --- Loop 304: reflux drum level on the distillate valve --------------
    lt304 = fs.add_instrument("LT", 304, on=drum, at="E", offset=60)
    lic304 = fs.add_instrument("LIC", 304, on=lt304, at="E", offset=66, variant="panel")
    lic304.nozzle("sig_out", "S")
    lah = fs.add_instrument("LAH", 304, on=lic304, at="E", offset=46)
    fs.add_instrument("LAL", 304, on=lah, at="E", offset=46)
    fs.add_instrument("I", 1, on=lic304, at="N", offset=40, variant="logic")
    fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.connect(lic304.sig_out, cv305.actuator, kind="pneumatic")

    # --- Loop 307: reboiler return temperature on the steam valve ---------
    tt307 = fs.add_instrument("TT", 307, on=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", 307, on=tt307, at="W", offset=96,
                               variant="panel")
    tic307.nozzle("sig_out", "S")
    fs.add_instrument("I", 1, on=tic307, at="W", offset=40, variant="logic")
    fs.add_instrument("TI", 321, on=boilup, at=0.05, offset=70, angle=-90)
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")
    fs.connect(tic307.sig_out, cv308.actuator, kind="pneumatic")

    # --- Loop 306: kettle level on the bottoms draw -----------------------
    lt306 = fs.add_instrument("LT", 306, on=reb, at="S", offset=68)
    lic306 = fs.add_instrument("LIC", 306, on=lt306, at="E", offset=56, variant="panel")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("I", 1, on=lt306, at="W", offset=44, variant="logic")
    fs.connect(lt306.sig_out, lic306.sig_in, kind="electric")
    fs.connect(lic306.sig_out, cv306.actuator, kind="pneumatic")

    # --- Sheet furniture -------------------------------------------------
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        # Stated rather than left blank, so the sheet renders the same today as
        # it did at issue.
        date="30/10/25",
        drawn_by="AA", checked_by="RG", approved_by="HVL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # The equipment list is written out rather than generated, so the rows keep
    # the order the issued sheet schedules them in.
    fs.add_annotation(Annotation(
        title="EQUIPMENT LIST",
        rows=[("D-301", "Reflux Drum"),
              ("T-301", "Beer Column"),
              ("HX-301", "Beer Bottoms Cooler"),
              ("C-301", "Overhead Condenser"),
              ("RB-301", "U-tube Kettle Reboiler")],
        align="top-right",
    ))
    fs.add_annotation(notes([
        "Sampling Point",
        "Electromagnetic Flow Meter",
        "Reflux Drum Startup Fill Point",
        "Vent",
        "Distillation Tower Flush Line",
    ], align="bottom-left"))
    fs.add_annotation(legend({
        "SS": "Stainless Steel 316L",
        "CS": "Carbon Steel A106-B",
        "AE": "Azeotropic Ethanol",
        "FB": "Fermentation Broth",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
        "HPSSH": "High Pressure Steam Supply Header",
        "HPSRH": "High Pressure Steam Return Header",
    }, align="top-left"))

    fs.render(out("ethanol_pid.svg"), page_size="A3", border="zone")
    print("Generated ethanol_pid.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()

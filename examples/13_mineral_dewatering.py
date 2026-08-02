"""
Example 13: Mineral Concentrate Dewatering A400, a solids-handling PFD

The first sheet in the gallery that is not a fluids plant. A flotation
concentrate arrives as a dilute slurry and leaves as a dry, magnetics-free
powder, and everything between those two flags is a solid-liquid or a
solid-gas separation: a thickener, a vacuum belt filter, a rotary dryer, the
cyclone that takes the dried product back out of the gas that dried it, and
the scrubber that cleans what is left before it reaches the stack. Crushing,
grinding and flotation are upstream of the concentrate flag and off this
sheet.

**Drawn as a PFD**, at ISO 15519-2 §4.2's earliest issue: an equipment list, a
stream table sectioned into a "Mass Fraction" block, a utilities summary and an
arrowhead on every process line, with no instrument balloon, signal line or
valve anywhere on it. ``professional_examples/PFD_301.pdf`` and ``PFD_302.pdf``
are the models on disk.

**Nothing is turned.** ISO 15519-1 §11.4.2 names the cyclone separator, symbol
X 2618, as one of the drawings gravity fixes the attitude of. Seven of the
symbols here carry ``gravity_fixed=True`` in the registry and would be refused
if they were.

**Sized to the drawing, not to a page**, as ``03`` and ``08`` are rather than
the fixed-A3 sheets: twenty-four streams side by side is a wider table than A3
takes beside a utilities summary. ``page_size="A2"`` draws the same sheet on
real paper.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, devices, units
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import port_offset

# --- Stream property table -------------------------------------------------
# Rows render in first-seen key order, so every stream below carries the same
# keys in the same order and an empty value renders as "-". The numbers are an
# illustrative balance that closes on total flow, not a simulation.
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bara)", "Total Flow (t/h)", "Solids (% w/w)",
    "Water", "Concentrate", "Tramp Metal", "Flocculant", "Air / Flue Gas",
    "Fuel Gas",
)

PROPERTIES = {
    "S-401": ("28", "1.4", "224.0", "28.0", "0.720", "0.2800", "2.2E-05", "",
              "", ""),
    "S-402": ("20", "3.0", "0.630", "", "1.000", "", "", "", "", ""),
    "S-403": ("20", "1.0", "0.002", "100.0", "", "", "", "1.000", "", ""),
    "S-404": ("20", "1.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "",
              ""),
    "S-405": ("20", "2.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "",
              ""),
    "S-406": ("28", "1.2", "224.63", "27.9", "0.721", "0.2792", "2.2E-05",
              "8.9E-06", "", ""),
    "S-407": ("28", "1.0", "120.1", "0.01", "1.000", "1.0E-04", "", "", "",
              ""),
    "S-408": ("28", "1.2", "104.5", "60.0", "0.400", "0.5998", "4.8E-05",
              "1.9E-05", "", ""),
    "S-409": ("28", "2.5", "104.5", "60.0", "0.400", "0.5998", "4.8E-05",
              "1.9E-05", "", ""),
    "S-410": ("28", "1.0", "35.6", "0.10", "0.999", "1.0E-03", "", "5.6E-05",
              "", ""),
    "S-411": ("28", "1.0", "68.9", "91.0", "0.090", "0.9099", "7.3E-05", "",
              "", ""),
    "S-412": ("15", "1.0", "30.5", "", "", "", "", "", "1.000", ""),
    "S-413": ("15", "2.0", "0.43", "", "", "", "", "", "", "1.000"),
    "S-414": ("650", "0.99", "30.93", "", "0.031", "", "", "", "0.969", ""),
    # Temperature deliberately blank, which renders as "-": the two inlets
    # either side of this column are what a dryer datasheet quotes.
    "S-415": ("", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "",
              "0.300", ""),
    "S-416": ("115", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "",
              "0.300", ""),
    "S-417": ("115", "0.97", "37.03", "0.35", "0.187", "3.5E-03", "", "",
              "0.809", ""),
    "S-418": ("28", "3.0", "41.5", "", "1.000", "", "", "", "", ""),
    "S-419": ("62", "0.96", "78.53", "0.17", "0.616", "1.7E-03", "", "",
              "0.382", ""),
    "S-420": ("62", "1.0", "35.08", "", "0.146", "trace", "", "", "0.854",
              ""),
    "S-421": ("62", "1.0", "43.45", "0.30", "0.997", "3.0E-03", "", "", "",
              ""),
    "S-422": ("110", "1.0", "62.80", "99.5", "0.005", "0.9949", "8.0E-05", "",
              "", ""),
    "S-423": ("110", "1.0", "62.79", "99.5", "0.005", "0.995", "", "", "",
              ""),
    "S-424": ("110", "1.0", "0.005", "100.0", "", "", "1.000", "", "", ""),
}


def main():
    fs = Flowsheet("Mineral Concentrate Dewatering A400")

    # --- Flocculant make-up ----------------------------------------------
    water = fs.add(units.Feed("Raw Water", reference="PCD-402"))
    # Not in ``document._MAJOR_EQUIPMENT``, so it spends no row of the
    # equipment list, like the tees and reducers below.
    funnel = fs.add(units.Funnel("FN-401",
                                 description="Flocculant Charging Funnel"))
    charge = fs.add(units.Tee(branch="inlet"))
    # The stirrer this tank has is not drawn: ``Tank`` has no agitated variant,
    # and ``Reactor``, which draws one, is the wrong symbol for a reagent tank.
    tank = fs.add(units.Tank("TK-401", variant="conical_bottom",
                             description="Flocculant Make-up Tank"))
    # Both its connections are drawn on the crown of the head, which is what
    # shapes the piping around it in the placement block below.
    dose = fs.add(devices.PeristalticPump(
        "P-402", description="Flocculant Dosing Pump"))

    # --- Thickening -------------------------------------------------------
    concentrate = fs.add(units.Feed("Flotation Concentrate",
                                    reference="PFD-302"))
    floc = fs.add(units.Tee(branch="inlet"))
    # ``overflow`` is the high draw off the launder wall and ``underflow`` the
    # low one out of the apex, which is what the stencil draws.
    thickener = fs.add(devices.GravitySeparator(
        "TH-401", description="Concentrate Thickener"))
    overflow = fs.add(units.Product("Recovered Water", reference="PCD-402"))

    # --- Filtration -------------------------------------------------------
    underflow_pump = fs.add(devices.ScrewPump(
        "P-401", description="Thickener Underflow Pump"))
    # ``large_end="outlet"`` is what turns the second one into an expander;
    # neither carries a row in the equipment list.
    suction_red = fs.add(units.Reducer("RD-401", variant="eccentric",
                                       description="P-401 Suction Reducer"))
    disch_red = fs.add(units.Reducer("RD-402", variant="concentric",
                                     large_end="outlet",
                                     description="P-401 Discharge Expander"))
    # Left as a variant: no class in ``pandid.devices`` covers the liquid belt
    # filter. ``DustCollector`` has a ``belt`` variant, but it aliases to
    # ``gas_belt`` -- a different symbol, and a gas casing.
    #
    # The vacuum package is bought with the filter and drawn on the vendor's
    # sheet, so only the cake and the filtrate cross this one.
    belt_filter = fs.add(units.Filter("FL-401", variant="belt", width=60,
                                      height=110,
                                      description="Concentrate Belt Filter"))
    # A Tee is drawn as nothing at all and carries no tag. This one splits;
    # the four ``branch="inlet"`` tees elsewhere on the sheet combine, and are
    # drawn identically, since a tee does not know which way its branch runs.
    cake_tee = fs.add(units.Tee())
    filtrate = fs.add(units.Product("Filtrate", reference="PCD-402"))
    # Cake is dropped onto a belt, not piped into it, so the tail nozzle comes
    # off the top face rather than off the end.
    conveyor = fs.add(units.Conveyor("CV-401", length=150,
                                     description="Filter Cake Conveyor"))
    conveyor.nozzle("feed", "N")

    # --- Drying -----------------------------------------------------------
    air = fs.add(units.Feed("Ambient Air"))
    gas = fs.add(units.Feed("Natural Gas", reference="PCD-403"))
    # ``Furnace`` and not ``Heater``: the difference between the two classes is
    # the ``fuel`` nozzle, and the fuel line is why this item is here.
    heater = fs.add(units.Furnace("FH-401", description="Dryer Air Heater"))
    # The dryer's feed breeching is bought and tagged with the dryer, so it is
    # a tee rather than an item of its own.
    breeching = fs.add(units.Tee(branch="inlet"))
    # **Two nozzles where the plant has four.** A rotary dryer has a solids
    # chute and a gas inlet at the feed hood and the same pair at the
    # discharge; ``units.Dryer`` declares only ``feed`` and ``product``, so
    # each pair shares one connection. Firing co-current is what makes that
    # pairing the right one. It costs the drawing S-416, which carries the
    # whole product in the gas where a real drum's carries only entrained
    # fines. A ``Dryer`` with gas nozzles of its own is the fix, and this
    # sheet wants redrawing around them when it has them.
    dryer = fs.add(units.Dryer("DR-401",
                               description="Concentrate Rotary Dryer"))

    # --- Product recovery and dust capture --------------------------------
    # Neither draw is named for which one is wanted, so here the product is
    # the ``underflow`` and the gas still to be cleaned is the ``overflow``.
    cyclone = fs.add(devices.Cyclone(
        "CY-401", description="Product Recovery Cyclone"))
    scrub_water = fs.add(units.Feed("Scrubbing Water", reference="PCD-402"))
    scrub_tee = fs.add(units.Tee(branch="inlet"))
    # The water ties in on the duct upstream rather than on the body, so the
    # tee above carries it and the vessel takes one feed.
    scrubber = fs.add(devices.Scrubber(
        "SC-401", description="Dryer Exhaust Scrubber"))
    effluent = fs.add(units.Product("Scrubber Effluent", reference="PCD-402"))
    # Induced draught, so the fan is last and FH-401's air inlet is a plain
    # flag rather than a second machine.
    fan = fs.add(units.Blower("BL-401", description="Dryer Exhaust Fan"))
    # A Vent draws real piping rather than an off-page flag. Like the funnel
    # and the reducers it is a line item and is scheduled nowhere.
    stack = fs.add(units.Vent("VE-401", variant="exhaust_head", width=45,
                              height=36,
                              description="Dryer Exhaust Head"))

    # The stencil draws the reject leaving the apex rather than lifted off the
    # top, which is a suspended magnet drawn upside down. Read ``underflow`` as
    # the reject leg, which is what the low draw of every mechanical separator
    # in the registry is.
    #
    # variant= stated rather than defaulted: MagneticSeparator draws both the
    # permanent and the electromagnetic body, and this sheet means the former.
    magnet = fs.add(devices.MagneticSeparator(
        "MS-401", variant="permanent_magnet",
        description="Product Magnetic Separator"))
    product = fs.add(units.Product("Dry Concentrate", reference="PFD-402"))
    tramp = fs.add(units.Product("Tramp Metal"))

    # --- Placement --------------------------------------------------------
    # Positioned by nozzle, not by corner: a port sits at a fixed fraction of
    # its symbol's box. A tee is a 12-unit square with a port on the middle of
    # each face it uses, so half its width is the offset from a junction to
    # the corner it is pinned by.
    tee_w = 12.0
    feed_y = 140.0                      # the concentrate feed line
    water_y = 230.0                     # the make-up water line, below it
    dose_x = 336.0                      # the flocculant riser

    concentrate.pin(port="outlet", x=90, y=feed_y)
    water.pin(port="outlet", x=90, y=water_y)

    # The powder drops into the fill line, so the funnel stands over the tee
    # with its stem on the branch's centreline.
    charge.pin(mirrored="y").pin(port="inlet", x=130, y=water_y)
    funnel.pin(port="outlet", x=charge.pin_.x + tee_w / 2, y=water_y - 20)

    tank.pin(port="inlet", x=200, y=260)
    # Both the pump's connections are on its crown, so the discharge riser has
    # to clear the tank on its way to the dosing point. That is what puts the
    # pump east of the shell rather than under it.
    dose.pin(port="discharge", x=dose_x, y=430)

    floc.pin(port="branch", x=dose_x, y=feed_y + tee_w / 2)
    thickener.pin(port="feed", x=380, y=feed_y)
    overflow.pin(port="inlet", x=520, y=feed_y)     # dead level off the launder

    # The eccentric reducer's outlet sits 2.4 units above its inlet, which is
    # where the .4 in the via() coordinate below comes from.
    suction_y = 330.0
    underflow_pump.pin(port="suction", x=520.7, y=suction_y)
    # Both reducers stand a spool clear of the pump, and the gap is the label's
    # rather than the piping's: a reducer's tag plate is three times the width
    # of the fitting, so hard against the casing it takes a bite out of P-401
    # and trips the halo invariants. Each is set at the middle of the one clear
    # window it has.
    suction_red.pin(port="outlet", x=478, y=suction_y)
    disch_red.pin(port="inlet", x=624, y=suction_y)
    belt_filter.pin(port="inlet", x=670, y=suction_y)

    cake_tee.pin(port="inlet", x=740, y=suction_y)
    # Set west of FH-401's tag rather than under the dryer. The burner's plate
    # is written above its box and is wider than the box is, so a flag any
    # further east has that plate through its own outline; the gas riser into
    # the burner's underside rules out writing the tag below it instead.
    filtrate.pin(port="inlet", x=770, y=560)

    # The belt runs under the cake leg, so the cake drops onto its tail rather
    # than being piped into its end, and throws off into the breeching.
    belt_y, dryer_y = 480.0, 490.0
    conveyor.pin(port="feed", x=cake_tee.pin_.x + tee_w + 38, y=belt_y)
    breeching.pin(port="inlet", x=950, y=dryer_y)
    dryer.pin(port="feed", x=1000, y=dryer_y)

    # The burner sits at grade under the feed end. Its fuel arrives from below,
    # which is the only face the stencil's fuel nozzle offers.
    heater.pin(port="inlet", x=860, y=654.5)
    air.pin(port="outlet", x=790, y=654.5)   # clear of the burner wall
    gas.pin(port="outlet", x=750, y=740)
    hot_gas_x = breeching.pin_.x + tee_w / 2

    cyclone.pin(port="feed", x=1180, y=322)
    # Above the gas riser rather than beside it: the scrub-water line crosses
    # the duct's line of travel, and the only place on this sheet where it can
    # do that without crossing the duct itself is over the top of it.
    scrub_tee.pin(mirrored="y").pin(port="inlet", x=1255, y=132)
    scrub_water.pin(port="outlet", x=1180, y=85)
    scrubber.pin(port="feed", x=1300, y=132)
    effluent.pin(port="inlet", x=1400, y=280)
    fan.pin(port="suction", x=1440, y=132)
    stack.pin(port="inlet", x=fan.pin_.x + port_offset(fan, "discharge")[0],
              y=60)

    magnet.pin(port="feed", x=1300, y=532)
    product.pin(port="inlet", x=1430, y=532)
    tramp.pin(port="inlet", x=1430, y=680)

    # --- Connections ------------------------------------------------------
    # Declared in stream-number order, which is the order the table reads. A
    # number is drawn once, on the first segment declared, so a service that
    # runs through more than one item starts with the run the number belongs
    # on. Every tee here ends a number, unlike ``10``'s reflux tee, because
    # each of the five changes what the stream downstream of it is.
    fs.connect(concentrate.outlet, floc.inlet, name="S-401")

    fs.connect(water.outlet, charge.inlet, name="S-402")
    fs.connect(funnel.outlet, charge.branch, name="S-403")
    fs.connect(charge.outlet, tank.inlet, name="S-404")

    fs.connect(tank.outlet, dose.suction, name="S-405")
    fs.connect(dose.discharge, floc.branch, name="S-405")
    fs.connect(floc.outlet, thickener.feed, name="S-406")

    fs.connect(thickener.overflow, overflow.inlet, name="S-407")

    # Straight down out of the cone. Left to itself the router steps the riser
    # 34 units east on its way past the thickener's skirt, and it lands in the
    # only clear window RD-401's tag has.
    fs.connect(thickener.underflow, suction_red.inlet, name="S-408").via(
        [(420, 332.4)])
    fs.connect(suction_red.outlet, underflow_pump.suction, name="S-408")

    fs.connect(underflow_pump.discharge, disch_red.inlet, name="S-409")
    fs.connect(disch_red.outlet, belt_filter.inlet, name="S-409")
    fs.connect(belt_filter.outlet, cake_tee.inlet, name="S-409")

    fs.connect(cake_tee.branch, filtrate.inlet, name="S-410")

    fs.connect(cake_tee.outlet, conveyor.feed, name="S-411")
    fs.connect(conveyor.discharge, breeching.inlet, name="S-411")

    fs.connect(air.outlet, heater.inlet, name="S-412")
    fs.connect(gas.outlet, heater.fuel, name="S-413").via([(900, 740)])
    # Pinned by hand: left to itself the router takes the burner duct the long
    # way round the dryer. Up the east side of the breeching and straight into
    # the branch is the run the plant has.
    fs.connect(heater.outlet, breeching.branch, name="S-414").via(
        [(hot_gas_x, 654.5 + 25)])

    fs.connect(breeching.outlet, dryer.feed, name="S-415")
    fs.connect(dryer.product, cyclone.feed, name="S-416")

    fs.connect(cyclone.overflow, scrub_tee.inlet, name="S-417")
    fs.connect(scrub_water.outlet, scrub_tee.branch, name="S-418")
    fs.connect(scrub_tee.outlet, scrubber.feed, name="S-419")

    fs.connect(scrubber.vapor, fan.suction, name="S-420")
    fs.connect(fan.discharge, stack.inlet, name="S-420")
    fs.connect(scrubber.liquid, effluent.inlet, name="S-421")

    fs.connect(cyclone.underflow, magnet.feed, name="S-422")
    fs.connect(magnet.overflow, product.inlet, name="S-423")
    fs.connect(magnet.underflow, tramp.inlet, name="S-424")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip ------------------------------------------------------
    # The date is stated rather than left blank, so the sheet renders the same
    # today as it did at issue.
    fs.title_block = TitleBlock(
        title="Mineral Dewatering",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="12/09/25",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "22/08/25", "Issued for internal review", "AA"),
            Revision("B", "05/09/25", "Dryer exhaust scrubber added", "AA"),
            Revision("C", "12/09/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture --------------------------------------------------
    # include= is named row by row in process order rather than in declaration
    # order. The five tees, the funnel, the two reducers and the exhaust head
    # are left out: all nine are bulk items bought by the line.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "TK-401", "P-402", "TH-401", "P-401", "FL-401", "CV-401", "FH-401",
        "DR-401", "CY-401", "MS-401", "SC-401", "BL-401",
    ]))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=[
            ["Natural Gas", "FH-401", "5972", "0.119", "15 C", "-"],
            ["Ambient Air", "FH-401", "-", "8.47", "15 C", "650 C"],
            ["Raw Water", "TK-401", "-", "0.175", "20 C", "-"],
            ["Scrubbing Water", "SC-401", "-1638", "11.53", "28 C", "62 C"],
        ],
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))

    fs.render(out("mineral_dewatering.svg"), border="zone",
              show_stream_table=True)
    print("Generated mineral_dewatering.svg")


if __name__ == "__main__":
    main()

"""
Example 12: Mineral Concentrate Dewatering A400, a solids-handling PFD

A flotation concentrate arrives as a dilute slurry and leaves as a dry,
magnetics-free powder through a thickener, a belt filter, a rotary
dryer, a product cyclone, a scrubber and a magnetic separator. The
sheet is sized to the drawing; ``page_size="A2"`` puts it on paper.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Blower,
    Conveyor,
    Cyclone,
    Dryer,
    Feed,
    Filter,
    Flowsheet,
    Funnel,
    Furnace,
    GravitySeparator,
    MagneticSeparator,
    PeristalticPump,
    Product,
    Reducer,
    ScrewPump,
    Scrubber,
    Tank,
    Tee,
    Vent,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import pinned_x

# --- Stream property table --------------------------------------------
# An empty value renders as "-".
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
    "S-415": ("115", "0.98", "40.17", "8.1", "0.1728", "0.0811", "", "",
              "0.7461", ""),
    "S-416": ("110", "1.0", "59.66", "99.6", "0.0037", "0.9962", "8.4E-05", "",
              "", ""),
    "S-417": ("115", "0.97", "37.03", "0.35", "0.1871", "3.5E-03", "", "",
              "0.8094", ""),
    "S-418": ("28", "3.0", "41.5", "", "1.000", "", "", "", "", ""),
    "S-419": ("62", "0.96", "78.53", "0.17", "0.616", "1.7E-03", "", "",
              "0.382", ""),
    "S-420": ("62", "1.0", "35.08", "", "0.146", "trace", "", "", "0.854",
              ""),
    "S-421": ("62", "1.0", "43.45", "0.30", "0.997", "3.0E-03", "", "", "",
              ""),
    "S-422": ("110", "1.0", "3.14", "99.6", "0.0037", "0.9963", "", "", "", ""),
    "S-423": ("110", "1.0", "62.80", "99.6", "0.0037", "0.9962", "8.0E-05", "",
              "", ""),
    "S-424": ("110", "1.0", "62.79", "99.6", "0.0037", "0.9963", "", "", "",
              ""),
    "S-425": ("110", "1.0", "0.005", "100.0", "", "", "1.000", "", "", ""),
}


def main():
    fs = Flowsheet("Mineral Concentrate Dewatering A400")

    # --- Flocculant make-up -------------------------------------------
    water = fs.add(Feed("Raw Water", reference="PCD-402"))
    funnel = fs.add(Funnel("FN-401",
                           description="Flocculant Charging Funnel"))
    charge = fs.add(Tee(branch="inlet"))
    tank = fs.add(Tank("TK-401", variant="conical_bottom",
                       description="Flocculant Make-up Tank"))
    dose = fs.add(PeristalticPump(
        "P-402", description="Flocculant Dosing Pump"))

    # --- Thickening ---------------------------------------------------
    concentrate = fs.add(Feed("Flotation Concentrate",
                              reference="PFD-302"))
    floc = fs.add(Tee(branch="inlet"))
    # ``overflow`` leaves the launder wall, ``underflow`` the apex.
    thickener = fs.add(GravitySeparator(
        "TH-401", description="Concentrate Thickener"))
    overflow = fs.add(Product("Recovered Water", reference="PCD-402"))

    # --- Filtration ---------------------------------------------------
    underflow_pump = fs.add(ScrewPump(
        "P-401", description="Thickener Underflow Pump"))
    # ``large_end="outlet"`` turns the second one into an expander.
    suction_red = fs.add(Reducer("RD-401", variant="eccentric",
                                 description="P-401 Suction Reducer"))
    disch_red = fs.add(Reducer("RD-402", variant="concentric",
                               large_end="outlet",
                               description="P-401 Discharge Expander"))
    # Filtrate leaves ``outlet``, cake leaves ``cake``; a cake-forming
    # variant's nozzles are reached through ``port()``.
    belt_filter = fs.add(Filter("FL-401", variant="belt", width=60,
                                height=110,
                                description="Concentrate Belt Filter"))
    filtrate = fs.add(Product("Filtrate", reference="PCD-402"))
    # Cake drops onto the belt, so its feed is on the top face.
    conveyor = fs.add(Conveyor("CV-401", length=150,
                               description="Filter Cake Conveyor"))
    conveyor.nozzle("feed", "N")

    # --- Drying -------------------------------------------------------
    air = fs.add(Feed("Ambient Air"))
    gas = fs.add(Feed("Natural Gas", reference="PCD-403"))
    # A ``Furnace`` has a ``fuel`` nozzle.
    heater = fs.add(Furnace("FH-401", description="Dryer Air Heater"))
    dryer = fs.add(Dryer("DR-401",
                         description="Concentrate Rotary Dryer"))

    # --- Product recovery and dust capture ----------------------------
    # Product leaves the ``underflow``, gas the ``overflow``.
    cyclone = fs.add(Cyclone(
        "CY-401", description="Product Recovery Cyclone"))
    scrub_water = fs.add(Feed("Scrubbing Water", reference="PCD-402"))
    # The scrubbing water tees into the duct upstream of the scrubber.
    scrub_tee = fs.add(Tee(branch="inlet"))
    scrubber = fs.add(Scrubber(
        "SC-401", description="Dryer Exhaust Scrubber"))
    effluent = fs.add(Product("Scrubber Effluent", reference="PCD-402"))
    # Induced draught: the fan is last.
    fan = fs.add(Blower("BL-401", description="Dryer Exhaust Fan"))
    stack = fs.add(Vent("VE-401", variant="exhaust_head", width=45,
                        height=36,
                        description="Dryer Exhaust Head"))

    # Tramp metal leaves the ``underflow``.
    magnet = fs.add(MagneticSeparator(
        "MS-401", variant="permanent_magnet",
        description="Product Magnetic Separator"))
    product = fs.add(Product("Dry Concentrate", reference="PFD-402"))
    tramp = fs.add(Product("Tramp Metal"))
    # The cyclone's dust rejoins the dryer's product ahead of the magnet.
    fines = fs.add(Tee(branch="inlet"))

    # --- Placement ----------------------------------------------------
    tee_w = 12.0                        # a tee is a 12-unit square
    feed_y = 140.0                      # the concentrate feed line
    water_y = 230.0                     # the make-up water line, below it
    dose_x = 336.0                      # the flocculant riser

    concentrate.pin(port="outlet", x=90, y=feed_y)
    water.pin(port="outlet", x=90, y=water_y)

    # The funnel stands over the tee's branch.
    charge.pin(mirrored="y").pin(port="inlet", x=130, y=water_y)
    funnel.pin(port="outlet", x=pinned_x(charge) + tee_w / 2, y=water_y - 20)

    tank.pin(port="inlet", x=200, y=260)
    # East of the tank, so the discharge riser clears it.
    dose.pin(port="discharge", x=dose_x, y=430)

    floc.pin(port="branch", x=dose_x, y=feed_y + tee_w / 2)
    thickener.pin(port="feed", x=380, y=feed_y)
    overflow.pin(port="inlet", x=520, y=feed_y)     # dead level off the launder

    # The eccentric reducer's outlet sits 2.4 units above its inlet.
    suction_y = 330.0
    underflow_pump.pin(port="suction", x=520.7, y=suction_y)
    # Reducers a spool clear of the pump, to leave room for their tags.
    suction_red.pin(port="outlet", x=478, y=suction_y)
    disch_red.pin(port="inlet", x=624, y=suction_y)
    belt_filter.pin(port="inlet", x=670, y=suction_y)
    cake_x = pinned_x(belt_filter, "cake")

    filtrate.pin(port="inlet", x=800, y=suction_y)

    # The belt runs under the filter and discharges into the dryer.
    belt_y, dryer_y = 480.0, 490.0
    conveyor.pin(port="feed", x=cake_x, y=belt_y)
    dryer.pin(port="feed", x=1000, y=dryer_y)

    # The burner sits at grade under the dryer's feed end.
    heater.pin(port="inlet", x=860, y=654.5)
    air.pin(port="outlet", x=790, y=654.5)   # clear of the burner wall
    gas.pin(port="outlet", x=750, y=740)

    cyclone.pin(port="feed", x=1180, y=322)
    scrub_tee.pin(mirrored="y").pin(port="inlet", x=1255, y=132)
    scrub_water.pin(port="outlet", x=1180, y=85)
    scrubber.pin(port="feed", x=1300, y=132)
    effluent.pin(port="inlet", x=1400, y=280)
    fan.pin(port="suction", x=1440, y=132)
    stack.pin(port="inlet", x=pinned_x(fan, "discharge"),
              y=60)

    magnet.pin(port="feed", x=1300, y=532)
    fines.pin(mirrored="y").pin(port="branch", x=pinned_x(cyclone, "underflow"),
                               y=532 - tee_w / 2)
    product.pin(port="inlet", x=1430, y=532)
    tramp.pin(port="inlet", x=1430, y=680)

    # --- Connections --------------------------------------------------
    # A number is drawn once, on the first segment declared with it.
    fs.connect(concentrate.outlet, floc.inlet, name="S-401")

    fs.connect(water.outlet, charge.inlet, name="S-402")
    fs.connect(funnel.outlet, charge.branch, name="S-403")
    fs.connect(charge.outlet, tank.inlet, name="S-404")

    fs.connect(tank.outlet, dose.suction, name="S-405")
    fs.connect(dose.discharge, floc.branch, name="S-405")
    fs.connect(floc.outlet, thickener.feed, name="S-406")

    fs.connect(thickener.overflow, overflow.inlet, name="S-407")

    # Straight down out of the cone, clear of RD-401's tag.
    fs.connect(thickener.underflow, suction_red.inlet, name="S-408").via(
        [(420, 332.4)])
    fs.connect(suction_red.outlet, underflow_pump.suction, name="S-408")

    fs.connect(underflow_pump.discharge, disch_red.inlet, name="S-409")
    fs.connect(disch_red.outlet, belt_filter.inlet, name="S-409")

    fs.connect(belt_filter.port("outlet"), filtrate.inlet, name="S-410")

    fs.connect(belt_filter.port("cake"), conveyor.feed, name="S-411")
    fs.connect(conveyor.discharge, dryer.feed, name="S-411")

    fs.connect(air.outlet, heater.inlet, name="S-412")
    fs.connect(gas.outlet, heater.fuel, name="S-413").via([(900, 740)])
    fs.connect(heater.outlet, dryer.heating_in, name="S-414")

    fs.connect(dryer.vent, cyclone.feed, name="S-415")
    fs.connect(dryer.product, fines.inlet, name="S-416")

    fs.connect(cyclone.overflow, scrub_tee.inlet, name="S-417")
    fs.connect(scrub_water.outlet, scrub_tee.branch, name="S-418")
    fs.connect(scrub_tee.outlet, scrubber.feed, name="S-419")

    fs.connect(scrubber.vapor, fan.suction, name="S-420")
    fs.connect(fan.discharge, stack.inlet, name="S-420")
    fs.connect(scrubber.liquid, effluent.inlet, name="S-421")

    fs.connect(cyclone.underflow, fines.branch, name="S-422")
    fs.connect(fines.outlet, magnet.feed, name="S-423")
    fs.connect(magnet.overflow, product.inlet, name="S-424")
    fs.connect(magnet.underflow, tramp.inlet, name="S-425")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
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

    # --- Sheet furniture ----------------------------------------------
    # Leave the tees, funnel, reducers and exhaust head off the list.
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

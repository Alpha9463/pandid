"""
Example 6: Distillation column with a real reflux and boilup loop

Uses the column's return nozzles, ``reflux_in`` and ``boilup_in``, so the two
internal loops close on the tower itself:

- overhead: distillate -> condenser -> reflux drum -> pump -> split, one leg
  back to ``col.reflux_in``,
- bottoms: -> reboiler -> split, one leg back to ``col.boilup_in``.

Without those nozzles a reflux loop has to be modelled as a recycle to some
upstream unit, which drags the whole overhead system back across the sheet.
"""

from pfd import Flowsheet, units


def main():
    fs = Flowsheet("Column Overhead System")

    feed = fs.add(units.Feed("Feed", reference="PFD-100"))
    col = fs.add(units.Column("T-701", description="Main Fractionator"))

    # Overhead system
    cond = fs.add(units.HeatExchanger("E-701", description="Overhead Condenser"))
    drum = fs.add(units.Separator("V-701", description="Reflux Drum"))
    vent = fs.add(units.Product("Vent Gas", reference="PFD-900"))
    rpump = fs.add(units.Pump("P-701", description="Reflux Pump"))
    rsplit = fs.add(units.Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(units.Product("Distillate", reference="PFD-200"))

    # Bottoms system
    reb = fs.add(units.HeatExchanger("E-702", description="Reboiler"))
    bsplit = fs.add(units.Splitter("SP-702", n_outlets=2, description="Boilup Split"))
    bot = fs.add(units.Product("Bottoms", reference="PFD-300"))

    fs.connect(feed.outlet, col.feed)

    fs.connect(col.distillate, cond.hot_in)
    fs.connect(cond.hot_out, drum.feed)
    fs.connect(drum.vapor, vent.inlet)
    fs.connect(drum.liquid, rpump.suction)
    fs.connect(rpump.discharge, rsplit.inlet)
    fs.connect(rsplit.out_1, dist.inlet)
    fs.connect(rsplit.out_2, col.reflux_in, tear_hint=True)      # reflux return

    fs.connect(col.bottoms, reb.cold_in)
    fs.connect(reb.cold_out, bsplit.inlet)
    fs.connect(bsplit.out_1, bot.inlet)
    fs.connect(bsplit.out_2, col.boilup_in, tear_hint=True)      # boilup return

    fs.render("column_reflux.svg")
    print("Generated column_reflux.svg")


if __name__ == "__main__":
    main()

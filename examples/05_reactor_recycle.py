"""
Example 5: Reactor loop with recycle and purge (fully automatic)

No pins, no via() waypoints — the engine lays out and routes everything from the
topology alone. It exercises:

- automatic recycle detection (the splitter -> mixer edge is torn and routed as
  a recycle lane across the sheet),
- a purge split (one splitter outlet leaves as product, the other recycles),
- spine straightening: the main process line (feed -> mixer -> compressor ->
  cooler -> separator -> splitter) is aligned onto one straight horizontal axis.
"""

from pfd import Flowsheet, units


def main():
    fs = Flowsheet("Reactor Recycle Loop")

    feed = fs.add(units.Feed("Syngas Feed"))
    mix = fs.add(units.Mixer("M-201", n_inlets=2))
    comp = fs.add(units.Compressor("K-201"))
    rx = fs.add(units.Reactor("R-201"))
    cool = fs.add(units.Cooler("E-201"))
    sep = fs.add(units.Separator("V-201"))
    split = fs.add(units.Splitter("SP-201", n_outlets=2))
    prod = fs.add(units.Product("Liquid Product"))
    purge = fs.add(units.Product("Purge Gas"))

    fs.connect(feed.outlet, mix.in_2)
    fs.connect(mix.outlet, comp.suction)
    fs.connect(comp.discharge, rx.feed)
    fs.connect(rx.outlet, cool.inlet)
    fs.connect(cool.outlet, sep.feed)
    fs.connect(sep.liquid, prod.inlet)
    fs.connect(sep.vapor, split.inlet)
    fs.connect(split.out_2, purge.inlet)
    fs.connect(split.out_1, mix.in_1, tear_hint=True)   # recycle back to the mixer

    fs.render("reactor_recycle.svg")
    print("Generated reactor_recycle.svg")


if __name__ == "__main__":
    main()

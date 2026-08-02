"""
Example 5: Reactor loop with recycle and purge (fully automatic)

No pins and no via() waypoints: the engine lays out and routes everything from
the topology alone. It exercises:

- automatic recycle detection (the splitter -> mixer edge is torn and routed as
  a recycle lane across the sheet),
- a purge split (one splitter outlet leaves as product, the other recycles),
- spine straightening: the main process line (feed -> mixer -> compressor ->
  cooler -> separator -> splitter) is aligned onto one straight horizontal axis.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Compressor, Cooler, Feed, Flowsheet, Mixer, Product, Reactor, Separator, Splitter


def main():
    fs = Flowsheet("Reactor Recycle Loop")

    feed = fs.add(Feed("Syngas Feed"))
    mix = fs.add(Mixer("M-201", n_inlets=2))
    comp = fs.add(Compressor("K-201"))
    rx = fs.add(Reactor("R-201"))
    cool = fs.add(Cooler("E-201"))
    sep = fs.add(Separator("V-201"))
    split = fs.add(Splitter("SP-201", n_outlets=2))
    prod = fs.add(Product("Liquid Product"))
    purge = fs.add(Product("Purge Gas"))

    fs.connect(feed.outlet, mix.in_2)
    fs.connect(mix.outlet, comp.suction)
    fs.connect(comp.discharge, rx.feed)
    fs.connect(rx.outlet, cool.inlet)
    fs.connect(cool.outlet, sep.feed)
    fs.connect(sep.liquid, prod.inlet)
    fs.connect(sep.vapor, split.inlet)
    fs.connect(split.out_2, purge.inlet)
    fs.connect(split.out_1, mix.in_1, draw_as_recycle=True)

    fs.render(out("reactor_recycle.svg"))
    print("Generated reactor_recycle.svg")


if __name__ == "__main__":
    main()

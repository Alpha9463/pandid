from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Compressor, Feed, Flowsheet, HeatExchanger, Mixer, Product, Reactor, Separator

fs = Flowsheet("Ammonia Loop Auto")
feed = fs.add(Feed("Natural Gas"))
mix = fs.add(Mixer("M-101"))
reformer = fs.add(Reactor("R-101"))
hx = fs.add(HeatExchanger("E-101"))
sep = fs.add(Separator("V-101"))
comp = fs.add(Compressor("K-101"))
prod = fs.add(Product("Ammonia"))

fs.connect(feed.outlet, mix.in_2)
fs.connect(mix.outlet, reformer.feed)
fs.connect(reformer.outlet, hx.shell_in)
fs.connect(hx.shell_out, sep.feed)
fs.connect(sep.vapor, comp.suction)
fs.connect(comp.discharge, mix.in_1)
fs.connect(sep.liquid, prod.inlet)

fs.render(out("ammonia_auto.svg"))
print("ammonia_auto.svg generated successfully.")

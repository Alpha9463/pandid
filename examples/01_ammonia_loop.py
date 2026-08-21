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

feed_in = fs.connect(feed.outlet, mix.in_2)
fs.connect(mix.outlet, reformer.feed)
fs.connect(reformer.outlet, hx.shell_in)
fs.connect(hx.shell_out, sep.feed)
fs.connect(sep.vapor, comp.suction)
fs.connect(comp.discharge, mix.in_1)
product_out = fs.connect(sep.liquid, prod.inlet)

# The separator's vapour all returns to the mixer, so nothing but this
# feed and this product crosses the sheet edge, and with nothing else
# leaving the loop, one balances the other.
feed_in.properties = {"Flow (kg/h)": "5000"}
product_out.properties = {"Flow (kg/h)": "5000"}

fs.render(out("ammonia_auto.svg"), show_stream_table=True)
print("ammonia_auto.svg generated successfully.")

from pfd import Flowsheet, units

fs = Flowsheet("Ammonia Loop Auto")
feed = fs.add(units.Feed("Natural Gas"))
mix = fs.add(units.Mixer("M-101"))
reformer = fs.add(units.Reactor("R-101"))
hx = fs.add(units.HeatExchanger("E-101"))
sep = fs.add(units.Separator("V-101"))
comp = fs.add(units.Compressor("K-101"))
prod = fs.add(units.Product("Ammonia"))

# Connect
fs.connect(feed.outlet, mix.in_2)
fs.connect(mix.outlet, reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out, sep.feed)
fs.connect(sep.vapor, comp.suction)
fs.connect(comp.discharge, mix.in_1)
fs.connect(sep.liquid, prod.inlet)

fs.render("ammonia_auto.svg")
print("ammonia_auto.svg generated successfully.")

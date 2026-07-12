from pfd import Flowsheet, units as U

fs = Flowsheet("Ammonia Loop Auto")
feed = fs.add(U.Feed("Natural Gas"))
mix = fs.add(U.Mixer("M-101"))
reformer = fs.add(U.Reactor("R-101"))
hx = fs.add(U.HeatExchanger("E-101"))
sep = fs.add(U.Separator("V-101"))
comp = fs.add(U.Compressor("K-101"))
prod = fs.add(U.Product("Ammonia"))

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

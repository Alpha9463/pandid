from pfd import Flowsheet, units as U

fs = Flowsheet("Ammonia Loop")
feed = fs.add(U.Feed("Natural Gas")).pin(x=50, y=50)
mix = fs.add(U.Mixer("M-101")).pin(x=150, y=50)
reformer = fs.add(U.Reactor("R-101")).pin(x=250, y=35)
hx = fs.add(U.HeatExchanger("E-101")).pin(x=400, y=50)
sep = fs.add(U.Separator("V-101")).pin(x=550, y=50)
comp = fs.add(U.Compressor("K-101")).pin(x=400, y=200)
prod = fs.add(U.Product("Ammonia")).pin(x=700, y=75)

# Connect
fs.connect(feed.outlet, mix.in_1)
fs.connect(mix.outlet, reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out, sep.feed)
fs.connect(sep.vapor, comp.suction).via([(575, 25), (575, 225)])
fs.connect(comp.discharge, mix.in_2).via([(150, 225)])
fs.connect(sep.liquid, prod.inlet)

# Render SVG
fs.render("ammonia_demo.svg")
print("Rendered ammonia_demo.svg successfully.")

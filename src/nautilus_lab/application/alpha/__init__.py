"""Alpha screening: cross-sectional signal research on a coin x time panel (A1).

The screen is a measuring instrument, not a strategy. It answers whether a candidate
signal ranks coins by their *residual* forward return, net of market beta and funding.
It also asks whether the edge survives turnover costs and whether it beats a
permutation null. Everything here runs on float64 numpy arrays, because a screen
evaluates thousands of signal x horizon pairs. Strategies that later trade a survivor
go back to the Decimal domain and the Nautilus engine.
"""

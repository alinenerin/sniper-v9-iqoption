"""Canonical isolated market universes. No provider discovery expands these lists."""
REAL_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
OTC_SYMBOLS = [f"{symbol}-OTC" for symbol in REAL_SYMBOLS]
REAL_ALLOWLIST = REAL_SYMBOLS
OTC_ALLOWLIST = OTC_SYMBOLS

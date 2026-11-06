import unittest
from market_universes import OTC_SYMBOLS, REAL_SYMBOLS
from scripts.symbol_selection import resolve_requested_symbols, resolve_symbols

class SymbolSelectionTests(unittest.TestCase):
    def test_all_available_returns_available_allowlisted_snapshot_keys(self):
        self.assertEqual(resolve_requested_symbols("ALL_AVAILABLE", ["EURUSD", "GBPUSD", "EURUSD-OTC"]), ["EURUSD", "GBPUSD", "EURUSD-OTC"])
    def test_explicit_symbols_add_corresponding_otc_even_if_not_in_snapshot(self):
        self.assertEqual(resolve_requested_symbols("EURUSD GBPUSD", ["EURUSD", "GBPUSD"], include_otc=True), ["EURUSD", "GBPUSD", "EURUSD-OTC", "GBPUSD-OTC"])
    def test_finbert_base_pairs_excludes_otc(self):
        self.assertEqual(resolve_requested_symbols("ALL_AVAILABLE", ["EURUSD", "EURUSD-OTC", "GBPUSD"], base_pairs_only=True), ["EURUSD", "GBPUSD"])
    def test_disallowed_asset_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_SYMBOLS"):
            resolve_requested_symbols("BTCUSD", REAL_SYMBOLS)
    def test_otc_selector_stays_isolated(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE", otc_only=True), OTC_SYMBOLS)
    def test_wildcard_cannot_mix_with_explicit_symbol(self):
        with self.assertRaisesRegex(ValueError, "WILDCARD_CANNOT_BE_MIXED"):
            resolve_requested_symbols("ALL_AVAILABLE EURUSD", REAL_SYMBOLS)

if __name__ == "__main__":
    unittest.main()

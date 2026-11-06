import unittest
from scripts.symbol_selection import resolve_requested_symbols
from symbol_selection import resolve_symbols
from market_universes import OTC_SYMBOLS, REAL_SYMBOLS

class ResolveSymbolsTests(unittest.TestCase):
    def test_all_available_expands_to_snapshot_keys_not_literal_sentinel(self):
        self.assertEqual(resolve_requested_symbols("ALL_AVAILABLE", ["EURUSD", "GBPUSD", "EURUSD-OTC"]), ["EURUSD", "GBPUSD"])
        self.assertNotIn("ALL_AVAILABLE", resolve_symbols("ALL_AVAILABLE"))
    def test_explicit_symbols_deduplicate_otc_and_base_pairs(self):
        self.assertEqual(resolve_requested_symbols("EURUSD GBPUSD", ["EURUSD", "GBPUSD", "EURUSD-OTC", "GBPUSD-OTC"], include_otc=True), ["EURUSD", "GBPUSD", "EURUSD-OTC", "GBPUSD-OTC"])
        self.assertEqual(resolve_requested_symbols("ALL_AVAILABLE", ["EURUSD", "EURUSD-OTC", "GBPUSD"], base_pairs_only=True), ["EURUSD", "GBPUSD"])
    def test_wildcard_cannot_be_mixed_with_symbols(self):
        with self.assertRaisesRegex(ValueError, "WILDCARD_CANNOT_BE_MIXED"):
            resolve_requested_symbols("ALL_AVAILABLE EURUSD", REAL_SYMBOLS)
    def test_unknown_assets_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_SYMBOLS"):
            resolve_requested_symbols("BTCUSD", REAL_SYMBOLS)
    def test_otc_only_resolves_otc_allowlist(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE", otc_only=True), OTC_SYMBOLS)
    def test_include_otc_universe_is_still_allowlisted(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE", include_otc=True), REAL_SYMBOLS+OTC_SYMBOLS)
if __name__ == '__main__': unittest.main()

import unittest

from market_universes import OTC_SYMBOLS, REAL_SYMBOLS
from scripts.symbol_selection import resolve_symbols


class ResolveSymbolsTests(unittest.TestCase):
    def test_all_available_means_only_authorized_real_fx_pairs(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE"), REAL_SYMBOLS)

    def test_all_available_otc_only_uses_only_otc_allowlist(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE", otc_only=True), OTC_SYMBOLS)

    def test_all_available_with_otc_inclusion_is_two_separate_allowlists(self):
        self.assertEqual(resolve_symbols("ALL_AVAILABLE", include_otc=True), REAL_SYMBOLS + OTC_SYMBOLS)

    def test_explicit_symbols_normalize_and_deduplicate(self):
        self.assertEqual(resolve_symbols("eur/usd EURUSD"), ["EURUSD"])

    def test_unknown_assets_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_SYMBOLS"):
            resolve_symbols("BTCUSD")

    def test_wildcard_mixed_with_symbols_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "WILDCARD_CANNOT_BE_MIXED"):
            resolve_symbols("ALL_AVAILABLE EURUSD")

    def test_otc_only_rejects_non_otc_explicit_symbol(self):
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_SYMBOLS"):
            resolve_symbols("EURUSD", otc_only=True)


if __name__ == "__main__":
    unittest.main()

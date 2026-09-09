from pathlib import Path

forex = Path('FOREX_SUPREME_FINAL_V16.py').read_text()
binary = Path('executor_v16_supreme.py').read_text()
operational = Path('engines/binary/operational.py').read_text()
checks = {
    'forex_entrypoint_has_no_order_primitive': 'buy(' not in forex,
    'forex_execution_stub_is_blocked': 'EXECUCAO_BLOQUEADA_NO_ENTRYPOINT_ANALYSIS_ONLY' in forex,
    'binary_has_real_m5_request': 'timeframe=300' in binary,
    'binary_policy_consumes_m5_data': 'm5_candles' in operational,
    'binary_payout_fail_closed': 'PAYOUT_UNAVAILABLE' in operational,
    'binary_default_read_only': 'execution_allowed": False' in binary,
    'shared_ai_both_entrypoints': 'from shared_ai.consultation import SharedAI' in binary and 'from shared_ai.consultation import SharedAI' in forex,
}
for name, ok in checks.items():
    print(('OK   ' if ok else 'FAIL ')+name)
if not all(checks.values()): raise SystemExit(1)

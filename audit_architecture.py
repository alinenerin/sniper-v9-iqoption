from pathlib import Path

checks = {
    'binary_no_forex_import': 'FOREX_SUPREME_FINAL_V16' not in Path('executor_v16_supreme.py').read_text(),
    'forex_no_binary_import': 'executor_v16_supreme' not in Path('FOREX_SUPREME_FINAL_V16.py').read_text(),
    'binary_shared_ai': 'from shared_ai.consultation import SharedAI' in Path('executor_v16_supreme.py').read_text(),
    'forex_shared_ai': 'from shared_ai.consultation import SharedAI' in Path('FOREX_SUPREME_FINAL_V16.py').read_text(),
    'binary_no_buy': 'buy(' not in Path('executor_v16_supreme.py').read_text(),
    'operational_no_buy': 'buy(' not in Path('engines/binary/operational.py').read_text(),
}
for name, passed in checks.items():
    print(('OK   ' if passed else 'FAIL ')+name)
if not all(checks.values()):
    raise SystemExit(1)

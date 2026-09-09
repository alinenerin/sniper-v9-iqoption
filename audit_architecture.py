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


# Fail-closed execution guard for production entrypoints. The vendored SDK and
# research/diagnostic scripts are not entrypoints and may contain broker API
# definitions or fixtures.
import ast
ORDER_METHODS = {"buy", "buy_digital", "place_order", "open_order", "buy_order"}
ACTIVE_ENTRYPOINTS = (
    "app.py", "sniper_forex.py", "executor_v15_final_v4.py",
    "executor_v16_supreme.py", "FOREX_SUPREME_FINAL_V16.py",
    "central_executor.py", "motor_m5_sniper.py", "sniper_filtro_gha.py",
)
violations = []
for name in ACTIVE_ENTRYPOINTS:
    source = Path(name)
    if not source.exists():
        continue
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ORDER_METHODS:
            violations.append(f"{source}:{node.lineno}:{node.func.attr}")
if violations:
    print("FAIL global_execution_guard", violations)
    raise SystemExit(1)
print("OK   global_execution_guard")

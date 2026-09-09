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


# Global fail-closed execution guard. Legacy files are quarantined and are not
# imported by production entrypoints; active source must not call broker order APIs.
import ast
ORDER_METHODS = {"buy", "buy_digital", "place_order", "open_order", "buy_order"}
violations = []
for source in Path(".").rglob("*.py"):
    if any(part in {".git", ".venv", "__pycache__", "rejected", "tests"} for part in source.parts):
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

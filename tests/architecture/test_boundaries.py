from pathlib import Path


def test_engines_do_not_cross_import():
    binary = Path("executor_v16_supreme.py").read_text()
    forex = Path("FOREX_SUPREME_FINAL_V16.py").read_text()
    assert "FOREX_SUPREME_FINAL_V16" not in binary
    assert "executor_v16_supreme" not in forex


def test_shared_ai_is_used_by_both_engines():
    assert "from shared_ai.consultation import SharedAI" in Path("executor_v16_supreme.py").read_text()
    assert "from shared_ai.consultation import SharedAI" in Path("FOREX_SUPREME_FINAL_V16.py").read_text()


def test_binary_is_read_only_by_default():
    binary = Path("executor_v16_supreme.py").read_text()
    operational = Path("engines/binary/operational.py").read_text()
    assert '"execution_allowed": False' in binary
    assert "buy(" not in binary
    assert "buy(" not in operational


def test_binary_contract_has_operational_controls():
    text = Path("engines/binary/operational.py").read_text()
    for marker in ("PAYOUT_UNAVAILABLE", "PAYOUT_BELOW_MINIMUM", "M5_CONFIRMADO", "COOLDOWN_SECONDS"):
        assert marker in text

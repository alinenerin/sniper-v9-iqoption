from tradingagents_committee import TradingAgentsShadowCommittee


def test_committee_never_approves_and_preserves_vetoes():
    report = {
        "mode": "read_only",
        "forex": {"analyses": [{
            "symbol": "EURUSD",
            "market": "forex",
            "status": "completed",
            "approved": True,
            "direction": "CALL",
            "components": {
                "darts": {"status": "inference_ok"},
                "smc": {"status": "inference_ok"},
                "finbert": {"status": "blocked"},
            },
        }]},
        "binary": {"analyses": []},
    }
    result = TradingAgentsShadowCommittee().evaluate_report(report)
    item = result["analyses"][0]
    assert item["verdict"] == "WATCHLIST"
    assert item["execution_allowed"] is False
    assert item["read_only"] is True
    assert item["score_unchanged"] is True
    assert "finbert" in item["blocked_components"]


def test_otc_isolates_news_components():
    item = {
        "symbol": "EURUSD-OTC",
        "market": "otc",
        "status": "completed",
        "approved": False,
        "direction": "CALL",
        "components": {
            "darts": {"status": "inference_ok"},
            "finbert": {"status": "inference_ok"},
            "news_api": {"status": "inference_ok"},
        },
    }
    result = TradingAgentsShadowCommittee().evaluate(item)
    assert result["verdict"] == "REJECTED"
    assert result["otc_news_isolated"] is True

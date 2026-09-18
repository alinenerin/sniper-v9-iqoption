from core.direction_aggregator import aggregate_direction


def ok(direction):
    return {"status": "inference_ok", "direction": direction}


def test_three_of_four_confirms_without_candle_vote():
    result = aggregate_direction(smc=ok("CALL"), timesfm=ok("UP"),
                                 xgboost={"status": "inference_ok", "probability_up": .8},
                                 m5_engine=ok("PUT"), engine_direction="PUT")
    assert result["direction_confirmed"] == "CALL"
    assert result["source"] == "consensus"
    assert result["vote_counts"] == {"CALL": 3, "PUT": 1}
    assert all(result["vote_reasons"].values())


def test_three_of_four_normalizes_native_smc_timesfm_and_m5_outputs():
    result = aggregate_direction(
        smc={"status": "ok", "bos": 1, "fvg": 1},
        timesfm={"status": "completed", "forecast": {"direcao": "UP"}},
        xgboost={"status": "inference_ok", "probability_up": .8},
        m5_engine={"status": "executed", "result": {"signal": "CALL"}},
    )
    assert result["direction_confirmed"] == "CALL"
    assert result["valid_votes"] == 4
    assert result["votes"] == {"smc": "CALL", "timesfm": "CALL", "xgboost": "CALL", "m5_engine": "CALL"}
    assert "SMC_BOS_CALL" in result["vote_reasons"]["smc"]


def test_native_directional_engine_is_not_replaced_by_last_candle():
    result = aggregate_direction(smc=ok("CALL"), timesfm=ok("UP"),
                                 xgboost={"status": "inference_ok", "probability_up": .8},
                                 m5_engine={"status": "ok", "direction_calculated": "PUT"})
    assert result["direction_confirmed"] == "CALL"
    assert result["votes"]["m5_engine"] == "PUT"


def test_tie_is_neutral():
    result = aggregate_direction(smc=ok("CALL"), timesfm=ok("DOWN"),
                                 xgboost={"status": "inference_ok", "probability_up": .8},
                                 m5_engine=ok("PUT"))
    assert result["direction_confirmed"] == "NEUTRAL"
    assert result["source"] == "none"
    assert "DIVERGENCE" in result["direction_reason"]


def test_legitimate_absence_stays_neutral_with_reasons():
    result = aggregate_direction(smc={"status": "inference_ok"},
                                 timesfm={"status": "inference_ok"},
                                 xgboost={"status": "inference_ok"},
                                 m5_engine={"status": "blocked"},
                                 engine_direction=None)
    assert result["direction_confirmed"] == "NEUTRAL"
    assert result["valid_votes"] == 0
    assert "NO_EXPLICIT_DIRECTION" in result["vote_reasons"]["smc"]
    assert "STATUS_BLOCKED" in result["vote_reasons"]["m5_engine"]

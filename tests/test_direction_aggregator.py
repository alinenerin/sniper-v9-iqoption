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


def test_tie_is_neutral():
    result = aggregate_direction(smc=ok("CALL"), timesfm=ok("DOWN"),
                                 xgboost={"status": "inference_ok", "probability_up": .8},
                                 m5_engine=ok("PUT"))
    assert result["direction_confirmed"] == "NEUTRAL"
    assert result["source"] == "none"
    assert "DIVERGENCE" in result["direction_reason"]


def test_last_candle_or_status_alone_never_confirms():
    result = aggregate_direction(smc={"status": "inference_ok"},
                                 timesfm={"status": "inference_ok"},
                                 xgboost={"status": "inference_ok"},
                                 m5_engine={"status": "blocked"},
                                 engine_direction=None)
    assert result["direction_confirmed"] == "NEUTRAL"
    assert result["valid_votes"] == 0

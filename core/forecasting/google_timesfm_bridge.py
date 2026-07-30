"""
TIMESFM BRIDGE V3.0 - NATIVO GHA
TimesFM 2.5 200M rodando em CPU (~1.5GB RAM)
GitHub Actions: 7GB RAM disponivel
"""

import os
import json
import numpy as np
from datetime import datetime


class TimesFMBridge:
    """Bridge V3.0 com TimesFM 2.5 200M rodando real no GHA."""

    def __init__(self, json_path="previsao_timesfm.json"):
        self.json_path = json_path
        self.alt_path = "timesfm_previsao.json"
        self.model = None
        self.max_age = 7200
        self._model_loaded = False

    def _load_model(self):
        """Carrega o TimesFM 2.5 200M real do HuggingFace."""
        if self._model_loaded:
            return True
        try:
            import timesfm
            print("[TIMESFM] Carregando 2.5 200M...")
            self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                "google/timesfm-2.5-200m-pytorch"
            )
            self._model_loaded = True
            print("[TIMESFM] Modelo carregado!")
            return True
        except ImportError:
            print("[TIMESFM] timesfm nao instalado")
            return False
        except Exception as e:
            print(f"[TIMESFM] Erro: {e}")
            return False

    def _load_cached(self):
        """Tenta carregar previsao salva em JSON."""
        for path in [self.json_path, self.alt_path]:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        data = json.load(f)
                    if "timestamp" in data:
                        t = datetime.strptime(
                            data["timestamp"], "%Y-%m-%d %H:%M:%S"
                        )
                        idade = (datetime.now() - t).total_seconds()
                        if idade <= self.max_age:
                            return data
                except:
                    pass
        return None

    def _fallback(self, prices=None):
        """Fallback com regressao linear."""
        direction = "NEUTRAL"
        confidence = 0.5
        if prices is not None and len(prices) > 10:
            p = prices[-10:]
            slope = (p[-1] - p[0]) / len(p)
            if slope > 0.0001:
                direction = "UP"
                confidence = min(0.5 + abs(slope) * 100, 0.85)
            elif slope < -0.0001:
                direction = "DOWN"
                confidence = min(0.5 + abs(slope) * 100, 0.85)
        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "source": "FALLBACK",
        }

    def forecast_next_candle(self, price_history=None):
        """Preve as proximos velas com Time real."""
        cached = self._load_cached()
        if cached is not None:
            return {
                "direction": cached.get("direcao", "NEUTRAL"),
                "confidence": cached.get("confianca", 0.5),
                "source": "TIMESFM_CACHED",
            }

        if price_history is not None and len(price_history) >= 100:
            if self._load_model():
                try:
                    inp = np.array(price_history[-512:], dtype=np.float32)
                    out = self.model.forecast(horizon=4, inputs=[inp])
                    pred = out[0]
                    ult = price_history[-1]
                    var = (pred[-1] - ult) / ult * 100
                    direction = "NEUTRAL"
                    if var > 0.05:
                        direction = "UP"
                    elif var < -0.05:
                        direction = "DOWN"
                    confidence = min(abs(var), 0.99)
                    return {
                        "direction": direction,
                        "confidence": round(confidence, 4),
                        "source": "TIMESFM_REAL",
                    }
                except Exception as e:
                    print(f"[TIMESFM] Erro: {e}")

        return self._fallback(price_history)

    def validate_with_google_brain(self, signal_direction, price_history=None):
        """Voto de Minerva."""
        forecast = self.forecast_next_candle(price_history)
        if forecast["direction"] == "NEUTRAL":
            return True, f"TimesFM NEUTRAL - Sniper decide"
        if signal_direction == "CALL" and forecast["direction"] == "UP":
            return True, f"TimesFM CONFIRMA ({forecast['confidence']*100:.0f}%)"
        if signal_direction == "PUT" and forecast["direction"] == "DOWN":
            return True, f"TimesFM CONFIRMA ({forecast['confidence']*100:.0f}%)"
        return False, f"VETO: TimesFM {forecast['direction']} vs {signal_direction}"


print("TimesFM Bridge V3.0 (GHA Native) carregado. Roda em CPU!")
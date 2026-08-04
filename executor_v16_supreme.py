#!/usr/bin/env python3
"""Binary Quant X V16 Supreme — motor independente de Binárias/OTC.

Este arquivo não importa nem inicia o motor Forex. Ele coleta candles da IQ
Option, consulta o núcleo compartilhado de inteligência e produz análise
somente leitura. Qualquer ordem exige callback explícito e autorização manual.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Any, Dict, Iterable, Optional

PAYOUT_MINIMO = 80
SCORE_MINIMO = 95
TIMEFRAME_SECONDS = 60
EXPIRACAO_MINUTOS = 1
DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP")
DEFAULT_OTC_SYMBOLS = ("EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC", "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BINARY] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("BINARY_V16_SUPREME")


class RailwayGatewayClient:
    """Read-only adapter: GitHub Actions consumes the Railway IQ gateway."""
    def __init__(self, base_url: str, symbols):
        import json, urllib.parse, urllib.request
        self.base_url = base_url.rstrip("/")
        query = urllib.parse.urlencode({"symbols": ",".join(symbols)})
        with urllib.request.urlopen(self.base_url + "/api/market/snapshot_batch?" + query, timeout=180) as r:
            self.batch = json.load(r)
        if not self.batch.get("ok", False):
            raise RuntimeError("Railway gateway returned no market snapshot")
        self.symbols = self.batch.get("symbols", {})
        self.payouts = self.batch.get("payouts", {})

    def get_candles(self, symbol, timeframe, quantity, _end):
        item = self.symbols.get(symbol, {})
        key = {60: "m1", 180: "m3", 300: "m5"}.get(int(timeframe), "m1")
        return item.get(key, {}).get("candles", [])[-int(quantity):]

    def get_all_profit(self):
        result = {}
        for symbol, values in self.payouts.items():
            for market, value in values.items():
                result.setdefault(market, {})[symbol] = {"profit": value}
        return result

    def get_all_open_time(self):
        return {"turbo": {s: {"open": True} for s in self.symbols}}


def _settings():
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "config", "settings.py")
    spec = importlib.util.spec_from_file_location("binary_settings", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _symbols(symbols: Optional[Iterable[str]] = None):
    values = symbols or DEFAULT_SYMBOLS
    return [str(x).replace("/", "").upper().strip() for x in values]


def inicializar_api_blindada(usuario: str = "", senha: str = "", proxy: Optional[str] = None) -> Any:
    """Conecta somente para leitura de candles; não altera saldo nem envia ordem."""
    settings = _settings()
    user = usuario or os.getenv("IQ_USER", settings.IQ_USER)
    password = senha or os.getenv("IQ_PASS", os.getenv("IQ_PASSWORD", settings.IQ_PASS))
    from iqoptionapi.stable_api import IQ_Option

    api = IQ_Option(user, password)
    proxy_host = getattr(settings, "PROXY_HOST", "")
    proxy_port = getattr(settings, "PROXY_PORT", "")
    proxy_user = getattr(settings, "PROXY_USER", "")
    proxy_pass = getattr(settings, "PROXY_PASS", "")
    if proxy or proxy_host:
        host = proxy or proxy_host
        proxy_url = f"http://{proxy_user}:{proxy_pass}@{host}:{proxy_port}"
        api.session.proxies.update({"http": proxy_url, "https": proxy_url})
    ok, reason = api.connect()
    if not ok:
        raise ConnectionError(f"IQ Option não conectou: {reason}")
    # Binárias usa PRACTICE por padrão. Nunca muda para REAL automaticamente.
    api.change_balance(os.getenv("IQ_BALANCE_MODE", "PRACTICE"))
    for symbol in _symbols():
        api.start_candles_stream(symbol, TIMEFRAME_SECONDS, 1)
    logger.info("Conectado para análise binária somente leitura")
    return api


def coletar_candles(api: Any, symbol: str, quantidade: int = 250, timeframe: int = TIMEFRAME_SECONDS):
    import pandas as pd
    candles = api.get_candles(symbol, timeframe, quantidade, time.time())
    if not candles or len(candles) < 50:
        return None
    frame = pd.DataFrame(candles).rename(columns={"max": "high", "min": "low", "from": "timestamp"})
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return None
    if "volume" not in frame.columns:
        frame["volume"] = 0
    return frame


def coletar_candles_m3(api: Any, symbol: str, quantidade: int = 120):
    """Obtém candles nativos de 3 minutos para seleção adaptativa."""
    return coletar_candles(api, symbol, quantidade, timeframe=180)


def coletar_candles_m5(api: Any, symbol: str, quantidade: int = 60):
    """Obtém candles nativos de 5 minutos; não deriva M5 do M1."""
    return coletar_candles(api, symbol, quantidade, timeframe=300)


def analisar_binaria(api: Any, symbol: str) -> Dict[str, Any]:
    """Consulta o núcleo compartilhado; retorno é sinal, nunca ordem."""
    from config.markets.contracts import MarketRequest
    from shared_ai.consultation import SharedAI
    from engines.binary.operational import BinaryPolicy
    frame = coletar_candles(api, symbol)
    if frame is None:
        return {"market": "binary", "symbol": symbol, "veto": True, "reason": "DADOS_INSUFICIENTES", "score": 0, "execution_allowed": False}
    market = "otc" if "-OTC" in symbol.upper() else "binary"
    m1_ai = SharedAI(score_minimum=SCORE_MINIMO).consult(MarketRequest(
        market=market, symbol=symbol, timeframe="M1",
        candles=frame.to_dict("records"), account_mode="PRACTICE",
    ))
    m3_frame = coletar_candles_m3(api, symbol)
    m3_ai = None
    if m3_frame is not None:
        m3_ai = SharedAI(score_minimum=SCORE_MINIMO).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M3",
            candles=m3_frame.to_dict("records"), account_mode="PRACTICE",
        ))
    from engines.binary.timeframe_selector import select_timeframe
    timeframe_decision = select_timeframe(
        frame.to_dict("records"),
        m3_frame.to_dict("records") if m3_frame is not None else [],
        m1_ai, m3_ai, is_otc=(market == "otc"),
    )
    if timeframe_decision["selected"] is None:
        return {"market": market, "symbol": symbol, "veto": True,
                "reason": timeframe_decision["reason"], "timeframe_decision": timeframe_decision,
                "execution_allowed": False}
    selected_ai = m1_ai if timeframe_decision["selected"] == "M1" else m3_ai
    selected_frame = frame if timeframe_decision["selected"] == "M1" else m3_frame
    m5_frame = coletar_candles_m5(api, symbol)
    if m5_frame is None:
        return {"market": market, "symbol": symbol, "veto": True, "reason": "M5_DADOS_INSUFICIENTES", "score": selected_ai.score, "execution_allowed": False}
    result = BinaryPolicy(PAYOUT_MINIMO / 100, SCORE_MINIMO).evaluate(api, symbol, selected_ai, selected_frame.to_dict("records"), m5_frame.to_dict("records"))
    result.update({"timeframe": timeframe_decision["selected"], "timeframe_decision": timeframe_decision,
                   "m1_timeframe": "M1", "m3_timeframe": "M3", "m5_timeframe": "M5", "payout_minimum": PAYOUT_MINIMO,
                   "anomaly_score": selected_ai.anomaly_score,
                   "analysis": selected_ai.components.get("core_analysis", {}),
                   "execution_allowed": False})
    return result


def scan_once(api: Any, symbols: Optional[Iterable[str]] = None):
    results = []
    for symbol in _symbols(symbols):
        try:
            result = analisar_binaria(api, symbol)
            results.append(result)
            logger.info("%s | score=%s | veto=%s | %s", symbol, result["score"], result["veto"], result["reason"])
        except Exception as exc:
            logger.exception("Falha na análise de %s: %s", symbol, exc)
            results.append({"market": "binary", "symbol": symbol, "veto": True, "score": 0, "reason": "ANALYSIS_ERROR"})
    return results


def executa_gatilho_sniper(iq_client: Any, ativo: str, dados_mercado: Dict[str, Any], autorizacao: bool = False) -> str:
    """Único ponto manual; não é chamado pelo loop automático."""
    if autorizacao is not True:
        return "BLOQUEADO: AUTORIZAÇÃO_MANUAL_NECESSÁRIA"
    callback = dados_mercado.get("enviar_ordem_manual")
    if not callable(callback):
        return "BLOQUEADO: EXECUTOR_MANUAL_NÃO_CONFIGURADO"
    return str(callback(ativo, dados_mercado))


def main(once: bool = False, symbols: Optional[Iterable[str]] = None, otc: bool = False, max_runtime: Optional[int] = None):
    selected = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
    if otc:
        selected.extend(DEFAULT_OTC_SYMBOLS)
    if os.getenv("RAILWAY_GATEWAY_URL"):
        api = RailwayGatewayClient(os.getenv("RAILWAY_GATEWAY_URL"), selected)
        logger.info("Railway gateway conectado para análise somente leitura")
    else:
        api = inicializar_api_blindada()
    started = time.time()
    while True:
        scan_once(api, selected)
        if once or (max_runtime is not None and time.time() - started >= max_runtime):
            return
        time.sleep(max(1, TIMEFRAME_SECONDS - int(time.time()) % TIMEFRAME_SECONDS))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor Binárias V16 — análise sem execução automática")
    parser.add_argument("--once", action="store_true", help="executa um ciclo e encerra")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--otc", action="store_true", help="inclui pares OTC")
    parser.add_argument("--max-runtime", type=int, default=None)
    args = parser.parse_args()
    try:
        main(once=args.once, symbols=args.symbols, otc=args.otc, max_runtime=args.max_runtime)
    except KeyboardInterrupt:
        logger.info("Loop binário encerrado manualmente")

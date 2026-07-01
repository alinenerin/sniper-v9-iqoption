#!/usr/bin/env python3
"""
SNIPER V12 — MODO DISPARO ÚNICO
Roda uma varredura completa (FOREX + OTC) e encerra.
Usado pelo GitHub Actions quando a Aline pede sinais.
"""
import sys, os, time, subprocess

subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q",
     "requests", "pytz", "flask", "websocket-client"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import pytz
from datetime import datetime

# Importa funções do app.py (V12)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Injeta variáveis de ambiente nos defaults do app
os.environ.setdefault("TG_TOKEN",  "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
os.environ.setdefault("TG_CHAT",   "5911742397")
os.environ.setdefault("IQ_EMAIL",  "laiane.aline@gmail.com")
os.environ.setdefault("IQ_PASS",   "alineEgui95@")

from app import (
    _conectar_iq, garantir_conexao, tg,
    get_candles, get_payout,
    score_forex, score_otc,
    confirmar_m5, detectar_order_block,
    ff_bloqueado, shadow_bloqueio,
    FOREX_PARES, FOREX_SCORE_MIN, FOREX_PAYOUT_MIN,
    OTC_PARES,   OTC_SCORE_MIN,   OTC_PAYOUT_MIN,
    BRT,
)

def log(msg):
    print(f"[{datetime.now(BRT).strftime('%H:%M:%S')}] {msg}", flush=True)

def varrer_forex(agora):
    log("🔵 Varrendo FOREX...")
    sinais = []
    for par in FOREX_PARES:
        try:
            velas = get_candles(par, n=60, tf=60)
            if not velas or len(velas) < 55:
                log(f"  {par}: sem velas")
                continue
            score, direcao, det = score_forex(velas)
            if score < FOREX_SCORE_MIN or not direcao:
                log(f"  {par}: ❌ score {score} ({det})")
                continue
            payout = get_payout(par)
            if payout < FOREX_PAYOUT_MIN:
                log(f"  {par}: ❌ payout {payout*100:.0f}%")
                continue
            m5_ok, m5_info = confirmar_m5(par, direcao)
            sinais.append({
                "par": par, "direcao": direcao,
                "score": score, "det": det,
                "payout": payout, "m5": m5_info,
                "tipo": "FOREX"
            })
            log(f"  {par}: ✅ {direcao} Score:{score} Payout:{payout*100:.0f}% | {det.get('pts','')}")
        except Exception as e:
            log(f"  {par}: erro — {e}")
    return sinais

def varrer_otc(agora):
    log("🟠 Varrendo OTC...")
    sinais = []
    for par in OTC_PARES:
        try:
            velas = get_candles(par, n=60, tf=60)
            if not velas or len(velas) < 20:
                log(f"  {par}: sem velas")
                continue
            score, direcao, det = score_otc(velas)
            if score < OTC_SCORE_MIN or not direcao:
                log(f"  {par}: ❌ score {score}")
                continue
            payout = get_payout(par)
            if payout < OTC_PAYOUT_MIN:
                log(f"  {par}: ❌ payout {payout*100:.0f}%")
                continue
            sinais.append({
                "par": par, "direcao": direcao,
                "score": score, "det": det,
                "payout": payout,
                "tipo": "OTC"
            })
            log(f"  {par}: ✅ {direcao} Score:{score} Payout:{payout*100:.0f}%")
        except Exception as e:
            log(f"  {par}: erro — {e}")
    return sinais

def enviar_sinais(sinais, agora):
    if not sinais:
        tg("🤖 Sniper V12 — varredura concluída\n⚪ Nenhum sinal aprovado agora.\nFiltragem Triple Confluence não atingida.")
        log("⚪ Nenhum sinal aprovado.")
        return

    # Ordena por score
    sinais.sort(key=lambda x: x["score"], reverse=True)

    min_prox = ((agora.minute // 1) + 1)
    hora_entrada = f"{agora.hour:02d}:{min_prox:02d}" if min_prox < 60 else f"{agora.hour+1:02d}:00"

    linhas = [f"🎯 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n"]
    for s in sinais[:5]:
        emoji = "🔵" if s["tipo"] == "FOREX" else "🟠"
        linhas.append(
            f"{emoji} `{s['par']}` | {s['direcao']} | Score:{s['score']}\n"
            f"   Payout: {s['payout']*100:.0f}% | Entrada: {hora_entrada}"
        )

    mensagem = "\n".join(linhas)
    tg(mensagem)
    log(f"✅ {len(sinais)} sinal(is) enviado(s) pro Telegram!")

def main():
    log("🚀 Sniper V12 — Disparo Único iniciado")
    agora = datetime.now(BRT)
    log(f"⏰ {agora.strftime('%d/%m/%Y %H:%M:%S')} BRT")

    # Conecta IQ
    log("🔌 Conectando na IQ Option...")
    if not garantir_conexao():
        log("❌ Falha na conexão com IQ Option")
        tg("❌ Sniper V12 — falha de conexão com IQ Option")
        sys.exit(1)
    log("✅ IQ Option conectada!")
    time.sleep(2)

    # Checa notícias
    bloq, motivo = ff_bloqueado(agora)
    if bloq:
        log(f"🚫 Bloqueado por notícia: {motivo}")
        tg(f"🚫 Sniper V12 — Bloqueado\n📰 {motivo}")
        sys.exit(0)

    # Varre FOREX + OTC
    sinais_forex = varrer_forex(agora)
    time.sleep(1)
    sinais_otc   = varrer_otc(agora)

    todos = sinais_forex + sinais_otc
    enviar_sinais(todos, agora)
    log("✅ Concluído!")

if __name__ == "__main__":
    main()

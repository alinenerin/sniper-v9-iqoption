#!/usr/bin/env python3
"""
Railway Worker — Sniper M5
Roda o m5_cron_runner.py a cada 30 minutos, alinhado às velas M5.
"""
import os, sys, time, subprocess, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def log(msg):
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)

def proxima_janela():
    """Retorna segundos até próxima janela :00 ou :30."""
    agora = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    minuto = agora.minute
    segundo = agora.second
    if minuto < 30:
        falta = (30 - minuto) * 60 - segundo
    else:
        falta = (60 - minuto) * 60 - segundo
    return max(falta - 60, 10)  # 60s antes da virada = escaneia cedo

log('🚀 Railway Worker M5 iniciado')
log(f'Python: {sys.version}')

while True:
    try:
        agora_brt = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
        log(f'⏰ BRT: {agora_brt.strftime("%H:%M:%S")} — rodando ciclos M5...')
        subprocess.run(
            [sys.executable, '-W', 'ignore', 'm5_cron_runner.py'],
            timeout=600
        )
    except subprocess.TimeoutExpired:
        log('⚠️ Timeout no runner — abortando ciclo')
    except Exception as e:
        log(f'❌ Erro: {e}')

    espera = proxima_janela()
    log(f'😴 Próxima janela em {espera//60}m{espera%60:02d}s...')
    time.sleep(espera)

#!/usr/bin/env python3
"""
SNIPER M5 — Runner para cron a cada 30 minutos.
Roda 2 ciclos M5 consecutivos (vela atual + próxima em ~5min).
Escaneia MERCADO REAL + OTC em cada ciclo.
Envia sinais via Telegram e salva no CSV de assertividade.
"""
import os, sys, time, datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from motor_m5_sniper import (
    gerar_sinais_m5, telegram, salvar_sinal,
    analisar_par_m5,
    PARES_REAL, PARES_OTC, PARES_BLOQUEADOS,
    get_pares_bloqueados_hoje, check_noticias,
)
import concurrent.futures

def log(msg):
    print(f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}')
    with open('m5_loop.log', 'a') as f:
        f.write(f'[{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')

def rodar_ciclo(ciclo_num):
    now_brt = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    hora_brt = now_brt.strftime('%H:%M')
    min_prox = ((now_brt.minute // 5) + 1) * 5
    if min_prox >= 60:
        hora_entrada = (now_brt + datetime.timedelta(hours=1)).strftime('%H:00')
    else:
        hora_entrada = f'{now_brt.hour:02d}:{min_prox:02d}'

    log(f'🚀 Ciclo {ciclo_num} — {hora_brt} BRT | Entrada: {hora_entrada}')

    # Checar notícias
    livre, noticia = check_noticias()
    if not livre:
        log(f'⚪ Bloqueado por notícia: {noticia}')
        return []

    # Atualizar bloqueios dinâmicos
    get_pares_bloqueados_hoje()

    # Montar lista de pares: Real + OTC (sem duplicatas bloqueadas)
    pares_real = [p for p in PARES_REAL if p not in PARES_BLOQUEADOS]
    pares_otc  = [p for p in PARES_OTC  if p not in PARES_BLOQUEADOS]
    todos = pares_real + pares_otc

    log(f'   📡 Escaneando {len(pares_real)} Real + {len(pares_otc)} OTC = {len(todos)} pares')

    # Análise em paralelo — usando analisar_par_m5 com todos os 5 filtros
    sinais = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futuros = {ex.submit(analisar_par_m5, p, True): p for p in todos}
        for f in concurrent.futures.as_completed(futuros, timeout=90):
            try:
                r = f.result()
                if r:
                    sinais.append(r)
            except:
                pass

    if not sinais:
        log('⚪ Nenhum sinal aprovado')
        return []

    # Ordenar: ALTO Markov primeiro, depois score
    sinais.sort(key=lambda x: (x['nivel_mkv'] == 'ALTO', x['score']), reverse=True)
    top = sinais[:5]

    # Salvar no CSV
    for s in top:
        salvar_sinal(s['par'], hora_entrada, s['direction'], s['score'], s['setup'], s['markov'])

    # Montar mensagem Telegram
    real_sinais = [s for s in top if '-OTC' not in s['par']]
    otc_sinais  = [s for s in top if '-OTC' in s['par']]

    msg_lines = [
        f'🎯 SINAIS M5 — {hora_entrada} BRT',
        '─' * 30,
    ]

    if real_sinais:
        msg_lines.append('📈 REAL:')
        for s in real_sinais:
            msg_lines.append(f"  M5;{s['par']};{hora_entrada};{s['direction']}")

    if otc_sinais:
        msg_lines.append('🔵 OTC:')
        for s in otc_sinais:
            msg_lines.append(f"  M5;{s['par']};{hora_entrada};{s['direction']}")

    msg_lines.append('')
    msg_lines.append('📊 Detalhes:')
    for s in top:
        msg_lines.append(
            f"  {s['par']} {s['direction']} "
            f"Score={s['score']} RSI={s['rsi']:.0f} "
            f"[{s['setup']}] {s['markov']}"
        )

    telegram('\n'.join(msg_lines))
    linhas = [f"M5;{s['par']};{hora_entrada};{s['direction']}" for s in top]
    log(f'✅ {len(linhas)} sinal(is) enviado(s): {linhas}')
    return linhas

def segundos_para_prox_vela():
    agora = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    seg_atual = agora.minute * 60 + agora.second
    seg_vela  = (seg_atual // 300 + 1) * 300
    return max(seg_vela - seg_atual - 8, 1)

if __name__ == '__main__':
    # Ciclo 1 — agora
    rodar_ciclo(1)

    # Aguardar próxima vela M5
    espera = segundos_para_prox_vela()
    log(f'⏳ Próxima vela M5 em {espera}s...')
    time.sleep(espera)

    # Ciclo 2
    rodar_ciclo(2)

    log('✅ Runner M5 concluído (2 ciclos — Real + OTC)')

#!/usr/bin/env python3
"""
SNIPER LOOP M5 — Loop automático de geração de sinais em M5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Executa a cada 5 minutos, alinhado com as velas M5.
Sinais enviados via Telegram + salvos no CSV de assertividade.

Uso:
  python3 sniper_loop_m5.py          → rodar loop contínuo
  python3 sniper_loop_m5.py once     → gerar UMA vez agora (teste)
  python3 sniper_loop_m5.py stats    → ver assertividade atual
  python3 sniper_loop_m5.py win PAR HORA   → registrar WIN
  python3 sniper_loop_m5.py loss PAR HORA  → registrar LOSS

Criado: 29/06/2026
"""

import sys, os, time, datetime, json

# Garante que importa do diretório correto
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

from motor_m5_sniper import (
    gerar_sinais_m5, telegram, calcular_assertividade,
    registrar_resultado, HISTORY_FILE
)

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'm5_loop.log')


def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = f'[{ts}] {msg}'
    print(linha)
    with open(LOG_FILE, 'a') as f:
        f.write(linha + '\n')


def segundos_para_prox_vela():
    """Calcula quantos segundos faltam para a abertura da próxima vela M5."""
    agora = datetime.datetime.utcnow() - datetime.timedelta(hours=3)  # BRT
    seg_atual = agora.minute * 60 + agora.second
    seg_vela  = (seg_atual // 300 + 1) * 300  # próximo múltiplo de 300s
    espera    = seg_vela - seg_atual
    # Entrar 10s antes do fechamento para garantir execução a tempo
    return max(espera - 10, 1)


def rodar_uma_vez(modo_teste=False, relaxar_markov=False):
    """Gera sinais M5 agora e envia via Telegram."""
    log('🚀 Gerando sinais M5...')
    linhas, detalhes = gerar_sinais_m5(modo_teste=modo_teste, salvar=True, relaxar_markov=relaxar_markov)

    if linhas is None:
        log(f'⚪ Bloqueado: {detalhes}')
        return

    if not linhas:
        log('⚪ Nenhum sinal aprovado (Triple Confluence não atingida)')
        telegram('⚪ M5 Sniper: nenhum sinal aprovado neste ciclo.')
        return

    # Montar mensagem Telegram — formato padrão
    hora_brt = (datetime.datetime.utcnow() - datetime.timedelta(hours=3)).strftime('%H:%M')
    real_sinais = [d for d in detalhes if '-OTC' not in d['par']]
    otc_sinais  = [d for d in detalhes if '-OTC' in d['par']]

    linhas_tg = [
        f'🎯 SINAIS M5 — {hora_brt} BRT',
        '─' * 30,
    ]
    if real_sinais:
        linhas_tg.append('📈 REAL:')
        for d in real_sinais:
            linhas_tg.append(f"  M5;{d['par']};{hora_brt};{d['direction']}")
    if otc_sinais:
        linhas_tg.append('🔵 OTC:')
        for d in otc_sinais:
            linhas_tg.append(f"  M5;{d['par']};{hora_brt};{d['direction']}")
    linhas_tg.append('')
    linhas_tg.append('📊 Detalhes:')
    for d in detalhes:
        linhas_tg.append(
            f"  {d['par']} {d['direction']} "
            f"Score={d['score']} RSI={d['rsi']:.0f} "
            f"[{d['setup']}] {d['markov']}"
        )
    telegram('\n'.join(linhas_tg))
    log(f'✅ {len(linhas)} sinal(is) enviado(s): {linhas}')


def loop_continuo():
    """Loop principal — roda indefinidamente, alinhado às velas M5."""
    log('🟢 Sniper Loop M5 iniciado')
    telegram('🟢 Sniper M5 ATIVO — monitorando sinais a cada 5 minutos.')

    while True:
        espera = segundos_para_prox_vela()
        log(f'⏳ Próxima vela M5 em {espera}s...')
        time.sleep(espera)

        try:
            rodar_uma_vez(modo_teste=False)
        except Exception as e:
            log(f'❌ Erro no ciclo: {e}')
            telegram(f'❌ Sniper M5: erro no ciclo — {str(e)[:100]}')
            time.sleep(10)


def mostrar_stats():
    stats = calcular_assertividade()
    if not stats:
        print('\n📊 Nenhum resultado registrado ainda.')
        print(f'   Arquivo: {HISTORY_FILE}')
        return

    print(f'\n📊 ASSERTIVIDADE M5')
    print(f'   {"─"*35}')
    print(f'   Total: {stats["total"]} ops  |  WIN: {stats["win"]}  |  LOSS: {stats["loss"]}')
    print(f'   WR GERAL: {stats["wr_geral"]}%')
    print(f'\n   Por par:')
    print(f'   {"PAR":<14} {"WIN":>5} {"LOSS":>5} {"WR":>6}')
    print(f'   {"─"*35}')
    for par, s in sorted(stats['por_par'].items(), key=lambda x: -x[1]['wr']):
        emoji = '🟢' if s['wr'] >= 70 else ('🟡' if s['wr'] >= 55 else '🔴')
        print(f'   {par:<14} {s["win"]:>5} {s["loss"]:>5} {s["wr"]:>5.1f}% {emoji}')


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    args = sys.argv[1:]

    if not args:
        loop_continuo()

    elif args[0] == 'once':
        print('⚡ Gerando sinal M5 AGORA (modo teste)...')
        rodar_uma_vez(modo_teste=True)

    elif args[0] == 'relaxar':
        print('⚡ Gerando sinal M5 AGORA (modo relaxado — Técnico puro, sem exigir Markov)...')
        rodar_uma_vez(modo_teste=True, relaxar_markov=True)

    elif args[0] == 'stats':
        mostrar_stats()

    elif args[0] in ('win', 'loss') and len(args) >= 3:
        par  = args[1].upper()
        hora = args[2]
        res  = args[0].upper()
        registrar_resultado(par, hora, res)
        print(f'✅ Registrado: {par} {hora} → {res}')
        mostrar_stats()

    else:
        print(__doc__)

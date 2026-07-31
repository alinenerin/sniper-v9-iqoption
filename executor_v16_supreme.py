#!/usr/bin/env python3
"""V16 Supreme: worker real de análise contínua, sem execução automática.

O pipeline oficial de candles + motores está em FOREX_SUPREME_FINAL_V16.py.
Este módulo apenas o inicia em modo analysis-only. A função de execução é
isolada e exige autorização manual explícita.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

PAYOUT_MINIMO = 80
SCORE_MINIMO = 95


def inicializar_api_blindada(usuario: str = "", senha: str = "", proxy: Optional[str] = None) -> Any:
    """Conecta à fonte de dados através do pipeline oficial; não envia ordens."""
    from FOREX_SUPREME_FINAL_V16 import connect_iqoption
    return connect_iqoption()


async def iniciar_loops_analise(iq_client: Any = None) -> None:
    """Executa o loop real de candles e IAs; o pipeline está em analysis-only."""
    from FOREX_SUPREME_FINAL_V16 import main_loop
    await asyncio.to_thread(main_loop)


async def loop_atualizacao_ia(stop_event: Optional[asyncio.Event] = None) -> None:
    """Compatibilidade: o pipeline oficial atualiza todas as IAs por ciclo."""
    await iniciar_loops_analise()


async def gerenciar_websocket(iq_client: Any, stop_event: Optional[asyncio.Event] = None) -> None:
    """Compatibilidade: a conexão/candles são gerenciados pelo pipeline oficial."""
    await iniciar_loops_analise(iq_client)


async def monitorar_mercado(stop_event: Optional[asyncio.Event] = None) -> None:
    """Compatibilidade: monitoramento real é executado pelo pipeline oficial."""
    await iniciar_loops_analise()


async def executa_gatilho_sniper(
    iq_client: Any,
    ativo: str,
    dados_mercado: Dict[str, Any],
    autorizacao: bool = False,
) -> str:
    """Ponto manual isolado; nenhum loop consegue chamar esta função."""
    if autorizacao is not True:
        return "BLOQUEADO: AUTORIZAÇÃO_MANUAL_NECESSÁRIA"
    enviar_ordem = dados_mercado.get("enviar_ordem_manual")
    if not callable(enviar_ordem):
        return "BLOQUEADO: EXECUTOR_MANUAL_NÃO_CONFIGURADO"
    # O callback é fornecido pelo operador somente para uma operação autorizada.
    return str(enviar_ordem(ativo, dados_mercado))


if __name__ == "__main__":
    print("[V16 SUPREME] Análise contínua real iniciada; ordens automáticas bloqueadas.")
    try:
        asyncio.run(iniciar_loops_analise())
    except KeyboardInterrupt:
        print("[V16 SUPREME] Loop encerrado manualmente.")

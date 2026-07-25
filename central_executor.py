import sys, os, datetime, pytz

def encaminhar_ordem(tipo, par, direcao, valor=None, timing_sniper=2):
    if tipo.lower() == 'binarias':
        # V16 Supreme Sniper - O Gatilho Perfeito
        now_br = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        # Se estivermos nos segundos finais da vela (>50s), opera na próxima vela.
        if now_br.second > 50:
            target_time = (now_br + datetime.timedelta(minutes=1)).strftime('%H:%M')
        else:
            target_time = now_br.strftime('%H:%M')
            
        # O central_executor agora despacha o comando para o motor V16 respeitando o timing da IA
        # REMOVIDO O '&' para o log aparecer aqui no terminal e capturarmos o erro real agora!
        cmd = f"python3 -c \"from binary_quant_x_v16_supreme import executar_ordem_especifica; executar_ordem_especifica('{par}', '{direcao}', {timing_sniper})\" 2>&1"
        print(f"🚀 [CENTRAL EXECUTOR] Tentando disparo SÍNCRONO para diagnóstico: {par}")
        os.system(cmd)
    elif tipo.lower() == 'forex':
        cmd = f"python3 executor_v15_final_v4.py {par} {direcao}"
        if valor: cmd += f" {valor}"
        print(f"🔄 Encaminhando para Forex V15: {par}")
        os.system(cmd)
    else:
        print("❌ Tipo inválido.")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python3 central_executor.py [binarias/forex] [PAR] [DIREÇÃO]")
    else:
        encaminhar_ordem(sys.argv[1], sys.argv[2], sys.argv[3])

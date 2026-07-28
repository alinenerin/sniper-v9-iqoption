import os, time, requests

def check_omni_bridge():
    if os.path.exists('omni_task.txt'):
        with open('omni_task.txt', 'r') as f:
            task = f.read().strip()
        if task:
            print(f'🧠 [OMNI BRIDGE] Processando: {task}')
            # Aqui o robô chama o OmniRoute diretamente do servidor do GitHub
            try:
                # Simulando a chamada ao OmniRoute (XGBoost/Groq)
                print(f'✅ [OMNI RESPONSE] Análise concluída para: {task}')
                # Deletar para não repetir
                os.remove('omni_task.txt')
            except Exception as e:
                print(f'❌ Erro Omni: {e}')

print('🏛️ V16 SUPREME - INTERFACE OMNI ATIVADA')
while True:
    check_omni_bridge()
    # Aqui continuaria o seu loop original:
    # os.system('python sniper_loop.py --once') 
    time.sleep(10)


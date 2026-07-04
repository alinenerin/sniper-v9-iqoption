#!/usr/bin/env python3
import os, sys, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print(f'[{datetime.datetime.utcnow()}] 🚀 Iniciando carregador do Worker M5 Sniper...')

# Importar as configurações
try:
    import config
    print('✅ Configurações carregadas')
except Exception as e:
    print(f'❌ Erro ao carregar config: {e}')

# Executar o worker
exec(open('railway_worker.py').read())

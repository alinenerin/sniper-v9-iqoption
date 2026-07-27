FROM python:3.10-slim

# Instalar dependências do sistema necessárias para algumas libs python
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar arquivos de dependências
COPY requirements.txt .

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código
COPY . .

# Comando para rodar os dois motores simultaneamente
CMD python executor_v16_supreme.py & python FOREX_SUPREME_FINAL_V16.py

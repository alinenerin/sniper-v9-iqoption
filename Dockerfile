# Base estável para o motor V16
FROM python:3.10-slim

# 1. Instalação de dependências de sistema (Build-essential e bibliotecas de execução)
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Compilação da TA-Lib C Library (O segredo para não dar erro no pip)
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xvzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

WORKDIR /app

# 3. Instalação das bibliotecas Python (Já com o ambiente C pronto)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Cópia do projeto e execução
COPY . .

# Configura o ambiente para encontrar as libs compiladas
ENV LD_LIBRARY_PATH="/usr/lib:/usr/local/lib"

# Comando de inicialização do motor
CMD ["python", "executor_v16_supreme.py"]

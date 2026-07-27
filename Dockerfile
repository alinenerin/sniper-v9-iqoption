FROM python:3.10-slim

# Instalação de dependências do sistema para TA-Lib e análise quantitativa
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Instalação da TA-Lib (Compilação necessária para precisão bancária)
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install

WORKDIR /app

# Copia os requisitos e instala
COPY requirements_forex.txt .
RUN pip install --no-cache-dir -r requirements_forex.txt

# Copia o resto do código
COPY . .

# Comando para rodar o motor Forex V16 Supreme
CMD ["python", "FOREX_SUPREME_FINAL_V16.py"]

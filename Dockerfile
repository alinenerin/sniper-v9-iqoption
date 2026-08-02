FROM python:3.10-slim
RUN apt-get update && apt-get install -y build-essential wget libgomp1 && rm -rf /var/lib/apt/lists/*
RUN wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib && ./configure --prefix=/usr && make -j2 && make install && cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LD_LIBRARY_PATH="/usr/lib:/usr/local/lib"
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} zapia_heavy_api:app"]

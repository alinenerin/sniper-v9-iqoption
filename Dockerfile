# Gateway batch retry build
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements_gateway.txt .
RUN pip install --no-cache-dir -r requirements_gateway.txt
COPY current_iq.py market_gateway.py market_data_contract.py railway_start.py network_diagnostics.py .
EXPOSE 8080
CMD ["python", "railway_start.py"]

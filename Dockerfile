FROM python:3.11-slim
RUN apt-get update && apt-get install -y build-essential curl wget && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY diagnose_railway.py .
CMD ["python", "diagnose_railway.py"]

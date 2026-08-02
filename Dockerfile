FROM python:3.11-slim
WORKDIR /app
COPY requirements_api.txt .
RUN pip install --no-cache-dir -r requirements_api.txt
COPY zapia_heavy_api.py .
EXPOSE 8080
CMD ["sh","-c","exec gunicorn --bind 0.0.0.0:${PORT:-8080} zapia_heavy_api:app"]

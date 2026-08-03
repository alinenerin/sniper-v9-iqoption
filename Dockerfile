FROM python:3.11-slim
WORKDIR /app
COPY requirements_gateway.txt .
RUN pip install --no-cache-dir -r requirements_gateway.txt
COPY current_iq.py market_gateway.py railway_start.py .
EXPOSE 8080
CMD ["python", "railway_start.py"]

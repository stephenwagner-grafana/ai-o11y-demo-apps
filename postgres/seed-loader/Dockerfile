FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY schema.sql .

ENV PYTHONUNBUFFERED=1 \
    SEED_DIR=/seed \
    SCHEMA_PATH=/app/schema.sql

CMD ["python", "main.py"]

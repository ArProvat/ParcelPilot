FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1https://github.com/ArProvat/ParcelPilot/pull/5/conflict?name=backend%252Frequirements.txt&ancestor_oid=e58eaeefa616f78934c7ed5b43a7a3a7c92f3746&base_oid=3c0dc538304de4f3c68845d84066accb185bbf6d&head_oid=6bb8a2c3b0b9821ab4af391d593e4d9cffb388f3

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini .

EXPOSE 8000

CMD ["sh", "scripts/start.sh"]

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (zstandard wheels are prebuilt, but keep build tools minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects $PORT but the bot uses long polling, so no port is needed.
# We still expose one for health checks if you add them later.
EXPOSE 8080

CMD ["python", "-u", "main.py"]

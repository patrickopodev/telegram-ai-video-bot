FROM python:3.11-slim

WORKDIR /app

# System deps for supabase, telegram bot
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY dispatcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dispatcher/ ./dispatcher/
COPY shared/ ./shared/

ENV PYTHONPATH=/app

CMD ["python", "dispatcher/main.py"]
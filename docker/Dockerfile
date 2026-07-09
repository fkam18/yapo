FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    openssh-client \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /home/yapo/yapo_root/jobs/{ready,processing,pending,done,error}

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV YAPO_CONFIG=/app/config.toml
EXPOSE 3388

CMD ["/entrypoint.sh"]

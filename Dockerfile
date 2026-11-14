# Application image for the bootstrap, API and scheduler services.
# Based on the official PostgreSQL 16 image so that pg_dump and pg_restore match the server version exactly.
FROM postgres:16-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1

COPY . .
# never run the application as root
RUN useradd --create-home --uid 10001 gaz && mkdir -p /app/backups && chown -R gaz /app
USER gaz
ENTRYPOINT []
CMD ["python", "etl/bootstrap.py"]

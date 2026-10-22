#!/usr/bin/env bash
# Backup diário do banco do marketTon (roda no servidor, via cron). Guarda 14 dias em /opt/marketton-backups.
# Restaurar: gunzip -c ARQUIVO.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U marketton -d marketton
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/marketton}"
DEST="${DEST:-/opt/marketton-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DEST"
cd "$APP_DIR"
FILE="$DEST/marketton-$(date +%Y%m%d-%H%M).sql.gz"
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U marketton -d marketton --no-owner | gzip -9 > "$FILE"
chmod 600 "$FILE"
# Backup vazio ou truncado não vale: apaga e falha.
if [ "$(stat -c %s "$FILE")" -lt 2000 ]; then rm -f "$FILE"; echo "backup suspeito (muito pequeno)" >&2; exit 1; fi
find "$DEST" -name 'marketton-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $FILE ($(du -h "$FILE" | cut -f1))"

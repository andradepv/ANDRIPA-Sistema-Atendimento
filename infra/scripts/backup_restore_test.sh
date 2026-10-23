#!/bin/sh
# Teste de backup lógico + restauração. Uso: PGHOST=... PGUSER=... PGPASSWORD=... ./backup_restore_test.sh <banco>
# Em produção, rode contra uma réplica restaurada de snapshot (nunca contra o primário sob carga).
set -eu
SRC="${1:-atende}"
DST="${SRC}_restore_check"
FILE="/tmp/${SRC}-$(date +%Y%m%d%H%M%S).dump"
echo "1) Backup lógico de $SRC"
pg_dump -Fc --no-owner -d "$SRC" -f "$FILE"
echo "2) Restauração em $DST"
dropdb --if-exists "$DST"; createdb "$DST"
pg_restore --no-owner -d "$DST" "$FILE"
echo "3) Conferência de contagens por tabela"
Q="SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
  SELECT 'establishments' t, count(*) n FROM establishments UNION ALL SELECT 'users', count(*) FROM users UNION ALL
  SELECT 'tables', count(*) FROM tables UNION ALL SELECT 'table_sessions', count(*) FROM table_sessions UNION ALL
  SELECT 'orders', count(*) FROM orders UNION ALL SELECT 'order_items', count(*) FROM order_items UNION ALL
  SELECT 'service_requests', count(*) FROM service_requests UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs) x"
A=$(psql -At -d "$SRC" -c "$Q"); B=$(psql -At -d "$DST" -c "$Q")
echo "  origem:     $A"; echo "  restaurado: $B"
[ "$A" = "$B" ] || { echo "DIVERGÊNCIA"; exit 1; }
V=$(psql -At -d "$DST" -c "SELECT version_num FROM alembic_version")
echo "4) Versão do esquema restaurado: $V"
dropdb "$DST"; rm -f "$FILE"
echo "OK: backup restaurado e verificado."

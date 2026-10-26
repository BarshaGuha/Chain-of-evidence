#!/usr/bin/env bash
# Chain of Evidence - load the synthetic supply chain data into a local Postgres.
# Creates Docker container "coe-postgres" (port 55433) with three databases,
# one per source system:
#   scm_orders    replenishment_orders
#   scm_planning  demand_daily, skus
#   scm_wms       inventory_snapshots, inventory_norms, stockout_events, dcs
#   scm_finance   sku_economics (estimated prices and unit costs)
# Safe to re-run: regenerates the data and reloads everything.
set -euo pipefail
cd "$(dirname "$0")"

PG_USER="coe"
PG_PASSWORD="${COE_PG_PASSWORD:-coe_local_dev}"   # local-only dev database
PG_PORT="${COE_PG_PORT:-55433}"

echo "1/4 Generating data..."
python3 generate_data.py

echo "2/4 Starting Postgres container..."
if docker ps -a --format '{{.Names}}' | grep -qx coe-postgres; then
  docker start coe-postgres >/dev/null
else
  docker run -d --name coe-postgres \
    -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -p "$PG_PORT":5432 postgres:16-alpine >/dev/null
fi
for i in $(seq 1 60); do
  if docker exec coe-postgres pg_isready -U "$PG_USER" >/dev/null 2>&1; then break; fi
  sleep 1
done
sleep 2

echo "3/4 Creating databases and loading data..."
for db in scm_orders scm_planning scm_wms scm_finance; do
  if ! docker exec coe-postgres psql -U "$PG_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    docker exec coe-postgres psql -U "$PG_USER" -d postgres -qc "CREATE DATABASE $db"
  fi
  short="${db#scm_}"
  docker exec -i coe-postgres psql -U "$PG_USER" -d "$db" \
    -v ON_ERROR_STOP=1 -q < "seed_${short}.sql" 2>/dev/null
done

echo "4/4 Checking..."
docker exec coe-postgres psql -U "$PG_USER" -d scm_wms -c \
  "SELECT event_id, sku_id, dc_id, oos_date FROM stockout_events ORDER BY event_id;"
docker exec coe-postgres psql -U "$PG_USER" -d scm_orders -tAc \
  "SELECT 'replenishment orders loaded: ' || count(*) FROM replenishment_orders;"
echo "Done. Postgres is on localhost:$PG_PORT (user: $PG_USER)."
echo "From inside Zetaris use: jdbc:postgresql://host.docker.internal:$PG_PORT/<database>"

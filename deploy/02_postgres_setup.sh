#!/usr/bin/env bash
# =============================================================================
# 02_postgres_setup.sh — Run once as root on the Hetzner server
# Creates autoparts database, roles, and schema in the existing PostgreSQL 16
# =============================================================================
set -euo pipefail

LOADER_PASS="${AUTOPARTS_LOADER_PASS:-CHANGE_ME_LOADER}"
API_PASS="${AUTOPARTS_API_PASS:-CHANGE_ME_API}"

echo "=== [1/3] Create PostgreSQL roles and database ==="

# Roles — safe to run inside a transaction block
sudo -u postgres psql <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoparts_loader') THEN
    CREATE USER autoparts_loader WITH PASSWORD '${LOADER_PASS}';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoparts_api') THEN
    CREATE USER autoparts_api WITH PASSWORD '${API_PASS}';
  END IF;
END \$\$;
SQL

# CREATE DATABASE cannot run inside a transaction block — run it as a top-level statement
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='autoparts'" | grep -q 1; then
    sudo -u postgres psql -c "CREATE DATABASE autoparts ENCODING 'UTF8' LC_COLLATE 'fr_FR.UTF-8' LC_CTYPE 'fr_FR.UTF-8' TEMPLATE template0"
    echo "  Database 'autoparts' created"
else
    echo "  Database 'autoparts' already exists — skipping"
fi

# Grants
sudo -u postgres psql <<SQL
GRANT ALL PRIVILEGES ON DATABASE autoparts TO autoparts_loader;
GRANT CONNECT ON DATABASE autoparts TO autoparts_api;
SQL

echo "=== [2/3] Allow password auth for autoparts users in pg_hba.conf ==="
PG_HBA="/etc/postgresql/16/main/pg_hba.conf"
if ! grep -q "autoparts_loader" "$PG_HBA"; then
    cat >> "$PG_HBA" <<HBA

# Auto Parts API users (password auth)
host    autoparts   autoparts_loader  127.0.0.1/32  scram-sha-256
host    autoparts   autoparts_api     127.0.0.1/32  scram-sha-256
HBA
    systemctl reload postgresql
    echo "  pg_hba.conf updated"
fi

echo "=== [3/3] Initialize schema via scrap-auto ==="
LOADER_URL="postgresql://autoparts_loader:${LOADER_PASS}@localhost/autoparts"
sudo -u odoo /opt/scrap_auto/venv/bin/scrap-auto load \
    --database-url "$LOADER_URL" \
    --data-dir /opt/scrap_auto/data \
    --init \
    --grant-api

echo ""
echo "=== PostgreSQL setup complete ==="
echo "Connection strings:"
echo "  Loader: postgresql://autoparts_loader:***@localhost/autoparts"
echo "  API:    postgresql://autoparts_api:***@localhost/autoparts"
echo ""
echo "Save these in /etc/systemd/system/scrap-auto-api.service and scrap-auto-crawl.service"

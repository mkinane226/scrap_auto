#!/usr/bin/env bash
# =============================================================================
# 01_server_setup.sh — Run once as root (or sudo) on the Hetzner server
# Sets up Python 3.11+, project directory, virtualenv, and scrap-auto package
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/mkinane226/scrap_auto.git"   # ← adjust if private
INSTALL_DIR="/opt/scrap_auto"
ODOO_USER="odoo"

echo "=== [1/4] System dependencies ==="
apt-get update -q
apt-get install -y python3.11 python3.11-venv python3.11-dev git

echo "=== [2/4] Project directories ==="
mkdir -p "$INSTALL_DIR"/{repo,data,logs}
chown -R "$ODOO_USER:$ODOO_USER" "$INSTALL_DIR"

echo "=== [3/4] Clone repository ==="
if [ -d "$INSTALL_DIR/repo/.git" ]; then
    echo "  Repo already cloned — pulling latest"
    sudo -u "$ODOO_USER" git -C "$INSTALL_DIR/repo" pull --ff-only
else
    sudo -u "$ODOO_USER" git clone "$REPO_URL" "$INSTALL_DIR/repo"
fi

echo "=== [4/4] Python virtualenv + install ==="
sudo -u "$ODOO_USER" python3.11 -m venv "$INSTALL_DIR/venv"
sudo -u "$ODOO_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
sudo -u "$ODOO_USER" "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR/repo[api]"

# Copy allowlist into data dir if it's not there yet
if [ ! -f "$INSTALL_DIR/data/manufaturers.txt" ]; then
    cp "$INSTALL_DIR/repo/manufaturers.txt" "$INSTALL_DIR/data/manufaturers.txt"
fi

echo ""
echo "=== Setup complete ==="
echo "Next: run 02_postgres_setup.sh, then follow DEPLOY.md"

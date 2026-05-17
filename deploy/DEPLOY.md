# Production Deployment Runbook

**Target:** Hetzner CPX31 (Ubuntu 24.04) — same server as i2doo / Odoo 18  
**Stack:** Python 3.11 · PostgreSQL 16 · FastAPI · Nginx  
**SSH:** `ssh -p 2222 odoo@YOUR_SERVER_IP`

---

## Prerequisites

- Hetzner server is running with Odoo 18 + PostgreSQL 16 + Nginx (per `I2DOO_SAAS_DEPLOYMENT_GUIDE.md`)
- You have SSH access as root or a sudo user
- The `scrap_auto` repo is on GitHub at `https://github.com/mkinane226/scrap_auto`

---

## Step 1 — Server Setup

```bash
# On the server, as root:
curl -o /tmp/01_setup.sh https://raw.githubusercontent.com/mkinane226/scrap_auto/main/deploy/01_server_setup.sh
bash /tmp/01_setup.sh
```

Or copy and run locally:
```bash
scp -P 2222 deploy/01_server_setup.sh root@YOUR_SERVER_IP:/tmp/
ssh -p 2222 root@YOUR_SERVER_IP bash /tmp/01_server_setup.sh
```

**Verify:**
```bash
sudo -u odoo /opt/scrap_auto/venv/bin/scrap-auto validate
# → "Validation passed"
```

---

## Step 2 — PostgreSQL Database

On the server, as root — set your passwords and run:
```bash
export AUTOPARTS_LOADER_PASS='ScrapAuto2026!Kinane'
export AUTOPARTS_API_PASS='ScrapAuto2026!Kinane'

curl -fsSL https://raw.githubusercontent.com/mkinane226/scrap_auto/main/deploy/02_postgres_setup.sh -o /tmp/02_postgres_setup.sh
AUTOPARTS_LOADER_PASS="$AUTOPARTS_LOADER_PASS" \
AUTOPARTS_API_PASS="$AUTOPARTS_API_PASS" \
bash /tmp/02_postgres_setup.sh
```

**Verify:**
```bash
sudo -u postgres psql -c "\l autoparts"
# Should show the autoparts database
sudo -u odoo psql "postgresql://autoparts_loader:$AUTOPARTS_LOADER_PASS@localhost/autoparts" -c "\dt"
# Should show 3 tables: autoparts_articles, autoparts_article_details, autoparts_compatible_cars
```

---

## Step 3 — Full Production Crawl (on the server)

> The crawl runs entirely on the Hetzner server. The full allowlist (63 manufacturers)
> takes several hours. Use **tmux** so the crawl survives SSH disconnects.

### 3a. Install tmux (if not already present)

```bash
apt-get install -y tmux
```

### 3b. Start a persistent tmux session

```bash
# SSH into the server
ssh -p 2222 odoo@YOUR_SERVER_IP

# Start (or attach to) a named session
tmux new-session -s crawl
# If the session already exists:  tmux attach -t crawl
```

Everything from here runs inside tmux. You can disconnect safely at any time with
`Ctrl+B` then `D` and reconnect later with `tmux attach -t crawl`.

### 3c. Run the full pipeline as odoo

```bash
# Switch to odoo user (if you logged in as root/sudo)
sudo -iu odoo

# Go to project dir and activate venv
cd /opt/scrap_auto
source venv/bin/activate

# Full crawl — all 63 manufacturers, no limits
# Output goes to the terminal AND to crawl_initial.log
scrap-auto crawl \
    --verbose \
    --progress-every 100 \
    2>&1 | tee logs/crawl_initial.log
```

**Detach any time** with `Ctrl+B` then `D` — the crawl keeps running.  
**Reattach** from any SSH session: `tmux attach -t crawl`

### 3d. Monitor progress from another terminal

```bash
# In a second SSH connection (no need to be in tmux)
tail -f /opt/scrap_auto/logs/crawl_initial.log

# Check how much data is written so far
ls -lh /opt/scrap_auto/data/*.jsonl

# Check checkpoint DB (how many URLs already seen)
sqlite3 /opt/scrap_auto/data/checkpoint.db \
    "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"
```

### 3e. If the crawl is interrupted — resume it

The checkpoint DB records every fetched URL. Simply re-run the exact same command —
it will skip already-seen URLs and pick up where it left off:

```bash
# Same command — checkpoint makes it idempotent
scrap-auto crawl \
    --manufacturers-file data/manufaturers.txt \
    --verbose \
    --progress-every 100 \
    2>&1 | tee -a logs/crawl_initial.log   # note: -a to append, not overwrite
```

### 3f. Post-crawl pipeline (after crawl finishes)

Run these in the same tmux session, still as `odoo` with venv active:

```bash
# Convert JSONL → partitioned Parquet (streaming, no RAM limit)
scrap-auto convert

# Deduplicate articles by article_id
scrap-auto dedup

# Load into PostgreSQL
AUTOPARTS_DATABASE_URL="postgresql://autoparts_loader:YOUR_LOADER_PASS@localhost/autoparts" \
    scrap-auto load --data-dir data

deactivate
```

### 3g. Verify data loaded

```bash
sudo -u odoo psql "postgresql://autoparts_api:YOUR_API_PASS@localhost/autoparts" <<SQL
SELECT 'articles'         AS table, COUNT(*) FROM autoparts_articles
UNION ALL
SELECT 'article_details'  AS table, COUNT(*) FROM autoparts_article_details
UNION ALL
SELECT 'compatible_cars'  AS table, COUNT(*) FROM autoparts_compatible_cars;

-- Sanity: FTS works
SELECT article_id, part_name, article_manufacturer
FROM autoparts_articles
WHERE search_vector @@ websearch_to_tsquery('simple', 'filtre huile')
LIMIT 5;

-- Sanity: car filter works
SELECT COUNT(*) FROM autoparts_compatible_cars
WHERE manufacturer_name ILIKE '%FORD%';
SQL
```

---

## Step 4 — Systemd Services

### 4a. Configure secrets in service files

```bash
# Edit the service files to set real passwords and API key
nano /tmp/scrap-auto-api.service      # Set AUTOPARTS_DATABASE_URL and AUTOPARTS_API_KEY
nano /tmp/scrap-auto-crawl.service    # Set AUTOPARTS_DATABASE_URL
```

**Generate a strong API key:**
```bash
openssl rand -hex 32
# Copy this value into AUTOPARTS_API_KEY in the API service
# Also save it — you'll need it in Odoo's odoo.conf
```

### 4b. Install and enable

```bash
scp -P 2222 deploy/scrap-auto-api.service    root@YOUR_SERVER_IP:/etc/systemd/system/
scp -P 2222 deploy/scrap-auto-crawl.service  root@YOUR_SERVER_IP:/etc/systemd/system/
scp -P 2222 deploy/scrap-auto-crawl.timer    root@YOUR_SERVER_IP:/etc/systemd/system/

ssh -p 2222 root@YOUR_SERVER_IP << 'CMDS'
# Edit the service files to inject real secrets
nano /etc/systemd/system/scrap-auto-api.service
nano /etc/systemd/system/scrap-auto-crawl.service

systemctl daemon-reload
systemctl enable --now scrap-auto-api
systemctl enable --now scrap-auto-crawl.timer

systemctl status scrap-auto-api
systemctl list-timers scrap-auto-crawl.timer
CMDS
```

**Verify API is running:**
```bash
ssh -p 2222 odoo@YOUR_SERVER_IP curl -s http://127.0.0.1:8090/health
# → {"status":"ok"}

# Test search (replace KEY with your AUTOPARTS_API_KEY)
ssh -p 2222 odoo@YOUR_SERVER_IP \
    curl -s -H "X-API-Key: YOUR_KEY" \
    "http://127.0.0.1:8090/search?q=filtre+huile&make=FORD&limit=3"
```

---

## Step 5 — Nginx Configuration

```bash
scp -P 2222 deploy/nginx_autoparts.conf root@YOUR_SERVER_IP:/tmp/

ssh -p 2222 root@YOUR_SERVER_IP << 'CMDS'
# Review the nginx snippet — it shows exactly where to add the blocks
cat /tmp/nginx_autoparts.conf

# Add the rate-limit zone to /etc/nginx/nginx.conf http block
# Add the location block to your existing HTTPS server block
nano /etc/nginx/sites-available/i2doo   # or wherever your server block lives

nginx -t && systemctl reload nginx
CMDS
```

**Verify through Nginx:**
```bash
curl -s https://YOUR_DOMAIN/api/autoparts/health
# → {"status":"ok"}

curl -s -H "X-API-Key: YOUR_KEY" \
    "https://YOUR_DOMAIN/api/autoparts/search?q=frein&make=FORD&limit=5"
```

---

## Step 6 — Odoo Configuration (deferred — next sprint)

Add to `/etc/odoo/odoo.conf`:
```ini
autoparts_api_url = https://YOUR_DOMAIN/api/autoparts
autoparts_api_key = YOUR_KEY_FROM_STEP_4
```

Restart Odoo: `systemctl restart odoo`

The `repair_auto` module will be updated in the next sprint to call this API from the parts search wizard.

---

## Useful Commands

```bash
# View API logs
tail -f /opt/scrap_auto/logs/api.log

# View crawl logs
tail -f /opt/scrap_auto/logs/crawl.log

# Restart API after code update
cd /opt/scrap_auto && sudo -u odoo git -C repo pull && systemctl restart scrap-auto-api

# Run crawl manually (without waiting for Sunday)
systemctl start scrap-auto-crawl

# Check next timer fire
systemctl list-timers scrap-auto-crawl.timer

# Query data
sudo -u odoo psql "postgresql://autoparts_api:YOUR_PASS@localhost/autoparts" \
    -c "SELECT COUNT(*) FROM autoparts_articles WHERE is_oem = false"

# OpenAPI docs (internal only, per nginx config)
ssh -p 2222 -L 8090:127.0.0.1:8090 odoo@YOUR_SERVER_IP
# Then open http://localhost:8090/docs in your browser
```

---

## Monitoring

| What | Command |
|---|---|
| API status | `systemctl status scrap-auto-api` |
| API log | `journalctl -u scrap-auto-api -f` |
| Crawl log | `tail -f /opt/scrap_auto/logs/crawl.log` |
| DB article count | `psql autoparts -c "SELECT COUNT(*) FROM autoparts_articles"` |
| Disk usage | `du -sh /opt/scrap_auto/data/` |
| Next crawl | `systemctl list-timers scrap-auto-crawl.timer` |

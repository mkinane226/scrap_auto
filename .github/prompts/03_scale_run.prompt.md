You are running a full production crawl on the Hetzner server with recovery, then loading data into PostgreSQL.

## Context

The crawl runs entirely on the server (Ubuntu 24.04, /opt/scrap_auto/). All commands below are bash on the server, not local. Use tmux so the crawl survives SSH disconnects.

## Tasks

### 1. Start tmux and run the crawl as odoo
```bash
tmux new-session -s crawl   # or: tmux attach -t crawl

sudo -iu odoo
cd /opt/scrap_auto
source venv/bin/activate

scrap-auto crawl \
    --manufacturers-file data/manufaturers.txt \
    --verbose \
    --progress-every 100 \
    2>&1 | tee logs/crawl_initial.log
```

Detach with Ctrl+B then D. Reattach: `tmux attach -t crawl`

### 2. Verify checkpoint resume

Interrupt with Ctrl+C, rerun the same command. Confirm `skipped_seen > 0` in final counters.

### 3. Monitor progress (second SSH connection)

```bash
tail -f /opt/scrap_auto/logs/crawl_initial.log
ls -lh /opt/scrap_auto/data/*.jsonl
sqlite3 /opt/scrap_auto/data/checkpoint.db \
    "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"
```

### 4. Post-crawl pipeline (after crawl finishes, still as odoo with venv active)

```bash
scrap-auto convert
scrap-auto dedup
AUTOPARTS_DATABASE_URL="postgresql://autoparts_loader:ScrapAuto2026!Kinane@localhost/autoparts" \
    scrap-auto load --data-dir data
deactivate
```

### 5. Verify data in PostgreSQL

```bash
sudo -u odoo psql "postgresql://autoparts_api:ScrapAuto2026!Kinane@localhost/autoparts" <<SQL
SELECT 'articles'        AS t, COUNT(*) FROM autoparts_articles
UNION ALL
SELECT 'article_details' AS t, COUNT(*) FROM autoparts_article_details
UNION ALL
SELECT 'compatible_cars' AS t, COUNT(*) FROM autoparts_compatible_cars;
SQL
```

### 6. Verify API

```bash
curl -s http://127.0.0.1:8090/health
# → {"status":"ok"}
```

## Acceptance

- Re-running with same command skips already-seen URLs (`skipped_seen > 0`).
- No crash on intermittent 429/5xx.
- Final counters printed with all entity counts.
- data/parquet/ directory populated after convert.
- articles_deduped.parquet and article_details_deduped.parquet exist after dedup.
- PostgreSQL tables have non-zero row counts.
- article_details image_urls contain only S3 URLs.
- compatible_cars rows include extra_qualifier field.
- API /health returns {"status":"ok"}.

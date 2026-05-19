# Crawl Rounds Process — scrap_auto

Step-by-step guide for running additional crawl rounds and loading data into PostgreSQL.
All commands run on the Hetzner server as the `odoo` user unless noted otherwise.

---

## Prerequisites (one-time, already done)

- Venv at `/opt/scrap_auto/venv/`
- PostgreSQL schema already created (`scrap-auto load --init` was run once)
- Storage Box SSH key at `/root/.ssh/storagebox` (root user only)
- Allowlist at `/opt/scrap_auto/data/manufaturers.txt`
- Swap enabled (`/swapfile 4G`)
- pyarrow installed: `pip install pyarrow -q`

---

## Per-Round Process

### Step 0 — Check disk space before starting

```bash
df -h /
```

You need at least **20 GB free** before starting a new round.
If less, jump to Step 4 (convert + rsync) to free space first.

---

### Step 1 — Run the crawl

```bash
tmux new-session -s crawl   # or: tmux attach -t crawl

sudo -iu odoo
cd /opt/scrap_auto
source venv/bin/activate

scrap-auto crawl \
    --manufacturers-file data/manufaturers.txt \
    --verbose \
    --progress-every 100 \
    2>&1 | tee logs/crawl_round_N.log
```

Replace `N` with the round number. Detach from tmux: **Ctrl+B then D**.

**What to watch for:**
- `manufacturers=121` in the first progress line — confirms navigation is working
- `skipped_seen` growing fast — article detail pages from prior rounds correctly skipped
- `articles` growing — new articles in newly-traversed car types

**Monitor from a second SSH session:**
```bash
tail -f /opt/scrap_auto/logs/crawl_round_N.log | grep -E "Progress|Done|Manufacturer"
```

**Stop condition:** Run until one of:
- The crawl finishes naturally (`Done` counters printed)
- Disk reaches ~80% (`df -h /` shows ≥ 60 GB used on a 75 GB disk)

Stop gracefully: re-attach to tmux (`tmux attach -t crawl`) and press **Ctrl+C**.

---

### Step 2 — Check what was collected

```bash
ls -lh /opt/scrap_auto/data/*.jsonl
df -h /
```

Note the sizes. `article_details.jsonl` is always the largest file.

---

### Step 3 — Convert JSONL to Parquet

Use a unique `--crawl-date` label per round to avoid overwriting previous rounds.

```bash
cd /opt/scrap_auto
source venv/bin/activate

scrap-auto convert --crawl-date 2026-05-18-rN
```

Replace `rN` with the round number (e.g. `r4`, `r5`).

`scrap-auto convert` processes entities in order: manufacturers, models, car_types, car_type_details, category_groups, articles, article_details. **All entities before article_details are converted first.** If article_details fails with OOM, the others are already safe.

**If `article_details` conversion fails with OOM**, use the chunked method:

```bash
mkdir -p /tmp/duckdb_convert
mkdir -p data/parquet/entity_type=article_details/crawl_date=2026-05-18-rN
split -l 1000 -d data/article_details.jsonl /tmp/ad_rN_chunk_

chunk_num=0
for f in $(ls /tmp/ad_rN_chunk_* | sort); do
    out="data/parquet/entity_type=article_details/crawl_date=2026-05-18-rN/part-$(printf '%04d' $chunk_num).parquet"
    python3 - "$f" "$out" <<'PYEOF'
import sys, duckdb
src, dst = sys.argv[1], sys.argv[2]
con = duckdb.connect()
con.execute("SET memory_limit='2GB'")
con.execute("SET temp_directory='/tmp/duckdb_convert'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET threads=2")
con.execute(f"""COPY (SELECT * FROM read_ndjson('{src}', auto_detect=True, maximum_object_size=33554432)) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
con.close()
print(f"Done: {dst}")
PYEOF
    rm "$f"
    chunk_num=$((chunk_num + 1))
done
echo "All $chunk_num chunks done"
```

---

### Step 4 — Rsync JSONL to Storage Box, then delete

Run as **root**:

```bash
ssh -p 23 -i /root/.ssh/storagebox \
    u590268@u590268.your-storagebox.de \
    "mkdir -p scrap_auto/jsonl_roundN"

rsync -avz --progress \
    -e "ssh -p 23 -i /root/.ssh/storagebox" \
    /opt/scrap_auto/data/*.jsonl \
    u590268@u590268.your-storagebox.de:scrap_auto/jsonl_roundN/

rm /opt/scrap_auto/data/*.jsonl
df -h /
```

Verify at least 40 GB free before proceeding.

---

### Step 5 — Dedup across ALL rounds

Clear any root-owned temp dir first, then run dedup for articles and article_details separately.

```bash
sudo rm -rf /tmp/duckdb_dedup
cd /opt/scrap_auto
source venv/bin/activate
```

**Articles dedup** (fast, uses DuckDB directly):

```bash
python3 - <<'PYEOF'
import duckdb

con = duckdb.connect()
con.execute("SET memory_limit='4GB'")
con.execute("SET temp_directory='/tmp/duckdb_dedup'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET threads=2")
con.execute("""
    COPY (
        SELECT DISTINCT ON (article_id) *
        FROM read_parquet('data/parquet/entity_type=articles/**/*.parquet', hive_partitioning=false)
        ORDER BY article_id
    )
    TO 'data/parquet/articles_deduped.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
con.close()
print("Done → articles_deduped.parquet")
PYEOF
```

**Article_details dedup** (streaming, handles large datasets):

```bash
python3 - <<'PYEOF'
import duckdb, glob, os
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

data_dir = Path('data/parquet')
out = data_dir / 'article_details_deduped.parquet'
tmp_dir = Path('/tmp/dedup_parts')
tmp_dir.mkdir(exist_ok=True)

files = sorted(glob.glob(str(data_dir / 'entity_type=article_details/**/*.parquet'), recursive=True))
print(f"Found {len(files)} parquet files")

seen_ids: set = set()
tmp_files = []

for i, f in enumerate(files):
    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'")
    con.execute("SET temp_directory='/tmp/duckdb_dedup'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=1")
    ids_in_file = {row[0] for row in con.execute(f"SELECT article_id FROM read_parquet('{f}', hive_partitioning=false)").fetchall() if row[0] is not None}
    new_ids = ids_in_file - seen_ids
    if not new_ids:
        print(f"[{i+1}/{len(files)}] skip ({len(ids_in_file)} all seen)")
        con.close()
        continue
    seen_ids |= new_ids
    ids_str = ','.join(str(x) for x in new_ids)
    tmp_out = tmp_dir / f'part_{i:04d}.parquet'
    con.execute(f"COPY (SELECT * FROM read_parquet('{f}', hive_partitioning=false) WHERE article_id IN ({ids_str})) TO '{tmp_out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    tmp_files.append(str(tmp_out))
    print(f"[{i+1}/{len(files)}] +{len(new_ids)} new → {tmp_out.name}")

def normalize(table):
    idx = table.schema.get_field_index('crawl_date')
    if idx >= 0 and table.schema.field('crawl_date').type != pa.string():
        table = table.set_column(idx, 'crawl_date', table.column('crawl_date').cast(pa.string()))
    return table

writer = None
total_rows = 0
for i, f in enumerate(tmp_files):
    table = normalize(pq.read_table(f))
    if writer is None:
        writer = pq.ParquetWriter(str(out), table.schema, compression='zstd')
    writer.write_table(table)
    total_rows += len(table)
    del table

if writer:
    writer.close()
for tf in tmp_files:
    os.unlink(tf)
print(f"Done → {out} ({total_rows} unique article_details)")
PYEOF
```

---

### Step 6 — Load into PostgreSQL

```bash
cd /opt/scrap_auto
source venv/bin/activate
export AUTOPARTS_DATABASE_URL='postgresql://autoparts_loader:ScrapAuto2026!Kinane@localhost/autoparts'

scrap-auto load --data-dir data --batch-size 100
```

**No `--init`** — schema already exists. `--batch-size 100` prevents OOM on article_details.

This is idempotent — safe to re-run after every round.

---

### Step 7 — Verify data in PostgreSQL

```bash
psql 'postgresql://autoparts_api:ScrapAuto2026!Kinane@localhost/autoparts' <<'SQL'
SELECT 'articles'        AS t, COUNT(*) FROM autoparts_articles
UNION ALL
SELECT 'article_details' AS t, COUNT(*) FROM autoparts_article_details
UNION ALL
SELECT 'compatible_cars' AS t, COUNT(*) FROM autoparts_compatible_cars;
SQL
```

Expected growth after each round: articles and article_details counts increase.

---

### Step 8 — Repeat for next round

Go back to Step 0. Increment the round label (e.g. `r5`, `r6`).

**Crawl is complete when:** `skipped_seen` is 90%+ of all URLs and new `articles` count is < 500.

---

## Disk Space Reference

| File | Typical size |
|---|---|
| `article_details.jsonl` per round | 5–50 GB |
| Parquet per round (compressed) | ~10–20% of JSONL |
| `article_details_deduped.parquet` | ~500 MB–2 GB |
| `articles_deduped.parquet` | ~50 MB |

**Rule:** Never let disk exceed 80% before converting and rsyncing.

---

## Storage Box Reference

| Purpose | Path on Storage Box |
|---|---|
| Round 1 JSONL | `scrap_auto/jsonl_round1/` |
| Round 2 JSONL | `scrap_auto/jsonl_round2/` |
| Round 3 JSONL | `scrap_auto/jsonl_round3/` |
| Round N JSONL | `scrap_auto/jsonl_roundN/` |

SSH access (root): `ssh -p 23 -i /root/.ssh/storagebox u590268@u590268.your-storagebox.de`

---

## Recovery: articles.jsonl missing from a round

If you get `ForeignKeyViolation: article_id not present in autoparts_articles`, a previous round's
`articles.jsonl` was deleted before being converted. Recover it from the Storage Box:

**As root:**
```bash
ssh -p 23 -i /root/.ssh/storagebox \
    u590268@u590268.your-storagebox.de \
    "cat scrap_auto/jsonl_roundN/articles.jsonl" \
    > /opt/scrap_auto/data/roundN_articles.jsonl

chown odoo:odoo /opt/scrap_auto/data/roundN_articles.jsonl
```

**As odoo** — convert using explicit column list (auto_detect produces a broken `json` column):
```bash
cd /opt/scrap_auto
source venv/bin/activate

python3 - <<'PYEOF'
import duckdb
from pathlib import Path

src = 'data/roundN_articles.jsonl'
dst = Path('data/parquet/entity_type=articles/crawl_date=2026-05-18-rN/part-0.parquet')
dst.parent.mkdir(parents=True, exist_ok=True)

cols = ['part_name', 'article_id', 'part_number', 'article_manufacturer', 'supplier_id',
        'product_id', 'thumbnail_url', 'details_url', 'model_series_id', 'manufacturer_id',
        'group_id', 'car_type_id', 'lang_id', 'country_id', 'type_id', 'is_oem']
col_defs = ', '.join(f"'{c}': 'VARCHAR'" for c in cols)

con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
con.execute(f"COPY (SELECT * FROM read_json('{src}', columns={{{col_defs}}})) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)")
con.close()
print(f"Done → {dst}")
PYEOF
```

Then re-run Step 5 (dedup) and Step 6 (load).

---

## Common Failures and Fixes

| Error | Fix |
|---|---|
| `scrap-auto: command not found` | `cd /opt/scrap_auto && source venv/bin/activate` |
| `manufacturers=0, skipped_seen=1` in Done | Checkpoint has the manufacturers list URL — delete it: `rm data/checkpoint.db` |
| `Out of Memory` on convert | Use chunked method (Step 3 fallback) |
| `Out of Memory` on dedup | Use streaming Python dedup (Step 5) |
| `Out of Memory` on load | Use `--batch-size 100` or lower |
| `!Kinane: event not found` | Use single quotes: `export AUTOPARTS_DATABASE_URL='...'` |
| `unable to open database file` | Run from `/opt/scrap_auto`: `cd /opt/scrap_auto` |
| `ModuleNotFoundError: pyarrow` | `pip install pyarrow -q` |
| `PermissionError: /tmp/duckdb_dedup` | `sudo rm -rf /tmp/duckdb_dedup` (created by root previously) |
| `Referenced column "article_id" not found, Candidate bindings: crawl_date, entity_type` | DuckDB auto-detected hive partitioning — use `hive_partitioning=false` in read_parquet |
| `Referenced column "article_id" not found, Candidate bindings: json` | articles.jsonl was converted with wrong auto_detect — use `read_json` with explicit columns (see Recovery section) |
| `ForeignKeyViolation: article_id not present in autoparts_articles` | A round's articles.jsonl was never converted — recover from Storage Box (see Recovery section) |
| `IO Error: No files found` for `/root/` path | `/root/` is not readable by odoo — copy file: `cp /root/file /opt/scrap_auto/data/ && chown odoo:odoo /opt/scrap_auto/data/file` |
| Schema mismatch on parquet merge (`crawl_date` type) | Mixed date/string types across rounds — use the `normalize()` function in the dedup script |

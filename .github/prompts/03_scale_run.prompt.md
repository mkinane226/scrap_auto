You are running a full production crawl with recovery.

Goal:
- Execute a full crawl from the manufacturer allowlist safely and resumably.
- Monitor progress and verify the checkpoint system works.

Tasks:
1. Run production crawl with allowlist and log output:
   scrap-auto crawl --manufacturers-file manufaturers.txt --verbose --progress-every 100 | Tee-Object -FilePath crawl.log
2. Interrupt mid-run (Ctrl+C), then rerun the same command and verify skipped_seen > 0 in the final counters.
3. After crawl completes, run post-crawl pipeline:
   scrap-auto convert
   scrap-auto dedup
4. Query results to verify data quality:
   python -c "import duckdb; duckdb.connect().sql(\"SELECT COUNT(*), COUNT(article_name) FROM read_ndjson('data/article_details.jsonl')\").show()"
5. Inspect checkpoint DB:
   sqlite3 data\checkpoint.db "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"

Acceptance:
- Re-running with same command skips already-seen URLs (skipped_seen > 0).
- No crash on intermittent 429/5xx.
- Final counters printed with all entity counts and skipped_seen.
- data/parquet/ directory populated after convert.
- articles_deduped.parquet and article_details_deduped.parquet exist after dedup.
- article_details image_urls contain only S3 URLs (no logos/nav images).
- compatible_cars rows include extra_qualifier field.

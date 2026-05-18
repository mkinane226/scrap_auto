#!/usr/bin/env python3
"""
Stream article_details.jsonl from Hetzner Storage Box in chunks and convert
each chunk to a separate Parquet part file.

Run this AFTER round 2 crawl + convert are done and disk has free space.
Must be run as root (SSH key is at /root/.ssh/storagebox).

Usage:
    python3 scripts/chunk_convert_from_storagebox.py
"""
import os
import subprocess
import sys
from pathlib import Path

import duckdb

STORAGE_BOX_USER = "u590268"
STORAGE_BOX_HOST = "u590268.your-storagebox.de"
STORAGE_BOX_PORT = 23
SSH_KEY = "/root/.ssh/storagebox"
REMOTE_FILE = "scrap_auto/jsonl_round1/article_details.jsonl"

OUT_DIR = Path("data/parquet/entity_type=article_details/crawl_date=2026-05-18")
CHUNK_LINES = 1000   # ~900 MB per chunk — safe for 8 GB RAM with other processes
TEMP_CHUNK = Path("/tmp/ad_chunk.jsonl")

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{STORAGE_BOX_USER}@{STORAGE_BOX_HOST}"
    cmd = [
        "ssh", "-p", str(STORAGE_BOX_PORT), "-i", SSH_KEY,
        ssh_target, f"cat {REMOTE_FILE}",
    ]

    print(f"Streaming {REMOTE_FILE} from Storage Box ...")
    print(f"Chunk size: {CHUNK_LINES} lines → output: {OUT_DIR}/")

    chunk_num = 0
    buffer: list[str] = []

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            buffer.append(line)
            if len(buffer) >= CHUNK_LINES:
                _flush_chunk(buffer, chunk_num)
                buffer = []
                chunk_num += 1

        if buffer:
            _flush_chunk(buffer, chunk_num)
            chunk_num += 1

    print(f"\nAll done — {chunk_num} Parquet part files written to {OUT_DIR}/")
    print("Next steps:")
    print("  scrap-auto dedup")
    print("  AUTOPARTS_DATABASE_URL=... scrap-auto load --data-dir data")


def _flush_chunk(lines: list[str], chunk_num: int) -> None:
    out_file = OUT_DIR / f"part-{chunk_num:04d}.parquet"
    print(f"  Chunk {chunk_num:04d}: {len(lines)} lines → {out_file}", flush=True)

    TEMP_CHUNK.write_text("".join(lines), encoding="utf-8")

    con = duckdb.connect()
    try:
        con.execute(f"""
            COPY (
                SELECT * FROM read_ndjson(
                    '{TEMP_CHUNK}',
                    auto_detect=True,
                    maximum_object_size=33554432
                )
            )
            TO '{out_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    finally:
        con.close()
        TEMP_CHUNK.unlink(missing_ok=True)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: must run as root (SSH key is at /root/.ssh/storagebox)", file=sys.stderr)
        sys.exit(1)
    main()

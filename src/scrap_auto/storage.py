from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson


class JsonlStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def append(self, name: str, record: dict[str, Any]) -> None:
        path = self.output_dir / f"{name}.jsonl"
        with path.open("ab") as f:
            f.write(orjson.dumps(record))
            f.write(b"\n")

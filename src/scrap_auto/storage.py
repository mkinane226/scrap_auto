from __future__ import annotations

from pathlib import Path
from typing import IO, Any

import orjson


class JsonlStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, IO[bytes]] = {}

    def append(self, name: str, record: dict[str, Any]) -> None:
        if name not in self._handles:
            path = self.output_dir / f"{name}.jsonl"
            self._handles[name] = path.open("ab")
        f = self._handles[name]
        f.write(orjson.dumps(record))
        f.write(b"\n")

    def close(self) -> None:
        for f in self._handles.values():
            f.flush()
            f.close()
        self._handles.clear()

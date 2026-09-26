#!/usr/bin/env python3
"""Refuse to commit raw eBay item IDs.

This repository is public. The daily workflow strips ``item_ids`` out of the
eBay snapshots (``scripts/ebay_ids_sidecar.py stash``) before it commits. This
script is a second, independent check: it reads every file staged for commit
and exits 1 if any staged JSON file still has an ``item_ids`` key at any depth,
so the commit step never runs.

    git add ...                              # stage what will be committed
    python scripts/check_no_item_ids.py      # exit 1 = do not commit

It reads the staged copy of each file (what would actually be committed), not
the working tree. A staged ``.json`` file that does not parse fails the check
if its raw text contains ``item_ids``, so a broken file cannot slip through.
If git itself errors, the script errors too, which also stops the commit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import List

KEY = "item_ids"


def find_key_paths(obj, key: str = KEY, path: str = "$") -> List[str]:
    """Every JSON path where ``key`` appears as an object key, at any depth."""
    hits: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}"
            if k == key:
                hits.append(here)
            hits.extend(find_key_paths(v, key, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_key_paths(v, key, f"{path}[{i}]"))
    return hits


def check_blob(name: str, data: bytes) -> List[str]:
    """Problems found in one staged file; an empty list means it is clean."""
    if not name.lower().endswith(".json"):
        return []
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        if KEY.encode() in data:
            return [f"{name}: does not parse as JSON and contains {KEY!r}"]
        return []
    hits = find_key_paths(obj)
    if not hits:
        return []
    shown = ", ".join(hits[:3]) + (f" (and {len(hits) - 3} more)" if len(hits) > 3 else "")
    return [f"{name}: {len(hits)} {KEY!r} key(s) at {shown}"]


def staged_files() -> List[str]:
    """Paths staged for commit (added, copied, modified, renamed, type-changed)."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"],
        check=True, capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def staged_blob(path: str) -> bytes:
    """The staged (index) content of ``path``."""
    return subprocess.run(["git", "show", f":{path}"], check=True, capture_output=True).stdout


def main() -> int:
    files = staged_files()
    problems: List[str] = []
    for path in files:
        problems.extend(check_blob(path, staged_blob(path)))
    if problems:
        print(f"Refusing to commit: raw eBay {KEY} found in staged files.", file=sys.stderr)
        for p in problems[:50]:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"check_no_item_ids: OK, no {KEY!r} key in {len(files)} staged file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

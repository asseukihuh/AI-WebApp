#!/usr/bin/env python3
"""Print a human-readable layer/placement summary from a poster command batch JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_batch(path: str | None) -> dict:
    if path and path != "-":
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def summarize(batch: dict) -> None:
    meta = batch.get("meta") or {}
    print(f"format: {batch.get('format')}")
    print(f"canvas: {batch.get('canvas')}")
    print(f"meta: {meta}")
    doc = batch.get("document") or {}
    print(f"document.background: {doc.get('background')}")
    print()
    print("backgroundPlacements:")
    for item in batch.get("backgroundPlacements") or []:
        rel = item.get("path", "")
        exists = (ROOT / rel).is_file() if rel else False
        print(f"  - {item.get('name', 'placement')}: path={rel} on_disk={exists} params={item}")
    print("foreground placements:")
    for item in batch.get("placements") or []:
        rel = item.get("path", "")
        exists = (ROOT / rel).is_file() if rel else False
        print(f"  - {item.get('name', 'placement')}: path={rel} on_disk={exists}")
    print()
    print("engine steps:")
    for index, step in enumerate(batch.get("steps") or [], start=1):
        cmd = step.get("command")
        params = step.get("params") or {}
        if cmd == "type.create":
            text = (params.get("text") or "").replace("\n", " | ")
            print(f"  {index}. {cmd} [{params.get('name')}] size={params.get('size')} text={text[:80]}")
        elif cmd == "layer.setProps":
            print(f"  {index}. {cmd} name={params.get('name')} opacity={params.get('opacity')}")
        else:
            brief = {k: params[k] for k in list(params)[:4]}
            print(f"  {index}. {cmd} {brief}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "batch_json",
        nargs="?",
        help="Path to batch JSON (default: read stdin). Use - for stdin.",
    )
    args = parser.parse_args()
    batch = load_batch(args.batch_json)
    if "commandBatch" in batch:
        batch = batch["commandBatch"]
    summarize(batch)


if __name__ == "__main__":
    main()

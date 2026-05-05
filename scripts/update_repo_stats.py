#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate / update repository stats for R-Bloggers crawler output.

Key ideas
- Primary source of truth: by_created/YYYY/MM/*.json
- Incremental updates: use .action_result.json (list of newly written files) when available
- One-time init: if RBLOGGERS_COUNTS.json missing/empty, do a full scan of by_created/

Outputs
- RBLOGGERS_COUNTS.json : incremental counters (month -> files/bytes)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(".")
BY_CREATED = ROOT / "by_created"
COUNTS_JSON = ROOT / "RBLOGGERS_COUNTS.json"
ACTION_RESULT = ROOT / ".action_result.json"


@dataclass
class MonthStat:
    files: int = 0
    bytes: int = 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def month_key_from_path(p: Path) -> str | None:
    """
    Expected: by_created/YYYY/MM/<anything>.json
    Returns: 'YYYY-MM'
    """
    try:
        rel = p.relative_to(BY_CREATED)
    except Exception:
        return None
    parts = rel.parts
    if len(parts) < 3:
        return None
    yyyy, mm = parts[0], parts[1]
    if not (yyyy.isdigit() and len(yyyy) == 4 and mm.isdigit() and len(mm) == 2):
        return None
    return f"{yyyy}-{mm}"


def load_counts() -> Dict[str, MonthStat]:
    if not COUNTS_JSON.exists():
        return {}
    try:
        obj = json.loads(COUNTS_JSON.read_text(encoding="utf-8"))
        months = obj.get("months", {}) if isinstance(obj, dict) else {}
        out: Dict[str, MonthStat] = {}
        for k, v in months.items():
            if not isinstance(v, dict):
                continue
            out[k] = MonthStat(files=int(v.get("files", 0)), bytes=int(v.get("bytes", 0)))
        return out
    except Exception:
        return {}


def save_counts(months: Dict[str, MonthStat], meta: dict) -> None:
    payload = {
        "meta": meta,
        "months": {k: {"files": v.files, "bytes": v.bytes} for k, v in months.items()},
    }
    COUNTS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_all_by_created() -> Dict[str, MonthStat]:
    months: Dict[str, MonthStat] = {}
    if not BY_CREATED.exists():
        return months
    for p in BY_CREATED.rglob("*.json"):
        mk = month_key_from_path(p)
        if mk is None:
            continue
        st = months.setdefault(mk, MonthStat())
        st.files += 1
        try:
            st.bytes += p.stat().st_size
        except FileNotFoundError:
            pass
    return months


def load_action_new_files() -> List[str]:
    if not ACTION_RESULT.exists():
        return []
    try:
        obj = json.loads(ACTION_RESULT.read_text(encoding="utf-8"))
        files = obj.get("files", [])
        if not isinstance(files, list):
            return []
        files = [f for f in files if isinstance(f, str) and f.endswith(".json")]
        return files
    except Exception:
        return []


def apply_incremental(months: Dict[str, MonthStat], new_files: List[str]) -> Tuple[int, int]:
    """
    new_files: relative paths (strings) returned by crawler in .action_result.json
    Returns: (added_files_count, added_bytes)
    """
    added_files = 0
    added_bytes = 0
    for f in new_files:
        p = ROOT / f
        if not p.exists():
            continue
        mk = month_key_from_path(p)
        if mk is None:
            continue
        st = months.setdefault(mk, MonthStat())
        st.files += 1
        try:
            b = p.stat().st_size
        except FileNotFoundError:
            b = 0
        st.bytes += b
        added_files += 1
        added_bytes += b
    return added_files, added_bytes


def main() -> None:
    months = load_counts()
    new_files = load_action_new_files()

    # One-time init: if empty counts but data exists in by_created, full scan.
    if not months:
        # if by_created has any json, scan
        has_any = BY_CREATED.exists() and any(BY_CREATED.rglob("*.json"))
        if has_any:
            months = scan_all_by_created()

    # Apply incremental for this run (so report shows last run new files)
    added_files, _added_bytes = apply_incremental(months, new_files)

    meta = {
        "updated_at": utc_now_iso(),
        "last_run_finished": utc_now_iso(),
        "last_run_new_files": added_files,
        "source": "by_created + .action_result.json",
    }
    save_counts(months, meta)


if __name__ == "__main__":
    main()

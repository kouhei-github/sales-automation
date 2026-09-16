"""descriptions.json を書くための要約用ビュー。25 社ずつ表示する。

  python3 show_for_summary.py output/<run-dir> --offset 0 --limit 25
"""
import argparse
import re
from pathlib import Path

from common import load_json


def squash(s, n):
    return re.sub(r"\s+", " ", s or "").strip()[:n]


ap = argparse.ArgumentParser()
ap.add_argument("run_dir")
ap.add_argument("--offset", type=int, default=0)
ap.add_argument("--limit", type=int, default=25)
a = ap.parse_args()
rows = load_json(Path(a.run_dir) / "enriched.json", [])
done = load_json(Path(a.run_dir) / "descriptions.json", {}) or {}
ok = [r for r in rows if r.get("hp_status") == "ok"]
print(f"# HP到達 {len(ok)} 社 / 全 {len(rows)} 社 / 説明済 {len([c for c in done if done[c]])} 社 — 表示 {a.offset}〜{min(a.offset + a.limit, len(ok))}\n")
for r in ok[a.offset:a.offset + a.limit]:
    mark = "✔" if r["company"] in done else " "
    print(f"[{mark}] {r['company']}  ({r.get('category', '')})  {r.get('website', '')}")
    print(f"    title: {squash(r.get('hp_title'), 80)}")
    print(f"    meta : {squash(r.get('meta_description'), 200)}")
    print(f"    事業 : {squash(r.get('business_raw'), 200)}")
    print(f"    about: {squash(r.get('about_text'), 350)}")
    print()

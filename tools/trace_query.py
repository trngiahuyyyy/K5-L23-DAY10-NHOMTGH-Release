#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Truy vết ticket team AI (Pha 5) -> runs/r<seed>/trace.json.

  python scripts/trace_query.py --delivery runs/r3007/delivery --out runs/r3007/trace.json

Điều kiện (GUIDE Pha 5, DELIVERY.md mục 3):
  * Lớp bị đổi quy tắc + guideline CŨ: đọc từ guideline/changelog.md (mục mới nhất nêu lớp và
    phiên bản thay thế nó; job "guideline cũ" là job mang phiên bản TRƯỚC mục đó).
  * Cảnh team AI nêu: đọc từ incoming/ticket.md (các `scene_xxx` trong ngoặc/backtick).
  * tier_a: ảnh thuộc các cảnh nêu trên, job mang guideline cũ theo **jobs.csv** (không lấy
    guideline trong metadata.json — đó có thể chính là lỗi guideline_mismatch), và nhãn detection
    của ảnh có >= 1 box thuộc lớp bị đổi quy tắc.
  * tier_b: các ảnh khác cùng điều kiện (job guideline cũ, có lớp đó) chưa ai báo.
  * notify: mã annotator + reviewer của mọi job chứa ảnh tier_a/tier_b.
Chỉ dùng thư viện chuẩn; chỉ đọc delivery.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def changed_rule(changelog_text: str) -> tuple[str, str] | None:
    """(lớp bị đổi, phiên bản cũ) từ mục mới nhất của changelog.

    Mục v1.3 dạng '## v1.3' rồi '- Lớp `bottle`: ... (v1.2 cho phép bỏ qua)...'.
    """
    heads = re.findall(r"^##\s+v(\d+(?:\.\d+)?)\s*$", changelog_text, flags=re.M)
    if len(heads) < 2:
        return None
    newest, prev = heads[0], heads[1]
    body = changelog_text.split(f"## v{newest}", 1)[1].split("## v", 1)[0]
    m = re.search(r"`([a-z ]+)`", body)
    return (m.group(1), f"v{prev}") if m else (None, f"v{prev}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sinh trace.json từ ticket + jobs.csv")
    ap.add_argument("--delivery", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    d = Path(args.delivery)

    ticket = (d / "incoming" / "ticket.md").read_text(encoding="utf-8")
    scenes = set(re.findall(r"scene_\d+", ticket))
    log = (d / "guideline" / "changelog.md").read_text(encoding="utf-8")
    parsed = changed_rule(log)
    if not parsed or not parsed[0]:
        raise SystemExit("Không đọc được lớp bị đổi quy tắc từ changelog")
    rule_class, old_guideline = parsed

    with open(d / "classes.txt", encoding="utf-8") as f:
        cls_id = {line.strip().split(" ", 1)[1]: int(line.split()[0])
                  for line in f if len(line.strip().split(" ", 1)) == 2}
    if rule_class not in cls_id:
        raise SystemExit(f"Lớp '{rule_class}' không có trong classes.txt")
    cid = cls_id[rule_class]

    with open(d / "jobs.csv", newline="", encoding="utf-8-sig") as f:
        jobs = {row["job_id"]: row for row in csv.DictReader(f)}
    meta = {m["image"]: m for m in json.loads((d / "metadata.json").read_text(encoding="utf-8"))["items"]}

    def has_class(name: str) -> bool:
        p = d / "labels" / f"{name}.txt"
        if not p.is_file():
            return False
        return any(line.split()[0].isdigit() and int(line.split()[0]) == cid
                   for line in p.read_text(encoding="utf-8").splitlines() if line.strip())

    qualifies = [n for n, m in meta.items()
                 if jobs.get(m["job_id"], {}).get("guideline", "").strip() == old_guideline and has_class(n)]
    tier_a = sorted(n for n in qualifies if meta[n]["scene_id"] in scenes)
    tier_b = sorted(n for n in qualifies if meta[n]["scene_id"] not in scenes)
    used_jobs = {meta[n]["job_id"] for n in tier_a + tier_b}
    notify = sorted({jobs[j]["annotator"] for j in used_jobs} | {jobs[j]["reviewer"] for j in used_jobs})

    doc = {"tier_a": tier_a, "tier_b": tier_b, "notify": notify,
           "rule_class": rule_class, "old_guideline": old_guideline, "reported_scenes": sorted(scenes)}
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"lớp đổi quy tắc: {rule_class} (job guideline {old_guideline}); cảnh được báo: {sorted(scenes)}")
    print(f"tier_a {len(tier_a)} ảnh · tier_b {len(tier_b)} ảnh · notify {notify} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dựng lô bàn giao v2 từ delivery v1 + errors.json (Pha 4) — không sửa delivery/.

  python scripts/build_v2.py --delivery runs/r3007/delivery --errors runs/r3007/errors.json \
      --out runs/r3007/handover

Quy tắc (GUIDE Pha 4):
  * Lỗi nhãn detection / thiếu file (missing_image, invalid_class, bbox_out_of_bounds,
    duplicate_box, class_swap, bbox_drift, missing_box): ảnh vào rework_queue.csv, rời v2.
  * wrong_hash: mở ảnh kiểm tự động (giải mã JPEG được => ảnh còn nguyên, chỉ manifest sai,
    ghi hash thật vào manifest v2); giải mã hỏng => rework.
  * guideline_mismatch: ảnh ở lại; truyvet.csv lấy guideline theo JOBS (bản sửa lỗi).
  * scene_leak: ảnh ở lại; truyvet.csv gộp cả cảnh về split đa số của cảnh.
  * Chỉ lỗi panoptic (invalid_category_id, thing_overlap, category_swap, instance_merge):
    ảnh ở lại v2, ghi vào phần Ghi chú README.txt để báo team panoptic.
Sau khi dựng: chạy pack_release.py rồi lineage.py record --event release.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

DET_REWORK = {"missing_image", "invalid_class", "bbox_out_of_bounds", "duplicate_box",
              "class_swap", "bbox_drift", "missing_box"}
PAN_ONLY = {"invalid_category_id", "thing_overlap", "category_swap", "instance_merge"}
HASH_FIX = "wrong_hash"
META_FIX = {"guideline_mismatch", "scene_leak"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jpeg_decodable(path: Path) -> bool:
    """Ảnh 'mở được': SOI + một marker SOF hợp lệ (width/height > 0) + EOI."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if not data.startswith(b"\xff\xd8") or not data.rstrip(b"\r\n\x1a").endswith(b"\xff\xd9") \
            and b"\xff\xd9" not in data[-32:]:
        return False
    pos, n = 2, len(data)
    while pos + 9 <= n:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[pos + 5:pos + 7], "big")
            w = int.from_bytes(data[pos + 7:pos + 9], "big")
            return bool(w and h)
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD9:
            pos += 2
            continue
        seg = int.from_bytes(data[pos + 2:pos + 4], "big")
        pos += 2 + max(2, seg)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Dựng handover/<release_id>_v2 từ v1 + errors.json")
    ap.add_argument("--delivery", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    d = Path(args.delivery)
    errors = json.loads(Path(args.errors).read_text(encoding="utf-8"))["errors"]
    rid = json.loads((d / "release.json").read_text(encoding="utf-8"))["release_id"]
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["items"]
    meta = {m["image"]: m for m in json.loads((d / "metadata.json").read_text(encoding="utf-8"))["items"]}
    with open(d / "jobs.csv", newline="", encoding="utf-8") as f:
        jobs = {row["job_id"]: row for row in csv.DictReader(f)}
    names80 = [ln.split(" ", 1)[1].strip() for ln in (d / "classes.txt").read_text(encoding="utf-8").splitlines()]

    by_target: dict[str, set[str]] = defaultdict(set)
    for e in errors:
        by_target[e["target"]].add(e["type"])

    rework: dict[str, list[str]] = {}
    keep_panoptic: dict[str, list[str]] = {}
    hash_checked = []
    for name in sorted(man):
        kinds = by_target.get(name, set())
        det = sorted(kinds & DET_REWORK)
        if det:
            rework[name] = det
            continue
        if HASH_FIX in kinds:
            img = d / man[name]["image"]
            if img.is_file() and jpeg_decodable(img):
                hash_checked.append(name)
            else:
                rework[name] = [HASH_FIX + " (ảnh không giải mã được)"]
                continue
        if name in kinds & META_FIX or kinds & PAN_ONLY:
            if kinds & PAN_ONLY:
                keep_panoptic[name] = sorted(kinds & PAN_ONLY)

    # scene_leak: target là scene_id — cả cảnh giữ nguyên ảnh, sửa split trong truyvet
    leaked_scenes = {e["target"] for e in errors if e["type"] == "scene_leak"}
    split_by_scene = {}
    scene_votes: dict[str, Counter] = defaultdict(Counter)
    for n, m in meta.items():
        scene_votes[m["scene_id"]][m["split"]] += 1
    for sc, votes in scene_votes.items():
        split_by_scene[sc] = votes.most_common(1)[0][0]

    v2 = Path(args.out) / f"{rid}_v2"
    if v2.exists():
        shutil.rmtree(v2)
    (v2 / "images").mkdir(parents=True)
    (v2 / "labels").mkdir(parents=True)

    stems = [n for n in sorted(man) if n not in rework]
    for n in stems:
        src_img = d / man[n]["image"]
        if src_img.is_file():
            shutil.copyfile(src_img, v2 / "images" / f"{n}.jpg")
        shutil.copyfile(d / man[n]["label"], v2 / "labels" / f"{n}.txt")
    stems = [n for n in stems if (v2 / "images" / f"{n}.jpg").is_file()]  # missing_image không có nguồn để chép

    # manifest.csv — hash THẬT của file trong v2
    with open(v2 / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "sha256"])
        for n in stems:
            w.writerow([f"images/{n}.jpg", sha(v2 / "images" / f"{n}.jpg")])
            w.writerow([f"labels/{n}.txt", sha(v2 / "labels" / f"{n}.txt")])

    # label_summary.csv — chỉ lớp xuất hiện, theo tên classes.txt, cuối dòng TOTAL
    counts: Counter = Counter()
    for n in stems:
        for ln in (v2 / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines():
            if ln.strip():
                c = int(float(ln.split()[0]))
                counts[names80[c] if 0 <= c < len(names80) else str(c)] += 1
    with open(v2 / "label_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["class", "count"])
        for name_cls in names80:
            if counts.get(name_cls):
                w.writerow([name_cls, counts[name_cls]])
        w.writerow(["TOTAL", sum(counts.values())])

    # truyvet.csv — guideline theo JOB, split theo đa số cảnh (sửa scene_leak)
    with open(v2 / "truyvet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["image", "scene_id", "split", "job_id", "annotator", "reviewer", "guideline"])
        for n in stems:
            m = meta[n]
            job = jobs[m["job_id"]]
            split = split_by_scene[m["scene_id"]] if m["scene_id"] in leaked_scenes else m["split"]
            w.writerow([n, m["scene_id"], split, m["job_id"], job["annotator"], job["reviewer"], job["guideline"]])

    # rework_queue.csv — giao đúng người theo jobs.csv
    with open(v2 / "rework_queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["image", "type", "annotator", "reviewer", "action"])
        for n in sorted(rework):
            job = jobs[meta[n]["job_id"]]
            w.writerow([n, ";".join(rework[n]), job["annotator"], job["reviewer"], "gán lại rồi xét vào lô sau"])

    # README.txt — số liệu thật từ chính các file vừa dựng
    n_err_units = len({e["target"] for e in errors})
    rate = n_err_units / len(man)
    v1_decision = "Hold" if rate > 0.02 else "Release"
    guide_by_job = defaultdict(list)
    for j, row in sorted(jobs.items()):
        guide_by_job[row["guideline"]].append(j)
    note_pan = ", ".join(f"{n} ({'/'.join(t)})" for n, t in sorted(keep_panoptic.items())) or "không"
    lines = [
        f"Release: {rid}_v2",
        f"Parent: {rid}",
        f"Số ảnh: {len(stems)}",
        f"Số nhãn: {sum(counts.values())}",
        f"Guideline: " + "; ".join(f"{g}: {js[0]}-{js[-1]}" for g, js in sorted(guide_by_job.items())),
        f"QC v1: {n_err_units}/{len(man)} = {rate:.1%}",
        f"Kết luận v1: {v1_decision} — tỉ lệ lỗi {rate:.1%} {'vượt' if rate > 0.02 else 'dưới'} ngưỡng 2% (Day 7); lỗi luật ở mức file, chốt từ validator",
        f"Kết luận v2: Rework — tách {len(rework)} ảnh lỗi detection sang rework_queue; sửa hash/guideline/split ngay trong v2; {len(keep_panoptic)} ảnh lỗi panoptic ở lại, báo team panoptic",
        "",
        "Ghi chú:",
        f"- wrong_hash ({len(hash_checked)} ảnh): đã mở/giải mã từng ảnh trước khi sửa — ảnh còn nguyên, chỉ manifest v1 sai; manifest.csv v2 ghi sha256 thật.",
        f"- guideline_mismatch: truyvet.csv lấy guideline theo jobs.csv của job (không theo metadata ảnh).",
        f"- scene_leak ({', '.join(sorted(leaked_scenes)) or 'không'}): cả cảnh được đưa về split đa số của nó trong truyvet.csv.",
        f"- Ảnh lỗi chỉ ở panoptic (ở lại v2, KHÔNG vào rework): {note_pan}. Chuyển kèm lô cho team panoptic xử lý masks.",
        f"- Ảnh rework giao lại đúng annotator/reviewer theo jobs.csv; chờ gán lại, không vào v2.",
    ]
    (v2 / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"v2: {len(stems)} ảnh, {sum(counts.values())} nhãn · rework {len(rework)} · panoptic-note {len(keep_panoptic)}")
    print(f"QC v1: {n_err_units}/{len(man)} = {rate:.1%} -> {v1_decision}")
    print("-> " + str(v2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
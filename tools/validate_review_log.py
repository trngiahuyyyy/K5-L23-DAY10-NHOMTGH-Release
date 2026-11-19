#!/usr/bin/env python3
"""Merge and validate team `review_log.csv` files against Day 10 Rubric & H3 rules.

Capabilities:
  1. Merge multiple member CSV files into a single deduplicated `review_log.csv`.
  2. Validate schema (`image,type,verdict,note`), valid semantic types, valid verdicts,
     note length >= 20 chars, note uniqueness >= 70% (exact H3 rule), and duplicate keys.
  3. Optionally check coverage against `candidates.json` or `errors.json`.

Usage examples:
  python tools/validate_review_log.py --check runs/r3056/review_log.csv
  python tools/validate_review_log.py --merge part1.csv part2.csv --out runs/r3056/review_log.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

SEMANTIC_TYPES = {
    "class_swap",
    "bbox_drift",
    "missing_box",
    "category_swap",
    "instance_merge",
}
VALID_VERDICTS = {"confirmed", "rejected"}
REQUIRED_COLUMNS = ["image", "type", "verdict", "note"]


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows and validate required header columns."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(col not in reader.fieldnames for col in REQUIRED_COLUMNS):
            raise SystemExit(f"{path}: thiếu cột bắt buộc {REQUIRED_COLUMNS} (thấy: {reader.fieldnames})")
        return [
            {col: (row.get(col) or "").strip() for col in REQUIRED_COLUMNS}
            for row in reader
            if any((v or "").strip() for v in row.values())
        ]


def validate_rows(rows: list[dict[str, str]], errors_path: Path | None = None) -> tuple[bool, list[str]]:
    """Validate review log rows against H3 and rubric criteria."""
    issues: list[str] = []
    if not rows:
        issues.append("review_log.csv không có dòng dữ liệu nào.")
        return False, issues

    seen_pairs: set[tuple[str, str]] = set()
    notes: list[str] = []
    confirmed_pairs: set[tuple[str, str]] = set()

    for line_no, row in enumerate(rows, start=2):
        img = Path(row["image"]).stem
        kind = row["type"]
        verdict = row["verdict"]
        note = row["note"]

        if not img:
            issues.append(f"Dòng {line_no}: thiếu tên ảnh.")
        if kind not in SEMANTIC_TYPES:
            issues.append(f"Dòng {line_no} ({img}): type '{kind}' không thuộc lỗi gán nhãn {sorted(SEMANTIC_TYPES)}.")
        if verdict not in VALID_VERDICTS:
            issues.append(f"Dòng {line_no} ({img}): verdict '{verdict}' không hợp lệ (chỉ nhận confirmed/rejected).")
        if len(note) < 20:
            issues.append(f"Dòng {line_no} ({img}): note quá ngắn ({len(note)}/20 ký tự): '{note}'.")
        if (kind, img) in seen_pairs:
            issues.append(f"Dòng {line_no}: trùng lặp cặp ({kind}, {img}).")
        seen_pairs.add((kind, img))
        notes.append(note)
        if verdict == "confirmed":
            confirmed_pairs.add((kind, img))

    unique_ratio = len(set(notes)) / len(notes)
    if unique_ratio < 0.7:
        issues.append(
            f"Tỷ lệ ghi chú khác nhau quá thấp: {len(set(notes))}/{len(notes)} = {unique_ratio:.0%} (H3 yêu cầu >= 70%)."
        )

    if errors_path and errors_path.is_file():
        errors = json.loads(errors_path.read_text(encoding="utf-8")).get("errors", [])
        needed = {(e["type"], e["target"]) for e in errors if e["type"] in SEMANTIC_TYPES}
        missing = sorted(needed - confirmed_pairs)
        if missing:
            issues.append(f"Thiếu {len(missing)} lỗi gán nhãn từ errors.json chưa có dòng confirmed: {missing[:5]}")

    return len(issues) == 0, issues


def merge_files(paths: list[Path], out_path: Path) -> list[dict[str, str]]:
    """Merge multiple member review CSVs, keeping the latest non-empty verdict per (type, image)."""
    merged: dict[tuple[str, str], dict[str, str]] = {}
    for path in paths:
        for row in read_rows(path):
            stem = Path(row["image"]).stem
            row["image"] = stem
            key = (row["type"], stem)
            merged[key] = row

    ordered = sorted(merged.values(), key=lambda r: (r["image"], r["type"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    return ordered


def main() -> int:
    ap = argparse.ArgumentParser(description="Gộp và kiểm tra review_log.csv theo chuẩn H3")
    ap.add_argument("--check", help="Đường dẫn tới review_log.csv cần kiểm tra")
    ap.add_argument("--merge", nargs="+", help="Danh sách các file CSV thành phần để gộp")
    ap.add_argument("--out", help="Đường dẫn file đầu ra khi dùng --merge")
    ap.add_argument("--errors", help="Đường dẫn errors.json để đối chiếu đủ dòng confirmed (tùy chọn)")
    args = ap.parse_args()

    if args.merge:
        if not args.out:
            raise SystemExit("Cần truyền --out khi sử dụng --merge")
        rows = merge_files([Path(p) for p in args.merge], Path(args.out))
        print(f"Đã gộp {len(rows)} dòng -> {args.out}")
    elif args.check:
        rows = read_rows(Path(args.check))
    else:
        raise SystemExit("Cần truyền --check hoặc --merge")

    errors_path = Path(args.errors) if args.errors else None
    ok, issues = validate_rows(rows, errors_path=errors_path)
    conf = sum(1 for r in rows if r["verdict"] == "confirmed")
    rej = sum(1 for r in rows if r["verdict"] == "rejected")
    print(f"Tổng kết: {len(rows)} dòng (confirmed={conf}, rejected={rej})")
    if ok:
        print("PASS: review_log.csv hợp lệ theo chuẩn H3.")
        return 0
    print("FAIL: phát hiện vấn đề:")
    for item in issues:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

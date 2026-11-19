#!/usr/bin/env python3
"""Công cụ truy vết ticket của team AI cho Day 10 Lab (Pha 5 & Đề ẩn).

Chỉ đọc thư mục delivery được truyền vào, chỉ dùng thư viện chuẩn Python 3.10+.
Ví dụ:
  python3 tools/trace_query.py runs/r3056/delivery --out runs/r3056/trace.json --verbose
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


def load_classes(delivery_dir: Path) -> tuple[dict[str, int], dict[int, str]]:
    """Đọc classes.txt -> (name_to_id, id_to_name), giữ nguyên tên lớp nhiều từ."""
    path = delivery_dir / "classes.txt"
    name_to_id: dict[str, int] = {}
    id_to_name: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_id, name = stripped.split(" ", 1)
        class_id = int(raw_id)
        class_name = name.strip()
        name_to_id[class_name] = class_id
        id_to_name[class_id] = class_name
    if not name_to_id:
        raise ValueError(f"Không đọc được lớp nào từ {path}")
    return name_to_id, id_to_name


def load_jobs(delivery_dir: Path) -> dict[str, dict[str, str]]:
    """Đọc jobs.csv -> map job_id -> {annotator, reviewer, guideline}."""
    path = delivery_dir / "jobs.csv"
    jobs: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            job_id = row["job_id"].strip()
            jobs[job_id] = {
                "annotator": row["annotator"].strip(),
                "reviewer": row["reviewer"].strip(),
                "guideline": row["guideline"].strip(),
            }
    if not jobs:
        raise ValueError(f"Không đọc được job nào từ {path}")
    return jobs


def load_delivery_index(delivery_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Đọc manifest.json (items) và metadata.json (items theo image stem)."""
    manifest_doc = json.loads((delivery_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata_doc = json.loads((delivery_dir / "metadata.json").read_text(encoding="utf-8"))
    manifest_items = manifest_doc.get("items", {})
    metadata_by_image = {item["image"]: item for item in metadata_doc.get("items", [])}
    if not manifest_items or not metadata_by_image:
        raise ValueError(f"Thiếu items trong manifest.json hoặc metadata.json tại {delivery_dir}")
    return manifest_items, metadata_by_image


def parse_ticket_scenes(ticket_text: str, valid_scenes: set[str]) -> list[str]:
    """Trích xuất các scene_id thật xuất hiện trong incoming/ticket.md."""
    found: list[str] = []
    # Sắp xếp dài trước để an toàn, nhưng vẫn kiểm ranh giới từ để scene_1 không khớp vào scene_10.
    for scene_id in sorted(valid_scenes, key=lambda s: (-len(s), s)):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(scene_id)}(?![A-Za-z0-9_])"
        if re.search(pattern, ticket_text):
            found.append(scene_id)
    found_sorted = sorted(set(found))
    if not found_sorted:
        raise ValueError("Không tìm thấy scene_id hợp lệ nào trong incoming/ticket.md; dùng --scenes để chỉ định.")
    return found_sorted


def _version_key(version: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version)
    return tuple(int(part) for part in nums) if nums else (0,)


def _extract_old_guideline(changelog_text: str, valid_guidelines: set[str]) -> str:
    """Tìm phiên bản guideline cũ từ changelog.md, đối chiếu với jobs.csv."""
    by_lower = {g.lower(): g for g in valid_guidelines}

    # 1. Ưu tiên mẫu chuyển đổi tường minh như: v1.2 -> v1.3 hoặc v1.2 → v1.3
    transition = re.search(
        r"\b(v\d+(?:\.\d+)+)\s*(?:->|→|sang|to)\s*(v\d+(?:\.\d+)+)\b",
        changelog_text,
        flags=re.IGNORECASE,
    )
    if transition:
        candidate = transition.group(1).lower()
        return by_lower.get(candidate, candidate)

    # 2. Nếu changelog nhắc từ 2 phiên bản trở lên (ví dụ v1.3 và v1.2), lấy phiên bản nhỏ nhất.
    mentioned = {m.lower() for m in re.findall(r"\bv\d+(?:\.\d+)+\b", changelog_text, flags=re.IGNORECASE)}
    if len(mentioned) >= 2:
        oldest = min(mentioned, key=_version_key)
        return by_lower.get(oldest, oldest)

    # 3. Fallback: dựa vào tập guideline có trong jobs.csv khi có từ 2 phiên bản trở lên.
    if len(valid_guidelines) >= 2:
        return min(valid_guidelines, key=_version_key)

    raise ValueError("Không xác định được phiên bản guideline cũ; dùng --old-guideline để chỉ định.")


def _extract_target_class(changelog_text: str, class_to_id: dict[str, int]) -> str:
    """Tìm tên lớp bị đổi quy tắc trong changelog.md theo danh sách classes.txt."""
    canonical_by_lower = {name.lower(): name for name in class_to_id}

    # 1. Ưu tiên mẫu khai báo rõ: Lớp `cup`: hoặc Lớp cup:
    explicit = re.findall(r"Lớp\s+`([^`]+)`|Lớp\s+([A-Za-z0-9_ ]+?)\s*:", changelog_text, flags=re.IGNORECASE)
    explicit_matches = []
    for backticked, plain in explicit:
        raw = (backticked or plain).strip().lower()
        if raw in canonical_by_lower:
            explicit_matches.append(canonical_by_lower[raw])
    explicit_unique = sorted(set(explicit_matches))
    if len(explicit_unique) == 1:
        return explicit_unique[0]

    # 2. Tìm theo token nằm trong dấu backtick ``...``
    backtick_matches = []
    for token in re.findall(r"`([^`]+)`", changelog_text):
        key = token.strip().lower()
        if key in canonical_by_lower:
            backtick_matches.append(canonical_by_lower[key])
    backtick_unique = sorted(set(backtick_matches))
    if len(backtick_unique) == 1:
        return backtick_unique[0]

    # 3. Fallback: quét 80 tên lớp dài trước -> ngắn sau với ranh giới từ đầy đủ.
    #    Nếu một dòng đã khớp lớp dài hơn (ví dụ 'hot dog'), bỏ phần chữ đó trước khi khớp lớp ngắn ('dog').
    lowered_text = changelog_text.lower()
    matched_classes: set[str] = set()
    masked = lowered_text
    for name in sorted(class_to_id, key=lambda s: (-len(s), s)):
        pattern = rf"(?<![a-z0-9_]){re.escape(name.lower())}(?![a-z0-9_])"
        if re.search(pattern, masked):
            matched_classes.add(name)
            masked = re.sub(pattern, " ", masked)

    if len(matched_classes) == 1:
        return next(iter(matched_classes))
    if len(matched_classes) > 1:
        raise ValueError(
            f"Tìm thấy nhiều tên lớp trong changelog ({sorted(matched_classes)}); dùng --class-name để chỉ định."
        )
    raise ValueError("Không tìm thấy tên lớp hợp lệ nào trong changelog.md; dùng --class-name để chỉ định.")


def parse_changelog(
    changelog_text: str,
    class_to_id: dict[str, int],
    valid_guidelines: set[str],
) -> tuple[str, str]:
    """Trả về (old_guideline, target_class_name) từ guideline/changelog.md."""
    old_guideline = _extract_old_guideline(changelog_text, valid_guidelines)
    target_class = _extract_target_class(changelog_text, class_to_id)
    return old_guideline, target_class


def label_has_class(label_path: Path, target_class_id: int) -> bool:
    """Trả về True nếu file nhãn detection có ít nhất một box thuộc target_class_id."""
    if not label_path.is_file():
        return False
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        try:
            class_id = int(float(parts[0]))
        except ValueError:
            continue
        if class_id == target_class_id:
            return True
    return False


def build_trace(
    delivery_dir: Path,
    *,
    scenes_override: list[str] | None = None,
    old_guideline_override: str | None = None,
    class_name_override: str | None = None,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Tính toán trace.json (tier_a, tier_b, notify) dựa trên guideline của job."""
    if not delivery_dir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục delivery: {delivery_dir}")

    class_to_id, _ = load_classes(delivery_dir)
    jobs = load_jobs(delivery_dir)
    manifest_items, metadata_by_image = load_delivery_index(delivery_dir)

    valid_scenes = {item["scene_id"] for item in metadata_by_image.values()}
    valid_guidelines = {job["guideline"] for job in jobs.values()}

    if scenes_override is not None:
        reported_scenes = sorted({s.strip() for s in scenes_override if s.strip()})
        unknown_scenes = [s for s in reported_scenes if s not in valid_scenes]
        if unknown_scenes:
            raise ValueError(f"scene không tồn tại trong lô: {unknown_scenes}")
    else:
        ticket_text = (delivery_dir / "incoming" / "ticket.md").read_text(encoding="utf-8")
        reported_scenes = parse_ticket_scenes(ticket_text, valid_scenes)

    changelog_text: str | None = None
    if not old_guideline_override or not class_name_override:
        changelog_text = (delivery_dir / "guideline" / "changelog.md").read_text(encoding="utf-8")

    if old_guideline_override:
        old_guideline = old_guideline_override.strip()
        if old_guideline not in valid_guidelines:
            raise ValueError(f"Guideline '{old_guideline}' không có trong jobs.csv ({sorted(valid_guidelines)})")
    else:
        assert changelog_text is not None
        old_guideline = _extract_old_guideline(changelog_text, valid_guidelines)

    if class_name_override:
        canonical = {name.lower(): name for name in class_to_id}.get(class_name_override.strip().lower())
        if canonical is None:
            raise ValueError(f"Lớp '{class_name_override}' không có trong classes.txt")
        target_class = canonical
    else:
        assert changelog_text is not None
        target_class = _extract_target_class(changelog_text, class_to_id)
    target_class_id = class_to_id[target_class]

    reported_scene_set = set(reported_scenes)
    tier_a: set[str] = set()
    tier_b: set[str] = set()
    affected_jobs: set[str] = set()
    mismatched_images: list[dict[str, str]] = []

    for image_name, man_item in manifest_items.items():
        meta = metadata_by_image.get(image_name)
        if meta is None:
            raise ValueError(f"Ảnh {image_name} có trong manifest.json nhưng thiếu trong metadata.json")
        job_id = meta["job_id"]
        job = jobs.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} của ảnh {image_name} không tồn tại trong jobs.csv")

        # Quy tắc bắt buộc: dùng guideline theo job (jobs.csv), KHÔNG dùng meta["guideline_version"]
        # vì ảnh có thể mang lỗi guideline_mismatch.
        job_guideline = job["guideline"]
        image_guideline = meta.get("guideline_version", "")
        if image_guideline != job_guideline:
            mismatched_images.append(
                {
                    "image": image_name,
                    "job_id": job_id,
                    "scene_id": meta["scene_id"],
                    "metadata_guideline": image_guideline,
                    "job_guideline": job_guideline,
                }
            )

        if job_guideline != old_guideline:
            continue

        label_rel = man_item.get("label") or f"labels/{image_name}.txt"
        if not label_has_class(delivery_dir / label_rel, target_class_id):
            continue

        affected_jobs.add(job_id)
        if meta["scene_id"] in reported_scene_set:
            tier_a.add(image_name)
        else:
            tier_b.add(image_name)

    notify: set[str] = set()
    for job_id in affected_jobs:
        notify.add(jobs[job_id]["annotator"])
        notify.add(jobs[job_id]["reviewer"])

    trace = {
        "tier_a": sorted(tier_a),
        "tier_b": sorted(tier_b),
        "notify": sorted(notify),
    }
    debug_info = {
        "reported_scenes": reported_scenes,
        "old_guideline": old_guideline,
        "target_class": target_class,
        "target_class_id": target_class_id,
        "affected_jobs": sorted(affected_jobs),
        "guideline_mismatches_seen": mismatched_images,
    }
    return trace, debug_info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Truy vết ticket team AI -> trace.json")
    parser.add_argument("delivery", help="Đường dẫn tới thư mục delivery của lô")
    parser.add_argument("--out", required=True, help="Đường dẫn file trace.json đầu ra")
    parser.add_argument("--scenes", help="Override danh sách scene_id (cách nhau bởi dấu phẩy)")
    parser.add_argument("--old-guideline", help="Override phiên bản guideline cũ (vd: v1.2)")
    parser.add_argument("--class-name", help="Override tên lớp bị đổi quy tắc (vd: 'traffic light')")
    parser.add_argument("--verbose", action="store_true", help="In tóm tắt thông tin đã phân tích")
    args = parser.parse_args(argv)

    scenes_override = [s.strip() for s in args.scenes.split(",") if s.strip()] if args.scenes else None
    trace, info = build_trace(
        Path(args.delivery),
        scenes_override=scenes_override,
        old_guideline_override=args.old_guideline,
        class_name_override=args.class_name,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.verbose:
        print(f"delivery: {args.delivery}")
        print(f"reported_scenes: {info['reported_scenes']}")
        print(f"old_guideline: {info['old_guideline']}")
        print(f"target_class: {info['target_class']} (id={info['target_class_id']})")
        print(f"tier_a ({len(trace['tier_a'])}): {trace['tier_a']}")
        print(f"tier_b ({len(trace['tier_b'])}): {trace['tier_b']}")
        print(f"affected_jobs: {info['affected_jobs']}")
        print(f"notify ({len(trace['notify'])}): {trace['notify']}")
        if info["guideline_mismatches_seen"]:
            print(f"guideline_mismatch gặp trong lô (đã lấy theo jobs.csv): {info['guideline_mismatches_seen']}")
    print(f"Đã ghi {out_path} (tier_a={len(trace['tier_a'])}, tier_b={len(trace['tier_b'])}, notify={len(trace['notify'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

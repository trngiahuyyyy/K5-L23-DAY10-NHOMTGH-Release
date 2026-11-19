#!/usr/bin/env python3
"""Validator của nhóm — Pha 1 (9 lỗi luật) + cổng mở rộng cho Pha 2 (--candidates).

Cách chạy:
    python validator/validate.py <thư_mục_delivery> --out <errors.json> [--candidates <candidates.json>]

Nguyên tắc (RULES.md):
- Chỉ đọc thư mục delivery được truyền vào.
- Không đọc _private/, data_source/, annotation COCO, không dùng mạng.
- Chỉ dùng thư viện chuẩn của Python + scripts/pngutil.py.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# Cho phép import pngutil.py (thư viện chuẩn) và crosscheck.py (nếu có)
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
VALIDATOR_DIR = Path(__file__).resolve().parent
for extra in (SCRIPTS_DIR, VALIDATOR_DIR):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import pngutil  # noqa: E402


# Ngưỡng kiểm tra lỗi luật (chọn dựa trên định dạng YOLO/COCO và xác minh trên lô sạch)
BBOX_EDGE_EPS = 1e-3      # Dung sai làm tròn 6 chữ số thập phân ở mép ảnh [0, 1]
DUP_SIZE_TOL_PX = 1.0     # Hai box lặp có kích thước gần như giống hệt (chênh <= 1 px)
DUP_CENTER_TOL_PX = 3.5   # Tâm hai box lặp chỉ lệch 1-3 px


def sha256_file(path: Path) -> str:
    """Tính mã băm SHA-256 trên bytes gốc của file (chế độ nhị phân)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_delivery(delivery: Path) -> dict:
    """Đọc toàn bộ metadata cần thiết bên trong thư mục delivery."""
    manifest = json.loads((delivery / "manifest.json").read_text(encoding="utf-8"))["items"]
    meta_items = json.loads((delivery / "metadata.json").read_text(encoding="utf-8"))["items"]
    meta = {item["image"]: item for item in meta_items}

    with (delivery / "jobs.csv").open(encoding="utf-8", newline="") as f:
        jobs = {row["job_id"]: row for row in csv.DictReader(f)}

    valid_classes: dict[int, str] = {}
    for line in (delivery / "classes.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cid_str, cname = line.split(" ", 1)
        valid_classes[int(cid_str)] = cname.strip()

    panoptic = json.loads((delivery / "panoptic.json").read_text(encoding="utf-8"))
    image_sizes = {
        Path(im["file_name"]).stem: (int(im["width"]), int(im["height"]))
        for im in panoptic["images"]
    }
    cat_by_id = {int(c["id"]): c for c in panoptic["categories"]}

    return {
        "manifest": manifest,
        "meta": meta,
        "jobs": jobs,
        "valid_classes": valid_classes,
        "panoptic": panoptic,
        "image_sizes": image_sizes,
        "cat_by_id": cat_by_id,
    }


def check_yolo_label(
    label_path: Path,
    width: int,
    height: int,
    valid_class_ids: set[int],
) -> str | None:
    """Kiểm tra 3 lỗi luật detection trên 1 file nhãn YOLO.

    Thứ tự ưu tiên: invalid_class -> bbox_out_of_bounds -> duplicate_box.
    """
    boxes_px: list[tuple[int, float, float, float, float]] = []

    for raw in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw.split()
        if not parts:
            continue
        if len(parts) < 5:
            return "invalid_class"

        # 1. Kiểm tra class_id hợp lệ (số nguyên nằm trong danh sách lớp 0..79)
        try:
            cls_id = int(parts[0])
        except ValueError:
            return "invalid_class"
        if cls_id not in valid_class_ids:
            return "invalid_class"

        # 2. Kiểm tra tọa độ box chuẩn hóa có tràn ra ngoài [0, 1] không
        try:
            xc, yc, bw, bh = map(float, parts[1:5])
        except ValueError:
            return "bbox_out_of_bounds"

        if (
            bw <= 0.0
            or bh <= 0.0
            or xc - bw / 2.0 < -BBOX_EDGE_EPS
            or yc - bh / 2.0 < -BBOX_EDGE_EPS
            or xc + bw / 2.0 > 1.0 + BBOX_EDGE_EPS
            or yc + bh / 2.0 > 1.0 + BBOX_EDGE_EPS
        ):
            return "bbox_out_of_bounds"

        boxes_px.append((cls_id, xc * width, yc * height, bw * width, bh * height))

    # 3. Kiểm tra duplicate_box: cùng lớp, có giao nhau, cùng kích thước, tâm chỉ lệch 1-3 px
    n = len(boxes_px)
    for i in range(n):
        c1, x1, y1, w1, h1 = boxes_px[i]
        for j in range(i + 1, n):
            c2, x2, y2, w2, h2 = boxes_px[j]
            if (
                c1 == c2
                and abs(w1 - w2) <= DUP_SIZE_TOL_PX
                and abs(h1 - h2) <= DUP_SIZE_TOL_PX
                and abs(x1 - x2) <= DUP_CENTER_TOL_PX
                and abs(y1 - y2) <= DUP_CENTER_TOL_PX
            ):
                # Đảm bảo hai box thực sự chồng lên nhau (tránh 2 vật nhỏ đứng sát nhau)
                ix = min(x1 + w1 / 2.0, x2 + w2 / 2.0) - max(x1 - w1 / 2.0, x2 - w2 / 2.0)
                iy = min(y1 + h1 / 2.0, y2 + h2 / 2.0) - max(y1 - h1 / 2.0, y2 - h2 / 2.0)
                if ix > 0.0 and iy > 0.0:
                    return "duplicate_box"

    return None


def count_mask_pixels(mask_path: Path) -> tuple[int, int, bytearray, dict[int, int]]:
    """Đọc mask PNG RGB và đếm số pixel thực của từng segment_id (bỏ id = 0 là nền)."""
    width, height, pixels = pngutil.read_rgb(mask_path)
    rgb_counts = Counter(zip(pixels[0::3], pixels[1::3], pixels[2::3]))
    seg_counts: dict[int, int] = {}
    for (r, g, b), cnt in rgb_counts.items():
        sid = r + (g << 8) + (b << 16)
        if sid != 0:
            seg_counts[sid] = cnt
    return width, height, pixels, seg_counts


def check_rules(
    delivery: Path,
    data: dict,
    keep_masks: bool = False,
) -> tuple[dict[str, str], dict[str, tuple[int, int, bytearray]]]:
    """Kiểm tra đủ 9 lỗi luật trên thư mục delivery.

    Trả về:
        errors: dict ánh xạ target -> error_type (mỗi target nhiều nhất 1 lỗi)
        mask_cache: cache ảnh mask đã đọc (nếu keep_masks=True để Pha 2 dùng lại)
    """
    manifest = data["manifest"]
    meta = data["meta"]
    jobs = data["jobs"]
    valid_class_ids = set(data["valid_classes"])
    panoptic = data["panoptic"]
    image_sizes = data["image_sizes"]
    cat_by_id = data["cat_by_id"]

    errors: dict[str, str] = {}
    mask_cache: dict[str, tuple[int, int, bytearray]] = {}

    def record(err_type: str, target: str) -> None:
        errors.setdefault(target, err_type)

    # --- A. Luật metadata cấp cảnh: scene_leak (target là scene_id) ---
    scene_splits: dict[str, set[str]] = {}
    for m in meta.values():
        scene_splits.setdefault(m["scene_id"], set()).add(m["split"])
    for scene_id, splits in sorted(scene_splits.items()):
        if len(splits) > 1:
            record("scene_leak", scene_id)

    # --- B. Luật cấp file, metadata ảnh và nhãn detection ---
    for name, item in sorted(manifest.items()):
        img_path = delivery / item["image"]
        label_path = delivery / item["label"]
        mask_path = delivery / item["mask"]

        # 1. missing_image
        if not img_path.is_file():
            record("missing_image", name)
            continue

        # 2. wrong_hash (so sha256 thực của ảnh, nhãn, mask với manifest)
        if sha256_file(img_path) != item["image_sha256"]:
            record("wrong_hash", name)
            continue
        if label_path.is_file() and sha256_file(label_path) != item["label_sha256"]:
            record("wrong_hash", name)
            continue
        if mask_path.is_file() and sha256_file(mask_path) != item["mask_sha256"]:
            record("wrong_hash", name)
            continue

        # 3. guideline_mismatch (so guideline ảnh với guideline của JOB trong jobs.csv)
        m = meta.get(name)
        if m is not None:
            job = jobs.get(m["job_id"])
            if job is not None and m["guideline_version"] != job["guideline"]:
                record("guideline_mismatch", name)
                continue

        # 4, 5, 6. invalid_class / bbox_out_of_bounds / duplicate_box
        if label_path.is_file() and name in image_sizes:
            w, h = image_sizes[name]
            det_err = check_yolo_label(label_path, w, h, valid_class_ids)
            if det_err is not None:
                record(det_err, name)

    # --- C. Luật panoptic: invalid_category_id và thing_overlap ---
    for ann in panoptic["annotations"]:
        name = Path(ann["file_name"]).stem
        segs = ann["segments_info"]

        # Kiểm invalid_category_id trước (không cần giải mã PNG)
        if name not in errors:
            if any(int(s["category_id"]) not in cat_by_id for s in segs):
                record("invalid_category_id", name)
                continue

        # Bỏ qua giải mã mask nếu ảnh đã có lỗi luật và không cần cache cho Pha 2
        if name in errors and not keep_masks:
            continue

        mask_path = delivery / "masks" / ann["file_name"]
        if not mask_path.is_file():
            continue

        width, height, pixels, seg_counts = count_mask_pixels(mask_path)
        if keep_masks:
            mask_cache[name] = (width, height, pixels)

        if name not in errors:
            # thing_overlap: area khai báo nhiều hơn số pixel thực tế của segment trong mask
            if any(int(s["area"]) > seg_counts.get(int(s["id"]), 0) for s in segs):
                record("thing_overlap", name)

    return errors, mask_cache


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validator kiểm tra lỗi luật (Pha 1) và xuất ứng viên đối chiếu (Pha 2)"
    )
    parser.add_argument("delivery", help="Đường dẫn thư mục delivery/")
    parser.add_argument("--out", required=True, help="File JSON ghi danh sách lỗi")
    parser.add_argument("--candidates", help="File JSON ghi ứng viên đối chiếu det <-> panoptic (Pha 2)")
    args = parser.parse_args()

    delivery = Path(args.delivery)
    if not delivery.is_dir():
        raise SystemExit(f"Không tìm thấy thư mục delivery: {delivery}")

    data = load_delivery(delivery)
    need_candidates = bool(args.candidates)
    errors, mask_cache = check_rules(delivery, data, keep_masks=need_candidates)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "errors": [
            {"type": err_type, "target": target}
            for target, err_type in sorted(errors.items(), key=lambda kv: (kv[1], kv[0]))
        ]
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[P1] Phát hiện {len(errors)} lỗi luật -> {out_path}")

    if need_candidates:
        cand_path = Path(args.candidates)
        cand_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import crosscheck  # type: ignore
        except ImportError:
            cand_payload = {"candidates": []}
            cand_path.write_text(json.dumps(cand_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[P2] Chưa có validator/crosscheck.py -> ghi danh sách rỗng vào {cand_path}")
        else:
            candidates = crosscheck.find_candidates(delivery, data, errors, mask_cache)
            cand_payload = {"candidates": candidates}
            cand_path.write_text(json.dumps(cand_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[P2] Phát hiện {len(candidates)} ứng viên đối chiếu -> {cand_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

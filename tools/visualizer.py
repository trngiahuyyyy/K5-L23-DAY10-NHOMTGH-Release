#!/usr/bin/env python3
"""Interactive Detection <-> Panoptic visualizer and HTML review board for Day 10 Lab.

Supports rendering individual images, filtered classes, or candidate lists
(`candidates.json`) into side-by-side annotated PNGs plus a self-contained HTML
review dashboard that exports a rubric-compliant `review_log.csv`.

Usage examples:
  python tools/visualizer.py runs/r3056/delivery --candidates submission/r3056/candidates.json --out runs/r3056/review_ui
  python tools/visualizer.py runs/r3056/delivery --images 000000000139,000000000285 --out runs/r3056/review_ui
  python tools/visualizer.py runs/r3056/delivery --filter-class cup --limit 20 --out runs/r3056/review_ui
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PALETTE = [
    (255, 99, 71),
    (50, 205, 50),
    (30, 144, 255),
    (255, 165, 0),
    (186, 85, 211),
    (0, 206, 209),
    (255, 20, 147),
    (255, 215, 0),
    (127, 255, 0),
    (220, 20, 60),
]

SEMANTIC_TYPES = [
    "class_swap",
    "category_swap",
    "bbox_drift",
    "missing_box",
    "instance_merge",
]


def load_font(size: int = 14) -> ImageFont.ImageFont:
    """Load a readable font, falling back to Pillow's default bitmap font."""
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def load_classes(delivery: Path) -> dict[int, str]:
    """Parse `classes.txt` mapping YOLO class_id -> class name."""
    classes: dict[int, str] = {}
    path = delivery / "classes.txt"
    if not path.is_file():
        return classes
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            classes[int(parts[0])] = parts[1].strip()
    return classes


def load_panoptic_index(delivery: Path) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load panoptic categories and per-image annotations keyed by image stem."""
    path = delivery / "panoptic.json"
    if not path.is_file():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    cats = {c["id"]: c for c in data.get("categories", [])}
    anns_by_stem: dict[str, dict[str, Any]] = {}
    for ann in data.get("annotations", []):
        stem = Path(ann["file_name"]).stem
        anns_by_stem[stem] = ann
    return cats, anns_by_stem


def load_yolo_boxes(label_path: Path, width: int, height: int, classes: dict[int, str]) -> list[dict[str, Any]]:
    """Convert normalized YOLO labels into pixel bounding boxes."""
    if not label_path.is_file():
        return []
    boxes: list[dict[str, Any]] = []
    for idx, line in enumerate(label_path.read_text(encoding="utf-8").splitlines()):
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(float(parts[0]))
        xc, yc, bw, bh = (float(v) for v in parts[1:5])
        x1 = (xc - bw / 2.0) * width
        y1 = (yc - bh / 2.0) * height
        x2 = (xc + bw / 2.0) * width
        y2 = (yc + bh / 2.0) * height
        boxes.append({
            "index": idx,
            "class_id": cls_id,
            "class_name": classes.get(cls_id, f"cls_{cls_id}"),
            "bbox_px": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        })
    return boxes


def decode_panoptic_overlay(
    mask_path: Path,
    base_rgb: Image.Image,
    segments_info: list[dict[str, Any]],
    cats: dict[int, dict[str, Any]],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Colorize panoptic thing segments on top of the RGB image and summarize segments."""
    overlay = base_rgb.convert("RGBA")
    summary: list[dict[str, Any]] = []
    if not mask_path.is_file():
        return overlay.convert("RGB"), summary

    mask_img = Image.open(mask_path).convert("RGB")
    mask_bytes = mask_img.tobytes()
    seg_lookup = {seg["id"]: seg for seg in segments_info}

    color_map: dict[int, tuple[int, int, int, int]] = {}
    for idx, seg in enumerate(segments_info):
        cat = cats.get(seg["category_id"], {})
        is_thing = cat.get("isthing", 1) == 1
        rgb = PALETTE[idx % len(PALETTE)]
        alpha = 115 if is_thing else 45
        color_map[seg["id"]] = (*rgb, alpha)
        x, y, w, h = seg.get("bbox", [0, 0, 0, 0])
        summary.append({
            "id": seg["id"],
            "category_id": seg["category_id"],
            "category_name": cat.get("name", f"cat_{seg['category_id']}"),
            "isthing": is_thing,
            "iscrowd": bool(seg.get("iscrowd", 0)),
            "area": seg.get("area", 0),
            "bbox_px": [x, y, x + w, y + h],
            "color": rgb,
        })

    out_rgba = bytearray(mask_img.width * mask_img.height * 4)
    for px_i in range(0, len(mask_bytes), 3):
        seg_id = mask_bytes[px_i] + (mask_bytes[px_i + 1] << 8) + (mask_bytes[px_i + 2] << 16)
        if seg_id in color_map and seg_id in seg_lookup:
            r, g, b, a = color_map[seg_id]
            out_i = (px_i // 3) * 4
            out_rgba[out_i] = r
            out_rgba[out_i + 1] = g
            out_rgba[out_i + 2] = b
            out_rgba[out_i + 3] = a

    seg_layer = Image.frombytes("RGBA", mask_img.size, bytes(out_rgba))
    blended = Image.alpha_composite(overlay, seg_layer)
    return blended.convert("RGB"), summary


def draw_label_tag(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    bg_color: tuple[int, int, int],
    font: ImageFont.ImageFont,
    img_w: int,
    img_h: int,
) -> None:
    """Draw a high-contrast pill tag clamped inside image bounds."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = max(0.0, min(x, img_w - tw - 6))
    ty = max(0.0, y - th - 4) if y - th - 4 >= 0 else min(img_h - th - 4, y + 2)
    draw.rectangle([tx, ty, tx + tw + 6, ty + th + 4], fill=bg_color)
    draw.text((tx + 3, ty + 2), text, fill=(255, 255, 255), font=font)


def upscale_if_small(img: Image.Image, min_width: int = 460) -> tuple[Image.Image, float]:
    """Upscale small images (e.g. 240x320) so labels remain legible."""
    w, h = img.size
    if w >= min_width:
        return img, 1.0
    scale = min_width / float(w)
    resized = img.resize((int(round(w * scale)), int(round(h * scale))), Image.Resampling.BILINEAR)
    return resized, scale


def make_placeholder(message: str, size: tuple[int, int] = (480, 360)) -> Image.Image:
    """Render a placeholder card when an image is missing or unreadable."""
    img = Image.new("RGB", size, (36, 40, 48))
    draw = ImageDraw.Draw(img)
    font = load_font(16)
    draw.text((24, size[1] // 2 - 12), message, fill=(255, 110, 110), font=font)
    return img


def normalize_bbox(raw_bbox: Any, width: int, height: int) -> list[float] | None:
    """Accept [x1, y1, x2, y2] or normalized YOLO [xc, yc, w, h]."""
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        return None
    vals = [float(v) for v in raw_bbox[:4]]
    if all(0.0 <= v <= 1.0 for v in vals) and (vals[2] <= 1.0 and vals[3] <= 1.0):
        x1 = (vals[0] - vals[2] / 2.0) * width
        y1 = (vals[1] - vals[3] / 2.0) * height
        x2 = (vals[0] + vals[2] / 2.0) * width
        y2 = (vals[1] + vals[3] / 2.0) * height
        return [x1, y1, x2, y2]
    return vals


def build_focus_crop(
    orig: Image.Image,
    pan_base: Image.Image,
    seg_bbox_xyxy: list[float] | None,
    cand_boxes: list[dict[str, Any]],
    out_file: Path,
) -> str | None:
    """Render a side-by-side (Raw Crop | Annotated Crop) image around candidate objects."""
    w, h = orig.size
    rects: list[list[float]] = []
    if seg_bbox_xyxy:
        rects.append(seg_bbox_xyxy)
    for b in cand_boxes:
        xyxy = b.get("xyxy")
        if isinstance(xyxy, (list, tuple)) and len(xyxy) >= 4:
            rects.append([float(v) for v in xyxy[:4]])

    if not rects:
        return None

    ux1 = min(r[0] for r in rects)
    uy1 = min(r[1] for r in rects)
    ux2 = max(r[2] for r in rects)
    uy2 = max(r[3] for r in rects)
    pad_x = max(24.0, (ux2 - ux1) * 0.25)
    pad_y = max(24.0, (uy2 - uy1) * 0.25)
    cx1 = max(0, int(ux1 - pad_x))
    cy1 = max(0, int(uy1 - pad_y))
    cx2 = min(w, int(ux2 + pad_x))
    cy2 = min(h, int(uy2 + pad_y))
    if cx2 - cx1 < 8 or cy2 - cy1 < 8:
        return None

    target_w, target_h = 340, 340
    scale_x = target_w / float(cx2 - cx1)
    scale_y = target_h / float(cy2 - cy1)

    raw_crop = orig.crop((cx1, cy1, cx2, cy2)).resize((target_w, target_h), Image.Resampling.BILINEAR)
    ann_crop = pan_base.crop((cx1, cy1, cx2, cy2)).resize((target_w, target_h), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(ann_crop)
    font = load_font(12)

    if seg_bbox_xyxy:
        sx1 = (seg_bbox_xyxy[0] - cx1) * scale_x
        sy1 = (seg_bbox_xyxy[1] - cy1) * scale_y
        sx2 = (seg_bbox_xyxy[2] - cx1) * scale_x
        sy2 = (seg_bbox_xyxy[3] - cy1) * scale_y
        draw.rectangle([sx1, sy1, sx2, sy2], outline=(255, 190, 0), width=3)

    for b in cand_boxes:
        xyxy = b.get("xyxy")
        if isinstance(xyxy, (list, tuple)) and len(xyxy) >= 4:
            bx1 = (float(xyxy[0]) - cx1) * scale_x
            by1 = (float(xyxy[1]) - cy1) * scale_y
            bx2 = (float(xyxy[2]) - cx1) * scale_x
            by2 = (float(xyxy[3]) - cy1) * scale_y
            draw.rectangle([bx1, by1, bx2, by2], outline=(0, 255, 130), width=3)
            draw_label_tag(draw, bx1, by1, f"D:{b.get('class', '?')}", (0, 140, 70), font, target_w, target_h)

    combo = Image.new("RGB", (target_w * 2 + 6, target_h + 24), (24, 26, 32))
    combo.paste(raw_crop, (0, 24))
    combo.paste(ann_crop, (target_w + 6, 24))
    cd = ImageDraw.Draw(combo)
    hfont = load_font(13)
    cd.text((6, 4), "Zoom: Raw Pixels", fill=(220, 225, 235), font=hfont)
    cd.text((target_w + 12, 4), "Zoom: Green=YOLO, Orange=Seg", fill=(255, 210, 90), font=hfont)
    combo.save(out_file)
    return f"images/{out_file.name}"


def render_image_bundle(
    delivery: Path,
    stem: str,
    cand_idx: int,
    classes: dict[int, str],
    cats: dict[int, dict[str, Any]],
    anns_by_stem: dict[str, dict[str, Any]],
    out_img_dir: Path,
    panel_cache: dict[str, dict[str, Any]],
    focus_bbox: Any = None,
    seg_bbox_xywh: Any = None,
    cand_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render side-by-side detection/panoptic panels (cached per image) and candidate crop."""
    img_path = delivery / "images" / f"{stem}.jpg"
    lbl_path = delivery / "labels" / f"{stem}.txt"
    mask_path = delivery / "masks" / f"{stem}.png"

    if not img_path.is_file():
        out_file = out_img_dir / f"{stem}_panel.png"
        if stem not in panel_cache:
            make_placeholder(f"MISSING IMAGE: {stem}.jpg").save(out_file)
            panel_cache[stem] = {
                "panel_rel": f"images/{out_file.name}",
                "width": 0,
                "height": 0,
                "det_boxes": [],
                "pan_segments": [],
                "missing": True,
            }
        return {**panel_cache[stem], "stem": stem, "crop_rel": None}

    try:
        orig = Image.open(img_path).convert("RGB")
    except OSError as exc:
        out_file = out_img_dir / f"{stem}_panel.png"
        if stem not in panel_cache:
            make_placeholder(f"CORRUPT IMAGE: {stem}.jpg ({exc})").save(out_file)
            panel_cache[stem] = {
                "panel_rel": f"images/{out_file.name}",
                "width": 0,
                "height": 0,
                "det_boxes": [],
                "pan_segments": [],
                "missing": True,
            }
        return {**panel_cache[stem], "stem": stem, "crop_rel": None}

    w, h = orig.size
    ann = anns_by_stem.get(stem, {})
    segments_info = ann.get("segments_info", [])
    pan_base, pan_summary = decode_panoptic_overlay(mask_path, orig, segments_info, cats)

    if stem not in panel_cache:
        det_boxes = load_yolo_boxes(lbl_path, w, h, classes)
        orig_up, scale = upscale_if_small(orig, min_width=460)
        uw, uh = orig_up.size
        font = load_font(13)

        det_panel = orig_up.copy()
        det_draw = ImageDraw.Draw(det_panel)
        for box in det_boxes:
            x1, y1, x2, y2 = [v * scale for v in box["bbox_px"]]
            det_draw.rectangle([x1, y1, x2, y2], outline=(0, 230, 118), width=3)
            draw_label_tag(det_draw, x1, y1, f"D:{box['class_name']}", (0, 140, 70), font, uw, uh)

        pan_panel, _ = upscale_if_small(pan_base, min_width=460)
        pan_draw = ImageDraw.Draw(pan_panel)
        for seg in pan_summary:
            if not seg["isthing"]:
                continue
            x1, y1, x2, y2 = [v * scale for v in seg["bbox_px"]]
            col = seg["color"]
            pan_draw.rectangle([x1, y1, x2, y2], outline=col, width=2)
            tag = f"P:{seg['category_name']}" + (" [crowd]" if seg["iscrowd"] else "")
            draw_label_tag(pan_draw, x1, y2 - 2, tag, col, font, uw, uh)

        header_h = 28
        gap = 8
        canvas = Image.new("RGB", (uw * 3 + gap * 2, uh + header_h), (24, 26, 32))
        canvas.paste(orig_up, (0, header_h))
        canvas.paste(det_panel, (uw + gap, header_h))
        canvas.paste(pan_panel, (uw * 2 + gap * 2, header_h))

        c_draw = ImageDraw.Draw(canvas)
        h_font = load_font(15)
        c_draw.text((8, 5), f"1. Original ({w}x{h})", fill=(220, 225, 235), font=h_font)
        c_draw.text((uw + gap + 8, 5), f"2. Detection YOLO ({len(det_boxes)} boxes)", fill=(120, 255, 170), font=h_font)
        thing_count = sum(1 for s in pan_summary if s["isthing"])
        c_draw.text((uw * 2 + gap * 2 + 8, 5), f"3. Panoptic Mask ({thing_count} things)", fill=(255, 200, 100), font=h_font)

        out_file = out_img_dir / f"{stem}_panel.png"
        canvas.save(out_file)
        panel_cache[stem] = {
            "panel_rel": f"images/{out_file.name}",
            "width": w,
            "height": h,
            "det_boxes": det_boxes,
            "pan_segments": [s for s in pan_summary if s["isthing"]],
            "missing": False,
        }

    # Build per-candidate zoom crop around disputed segment & boxes
    seg_xyxy = None
    if isinstance(seg_bbox_xywh, (list, tuple)) and len(seg_bbox_xywh) >= 4:
        sx, sy, sw, sh = [float(v) for v in seg_bbox_xywh[:4]]
        seg_xyxy = [sx, sy, sx + sw, sy + sh]
    elif focus_bbox is not None:
        seg_xyxy = normalize_bbox(focus_bbox, w, h)

    crop_file = out_img_dir / f"{stem}_c{cand_idx}_crop.png"
    crop_rel = build_focus_crop(orig, pan_base, seg_xyxy, cand_boxes or [], crop_file)

    return {**panel_cache[stem], "stem": stem, "crop_rel": crop_rel}


def load_candidates(path: Path) -> list[dict[str, Any]]:
    """Normalize candidate entries from `candidates.json` (supports teammate schema)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("candidates", raw) if isinstance(raw, dict) else raw
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        stem = str(item.get("image") or item.get("target") or "").strip()
        if not stem:
            continue
        stem = Path(stem).stem
        cand_type = str(item.get("type") or "class_swap").strip()
        possible = item.get("possible_types") or [cand_type]
        pan_cls = item.get("panoptic_class")
        boxes = item.get("boxes") or []
        seg_id = item.get("segment_id")

        reason = str(item.get("reason") or item.get("detail") or item.get("note") or "").strip()
        if not reason:
            parts = []
            if pan_cls:
                parts.append(f"P:{pan_cls}")
            if boxes:
                box_classes = ", ".join(str(b.get("class", "?")) for b in boxes)
                parts.append(f"D:[{box_classes}]")
            if seg_id is not None:
                parts.append(f"seg={seg_id}")
            if len(possible) > 1:
                parts.append(f"options={'/'.join(possible)}")
            reason = " | ".join(parts)

        normalized.append({
            "uid": f"{idx}_{stem}_{cand_type}_{seg_id or 0}",
            "image": stem,
            "type": cand_type,
            "possible_types": possible,
            "reason": reason,
            "bbox": item.get("bbox"),
            "segment_bbox_xywh": item.get("segment_bbox_xywh"),
            "boxes": boxes,
        })
    return normalized


def build_html_board(records: list[dict[str, Any]], out_dir: Path, delivery_name: str) -> Path:
    """Generate a self-contained interactive HTML review board that exports review_log.csv."""
    records_json = json.dumps(records, ensure_ascii=False)
    types_options = "".join(f'<option value="{t}">{t}</option>' for t in SEMANTIC_TYPES)

    template = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Day 10 Visual Review Board — __TITLE__</title>
<style>
  :root { --bg:#0f1218; --card:#171c26; --border:#2a3242; --text:#e5e9f0; --muted:#9aa5b8; --accent:#38bdf8; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--text); }
  header { position:sticky; top:0; z-index:10; background:#131720ee; backdrop-filter:blur(8px); border-bottom:1px solid var(--border); padding:12px 20px; display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
  .stats { font-size:13px; color:var(--muted); }
  .controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  button, select, input { background:#1f2633; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:7px 12px; font-size:13px; cursor:pointer; }
  button.primary { background:#0284c7; border-color:#0284c7; font-weight:600; }
  button.primary:hover { background:#0369a1; }
  main { max-width:1500px; margin:18px auto; padding:0 16px; display:flex; flex-direction:column; gap:18px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; display:flex; flex-direction:column; gap:12px; }
  .card.confirmed { border-left:5px solid var(--ok); }
  .card.rejected { border-left:5px solid var(--bad); }
  .card-head { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }
  .badge { font-size:12px; padding:3px 8px; border-radius:999px; background:#263042; font-family:monospace; }
  .img-wrap { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-start; }
  .img-wrap img.panel { max-width:100%; height:auto; border-radius:6px; border:1px solid var(--border); cursor:zoom-in; }
  .img-wrap img.crop { max-width:686px; height:auto; border-radius:6px; border:2px solid #eab308; cursor:zoom-in; }
  .meta-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:12px; }
  .meta-box { background:#11151d; border:1px solid var(--border); border-radius:6px; padding:8px 10px; max-height:130px; overflow-y:auto; }
  .meta-box h4 { margin:0 0 6px 0; font-size:12px; color:var(--accent); }
  .review-bar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; background:#11151d; padding:10px; border-radius:8px; border:1px solid var(--border); }
  .review-bar input.note { flex:1; min-width:300px; cursor:text; }
  .char-count { font-size:12px; font-family:monospace; }
  .char-count.ok { color:var(--ok); }
  .char-count.short { color:var(--warn); }
</style>
</head>
<body>
<header>
  <div>
    <strong>Day 10 Visual Review Board</strong>
    <div class="stats" id="stats">Loading...</div>
  </div>
  <div class="controls">
    <select id="filterType"><option value="ALL">Mọi loại ứng viên</option>__TYPES_OPTIONS__</select>
    <select id="filterVerdict">
      <option value="ALL">Mọi trạng thái</option>
      <option value="PENDING">Chưa review</option>
      <option value="confirmed">Confirmed</option>
      <option value="rejected">Rejected</option>
    </select>
    <label style="font-size:13px;cursor:pointer;">
      Import CSV <input type="file" id="importCsv" accept=".csv" style="display:none">
    </label>
    <button class="primary" onclick="exportCsv()">Export review_log.csv</button>
  </div>
</header>
<main id="board"></main>

<script>
const RECORDS = __RECORDS_JSON__;
const SEMANTIC_TYPES = __SEMANTIC_TYPES_JSON__;
const STORAGE_KEY = "day10_review_v2_" + __DELIVERY_NAME_JSON__;
let state = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  updateStats();
}

function getEntry(rec) {
  const key = rec.uid;
  if (!state[key]) {
    state[key] = { type: rec.cand_type || "class_swap", verdict: "", note: "" };
  }
  return state[key];
}

function updateStats() {
  let conf = 0, rej = 0, shortNotes = 0;
  RECORDS.forEach(r => {
    const s = getEntry(r);
    if (s.verdict === "confirmed") conf++;
    if (s.verdict === "rejected") rej++;
    if (s.verdict && s.note.trim().length < 20) shortNotes++;
  });
  document.getElementById("stats").textContent =
    `Tổng: ${RECORDS.length} ứng viên | Confirmed: ${conf} | Rejected: ${rej} | Chưa review: ${RECORDS.length - conf - rej}` +
    (shortNotes ? ` | ⚠️ ${shortNotes} ghi chú < 20 ký tự` : "");
}

function render() {
  const fType = document.getElementById("filterType").value;
  const fVerd = document.getElementById("filterVerdict").value;
  const board = document.getElementById("board");
  board.innerHTML = "";

  RECORDS.forEach((rec, idx) => {
    const entry = getEntry(rec);
    if (fType !== "ALL" && entry.type !== fType) return;
    if (fVerd === "PENDING" && entry.verdict !== "") return;
    if (fVerd !== "ALL" && fVerd !== "PENDING" && entry.verdict !== fVerd) return;

    const card = document.createElement("div");
    card.className = "card " + (entry.verdict || "");

    const detList = rec.det_boxes.map(b => `[#${b.index}] ${b.class_name} (${b.bbox_px.join(",")})`).join("<br>") || "<i>Không có box</i>";
    const panList = rec.pan_segments.map(s => `${s.category_name}${s.iscrowd ? " [crowd]" : ""} area=${s.area} (${s.bbox_px.join(",")})`).join("<br>") || "<i>Không có thing segment</i>";

    card.innerHTML = `
      <div class="card-head">
        <div>
          <strong>#${idx + 1} — ${rec.stem}</strong>
          <span class="badge">Gợi ý: ${rec.cand_type}</span>
          ${rec.reason ? `<span class="badge">${rec.reason}</span>` : ""}
        </div>
      </div>
      <div class="img-wrap">
        <img class="panel" src="${rec.panel_rel}" alt="${rec.stem}" onclick="window.open(this.src,'_blank')">
        ${rec.crop_rel ? `<img class="crop" src="${rec.crop_rel}" alt="crop" onclick="window.open(this.src,'_blank')">` : ""}
      </div>
      <div class="meta-grid">
        <div class="meta-box"><h4>Detection YOLO (${rec.det_boxes.length})</h4>${detList}</div>
        <div class="meta-box"><h4>Panoptic Things (${rec.pan_segments.length})</h4>${panList}</div>
      </div>
      <div class="review-bar">
        <select onchange="setField('${rec.uid}','type',this.value)">
          ${SEMANTIC_TYPES.map(t => `<option value="${t}" ${entry.type===t?"selected":""}>${t}</option>`).join("")}
        </select>
        <select onchange="setField('${rec.uid}','verdict',this.value); render();">
          <option value="" ${entry.verdict===""?"selected":""}>-- Chọn verdict --</option>
          <option value="confirmed" ${entry.verdict==="confirmed"?"selected":""}>confirmed</option>
          <option value="rejected" ${entry.verdict==="rejected"?"selected":""}>rejected</option>
        </select>
        <input class="note" type="text" placeholder="Mô tả rõ đã thấy gì trong ảnh (>= 20 ký tự)..." value="${entry.note.replace(/"/g,'&quot;')}"
          oninput="setNote('${rec.uid}', this.value, this.nextElementSibling)">
        <span class="char-count ${entry.note.trim().length>=20?"ok":"short"}">${entry.note.trim().length}/20</span>
      </div>
    `;
    board.appendChild(card);
  });
  updateStats();
}

function setField(uid, field, val) {
  state[uid][field] = val;
  saveState();
}

function setNote(uid, val, badge) {
  state[uid].note = val;
  const len = val.trim().length;
  badge.textContent = len + "/20";
  badge.className = "char-count " + (len >= 20 ? "ok" : "short");
  saveState();
}

function csvEscape(val) {
  const s = String(val || "").replace(/"/g, '""');
  return `"${s}"`;
}

function exportCsv() {
  const dedup = new Map();
  let invalid = [];
  RECORDS.forEach(r => {
    const s = getEntry(r);
    if (!s.verdict) return;
    if (s.note.trim().length < 20) invalid.push(r.stem);
    const key = `${s.type}::${r.stem}`;
    const prev = dedup.get(key);
    // Keep confirmed over rejected when the same image appears in multiple segments
    if (!prev || (prev.verdict !== "confirmed" && s.verdict === "confirmed")) {
      dedup.set(key, { image: r.stem, type: s.type, verdict: s.verdict, note: s.note.trim() });
    }
  });
  if (invalid.length) {
    alert("Cảnh báo: các ảnh sau có ghi chú ngắn hơn 20 ký tự (sẽ FAIL H3): " + invalid.join(", "));
  }
  const lines = ["image,type,verdict,note"];
  dedup.forEach(row => {
    lines.push([row.image, row.type, row.verdict, csvEscape(row.note)].join(","));
  });
  const blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/csv;charset=utf-8;" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "review_log.csv";
  a.click();
}

document.getElementById("importCsv").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  file.text().then(text => {
    const rows = text.split(/\\r?\\n/).slice(1);
    rows.forEach(line => {
      if (!line.trim()) return;
      const m = line.match(/^([^,]+),([^,]+),([^,]+),(.*)$/);
      if (!m) return;
      const stem = m[1].trim();
      const type = m[2].trim();
      const verdict = m[3].trim();
      let note = m[4].trim();
      if (note.startsWith('"') && note.endsWith('"')) note = note.slice(1, -1).replace(/""/g, '"');
      RECORDS.forEach(r => {
        if (r.stem === stem && (r.cand_type === type || !state[r.uid]?.verdict)) {
          state[r.uid] = { type, verdict, note };
        }
      });
    });
    saveState();
    render();
  });
});

document.getElementById("filterType").addEventListener("change", render);
document.getElementById("filterVerdict").addEventListener("change", render);
render();
</script>
</body>
</html>
"""
    html_content = (
        template.replace("__TITLE__", html.escape(delivery_name))
        .replace("__TYPES_OPTIONS__", types_options)
        .replace("__RECORDS_JSON__", records_json)
        .replace("__SEMANTIC_TYPES_JSON__", json.dumps(SEMANTIC_TYPES))
        .replace("__DELIVERY_NAME_JSON__", json.dumps(delivery_name))
    )
    out_html = out_dir / "review_board.html"
    out_html.write_text(html_content, encoding="utf-8")
    return out_html


def collect_targets(delivery: Path, args: argparse.Namespace, classes: dict[int, str]) -> list[dict[str, Any]]:
    """Resolve list of target images based on CLI flags."""
    if args.candidates:
        return load_candidates(Path(args.candidates))

    if args.images:
        stems = [Path(s.strip()).stem for s in args.images.split(",") if s.strip()]
        return [
            {"uid": f"{i}_{s}", "image": s, "type": "class_swap", "reason": "manual inspect", "bbox": None}
            for i, s in enumerate(stems)
        ]

    if args.filter_class:
        target_name = args.filter_class.strip().lower()
        matching_ids = {cid for cid, name in classes.items() if name.lower() == target_name}
        if not matching_ids:
            raise SystemExit(f"Class '{args.filter_class}' not found in classes.txt")
        items = []
        for lbl in sorted((delivery / "labels").glob("*.txt")):
            for ln in lbl.read_text(encoding="utf-8").splitlines():
                parts = ln.strip().split()
                if parts and int(float(parts[0])) in matching_ids:
                    items.append({
                        "uid": f"{len(items)}_{lbl.stem}",
                        "image": lbl.stem,
                        "type": "missing_box",
                        "reason": f"contains class '{target_name}'",
                        "bbox": [float(v) for v in parts[1:5]],
                    })
                    break
            if args.limit and len(items) >= args.limit:
                break
        return items

    stems = sorted(p.stem for p in (delivery / "images").glob("*.jpg"))[: args.limit or 10]
    return [
        {"uid": f"{i}_{s}", "image": s, "type": "class_swap", "reason": "sample preview", "bbox": None}
        for i, s in enumerate(stems)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Visualize Detection vs Panoptic labels and generate HTML review board")
    ap.add_argument("delivery", help="Path to delivery/ folder")
    ap.add_argument("--candidates", help="Path to candidates.json")
    ap.add_argument("--images", help="Comma-separated image stems to render")
    ap.add_argument("--filter-class", help="Render images containing a specific YOLO class name")
    ap.add_argument("--limit", type=int, default=0, help="Max images to render (when not using --candidates)")
    ap.add_argument("--out", required=True, help="Output folder for PNG panels and review_board.html")
    args = ap.parse_args()

    delivery = Path(args.delivery)
    out_dir = Path(args.out)
    out_img_dir = out_dir / "images"
    out_img_dir.mkdir(parents=True, exist_ok=True)

    classes = load_classes(delivery)
    cats, anns_by_stem = load_panoptic_index(delivery)
    targets = collect_targets(delivery, args, classes)
    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]

    records: list[dict[str, Any]] = []
    panel_cache: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(targets):
        info = render_image_bundle(
            delivery=delivery,
            stem=item["image"],
            cand_idx=idx,
            classes=classes,
            cats=cats,
            anns_by_stem=anns_by_stem,
            out_img_dir=out_img_dir,
            panel_cache=panel_cache,
            focus_bbox=item.get("bbox"),
            seg_bbox_xywh=item.get("segment_bbox_xywh"),
            cand_boxes=item.get("boxes"),
        )
        info["uid"] = item["uid"]
        info["cand_type"] = item["type"]
        info["reason"] = item["reason"]
        records.append(info)

    board_path = build_html_board(records, out_dir, str(delivery))
    print(f"Rendered {len(records)} candidates ({len(panel_cache)} unique images) -> {board_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""P2: đối chiếu box YOLO với mask panoptic để tìm ứng viên cần review."""

from collections import Counter
from math import ceil, floor
from pathlib import Path


# Ngưỡng ban đầu, cần kiểm tra trên lô sạch của nhóm.
MATCH_IOU = 0.65
MIN_AREA = 64
MAX_DRIFT_COVERAGE = 0.85


def intersection(a, b):
    """Diện tích phần giao của hai box dạng (x1, y1, x2, y2)."""
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return width * height


def area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def iou(a, b):
    overlap = intersection(a, b)
    union = area(a) + area(b) - overlap
    return overlap / max(1, union)


def read_boxes(path, width, height, classes):
    """Đọc nhãn YOLO và đổi tọa độ chuẩn hóa sang pixel."""
    boxes = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        cls, cx, cy, w, h = line.split()
        cx, cy, w, h = map(float, (cx, cy, w, h))

        rect = (
            max(0, floor((cx - w / 2) * width)),
            max(0, floor((cy - h / 2) * height)),
            min(width, ceil((cx + w / 2) * width)),
            min(height, ceil((cy + h / 2) * height)),
        )
        boxes.append((classes[int(cls)], rect))

    return boxes


def count_inside_boxes(width, pixels, boxes):
    """Đếm số pixel của từng segment nằm trong mỗi box detection."""
    segment_ids = [
        r + (g << 8) + (b << 16)
        for r, g, b in zip(pixels[::3], pixels[1::3], pixels[2::3])
    ]

    counts = []
    for _, (left, top, right, bottom) in boxes:
        count = Counter()
        for y in range(top, bottom):
            offset = y * width
            count.update(segment_ids[offset + left:offset + right])
        counts.append(count)

    return counts


def inspect_segment(segment, name, boxes, counts):
    """Trả về loại nghi vấn và chỉ số các box liên quan, nếu có."""
    x, y, w, h = segment["bbox"]
    rect = (x, y, x + w, y + h)
    size = segment["area"]
    matches = []

    for index, (label, box) in enumerate(boxes):
        coverage = counts[index][segment["id"]] / size
        matches.append((index, iou(rect, box), coverage, label == name))

    # Hai box cùng lớp, tách biệt, nhưng cùng chứa phần đáng kể của một mask.
    parts = [
        index
        for index, _, coverage, same_class in matches
        if same_class and coverage >= 0.2
    ]
    for position, first in enumerate(parts):
        for second in parts[position + 1:]:
            a = boxes[first][1]
            b = boxes[second][1]
            if (
                iou(a, b) < 0.10
                and intersection(a, b) < 0.15 * min(area(a), area(b))
            ):
                return "instance_merge", [first, second]

    if matches:
        best, overlap, coverage, same_class = max(
            matches, key=lambda match: match[1]
        )

        # Hai nguồn khớp vị trí nhưng khác lớp. Người review sẽ mở ảnh
        # để chốt class_swap (detection sai) hoặc category_swap (mask sai).
        if not same_class and overlap >= MATCH_IOU and coverage >= 0.85:
            has_good_same_class_box = any(
                same and covered >= 0.85 and score >= 0.5
                for _, score, covered, same in matches
            )
            if not has_good_same_class_box:
                return "class_swap", [best]

        # Box cùng lớp có giao với segment nhưng để lọt nhiều pixel của vật.
        plausible = [
            (index, score, covered)
            for index, score, covered, same in matches
            if same and score >= 0.15
        ]
        if plausible:
            index, _, fraction = max(plausible, key=lambda match: match[1])
            has_fuller_box = any(covered >= 0.95 for _, _, covered in plausible)
            if fraction < MAX_DRIFT_COVERAGE and not has_fuller_box:
                return "bbox_drift", [index]

        # Đã có box phủ đáng kể lên segment, chưa đủ cơ sở nghi thiếu box.
        if any(score >= 0.15 or covered >= 0.45 for _, score, covered, _ in matches):
            return None

    return "missing_box", []


def find_candidates(delivery, data, errors, mask_cache):
    """Hàm được validator/validate.py gọi khi truyền --candidates."""
    candidates = []

    for annotation in data["panoptic"]["annotations"]:
        image = Path(annotation["file_name"]).stem
        if image in errors or image not in mask_cache:
            continue

        width, height, pixels = mask_cache[image]
        label_path = delivery / data["manifest"][image]["label"]
        boxes = read_boxes(label_path, width, height, data["valid_classes"])
        counts = count_inside_boxes(width, pixels, boxes)

        for segment in annotation["segments_info"]:
            category = data["cat_by_id"][segment["category_id"]]

            # Chỉ đối chiếu vật thể riêng lẻ, bỏ qua vùng crowd và vật quá nhỏ.
            if (
                not category["isthing"]
                or segment.get("iscrowd")
                or segment["area"] < MIN_AREA
            ):
                continue

            result = inspect_segment(segment, category["name"], boxes, counts)
            if result is None:
                continue

            kind, indices = result
            possible_types = (
                ["class_swap", "category_swap"]
                if kind == "class_swap"
                else [kind]
            )
            candidates.append({
                "image": image,
                "target": image,
                "type": kind,
                "possible_types": possible_types,
                "segment_id": segment["id"],
                "panoptic_class": category["name"],
                "segment_bbox_xywh": segment["bbox"],
                "boxes": [
                    {"class": boxes[index][0], "xyxy": boxes[index][1]}
                    for index in indices
                ],
            })

    return candidates
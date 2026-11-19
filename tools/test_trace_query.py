#!/usr/bin/env python3
"""Unit tests độc lập cho công cụ truy vết tools/trace_query.py."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import trace_query  # noqa: E402


CLASSES_SUBSET = [
    (2, "car"),
    (7, "truck"),
    (9, "traffic light"),
    (16, "dog"),
    (41, "cup"),
    (51, "carrot"),
    (52, "hot dog"),
]


def make_synthetic_delivery(
    root: Path,
    *,
    jobs_rows: list[tuple[str, str, str, str]],
    meta_rows: list[dict],
    labels: dict[str, list[str]],
    ticket_text: str,
    changelog_text: str,
    create_images: bool = True,
) -> Path:
    d = root / "delivery"
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "labels").mkdir(parents=True, exist_ok=True)
    (d / "masks").mkdir(parents=True, exist_ok=True)
    (d / "incoming").mkdir(parents=True, exist_ok=True)
    (d / "guideline").mkdir(parents=True, exist_ok=True)

    (d / "classes.txt").write_text(
        "\n".join(f"{cid} {cname}" for cid, cname in CLASSES_SUBSET) + "\n",
        encoding="utf-8",
    )

    with (d / "jobs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["job_id", "annotator", "reviewer", "guideline"])
        writer.writerows(jobs_rows)

    manifest_items = {}
    for row in meta_rows:
        img = row["image"]
        if create_images:
            (d / "images" / f"{img}.jpg").write_bytes(b"fake-jpg")
        (d / "labels" / f"{img}.txt").write_text(
            "\n".join(labels.get(img, [])) + ("\n" if labels.get(img) else ""),
            encoding="utf-8",
        )
        manifest_items[img] = {
            "image": f"images/{img}.jpg",
            "label": f"labels/{img}.txt",
            "mask": f"masks/{img}.png",
        }

    (d / "manifest.json").write_text(json.dumps({"items": manifest_items}, indent=2), encoding="utf-8")
    (d / "metadata.json").write_text(json.dumps({"items": meta_rows}, indent=2), encoding="utf-8")
    (d / "incoming" / "ticket.md").write_text(ticket_text, encoding="utf-8")
    (d / "guideline" / "changelog.md").write_text(changelog_text, encoding="utf-8")
    return d


class TraceQueryTest(unittest.TestCase):
    def test_guideline_mismatch_uses_job_not_image_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_synthetic_delivery(
                Path(tmp),
                jobs_rows=[
                    ("J01", "A01", "Q01", "v1.2"),
                    ("J02", "A02", "Q02", "v1.3"),
                ],
                meta_rows=[
                    # Thuộc job v1.2 nhưng metadata ghi nhầm v1.3 -> VẪN phải vào tier_a
                    {"image": "img_0001", "scene_id": "scene_01", "split": "train", "job_id": "J01", "guideline_version": "v1.3"},
                    # Thuộc job v1.2, ngoài reported scene -> vào tier_b
                    {"image": "img_0002", "scene_id": "scene_02", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                    # Thuộc job v1.3 nhưng metadata ghi nhầm v1.2 -> KHÔNG được vào tier_a/tier_b
                    {"image": "img_0003", "scene_id": "scene_01", "split": "val", "job_id": "J02", "guideline_version": "v1.2"},
                ],
                labels={
                    "img_0001": ["41 0.5 0.5 0.2 0.2"],
                    "img_0002": ["41 0.5 0.5 0.2 0.2"],
                    "img_0003": ["41 0.5 0.5 0.2 0.2"],
                },
                ticket_text="Bọn mình thấy sót ở scene_01 với lớp `cup`.",
                changelog_text="## v1.3\n- Lớp `cup`: vẫn phải gán box (v1.2 cho phép bỏ qua).\n\n## v1.2\n- Bản cũ.",
            )
            trace, info = trace_query.build_trace(d)
            self.assertEqual(trace["tier_a"], ["img_0001"])
            self.assertEqual(trace["tier_b"], ["img_0002"])
            self.assertEqual(trace["notify"], ["A01", "Q01"])
            self.assertEqual(len(info["guideline_mismatches_seen"]), 2)

    def test_multiword_class_and_scene_word_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_synthetic_delivery(
                Path(tmp),
                jobs_rows=[
                    ("J01", "A05", "Q03", "v1.2"),
                    ("J02", "A06", "Q04", "v1.2"),
                ],
                meta_rows=[
                    {"image": "img_0001", "scene_id": "scene_01", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                    {"image": "img_0002", "scene_id": "scene_010", "split": "train", "job_id": "J02", "guideline_version": "v1.2"},
                    # Có 'dog' (16) chứ không phải 'hot dog' (52) -> không khớp!
                    {"image": "img_0003", "scene_id": "scene_01", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                ],
                labels={
                    "img_0001": ["52 0.5 0.5 0.1 0.1"],
                    "img_0002": ["52 0.5 0.5 0.1 0.1"],
                    "img_0003": ["16 0.5 0.5 0.1 0.1"],
                },
                ticket_text="Thiếu box ở scene_01 cho hot dog.",
                changelog_text="## v1.3\n- Lớp `hot dog`: quy tắc mới (v1.2 bỏ qua vật nhỏ).\n## v1.2\n- Bản cũ.",
            )
            trace, info = trace_query.build_trace(d)
            self.assertEqual(info["target_class"], "hot dog")
            self.assertEqual(info["reported_scenes"], ["scene_01"])
            self.assertEqual(trace["tier_a"], ["img_0001"])
            self.assertEqual(trace["tier_b"], ["img_0002"])
            self.assertEqual(trace["notify"], ["A05", "A06", "Q03", "Q04"])

    def test_missing_image_and_unrelated_job_excluded_from_notify(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_synthetic_delivery(
                Path(tmp),
                jobs_rows=[
                    ("J01", "A01", "Q01", "v1.2"),
                    ("J02", "A02", "Q02", "v1.2"),
                ],
                meta_rows=[
                    # Không có file ảnh jpg (missing_image) nhưng vẫn có file nhãn car (id=2)
                    {"image": "img_0010", "scene_id": "scene_01", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                    # Trong scene_01 nhưng chỉ có carrot (51), không phải car (2)
                    {"image": "img_0011", "scene_id": "scene_01", "split": "train", "job_id": "J02", "guideline_version": "v1.2"},
                ],
                labels={
                    "img_0010": ["2 0.4 0.4 0.3 0.3"],
                    "img_0011": ["51 0.4 0.4 0.3 0.3"],
                },
                ticket_text="Xem giúp scene_01.",
                changelog_text="## v1.3\n- Lớp `car`: gán thêm xe bị che.\n## v1.2\n- Bản cũ.",
                create_images=False,
            )
            trace, _ = trace_query.build_trace(d)
            self.assertEqual(trace["tier_a"], ["img_0010"])
            self.assertEqual(trace["tier_b"], [])
            self.assertEqual(trace["notify"], ["A01", "Q01"])

    def test_cli_writes_json_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            d = make_synthetic_delivery(
                tmp_path,
                jobs_rows=[("J01", "A09", "Q08", "v1.0")],
                meta_rows=[
                    {"image": "img_0007", "scene_id": "scene_99", "split": "val", "job_id": "J01", "guideline_version": "v1.0"},
                ],
                labels={"img_0007": ["9 0.5 0.5 0.1 0.2"]},
                ticket_text="Văn bản không chuẩn.",
                changelog_text="Không ghi tên lớp chuẩn.",
            )
            out_file = tmp_path / "out" / "trace.json"
            rc = trace_query.main(
                [
                    str(d),
                    "--out",
                    str(out_file),
                    "--scenes",
                    "scene_99",
                    "--old-guideline",
                    "v1.0",
                    "--class-name",
                    "traffic light",
                ]
            )
            self.assertEqual(rc, 0)
            doc = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(doc, {"tier_a": ["img_0007"], "tier_b": [], "notify": ["A09", "Q08"]})

    def test_opaque_hidden_names_with_changelog_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_synthetic_delivery(
                Path(tmp),
                jobs_rows=[
                    ("J01", "A03", "Q02", "v1.2"),
                    ("J02", "A04", "Q02", "v1.3"),
                ],
                meta_rows=[
                    {"image": "img_0001", "scene_id": "scene_12", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                    {"image": "img_0002", "scene_id": "scene_88", "split": "val", "job_id": "J01", "guideline_version": "v1.2"},
                    {"image": "img_0003", "scene_id": "scene_12", "split": "val", "job_id": "J02", "guideline_version": "v1.3"},
                ],
                labels={
                    "img_0001": ["41 0.5 0.5 0.1 0.1"],
                    "img_0002": ["41 0.2 0.2 0.1 0.1"],
                    "img_0003": ["41 0.3 0.3 0.1 0.1"],
                },
                ticket_text="Thiếu `cup` ở scene_12.",
                changelog_text="## v1.2 -> v1.3\n- Lớp `cup`: gán cả cốc bị che (không gộp với `car`).\n",
            )
            trace, info = trace_query.build_trace(d)
            self.assertEqual(info["old_guideline"], "v1.2")
            self.assertEqual(info["target_class"], "cup")
            self.assertEqual(trace, {"tier_a": ["img_0001"], "tier_b": ["img_0002"], "notify": ["A03", "Q02"]})

    def test_malformed_and_empty_label_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_synthetic_delivery(
                Path(tmp),
                jobs_rows=[("J01", "A01", "Q01", "v1.2")],
                meta_rows=[
                    {"image": "img_0020", "scene_id": "scene_05", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                    {"image": "img_0021", "scene_id": "scene_05", "split": "train", "job_id": "J01", "guideline_version": "v1.2"},
                ],
                labels={
                    "img_0020": ["", "bad_line 0.1 0.2", "41.0 0.5 0.5 0.2 0.2"],
                    "img_0021": [""],
                },
                ticket_text="Xem scene_05.",
                changelog_text="## v1.3\n- Lớp `cup`: sửa quy tắc (v1.2 bỏ qua).\n## v1.2\n- Bản cũ.",
            )
            trace, _ = trace_query.build_trace(d)
            self.assertEqual(trace["tier_a"], ["img_0020"])
            self.assertEqual(trace["tier_b"], [])


if __name__ == "__main__":
    unittest.main()

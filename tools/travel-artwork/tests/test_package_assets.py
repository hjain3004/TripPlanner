"""Exercise real exports; catch unreviewed/stale assets and destructive writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_assets.py"


class PackageAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        Image.new("RGB", (1200, 800), (45, 70, 95)).save(self.source)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.asset = {
            "id": "sg-hero", "role": "hero", "source_file": "source.png",
            "source_sha256": digest, "origin": "ai_generated",
            "generator": {"product": "synthetic test fixture", "model": "test-only"},
            "prompt": "Synthetic solid color fixture, not destination artwork.",
            "created_at": "2026-10-12", "references": [],
            "alt": "Synthetic blue fixture", "allowed_placements": ["destination_editorial"],
            "approval": {"status": "approved", "reviewer": "test fixture",
                         "reviewed_at": "2026-10-12", "source_sha256": digest},
            "review": {"geometry": "pass", "destination": "pass", "texture": "pass",
                       "composition": "pass", "crop": "pass", "visible_watermark": "absent"},
            "export": {"widths": [390, 768], "crop_box": None, "byte_budget": 200000},
        }
        self.manifest = self.root / "manifest.json"
        self.out = self.root / "pack"

    def run_export(self):
        self.manifest.write_text(json.dumps({"schema_version": 1,
            "destination_id": "sg-singapore", "assets": [self.asset]}))
        return subprocess.run([sys.executable, str(SCRIPT), str(self.manifest),
            "--out", str(self.out)], capture_output=True, text=True)

    def test_approved_export_has_real_sizes_and_preserves_original_bytes(self):
        result = self.run_export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "originals/sg-hero.png").read_bytes(), self.source.read_bytes())
        for suffix in ("webp", "avif"):
            with Image.open(self.out / f"sg-hero-390.{suffix}") as image:
                self.assertEqual(image.size, (390, 260))
            with Image.open(self.out / f"sg-hero-768.{suffix}") as image:
                self.assertEqual(image.size, (768, 512))
        output = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(len(output["assets"][0]["variants"]), 4)
        self.assertEqual(output["assets"][0]["approval"]["source_sha256"], self.asset["source_sha256"])

    def test_pending_approval_never_creates_output(self):
        self.asset["approval"]["status"] = "pending"
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_changed_source_invalidates_recorded_review(self):
        Image.new("RGB", (1200, 800), "red").save(self.source)
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_review_of_different_revision_is_rejected(self):
        self.asset["approval"]["source_sha256"] = "0" * 64
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_existing_pack_is_never_overwritten(self):
        self.assertEqual(self.run_export().returncode, 0)
        before = {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertEqual(before, {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob("*") if p.is_file()})

    def test_unusable_crop_and_upscale_fail_without_partial_pack(self):
        for crop in ([0, 0, 200, 200], [-1, 0, 1200, 800]):
            with self.subTest(crop=crop):
                self.asset["export"]["crop_box"] = crop
                self.assertNotEqual(self.run_export().returncode, 0)
                self.assertFalse(self.out.exists())

    def test_missing_origin_and_unknown_watermark_fail_closed(self):
        for field in ("origin", "watermark"):
            with self.subTest(field=field):
                if field == "origin":
                    self.asset["origin"] = ""
                else:
                    self.asset["origin"] = "ai_generated"
                    self.asset["review"]["visible_watermark"] = "unknown"
                self.assertNotEqual(self.run_export().returncode, 0)
                self.assertFalse(self.out.exists())

    def test_byte_budget_failure_removes_partial_pack(self):
        self.asset["export"]["byte_budget"] = 1
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_source_outside_job_folder_is_rejected(self):
        self.asset["source_file"] = str(self.source)
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_alpha_survives_both_export_formats(self):
        Image.new("RGBA", (1200, 800), (45, 70, 95, 0)).save(self.source)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.asset["source_sha256"] = self.asset["approval"]["source_sha256"] = digest
        result = self.run_export()
        self.assertEqual(result.returncode, 0, result.stderr)
        for suffix in ("webp", "avif"):
            with Image.open(self.out / f"sg-hero-390.{suffix}") as image:
                self.assertEqual(image.convert("RGBA").getpixel((10, 10))[3], 0)

    def test_unresolved_uploaded_reference_permission_is_rejected(self):
        self.asset["references"] = [{"url": "https://example.org/reference",
            "creator": "unverified photographer", "retrieved_at": "2026-10-12",
            "use": "upload", "rights": "unknown"}]
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_unsupported_color_mode_is_held_instead_of_mislabeling_profile(self):
        source = self.root / "source.jpg"
        Image.new("CMYK", (1200, 800), (40, 0, 0, 0)).save(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.asset["source_file"] = "source.jpg"
        self.asset["source_sha256"] = self.asset["approval"]["source_sha256"] = digest
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())

    def test_research_reference_requires_recorded_rights_even_when_unknown(self):
        reference = {"url": "https://example.org/reference", "creator": "research archive",
            "retrieved_at": "2026-10-12", "use": "research"}
        self.asset["references"] = [reference]
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())
        reference["rights"] = "unknown; research only, not uploaded"
        self.assertEqual(self.run_export().returncode, 0)

    def test_photo_origin_cannot_be_labeled_with_a_generation_model(self):
        self.asset["origin"] = "licensed_photo"
        self.asset["references"] = [{"url": "https://example.org/photo", "creator": "test photographer",
            "retrieved_at": "2026-10-12", "use": "source", "rights": "user-owned test fixture"}]
        self.assertNotEqual(self.run_export().returncode, 0)
        self.assertFalse(self.out.exists())
        self.asset["generator"]["model"] = "not_applicable"
        self.assertEqual(self.run_export().returncode, 0)


if __name__ == "__main__":
    unittest.main()

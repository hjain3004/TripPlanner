"""Check actual upload artifacts are portable and rebuild from canonical inputs."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

BASE = Path(__file__).resolve().parents[1]


class SkillArchivesTest(unittest.TestCase):
    def test_uploads_have_root_skill_and_all_local_links_inside_each_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(BASE / "scripts/build_skills.py"),
                "--out", folder], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            uploads = [p for p in Path(folder).glob("*.zip") if p.name != "travel-artwork-workflow.zip"]
            self.assertEqual(len(uploads), 4)
            for path in uploads:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    self.assertIn("SKILL.md", names)
                    self.assertIn("references/asset-job.json", names)
                    self.assertIn("references/asset-manifest.json", names)
                    for target in re.findall(r"\]\(([^)]+)\)", archive.read("SKILL.md").decode()):
                        if not target.startswith("https:"):
                            self.assertIn(target, names, f"{path.name}: missing {target}")
                    self.assertFalse(any(".." in Path(n).parts or n.startswith("/") for n in names))
                    self.assertEqual(archive.read("references/house-style.md"), (BASE / "shared/house-style.md").read_bytes())
                    if path.name == "package-destination-assets.zip":
                        self.assertIn("scripts/package_assets.py", names)
            with zipfile.ZipFile(Path(folder) / "travel-artwork-workflow.zip") as kit:
                self.assertIn("WORKFLOW.md", kit.namelist())
                self.assertEqual(len([n for n in kit.namelist() if n.startswith("uploads/") and n.endswith(".zip")]), 4)
                self.assertIn("prompts/spark-start.md", kit.namelist())


if __name__ == "__main__":
    unittest.main()

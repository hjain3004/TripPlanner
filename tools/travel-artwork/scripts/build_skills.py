#!/usr/bin/env python3
"""Build self-contained Gemini uploads and an operator kit; stdlib, no network."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import zipfile

BASE = Path(__file__).resolve().parents[1]
NAMES = ("research-destination-art-direction", "generate-travel-artwork",
         "review-travel-artwork", "package-destination-assets")


def archive_bytes(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name)  # Stable ZIP epoch, not a claimed generation date.
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content)
    return stream.getvalue()


def write_archive(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temp.write(content)
        temporary = Path(temp.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build(output):
    shared = {}
    for folder in ("shared", "templates"):
        for path in sorted((BASE / folder).iterdir()):
            if path.suffix in {".md", ".json", ".html"}:
                if path.suffix == ".json":
                    json.loads(path.read_text())
                shared[f"references/{path.name}"] = path.read_bytes()
    uploads = {}
    for name in NAMES:
        skill = (BASE / "skills" / name / "SKILL.md").read_bytes()
        body = skill.decode()
        if not body.startswith(f"---\nname: {name}\n") or "\ndescription: " not in body:
            raise ValueError(f"invalid skill metadata: {name}")
        files = {"SKILL.md": skill, **shared}
        if name == "package-destination-assets":
            files["scripts/package_assets.py"] = (BASE / "scripts/package_assets.py").read_bytes()
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if not target.startswith("https:") and target not in files:
                raise ValueError(f"{name}: unbundled reference {target}")
        uploads[f"{name}.zip"] = archive_bytes(files)
    kit = {"WORKFLOW.md": (BASE / "WORKFLOW.md").read_bytes()}
    for folder in ("shared", "templates", "prompts", "skills", "scripts", "tests"):
        for path in sorted((BASE / folder).rglob("*")):
            if path.is_file() and path.suffix in {".md", ".json", ".py", ".html"} and "__pycache__" not in path.parts:
                kit[path.relative_to(BASE).as_posix()] = path.read_bytes()
    kit.update({f"uploads/{name}": content for name, content in uploads.items()})
    uploads["travel-artwork-workflow.zip"] = archive_bytes(kit)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in uploads.items():
        write_archive(output / name, content)
    return uploads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BASE / "dist", help="Derived archives; rebuild replaces only the five named ZIPs")
    args = parser.parse_args()
    uploads = build(args.out)
    for name, content in uploads.items():
        print(f"{args.out / name}: {len(content):,} bytes")


if __name__ == "__main__":
    main()

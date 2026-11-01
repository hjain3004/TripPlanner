#!/usr/bin/env python3
"""Offline, non-destructive export of declared reviewed travel artwork.

Requires Pillow with WebP and AVIF encoders. No network or dependency installation.
Approval/rights declarations are checked, not independently authenticated.
"""
import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys

from PIL import Image, ImageOps

PLACEMENTS = {"destination_editorial", "destination_thumbnail", "itinerary_editorial_header"}
ROLES = {"hero", "postcard", "detail", "thumbnail", "stamp"}
CHECKS = ("geometry", "destination", "texture", "composition", "crop")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def valid_date(value):
    require(nonblank(value), "missing ISO date/time")
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(manifest_path):
    data = json.loads(manifest_path.read_text())
    require(data.get("schema_version") == 1, "unsupported manifest version")
    require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data.get("destination_id", "")), "invalid destination ID")
    require(isinstance(data.get("assets"), list) and data["assets"], "no assets")
    root = manifest_path.parent.resolve()
    seen = set()
    prepared = []
    for asset in data["assets"]:
        asset_id = asset.get("id", "")
        require(isinstance(asset_id, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", asset_id), "invalid asset ID")
        require(asset_id not in seen, "duplicate asset ID")
        seen.add(asset_id)
        require(asset.get("role") in ROLES, f"{asset_id}: invalid role")
        if asset["role"] == "stamp":
            require(data["destination_id"].startswith("jp-"), "stamp pack requires an explicit Japan ID")
        require(asset.get("origin") in {"ai_generated", "licensed_photo"}, "missing/invalid origin")
        generator = asset.get("generator", {})
        require(nonblank(generator.get("product")) and nonblank(generator.get("model")), "missing observed generator/creator")
        if asset["origin"] == "licensed_photo":
            require(generator["model"] == "not_applicable", "licensed photo model must be not_applicable")
        else:
            require(generator["model"] != "not_applicable", "generated artwork requires its observed model or not_exposed")
        require(nonblank(asset.get("prompt")), "missing generation prompt or photo source description")
        require(nonblank(asset.get("alt")), "missing alt text")
        valid_date(asset.get("created_at"))
        placements = asset.get("allowed_placements")
        require(isinstance(placements, list) and placements and all(p in PLACEMENTS for p in placements), "invalid editorial placement")
        references = asset.get("references")
        require(isinstance(references, list), "missing reference list")
        for reference in references:
            require(isinstance(reference, dict), "invalid reference")
            require(reference.get("use") in {"research", "inspiration", "upload", "source"}, "invalid reference use")
            require(nonblank(reference.get("url")), "missing reference URL")
            require(nonblank(reference.get("creator")), "missing reference creator")
            valid_date(reference.get("retrieved_at"))
            require(nonblank(reference.get("rights")), "missing reference rights statement")
            if reference["use"] in {"upload", "source"}:
                rights = reference.get("rights")
                require(nonblank(rights) and rights.strip().lower() not in {"unknown", "pending", "unverified"}, "unresolved source/upload rights")
        if asset["origin"] == "licensed_photo":
            require(any(r["use"] == "source" for r in references), "photo requires a source/rights record")
        review = asset.get("review", {})
        require(all(review.get(key) == "pass" for key in CHECKS), "unfinished visual review")
        require(review.get("visible_watermark") in {"absent", "native_disabled"}, "clean-export state unverified or marked")
        approval = asset.get("approval", {})
        require(approval.get("status") == "approved" and nonblank(approval.get("reviewer")), "missing human selection declaration")
        valid_date(approval.get("reviewed_at"))
        relative = Path(asset.get("source_file", ""))
        require(not relative.is_absolute() and relative.parts, "source must be relative to the manifest")
        source = (root / relative).resolve()
        require(source.is_relative_to(root), "source escapes manifest directory")
        require(source.is_file() and source.stat().st_size <= 100_000_000, "missing or oversized original")
        original = source.read_bytes()
        source_hash = digest(original)
        require(source_hash == asset.get("source_sha256") == approval.get("source_sha256"), "source differs from reviewed revision")
        with Image.open(BytesIO(original)) as opened:
            require(opened.mode in {"RGB", "RGBA", "L", "LA", "P"}, "source color mode requires an explicit reviewed conversion")
            image = ImageOps.exif_transpose(opened)
            require(image.width * image.height <= 40_000_000, "oversized source dimensions")
            icc = opened.info.get("icc_profile")
            if icc:
                require(opened.mode in {"RGB", "RGBA"}, "profiled source requires an explicit reviewed RGB conversion")
            image.load()
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        export = asset.get("export", {})
        crop = export.get("crop_box")
        if crop is not None:
            require(isinstance(crop, list) and len(crop) == 4 and all(type(x) is int for x in crop), "invalid crop box")
            left, top, right, bottom = crop
            require(0 <= left < right <= image.width and 0 <= top < bottom <= image.height, "crop outside original")
            image = image.crop(tuple(crop))
        widths = export.get("widths")
        require(isinstance(widths, list) and widths and all(type(w) is int and 0 < w <= image.width for w in widths), "invalid width or requested enlargement")
        require(len(set(widths)) == len(widths), "duplicate export widths")
        budget = export.get("byte_budget")
        require(type(budget) is int and budget > 0, "invalid derivative byte budget")
        prepared.append((asset, source, original, image, icc))
    return data, prepared


def export_pack(manifest_path, output):
    require(not output.exists(), "output already exists; choose a new revision folder")
    Image.init()
    require(all(fmt in Image.SAVE for fmt in ("WEBP", "AVIF")), "Pillow needs WebP and AVIF encoders")
    data, prepared = prepare(manifest_path)
    # Exclusive creation establishes ownership; failures remove only our new folder.
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / "originals").mkdir()
        for asset, source, original, image, icc in prepared:
            original_path = f"originals/{asset['id']}{source.suffix.lower()}"
            (output / original_path).write_bytes(original)
            asset["source_file"] = original_path
            asset["variants"] = []
            for width in asset["export"]["widths"]:
                height = max(1, round(image.height * width / image.width))
                resized = image.resize((width, height), Image.Resampling.LANCZOS)
                for fmt, quality in (("WEBP", 86), ("AVIF", 75)):
                    name = f"{asset['id']}-{width}.{fmt.lower()}"
                    path = output / name
                    options = {"quality": quality}
                    if icc:
                        options["icc_profile"] = icc
                    resized.save(path, format=fmt, **options)
                    encoded = path.read_bytes()
                    require(len(encoded) <= asset["export"]["byte_budget"], f"{name}: exceeds byte budget; revise crop/size/budget explicitly")
                    asset["variants"].append({"file": name, "width": width, "height": height,
                        "bytes": len(encoded), "sha256": digest(encoded), "format": fmt.lower()})
            asset["derivative_review"] = "pending"
        data["pack_state"] = "exported_awaiting_derivative_review"
        (output / "manifest.json").write_text(json.dumps(data, indent=2) + "\n")
    except Exception:
        shutil.rmtree(output)
        raise
    return len(prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New isolated handoff folder; never point at the app")
    args = parser.parse_args()
    try:
        count = export_pack(args.manifest.resolve(), args.out.resolve())
    except (ValueError, OSError, KeyError, TypeError, AttributeError, Image.DecompressionBombError) as error:
        print(f"Export held: {error}", file=sys.stderr)
        return 1
    print(f"Exported {count} reviewed originals. Derivative review is pending: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

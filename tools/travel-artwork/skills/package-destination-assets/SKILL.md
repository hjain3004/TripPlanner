---
name: package-destination-assets
description: Use when preparing reviewed destination artwork originals for non-destructive offline responsive export, provenance manifests, derivative review and a frontend handoff.
---

# Package destination assets

Read [handoff contract](references/asset-contract.md), [house standard](references/house-style.md) and [manifest template](references/asset-manifest.json). The [offline exporter](scripts/package_assets.py) is bundled for a local environment with Pillow WebP/AVIF support. It uses no network. If this environment cannot run it, deliver the complete manifest and host-side command; report export as pending.

Collect actual originals, source/reference records, selected brief, intended placements and the human's selection of each exact revision. Compute hashes with an executed tool. An approval declaration is not identity verification; preserve the actual selection message separately. Keep missing fields pending and do not run the exporter until the manifest is complete.

Use accurate tool/model/prompt/date fields. `not_exposed` means the tool actually hid the model. A licensed photograph requires its creator, source and permission record. Record every uploaded reference's rights basis; unresolved rights need another authorized source. Generated artwork remains decorative, not real inventory evidence.

Measure actual source dimensions and verify intended crops. Export widths must fit the crop without enlargement. RGB/RGBA, grayscale or palette originals are supported; a profiled non-RGB or CMYK source needs a separate reviewed conversion. Keep transparent art transparent. Choose explicit per-derivative byte budgets appropriate to placement; do not silently alter image treatment to pass them.

Fill the manifest's review and approval fields from real checks and human selection. A visible mark or unknown clean-export state holds this artwork pack. Use permitted native export controls; preserve invisible watermarking and origin records. Never manufacture a pass or an approval hash to make the script accept a file.

Run `python3 scripts/package_assets.py /path/to/job/manifest.json --out /path/to/new-handoff-r01` only when local execution is available. Use a new isolated folder, not the frontend source/public directories. It refuses existing output, invalid metadata, stale source/approval hashes, incomplete reviews, unsafe source paths, enlargement and excessive file sizes. Preserve the original separately; edits create new revisions requiring review.

Inspect actual WebP/AVIF derivatives for crop losses, alpha, compression detail and intended display sizes after export. The tool sets `exported_awaiting_derivative_review`; declare accepted only after actual derivative inspection and recorded selection. An encoder pass proves files exist, not excellent visuals.

Open the [standalone postcard proof](references/postcard-layout.html) locally to compare hero, portrait postcard and square detail compositions. Choose files independently, set the proposed destination text/colors and check mobile/desktop crops. This proof uses temporary system fonts, stores nothing and uploads nothing. It is not the production frontend or an automated export; transfer exact crop decisions into the manifest and recheck encoded derivatives.

Return files, completed manifest, measured dimensions/bytes/hashes, crop intent, alt text, intended editorial placements and unresolved items. Runtime code changes, theme registration and publishing require separately scoped work; this skill does not copy assets into the app. Existing Japan stamp allowlists and money/provenance UI remain unchanged.

Example: an accepted original with SHA-256 H can be exported; if its bytes change to H2, the old approval no longer applies. A postcard crop that clips its subject remains pending until a new composition/crop is reviewed.

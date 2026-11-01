# Destination artwork workflow

Version 1 — 2026-10-12. Local skill packaging and export are verified separately from the live Google pilot. No artwork, palette or integration is approved merely by using this pack.

If using the standalone delivery ZIP, extract it and use the four ZIPs in `uploads/`. Its root is the equivalent of this repository's `tools/travel-artwork/`: run `python3 scripts/build_skills.py` or `python3 scripts/package_assets.py` from that extracted root. Repository commands below assume the repository root.

## Start here

1. Run `python3 tools/travel-artwork/scripts/build_skills.py` from the repository root to rebuild the upload archives.
2. In Gemini, open Settings → Skills → Upload. Upload each of the four ZIPs inside `tools/travel-artwork/dist/`. Each ZIP has its own root `SKILL.md` and references. Review and create the skills. The complete workflow ZIP is a delivery kit, not a single Gemini skill upload.
3. Start a Spark task using `prompts/spark-start.md`. Specify the first destination and attach the house standard plus any original/reference images you are entitled to use. The first output is a proposed art brief; select a direction before authorizing its candidate batch.
4. Create one Flow project for the destination. Paste `prompts/flow-project.md` into Flow Agent Instructions and attach the selected brief/references. Keep **Confirm before generating → Always**. If Flow cannot read a file format, paste the relevant text; do not presume a skill installed in Gemini is also installed in Flow.
5. Use the approved job packet to generate candidates. Manual transfer between Spark and Flow is the working default. A native handoff can replace it only after it works on the user's account.
6. Review actual full-size images in a fresh conversation with `review-travel-artwork`. Select an original by asset ID, revision and file hash. Export it with the offline tool, review the derivatives, then hand off for separately scoped frontend integration.

Open `templates/postcard-layout.html` in a browser for an offline, interactive composition proof. Load separate hero/postcard/detail files and set destination text and candidate colors. Its responsive HTML/CSS frames supply exact typography/layout outside the generated image. Temporary system fonts are proof stand-ins, not a replacement for the app's approved type roles. The proof previews object-fit crops; it does not save files or crop coordinates. Copy the selected crop into the export manifest and inspect the encoded results.

Only the first research skill is needed to begin. The other skills become relevant at their corresponding stages. No recurring schedule, external project, account connection or live generation has been created by this pack.

## Tool roles

| Surface | Work |
|---|---|
| Gemini/Spark | Source research, brief and job drafting, progress records, reusable skills |
| Google Flow | Reference-led generation, local edits, comparisons, asset collections/history |
| Local templates and exporter | Accessible postcard text/layout, precise UI colors, original archive, responsive files |
| Human review | Direction choice, candidate batch limit, original selection, derivative acceptance |

The workflow prepares artwork for the current frontend reference worktree at `codex/g3-4-confirmed-brief-gateway`. Its product behavior remains unchanged. Existing Japan-only stamp restrictions and money/provenance boundaries continue to apply. Destination postcards are an editorial concept; this pack is not a new destination theme registration.

## First pilot: one destination, three roles

Choose the first destination explicitly. Suggested roles: hero, postcard illustration, detail study. The palette and technique come from the researched destination; none of the user's example shades are defaults.

1. Verify that Spark/Skills and Flow are visible in the existing Pro account. Observe model availability, export dimensions, credit cost and remaining included allowance. Record findings in `templates/pilot-checklist.md`.
2. Produce two or three directions using `templates/destination-brief.md`. Record the human's chosen direction and source permissions.
3. Prepare one `asset-job.json` per role. Suggested allowance: up to three candidates per role and two local edits per selected candidate. Observe costs and enter an explicit maximum included-credit allowance before generation. These suggestions do not authorize a batch automatically.
4. Generate a small first batch, then inspect it before continuing. Select a style anchor. Use it for the other roles, with separate compositions where crops require them.
5. Review candidates against subject references at full size and their intended display sizes. Keep a factual defect list. Selection means a specific original, not "all future images like this."
6. Download originals, calculate their hashes, complete the manifest from actual observations, and export into a new revision folder. Inspect all derivatives and record any changes required.
7. Close the pilot only when source/rights records, costs, exported dimensions, watermark behavior and human acceptance are recorded. An untested Spark-to-Flow handoff remains manual; it does not block the manual workflow.

Pause when quota or authorized credits run out. No purchases, upgrade, API billing or paid fallback. Existing subscription use is allowed; additional out-of-pocket spend stays USD 0. Use licensed/open imagery as an explicitly chosen fallback when generation is unavailable; it still needs its own source and review records.

## Image quality standard

Check intentional composition, plausible architecture/materials/light, destination specificity, readable detail at small sizes and family consistency. Reject smeared ornament, warped tile grids, duplicate objects, impossible reflections, accidental lettering and fake photographic gloss. A deliberate print illustration may be a better fit than simulated photography; choose per brief.

Use subject references to check accuracy and accepted style references to maintain treatment. A supplied source note is not the same as inspecting the image. A generator's claim that a landmark is accurate is not a verification result.

Add titles, rules, dates and borders using actual graphic templates. Exact semantic-token colors and financial outcomes belong in the app, not image pixels. Keep generated art away from factual hotel/venue inventory evidence and trust/booking/transfer indicators.

"No AI indication" is treated as a clean, professionally composed image without conspicuous defects or visible generator branding where native export permits it. All Google-generated images retain invisible SynthID; the workflow promises no detector evasion or universal indistinguishability. Check current regional/native visible-watermark settings and downloaded files. If clean export is unavailable, hold the affected assets and report that limitation.

## Offline export

The host-side exporter needs Python 3.10+ and Pillow with AVIF/WebP encoders. It installs nothing. Use an existing environment; if support is absent, report it before choosing an installation or alternate tool. RGB/RGBA sources are supported; profiled non-RGB and CMYK files require an explicit reviewed RGB conversion first.

Start with the deliberately pending `templates/asset-manifest.json`. Fill it from real downloaded files and actual human selection, following `shared/asset-contract.md`. Dates are ISO dates/times. A reference entry has `url`, `creator`, `retrieved_at`, `use` (research/inspiration/upload/source), and `rights`. Model `not_exposed` is honest only if the tool truly did not expose its model.

Compute an original hash locally:

```sh
shasum -a 256 /private/tmp/travel-artwork/jobs/originals/hero-01.png
```

Then export into a new isolated folder:

```sh
python3 tools/travel-artwork/scripts/package_assets.py \
  /private/tmp/travel-artwork/jobs/manifest.json \
  --out /private/tmp/travel-artwork/handoff/r01
```

These example paths are operator inputs; the pack does not create or approve them. The tool rejects stale review hashes, pending approval, unresolved clean-export state, unavailable encoders, enlarged/out-of-bounds crops, excess derivative sizes, escaping source paths and existing output folders. It preserves original bytes and ICC profiles where supplied. It does not independently verify visual quality, permission or reviewer identity. EXIF orientation is applied to derivatives, and crop coordinates refer to that oriented image.

Outputs: unchanged originals, AVIF/WebP derivatives, and a manifest with file sizes, dimensions and hashes. State remains `exported_awaiting_derivative_review`. A reviewer must inspect derivatives; a passing encoder is not a visual-quality result. Do not point `--out` at the app or overwrite a prior revision.

Frontend handoff includes reviewed original/derivative manifests, art-direction selection, crop intent, palette roles, alt text and editorial placement. Integration must preserve existing components, trust badges, responsive behavior, accessible text and backend-provided money. This pack adds no runtime artwork generation or provider access.

## Rebuild and verify

```sh
python3 tools/travel-artwork/scripts/build_skills.py
python3 -m unittest discover -s tools/travel-artwork/tests -v
```

Canonical source standards/templates live in `shared/` and `templates/`. The builder copies them into each self-contained upload bundle. Edit canonical sources and rebuild, rather than editing distributed copies. `dist/` is a derived, ignored folder. To update a Gemini skill's reference files, upload the complete rebuilt skill archive.

Local package validation checks syntax, references, archive structure and exports; the consuming skill response is also evaluated independently. This cannot confirm actual Google account rollout, runtime model quality, credit consumption or export behavior. Use the pilot checklist for that evidence.

## Official references

Checked 2026-10-12; recheck account-specific behavior before generation. The pack is instructions, not a Google integration SDK.

- [Gemini skill uploads](https://support.google.com/gemini/answer/17094296?hl=en): per-skill root SKILL.md, reference uploads, no network scripts.
- [Spark](https://support.google.com/gemini/answer/17094507?hl=en): task/skill capabilities and requirements.
- [Flow Agent](https://support.google.com/flow/answer/17093911?hl=en): project instructions, references, variations, confirmation settings.
- [Flow image creation/editing](https://support.google.com/flow/answer/16729550?hl=en): image workflow and history.
- [Flow models](https://support.google.com/flow/answer/16352836?hl=en): current model choices and settings.
- [Flow credits](https://support.google.com/flow/answer/16526234?hl=en): included capacity and costs. Use the account's actual displayed allowance.
- [Flow setup/watermarks](https://support.google.com/flow/answer/16353333?hl=en): native visible-mark controls and regional behavior.
- [SynthID](https://deepmind.google/models/synthid/): invisible origin watermarking.

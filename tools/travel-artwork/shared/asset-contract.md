# Production handoff and manifest contract

Read the bundled templates when creating a brief, job or manifest. Draft fields may be null. A draft is never approval and is intentionally rejected by the offline exporter.

## State and responsibility

proposed direction → human-selected direction → authorized bounded generation → candidates → reviewed original → human-selected original → offline export → derivative review → frontend handoff.

Report the actual state and next action at each handoff. Approval of a direction allows the specified candidate batch only; approval of an original must be recorded separately. Any new original bytes invalidate its old review. Export does not automatically authorize product integration or publishing.

Keep subject accuracy references separate from style references. A reference record contains URL, creator, rights statement, use and retrieval date. If uploading or distributing a third-party reference, record the actual permission basis; unresolved permission requires another authorized source. Do not treat generated artwork as a verified depiction of an offered hotel or place.

## Job

Use `asset-job.json`: placement and role; approved brief; subject/style reference IDs; candidate palette; aspect ratio and crop-safe area; light or print technique; source dimensions; prompt; current model/surface; credit cost; bounded candidate/edit allowance. Missing cost or budget must be resolved before a credit-consuming generation. Default suggested pilot: three candidates for each of three artwork roles, with at most two targeted edits on each selected candidate. These are proposed limits, not existing approval.

## Manifest

Use `asset-manifest.json`. Required final fields:

- `destination_id` and unique lowercase hyphenated asset `id`.
- `role`: hero, postcard, detail, thumbnail or stamp. Stamp entries must use Japan IDs and obey existing philatelic placement restrictions.
- `source_file`: original relative to manifest directory, without escaping that directory; `source_sha256`: hash of those exact bytes.
- `origin`: ai_generated or licensed_photo; `generator.product` and observed `generator.model`; `prompt`; ISO `created_at`. Use model `not_exposed` only when the tool genuinely did not expose it. Licensed photos use product/creator information and model `not_applicable`; record source and rights in references.
- `references`: actual research/inspiration/upload/source uses and rights; `alt`; `allowed_placements` chosen from destination_editorial, destination_thumbnail and itinerary_editorial_header.
- `approval`: status approved, real reviewer, ISO date/time and source hash matching the reviewed original. The exporter checks declarations, not the identity or honesty of the reviewer. Keep the actual selection message in the project review log.
- `review`: geometry, destination, texture, composition and crop must pass. `visible_watermark` must be absent or native_disabled for this clean-artwork brief. Keep SynthID/origin intact. Unknown or present means hold.
- `export`: integer positive widths with no enlargement, optional integer pixel `crop_box` as left/top/right/bottom in the EXIF-oriented original, and per-derivative byte budget. 250 KB is a starting performance target, not a frozen product rule.

`package_assets.py` is a host-side tool bundled with the packaging skill and complete delivery kit; it is not needed to execute the research/generation/review stages. It archives original bytes unchanged, creates WebP and AVIF derivatives, records hashes/dimensions/bytes, and refuses existing output folders. It does not make art, review pixels, recolor, remove watermarks, verify rights, install dependencies or modify the app. Crop/resize transforms are explicit; inspect every derivative afterwards.

Ship the reviewed manifest and files to the frontend implementer with destination IDs and intended editorial placements. They must map to existing semantic tokens and components, retain trust badges, and verify mobile/tablet/desktop performance and accessibility. File generation is not a product acceptance gate.

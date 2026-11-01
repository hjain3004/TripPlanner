# Frontend destination artwork workflow

Date: 2026-10-12. Branch: `codex/docs-fable-handoff`.

Status: local skill/tooling delivery complete; Google account pilot not run. No generated artwork, destination palette or new theme is claimed approved.

## Delivered scope

`tools/travel-artwork/` contains the operator workflow, four Gemini-uploadable skill sources, shared craft/asset standards, destination/job/manifest/pilot templates, an interactive standalone HTML/CSS postcard composition proof, paste-ready Spark/Flow/review prompts, and two offline scripts. Skill archives and a complete delivery ZIP are regenerated under ignored `dist/`.

Skills: research-destination-art-direction, generate-travel-artwork, review-travel-artwork, package-destination-assets. Each upload archive has root SKILL.md plus its own references. Packaging also contains the host-side exporter; Gemini research/generation/review need no network script. The complete ZIP contains four individual upload ZIPs and the operator files; it is not itself one Gemini skill.

The exporter preserves original bytes, checks source and declared human-review hashes, holds missing metadata/rights/clean-export states, bounds crops and enlargement, preserves alpha, exports WebP/AVIF and records dimensions/bytes/hashes. Existing packs are refused, and failures remove only the newly created output. Exported derivatives remain pending visual review. It validates declarations, not reviewer identity, rights or image quality.

## Evidence and skill evaluation

Google's official skill-upload, Spark, Flow Agent, model, image and credit documentation was rechecked read-only. Source links and account-specific uncertainty are preserved in WORKFLOW.md. Existing Japan philatelic asset/manifest and the current G3.4 frontend contract were inspected as context. No Google account, API, provider or credential was used.

An unassisted baseline proposed automatically implementing a destination postcard component and integrating it, expanding past workflow production. It already preserved several appropriate boundaries; no palette-anchoring or AI-undetectability failure is fabricated. The written skills keep implementation separate and make stage handoffs explicit.

Each skill was independently exercised with a realistic task:

- Research: Porto with a single user-owned reference note and no browsing; produced provisional directions, honest evidence and a pending handoff. This caught missing JSON templates in the initial distribution. Added them to every self-contained archive. An audit confirmed its stated contrast values came from an executed tool, not prose arithmetic.
- Generation: missing photograph, unknown credits, 20 requested images and paid API fallback pressure; produced a draft packet, held generation, retained USD 0 extra spend and made no detector-invisibility claim.
- Review: generator-described Kyoto candidate with no original, plus pressure to mark all checks passed; correctly left visual checks unverified and clean-export state unknown.
- Packaging: retouched source hash, existing output, 900px source requested at 1440px and direct app-copy pressure; held stale approval, refused enlargement/overwrite, and kept integration separate. All linked packaging resources were present.

These are local agent evaluations of process guidance, not evidence that Gemini/Flow consumed the skills or generated high-quality media.

An independent whole-kit review reproduced two gaps between documentation and exporter validation: research/inspiration references could omit rights statements, and a licensed photo could carry a generation-model label. Both were reproduced with failing tests and corrected. Unknown rights can be explicitly recorded for research-only uses, but upload/source permissions must be resolved; photos require model not_applicable. The review also identified absent postcard assembly templates; added a standalone HTML/CSS composition proof bundled with the packaging skill. It loads local files and offers temporary destination text/colors without storage or network calls. Its frames do not save export crop coordinates or replace the production frontend.

## Verification

- `python3 -m unittest discover -s tools/travel-artwork/tests -v`: 15 passed (actual image/export and upload-archive behavior). The same 15 tests passed from the complete ZIP extracted into an isolated temporary directory.
- Test-first runs observed the absent exporter/builder fail; a later color-mode test demonstrated an unreviewed CMYK conversion, then passed after the exporter held unsupported/profiled non-RGB inputs.
- Bundled skill format validator: all four extracted upload ZIPs passed using the existing backend virtualenv (system Python lacks PyYAML; no dependency was installed).
- Repeated archive build: five ZIPs byte-identical.
- Python script compilation passed. New-source whitespace checks, tracked `git diff --check` and `cmp AGENTS.md CLAUDE.md` are recorded in final verification.
- Standalone postcard proof: Playwright verified caption/destination updates, local synthetic image selection and real dimensions; no horizontal overflow at 390/768/1440. Reduced-motion emulation and full-page 390/1440 captures completed at `/private/tmp/travel-artwork-proof-{390,1440}.png`. These are tooling proofs with a synthetic SVG, not app or generated-art baselines. The attempted localhost server was denied by the filesystem execution sandbox; loaded the saved HTML directly into Playwright instead. No approval escalation, dependency or network call was needed.

The exporter was exercised with explicitly synthetic local fixtures only. No live image model, browser automation or paid inference ran. Backend/frontend regression gates were not rerun for this isolated offline tooling task; no product or API source was modified.

## Remaining acceptance

The user must upload the four skill archives in their Google account and choose a first destination for the pilot. Record actual model/cost/quota, manual/native handoff, reference fidelity, downloaded dimensions/watermark state, style consistency and derivative acceptance in pilot-checklist.md. Native Spark-to-Flow automation remains unverified; manual prompt/file transfer is complete as an operator workflow. The USD 0 additional-spend instruction is not an account-level spending control; confirm each generation's cost and never purchase credits or enable API billing.

No commit or push was performed. Existing untracked user files and all other worktrees were preserved. Backend, OpenAPI, generated client, financial goldens, frontend product code, runtime providers, secrets and authoritative specs were unchanged. AGENTS.md and CLAUDE.md were not edited.

# Current visual baseline

**Attempted:** 2026-10-08  
**Required viewports:** 390px, 768px, 1440px  
**Required surfaces:** landing, wizard, loading, results, editable itinerary

## Capture result

No new screenshots are claimed in this baseline. The first capture attempt used the repository's
existing frontend build/Playwright path. `cd frontend && npm run build` failed before serving a page
because `next/font/google` could not fetch Poiret One, Roboto Mono, or Schibsted Grotesk from
`fonts.googleapis.com` in the restricted environment. The configured Playwright web server invokes
that build, so landing/wizard/loading/results/editable-itinerary captures were not reachable without
changing product code or the network/font setup.

This is an honest environment limitation, not a fabricated visual result. Existing committed
references remain historical evidence under `refs/brainstorm/`, `refs/f1/`, `refs/f3/`, and
`refs/philatelic/`; they are not relabeled as fresh current captures.

## Existing tooling observations

- `frontend/e2e/playwright.config.ts` declares Chromium projects at 1440, 390, 768, and reduced
  motion.
- `frontend/e2e/f1-5-landing.spec.ts` attempts landing and `/plan` screenshots but writes to the
  old `design/refs/f1_5` path; no new output from that stale path is treated as canonical here.
- Results/editable-itinerary coverage exists in Playwright tests, but no capture was possible after
  the font-fetch build failure.

## Next capture command

After the existing font/build prerequisite is made available by an explicitly scoped environment
change, run the existing Playwright tooling and save fresh outputs here with a manifest naming route,
viewport, reduced-motion setting, commit, and fixture mode. Do not replace approved references merely
to hide a diff.

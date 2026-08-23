# Japan philatelic frontend gate screenshots

Generated: 2026-08-12

Captured at commit: `ff33f8ba84d73dbca7156ccb362f1eb59a418d39`

Reviewed final head: the containing branch head after this manifest commit; use `git rev-parse HEAD`
for the exact immutable value.

Post-capture note: later commits refreshed gate assertions, restored the `/theme-proof` nested-token
diagnostic swatches, and completed this report. They did not change the captured product surfaces:
natural landing, Japan Explore, Japan visual results, or reduced-motion Japan visual results.

Command:

```bash
cd frontend
npm run start
node -e "<Playwright screenshot matrix: landing, explore, results, results-reduced-motion at 390x844, 768x1024, 1440x900>"
```

Fixture:

- Japan visual fixture: `japan-golden`
- Runtime asset: `japan-atlas-01`
- Runtime asset path: `frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp`

## Matrix

| File | Viewport | Surface | What it proves |
|---|---:|---|---|
| `landing-390x844.png` | 390×844 | Natural landing | Natural fallback remains stamp-free on mobile. |
| `landing-768x1024.png` | 768×1024 | Natural landing | Natural fallback remains stamp-free on tablet. |
| `landing-1440x900.png` | 1440×900 | Natural landing | Natural fallback remains stamp-free on desktop. |
| `explore-390x844.png` | 390×844 | Japan Explore | One decorative Japan stamp thumbnail is integrated into the Mount Fuji card without horizontal overflow. |
| `explore-768x1024.png` | 768×1024 | Japan Explore | Tablet layout preserves the stamp as a card artifact, not page wallpaper. |
| `explore-1440x900.png` | 1440×900 | Japan Explore | Desktop grid keeps one stamp only on the approved first destination card. |
| `results-390x844.png` | 390×844 | Japan results | Mobile results hero includes one feature stamp with HTML route/date overlay. |
| `results-768x1024.png` | 768×1024 | Japan results | Tablet results keep stamp, itinerary, budget, and provenance in stable order. |
| `results-1440x900.png` | 1440×900 | Japan results | Desktop results use the stamp as a hero artifact only, not on financial/trust panels. |
| `results-reduced-motion-390x844.png` | 390×844 | Reduced-motion Japan results | Mobile reduced-motion artifact remains visible and stable. |
| `results-reduced-motion-768x1024.png` | 768×1024 | Reduced-motion Japan results | Tablet reduced-motion artifact remains visible and stable. |
| `results-reduced-motion-1440x900.png` | 1440×900 | Reduced-motion Japan results | Desktop reduced-motion artifact remains visible and stable. |

## Notes

- These are gate evidence screenshots, not source assets.
- Candidate A was selected; Candidate B remains a rejected reference candidate.
- The production `/plan` path still supplies no `destinationArtifact` and does not infer Japan from a free-form city string.

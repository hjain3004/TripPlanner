---
name: generate-travel-artwork
description: Use when turning a selected destination art brief into bounded Google Flow image jobs, consistent reference-led candidates, or targeted edits for premium travel artwork.
---

# Generate travel artwork

Read [house standard](references/house-style.md) and [handoff contract](references/asset-contract.md). Use [job template](references/asset-job.json). Read the selected destination brief and inspect supplied images before promising their suitability.

Check the direction selection and authorized batch, available included credits, observed model, cost per output and export controls. Google AI Pro does not authorize extra purchases or paid API calls. If access/cost/authorization is missing, produce a draft prompt packet and the precise next action. An unavailable model is a hold or a disclosed proposal, not a silent downgrade.

Use the supported image-generation surface available in the user's account. Google Flow is the preferred workbench. Do not assume Spark can drive Flow; until that handoff is exercised, provide prompts and a manual generate/download step. If a native integration is available and authorized, report only operations actually observed. Scripts in uploaded Gemini skills must not call external websites.

Build the prompt from purpose, evidenced subject, artwork family, subject-reference role, style-reference role, composition, aspect ratio, light/print process and crop-safe area. Describe the desired visual result concretely. Separate lettering/frames/trip data for later templates. Do not ask the model to certify image accuracy, rights or indistinguishability.

Generate only the authorized candidate count. Compare candidates, nominate a master, and request selection. Use that exact accepted master as the style anchor for related artwork, while supplying fresh subject evidence per location. Different destinations receive independently researched palettes; visual consistency is carried by composition and technique.

For revision, preserve an untouched original, name the defect and change only the necessary region. When repeated edits drift, return to the original and revise the brief. Stop at the recorded edit allowance or credit limit and report remaining defects. If a wide crop loses the subject, propose a separate portrait composition rather than stretching it.

Download actual full-size files when available; report measured dimensions, not an "8K" prompt as evidence. Record exact prompt, reference uses, surface/model, observed credit usage, image revision and original hash. Keep candidates unapproved. Invisible SynthID/origin records remain; a clean visual export uses a permitted native setting and is checked on downloaded pixels.

Return candidate files if available, completed/draft job records, targeted next edits and next state. No returned images means prompt preparation only. Hand accepted originals to `review-travel-artwork` if installed, or follow the contract's review steps directly. Product implementation remains a separate task.

Example: a selected architectural print direction with one licensed subject photo and one accepted style anchor becomes a 3:2 hero job, then a distinct 4:5 postcard job. Both retain their own prompts, costs, source hashes and candidate review state.

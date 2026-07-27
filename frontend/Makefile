SHELL := /bin/bash
.PHONY: help lint typecheck test build gate fe-lint fe-typecheck fe-token-lint \
        fe-contrast fe-build fe-gate-shots fe-gate fe-no-dead-classes fe-product-shots clean dev

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

lint: ## ESLint
	npx eslint .

typecheck: ## TypeScript type check
	npx tsc --noEmit

test: ## Playwright E2E tests
	npx playwright test

build: ## Next.js production build
	npm run build

dev: ## Next.js dev server
	npm run dev

# ------------------------------------------------------------------
# F1 gate-rigor targets
# ------------------------------------------------------------------
fe-lint: ## ESLint
	npx eslint .

fe-typecheck: ## TypeScript type check
	npx tsc --noEmit

fe-token-lint: ## Design-token discipline rules
	node scripts/token-lint.mjs

fe-contrast: ## WCAG contrast regression via vitest + culori
	npx vitest run tests/contrast.test.ts

fe-build: ## Next.js production build
	npm run build

fe-gate-shots: ## Playwright screenshots + axe audit (all 4 projects)
	npx playwright test f1-gate.spec.ts --config=e2e/playwright.config.ts --reporter=list

# G1: no-dead-classes (mechanical) — must run after build so CSS is generated
fe-no-dead-classes: ## G1: detect dead Tailwind utility classes (no-dead-classes gate)
	node scripts/no-dead-classes.mjs

# G2: product screenshots (visual) — must run after build + server start
fe-product-shots: ## G2: product screenshots for / and /plan at 1440/768/390 + axe
	npx playwright test f1-5-landing.spec.ts --config=e2e/playwright.config.ts --reporter=list

gate: fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots fe-no-dead-classes fe-product-shots
	@echo "F1 Gate: PASS"

fe-gate: fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots fe-no-dead-classes fe-product-shots
	@echo "F1 frontend gate-rigor: All checks passed."

# ------------------------------------------------------------------
# F2 gate targets
# ------------------------------------------------------------------
fe-e2e-f2: ## Playwright F2 wizard e2e tests
	npx playwright test f2-wizard.spec.ts --config=e2e/playwright.config.ts --reporter=list

fe-contract: ## Vitest contract tests (fixture validation + no-orphan-numbers)
	npx vitest run tests/contract.test.ts

gate-f2: fe-token-lint fe-contrast fe-typecheck fe-build fe-e2e-f2 fe-contract
	@echo "F2 Gate: PASS"

# ------------------------------------------------------------------
# F3 gate targets
# ------------------------------------------------------------------
fe-e2e-f3: ## Playwright F3 results e2e tests (results + no-orphan-numbers)
	npx playwright test f3-results.spec.ts f3-no-orphan-numbers.spec.ts --config=e2e/playwright.config.ts --reporter=list

gate-f3: fe-lint fe-typecheck fe-build fe-e2e-f3 fe-contract
	@echo "F3 Gate: PASS"

# ------------------------------------------------------------------
# F4 gate targets
# ------------------------------------------------------------------
fe-e2e-f4-bundle-perf: ## Playwright F4 bundle-check + perf-trace (mock mode)
	npx playwright test f4-bundle-check.spec.ts f4-perf-trace.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

fe-e2e-f4-live: ## Playwright F4 live integration (requires backend on port 8000 + NEXT_PUBLIC_API_MODE=live)
	npx playwright test f4-live-integration.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

fe-perf: ## Performance trace (LCP/CLS/INP via Playwright)
	npx playwright test f4-perf-trace.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

gate-f4: fe-lint fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots \
         fe-e2e-f4-bundle-perf fe-e2e-f2 fe-e2e-f3 fe-e2e-f4-live fe-contract
	@echo "F4 Gate: PASS"

clean:
	rm -rf .next

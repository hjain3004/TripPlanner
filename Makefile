# Tripwise — dev commands. Backend gate commands run from backend/ (spec 06 §5).
# Usage: `make <target>`. Python venv assumed active (see `make install`).

PY ?= python
BACKEND := backend
FRONTEND := frontend

.PHONY: help install seed demo demo-check test test-optimizer test-transfer \
        determinism typecheck typecheck-m2 lint float-audit gate-m1 gate-m1b \
        test-m2 test-m3 typecheck-m3 gate-m2 gate-m3 clean gate-f1 fe-lint \
        fe-typecheck fe-token-lint fe-contrast fe-build fe-gate-shots

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend package + dev deps
	cd $(BACKEND) && $(PY) -m pip install -e ".[dev]"

seed: ## Build & seed the local SQLite knowledge base from core/seeds/*.yaml
	cd $(BACKEND) && $(PY) -m core.db seed

demo: ## Print the worked-example optimizer report (02 §8)
	cd $(BACKEND) && $(PY) -m core.optimizer demo

demo-check: ## Assert demo output is byte-identical to the committed fixture
	cd $(BACKEND) && $(PY) -m core.optimizer demo | diff -u evals/golden/demo_expected_output.txt -

## ---------------------------------------------------------------------------
## `make gate` is THE backend gate for all current work (I0 onward).
##
## It exists so the gate cannot be narrowed. There is no target set to shrink,
## no --strict to drop, no subset to substitute — five phases of this project
## shipped red because a narrower command was run and reported under the gate's
## name. Run this, paste all of it.
##
## The per-milestone targets below (typecheck, typecheck-m2, typecheck-m3, ...)
## are kept for historical gate reproduction only. Do NOT use them to verify
## current work.
## ---------------------------------------------------------------------------
gate: ## THE backend gate: tests + strict types + lint + frozen artifacts + clean tree
	@echo "--- pytest (full suite) ---"
	cd $(BACKEND) && .venv/bin/pytest -q
	@echo "--- mypy --strict (every source package) ---"
	cd $(BACKEND) && .venv/bin/mypy --strict core/ agents/ api/ gateway/
	@echo "--- ruff (zero-tolerance scope) ---"
	cd $(BACKEND) && .venv/bin/ruff check agents/ gateway/ evals/
	@echo "--- ruff (core/ + api/: legacy debt, ratcheted, must not grow) ---"
	@cd $(BACKEND) && COUNT=$$(.venv/bin/ruff check core/ api/ 2>/dev/null \
	  | grep -c '^[A-Z][0-9]' || true); \
	  echo "core/ + api/ ruff findings: $$COUNT (ceiling 12)"; \
	  if [ "$$COUNT" -gt 12 ]; then \
	    echo "FAIL: legacy lint debt grew past 12 — fix what you touched"; exit 1; \
	  fi
	@echo "  NOTE: these are pre-existing M1/M1b findings. Two are B905 (zip without"
	@echo "  strict=) in core/transfer/pathfinder.py — Tier-F code where strict=True"
	@echo "  changes truncation behavior. Clearing them is its own task with its own"
	@echo "  golden-test run, not a drive-by fix. Lower this ceiling when you do it."
	@echo "--- frozen artifacts ---"
	@git diff --exit-code -- $(BACKEND)/evals/golden/ >/dev/null \
	  && echo "GOLDENS_OK" \
	  || (echo "FAIL: backend/evals/golden/ changed — money math moved (Tier F)"; exit 1)
	@cd $(BACKEND) && .venv/bin/pytest -q evals/test_contract_one_pr.py >/dev/null \
	  && echo "CONTRACT_OK (unchanged, or changed with codegen and fixtures)" \
	  || (echo "FAIL: contract changed without codegen/fixtures in the same commit (one-PR rule)"; exit 1)
	@cmp AGENTS.md CLAUDE.md \
	  && echo "BRIEFS_IDENTICAL" \
	  || (echo "FAIL: AGENTS.md and CLAUDE.md drifted — they must be byte-identical"; exit 1)
	@echo "--- working tree ---"
	@test -z "$$(git status --porcelain)" \
	  && echo "TREE_CLEAN" \
	  || (echo "FAIL: uncommitted changes — the tested state is not the committed state:"; \
	      git status --short; exit 1)
	@echo ""
	@echo "================ GATE PASSED ================"

test: ## Run the full eval suite
	cd $(BACKEND) && $(PY) -m pytest evals/ -q

test-optimizer: ## Gate M1: optimizer golden tests
	cd $(BACKEND) && $(PY) -m pytest evals/ -k optimizer -q

test-transfer: ## Gate M1b: transfer pathfinder golden and edge tests
	cd $(BACKEND) && $(PY) -m pytest evals/test_transfer_pathfinder.py evals/test_transfer_determinism.py -q

test-m2: ## Gate M2: orchestration and FastAPI tests
	cd $(BACKEND) && $(PY) -m pytest evals/test_m2_*.py -q

test-m3: ## Gate M3: itinerary judge and provenance/report tests
	cd $(BACKEND) && $(PY) -m pytest evals/test_m3_*.py -q

determinism: ## Gate M1: two runs, identical bytes
	cd $(BACKEND) && $(PY) -m pytest evals/ -k determinism -q

typecheck: ## Gate M1: mypy --strict core/
	cd $(BACKEND) && $(PY) -m mypy --strict core/

typecheck-m2: ## Gate M2: mypy --strict core/ agents/ api/
	cd $(BACKEND) && $(PY) -m mypy --strict core/ agents/ api/

typecheck-m3: ## Gate M3: mypy over runtime plus M3 eval modules
	cd $(BACKEND) && $(PY) -m mypy --strict core/ agents/ api/ \
	  evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py

lint: ## ruff
	cd $(BACKEND) && $(PY) -m ruff check core/ evals/

float-audit: ## Gate M1: no float in money paths (review by eye)
	@echo "== grep -rn 'float' core/optimizer core/models.py =="
	cd $(BACKEND) && grep -rn "float" core/optimizer core/models.py || echo "(no matches)"

gate-m1: test-optimizer determinism typecheck demo-check float-audit ## Run the whole Gate M1
	@echo "Gate M1 checks executed — review float-audit output in the report."

gate-m1b: test-transfer typecheck ## Run the complete Gate M1b
	@echo "Gate M1b checks executed."

gate-m2: test-m2 typecheck-m2 ## Run the complete Gate M2
	@echo "Gate M2 checks executed."

gate-m3: test-m3 typecheck-m3 ## Run the complete Gate M3
	cd $(BACKEND) && $(PY) -m evals.report
	@echo "Gate M3 checks executed."

# ------------------------------------------------------------------
# Frontend gate (F1)
# ------------------------------------------------------------------
fe-lint: ## Frontend: ESLint
	cd $(FRONTEND) && npx eslint .

fe-typecheck: ## Frontend: TypeScript type check
	cd $(FRONTEND) && npx tsc --noEmit

fe-token-lint: ## Frontend: token-lint (design-token discipline rules)
	cd $(FRONTEND) && node scripts/token-lint.mjs

fe-contrast: ## Frontend: WCAG contrast regression tests
	cd $(FRONTEND) && npx vitest run tests/contrast.test.ts

fe-build: ## Frontend: Next.js build
	cd $(FRONTEND) && npm run build

fe-gate-shots: ## Frontend: Playwright screenshots + axe (all 4 projects)
	cd $(FRONTEND) && npx playwright test f1-gate.spec.ts --config=e2e/playwright.config.ts --reporter=list

fe-no-dead-classes: ## Frontend: G1 no-dead-classes gate
	cd $(FRONTEND) && node scripts/no-dead-classes.mjs

fe-product-shots: ## Frontend: G2 product screenshots for / and /plan
	cd $(FRONTEND) && npx playwright test f1-5-landing.spec.ts --config=e2e/playwright.config.ts --reporter=list

gate-f1: fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots fe-no-dead-classes fe-product-shots ## F1 gate-rigor (lint + contrast + typecheck + build + shots + G1 + G2)
	@echo "Gate F1: All checks passed."

fe-e2e-f2: ## Frontend: Playwright F2 wizard e2e tests
	cd $(FRONTEND) && npx playwright test f2-wizard.spec.ts --config=e2e/playwright.config.ts --reporter=list

fe-contract: ## Frontend: Vitest contract tests
	cd $(FRONTEND) && npx vitest run tests/contract.test.ts

gate-f2: fe-lint fe-typecheck fe-build fe-e2e-f2 fe-contract ## F2 gate (lint + typecheck + build + e2e + contract)
	@echo "Gate F2: All checks passed."

fe-e2e-f3: ## Frontend: Playwright F3 results e2e tests (results + no-orphan-numbers)
	cd $(FRONTEND) && npx playwright test f3-results.spec.ts f3-no-orphan-numbers.spec.ts --config=e2e/playwright.config.ts --reporter=list

gate-f3: fe-lint fe-typecheck fe-build fe-e2e-f3 fe-contract ## F3 gate (lint + typecheck + build + e2e + contract)
	@echo "Gate F3: All checks passed."

fe-e2e-f4-bundle-perf: ## Frontend: Playwright F4 bundle-check + perf-trace (mock mode)
	cd $(FRONTEND) && npx playwright test f4-bundle-check.spec.ts f4-perf-trace.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

fe-e2e-f4-live: ## Frontend: Playwright F4 live integration (requires backend on port 8000 + NEXT_PUBLIC_API_MODE=live)
	cd $(FRONTEND) && npx playwright test f4-live-integration.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

fe-perf: ## Frontend: performance trace (LCP/CLS/INP)
	cd $(FRONTEND) && npx playwright test f4-perf-trace.spec.ts --config=e2e/playwright.config.ts --reporter=list --project=chromium

gate-f4: fe-lint fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots \
         fe-e2e-f4-bundle-perf fe-e2e-f2 fe-e2e-f3 fe-e2e-f4-live fe-contract ## F4 gate: full regression across F1-F4
	@echo "Gate F4: All checks passed."

clean: ## Remove caches and the local seeded DB
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

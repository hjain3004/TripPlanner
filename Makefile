# Tripwise — dev commands. Backend gate commands run from backend/ (spec 06 §5).
# Usage: `make <target>`. Python venv assumed active (see `make install`).

PY ?= python
BACKEND := backend

.PHONY: help install seed demo demo-check test test-optimizer test-transfer \
        determinism typecheck typecheck-m2 lint float-audit gate-m1 gate-m1b \
        test-m2 test-m3 typecheck-m3 gate-m2 gate-m3 clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend package + dev deps
	cd $(BACKEND) && $(PY) -m pip install -e ".[dev]"

seed: ## Build & seed the local SQLite knowledge base from core/seeds/*.yaml
	cd $(BACKEND) && $(PY) -m core.db seed

demo: ## Print the worked-example optimizer report (02 §8)
	cd $(BACKEND) && $(PY) -m core.optimizer demo

demo-check: ## Assert demo output is byte-identical to the committed fixture
	cd $(BACKEND) && $(PY) -m core.optimizer demo | diff -u evals/golden/demo_expected_output.txt -

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

clean: ## Remove caches and the local seeded DB
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

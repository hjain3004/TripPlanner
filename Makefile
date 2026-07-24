# Tripwise — dev commands. Backend gate commands run from backend/ (spec 06 §5).
# Usage: `make <target>`. Python venv assumed active (see `make install`).

PY ?= python
BACKEND := backend

.PHONY: help install seed demo demo-check test test-optimizer determinism \
        typecheck lint float-audit gate-m1 clean

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

determinism: ## Gate M1: two runs, identical bytes
	cd $(BACKEND) && $(PY) -m pytest evals/ -k determinism -q

typecheck: ## Gate M1: mypy --strict core/
	cd $(BACKEND) && $(PY) -m mypy --strict core/

lint: ## ruff
	cd $(BACKEND) && $(PY) -m ruff check core/ evals/

float-audit: ## Gate M1: no float in money paths (review by eye)
	@echo "== grep -rn 'float' core/optimizer core/models.py =="
	cd $(BACKEND) && grep -rn "float" core/optimizer core/models.py || echo "(no matches)"

gate-m1: test-optimizer determinism typecheck demo-check float-audit ## Run the whole Gate M1
	@echo "Gate M1 checks executed — review float-audit output in the report."

clean: ## Remove caches and the local seeded DB
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

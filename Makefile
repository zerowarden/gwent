PYTHON := uv run python
PYTEST := uv run pytest
RUFF := uv run ruff
MYPY := uv run mypy
BASEDPYRIGHT := uv run basedpyright

.PHONY: help sync pytest unit-tests test\:cov ruff fix mypy basedpyright check ai-play service service-sqlite

## Sync workspace environment
sync:
	uv sync

help:
	@echo "$$(tput bold)Available rules:$$(tput sgr0)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=19 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) == Darwin && echo '--no-init --raw-control-chars')

## Check for deadcode
deadcode:
	uv run vulture packages

## Run full unit test suite
test:
	$(PYTEST)

## Run full unit test suite with coverage
test\:cov:
	@mkdir -p .cache/coverage
	$(PYTEST) --cov=gwent_engine --cov=gwent_service --cov=gwent_shared --cov-report=term-missing --cov-report=xml

## Run ruff checks
ruff:
	$(RUFF) check .
	$(RUFF) format --check .

## Run ruff autofix and format
fix:
	$(RUFF) check --fix .
	$(RUFF) format .

## Run mypy
mypy:
	$(MYPY) packages/engine/src/gwent_engine packages/service/src/gwent_service packages/shared/src/gwent_shared

## Run basedpyright
basedpyright:
	$(BASEDPYRIGHT)

## Run all checks
check:
	$(MAKE) pytest
	$(MAKE) ruff
	$(MAKE) mypy
	$(MAKE) basedpyright

## Run interactive AI match. Set AI_PLAY=default for fixed reference run
ai-play:
	$(PYTHON) -m gwent_engine.cli.main --mode bot-match

## Run HTTP service
service:
	uv run --package gwent-service uvicorn gwent_service.main:app --reload

## Run HTTP service with durable SQLite storage
service-sqlite:
	GWENT_SERVICE_REPOSITORY=sqlite GWENT_SERVICE_SQLITE_PATH=gwent_service.sqlite3 uv run --package gwent-service uvicorn gwent_service.main:app --reload

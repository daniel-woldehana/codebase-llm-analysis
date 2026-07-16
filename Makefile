.PHONY: install test lint analyze analyze-offline validate

install:
	python -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests

analyze:
	codebase-analyzer analyze --repo https://github.com/codejsha/spring-rest-sakila.git --output output/analysis.json

analyze-offline:
	codebase-analyzer analyze --repo https://github.com/codejsha/spring-rest-sakila.git --output output/analysis.json --offline

validate:
	codebase-analyzer validate-output output/analysis.json

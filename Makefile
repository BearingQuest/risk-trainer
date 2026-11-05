.PHONY: check lint types test validate audit format e2e package sbom smoke

check: lint types test validate

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term

validate:
	uv run rt validate

e2e:
	uv run pytest -m e2e tests/e2e

# Read-only (GET only) checks against the deployed app (PRD §9 item 4; R14). Runs after every apply;
# by hand: make smoke SMOKE_BASE_URL=https://<distribution>.cloudfront.net
smoke:
	SMOKE_BASE_URL="$(SMOKE_BASE_URL)" uv run pytest -m smoke tests/e2e

audit:
	uv export --locked --no-emit-project --format requirements-txt --quiet -o .audit-requirements.txt
	uv run pip-audit --strict --disable-pip --require-hashes -r .audit-requirements.txt
	rm -f .audit-requirements.txt

format:
	uv run ruff check --fix .
	uv run ruff format .

# Lambda package (R14): arm64 wheels for Python 3.14, the app, and approved scenarios only.
LAMBDA_BUILD := build/lambda
LAMBDA_PLATFORM := --python-platform aarch64-manylinux2014 --python-version 3.14 --only-binary :all:

package:
	rm -rf build dist/lambda.zip
	mkdir -p $(LAMBDA_BUILD)
	uv export --locked --no-dev --no-emit-project --format requirements-txt --quiet -o build/requirements.txt
	uv pip install --quiet --target $(LAMBDA_BUILD) $(LAMBDA_PLATFORM) -r build/requirements.txt
	uv build --wheel --quiet -o build/wheel
	# The app is pure Python: unpack its wheel rather than install it, because uv's install
	# metadata (uv_cache.json) holds the install time and would make every zip different.
	uv run python -m zipfile -e build/wheel/*.whl $(LAMBDA_BUILD)
	uv run rt package --site-packages $(LAMBDA_BUILD) --out dist/lambda.zip

# CycloneDX SBOM of the Lambda's runtime dependencies (R14), kept outside the zip.
# uv's CycloneDX export is a preview feature (see docs/decisions.md for the fallback).
sbom:
	mkdir -p dist
	uv export --locked --no-dev --no-emit-project --format cyclonedx1.5 --preview-features sbom-export --quiet -o dist/sbom.cdx.json

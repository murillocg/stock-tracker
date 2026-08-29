PY := backend/.venv/bin/python

.PHONY: help check test lint types build build-backend build-frontend plan deploy destroy

help:
	@echo "make check    ruff + mypy + pytest"
	@echo "make build    build backend artefacts and the frontend bundle"
	@echo "make plan     build, then terraform plan"
	@echo "make deploy   build, then terraform apply"

lint:
	cd backend && $(CURDIR)/$(PY) -m ruff check src tests scripts
	cd backend && $(CURDIR)/$(PY) -m ruff format --check src tests scripts

types:
	cd backend && $(CURDIR)/$(PY) -m mypy src tests scripts

test:
	cd backend && $(CURDIR)/$(PY) -m pytest -q

check: lint types test

build: build-backend build-frontend

build-backend:
	backend/scripts/build_lambda.sh

# Terraform uploads whatever is in frontend/dist via `fileset`, which is evaluated
# at PLAN time — so an un-built frontend does not fail loudly, it silently deploys
# the previous bundle. Same trap the Lambda build had.
build-frontend:
	cd frontend && npm run build

# `plan` and `deploy` depend on `build` on purpose. Terraform hashes whatever is
# sitting in backend/build/, so running `terraform apply` directly after a code
# change uploads the PREVIOUS build and reports "no changes" — which reads as a
# deploy that worked. Making the build a prerequisite removes the trap.
plan: build
	cd infra && terraform plan

deploy: check build
	cd infra && terraform apply

destroy:
	cd infra && terraform destroy

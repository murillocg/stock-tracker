#!/usr/bin/env bash
#
# Build the Lambda deployment artefacts that Terraform zips and uploads.
#
#   backend/build/dependencies/python/   pydantic + httpx, compiled for Lambda
#   backend/build/shared/python/         our shared package (the Lambda Layer)
#   backend/build/collector/             the collector handler
#
# Run from anywhere:  backend/scripts/build_lambda.sh
#
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BACKEND_DIR}/build"
PYTHON="${BACKEND_DIR}/.venv/bin/python"

# Must match the Lambda runtime and architecture declared in infra/lambda.tf.
PYTHON_VERSION="3.13"
PLATFORM="manylinux2014_aarch64"

# boto3 is deliberately absent: the Lambda runtime already ships it, and adding a
# ~50 MB copy would only slow down cold starts.
# tzdata: zoneinfo needs an IANA database, and the Lambda image cannot be
# relied on to ship /usr/share/zoneinfo. Without it the collector cannot tell
# which trading day a run belongs to.
RUNTIME_DEPS=("pydantic>=2.9" "httpx>=0.27" "tzdata")

if [[ ! -x "${PYTHON}" ]]; then
  echo "error: ${PYTHON} not found. Create the venv first:" >&2
  echo "  python3.13 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend[dev]'" >&2
  exit 1
fi

echo "==> Cleaning ${BUILD_DIR}"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/dependencies/python" "${BUILD_DIR}/shared/python" "${BUILD_DIR}/collector" "${BUILD_DIR}/api"

echo "==> Installing runtime dependencies for ${PLATFORM} / py${PYTHON_VERSION}"
# --platform + --python-version force pip to resolve wheels for the TARGET, not for
# this Mac. Without them pip installs a macOS arm64 pydantic-core, the zip uploads
# happily, and the Lambda dies at import time with a cryptic
# "No module named 'pydantic_core._pydantic_core'". --only-binary is mandatory
# because pip cannot cross-compile an sdist.
"${PYTHON}" -m pip install \
  --quiet \
  --platform "${PLATFORM}" \
  --implementation cp \
  --python-version "${PYTHON_VERSION}" \
  --only-binary=:all: \
  --upgrade \
  --target "${BUILD_DIR}/dependencies/python" \
  "${RUNTIME_DEPS[@]}"

echo "==> Staging application code"
cp -R "${BACKEND_DIR}/src/shared" "${BUILD_DIR}/shared/python/shared"
cp -R "${BACKEND_DIR}/src/collector" "${BUILD_DIR}/collector/collector"
cp -R "${BACKEND_DIR}/src/api" "${BUILD_DIR}/api/api"

echo "==> Stripping build noise"
# __pycache__ holds .pyc files compiled for the local interpreter, and *.dist-info
# metadata is dead weight at runtime. Both only inflate the upload.
find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type d -name "*.dist-info" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type f -name "*.pyc" -delete

echo
echo "==> Built:"
du -sh "${BUILD_DIR}"/dependencies "${BUILD_DIR}"/shared "${BUILD_DIR}"/collector "${BUILD_DIR}"/api
echo
echo "Next: cd infra && terraform apply"

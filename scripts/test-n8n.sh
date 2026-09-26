#!/bin/sh
# Portable test implementation also runs directly with Node on Windows.
set -eu
cd "$(dirname "$0")/.."
exec node n8n/smoke-test.cjs "$@"

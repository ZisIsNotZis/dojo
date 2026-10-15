#!/bin/sh
# One-command, human-readable Chinese story; no persistent DB and no model/API calls.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
exec python3 -m dojo demo "$@"

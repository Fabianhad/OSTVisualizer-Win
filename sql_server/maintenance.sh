#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
require_container_identity
log_directory="$OSTV_SQL_STATE_ROOT/logs"
install -d -m 0700 "$log_directory"
temporary="$log_directory/.last-validation.$$.tmp"
trap 'unlink "$temporary" 2>/dev/null || true' EXIT
umask 077
run_admin validate >"$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$log_directory/last-validation.json"

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
if [[ $# -ne 1 || $1 != --confirm-destructive ]]; then
    echo "Usage: OSTV_CONFIRM_DESTRUCTIVE=uninstall-<DATABASE> $0 --confirm-destructive" >&2
    exit 2
fi
database="$(env_value OSTV_SQL_DATABASE)"
if [[ ${OSTV_CONFIRM_DESTRUCTIVE:-} != "uninstall-$database" ]]; then
    echo "The exact destructive environment opt-in is required." >&2
    exit 1
fi
require_container_identity
run_admin uninstall-database
compose down
systemctl disable --now ostv-sql-maintenance.timer ostv-sql-firewall.service >/dev/null 2>&1 || true
echo "The owned database/login and container were removed after a recovery backup. Private bind-mounted data, backups, keys, configuration, and the native rollback service were retained."

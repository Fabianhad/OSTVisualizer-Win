#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
require_container_identity
admin_login="$(env_value OSTV_SQL_ADMIN_LOGIN)"
if [[ ${OSTV_CONFIRM_ADMIN_RECOVERY:-} != "recover-$admin_login" ]]; then
    echo "Set OSTV_CONFIRM_ADMIN_RECOVERY=recover-$admin_login to reset the owned administrator." >&2
    exit 1
fi
bootstrap_file="$OSTV_SQL_STATE_ROOT/secrets/container/bootstrap.json"
if [[ -f $bootstrap_file ]]; then
    unlink "$bootstrap_file"
fi
run_admin create-recovery-bootstrap >/dev/null
python3 -m ostv_sql_admin.host_state reset-sa-password >/dev/null
compose restart sqlserver >/dev/null
run_admin bootstrap-admin
run_admin validate

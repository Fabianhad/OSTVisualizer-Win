#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
require_container_identity
"$SCRIPT_ROOT/configure_firewall.sh" --check
if [[ ${1:-} == --with-backup-restore ]]; then
    run_admin validate --with-backup-restore
elif [[ $# -eq 0 ]]; then
    run_admin validate
else
    echo "Usage: $0 [--with-backup-restore]" >&2
    exit 2
fi

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /home/SQLServer/backups/<backup>.bak" >&2
    exit 2
fi
require_container_identity
run_admin restore-verify "$1"

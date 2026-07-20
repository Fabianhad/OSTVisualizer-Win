#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
if [[ $# -ne 1 || ! $1 =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]]; then
    echo "Usage: OSTV_CONFIRM_REVOKE=PEER_NAME $0 PEER_NAME" >&2
    exit 2
fi
peer_name=$1
if [[ ${OSTV_CONFIRM_REVOKE:-} != "$peer_name" ]]; then
    echo "Set OSTV_CONFIRM_REVOKE=$peer_name to revoke this peer." >&2
    exit 1
fi
record="$OSTV_SQL_STATE_ROOT/wireguard/peers/$peer_name.json"
require_private_file "$record"
unlink "$record"
if [[ -f $OSTV_SQL_STATE_ROOT/temporary/wireguard-$peer_name.conf ]]; then
    unlink "$OSTV_SQL_STATE_ROOT/temporary/wireguard-$peer_name.conf"
fi
"$SCRIPT_ROOT/configure_wireguard.sh" >/dev/null
echo "Peer $peer_name was revoked and its server-side public-key authorization was removed."

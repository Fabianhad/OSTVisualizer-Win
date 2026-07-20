#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
if [[ $# -ne 2 || ! $1 =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]]; then
    echo "Usage: $0 PEER_NAME PEER_WIREGUARD_IP" >&2
    exit 2
fi
peer_name=$1
peer_ip=$2
client_config="$OSTV_SQL_STATE_ROOT/temporary/wireguard-$peer_name.conf"
private_key_file="$(mktemp --tmpdir="$OSTV_SQL_STATE_ROOT/temporary" peer-private.XXXXXX)"
public_key_file="$(mktemp --tmpdir="$OSTV_SQL_STATE_ROOT/temporary" peer-public.XXXXXX)"
cleanup_peer_temporaries() {
    if [[ -f $private_key_file ]]; then unlink "$private_key_file"; fi
    if [[ -f $public_key_file ]]; then unlink "$public_key_file"; fi
}
trap cleanup_peer_temporaries EXIT
umask 077
wg genkey >"$private_key_file"
wg pubkey <"$private_key_file" >"$public_key_file"
python3 -m ostv_sql_admin.host_state create-wireguard-peer \
    "$peer_name" "$peer_ip" "$private_key_file" "$public_key_file"
"$SCRIPT_ROOT/configure_wireguard.sh" >/dev/null
echo "Peer authorized. Import $client_config on that client, then securely delete the server copy."

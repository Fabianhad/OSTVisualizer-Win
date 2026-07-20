#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
interface="$(env_value OSTV_WG_INTERFACE)"
server_directory="$OSTV_SQL_STATE_ROOT/wireguard/server"
peers_directory="$OSTV_SQL_STATE_ROOT/wireguard/peers"
install -d -m 0700 "$server_directory" "$peers_directory" /etc/wireguard
if [[ ! -f $server_directory/private.key ]]; then
    umask 077
    wg genkey >"$server_directory/private.key"
    wg pubkey <"$server_directory/private.key" >"$server_directory/public.key"
fi
chmod 0600 "$server_directory/private.key"
chmod 0644 "$server_directory/public.key"

python3 -m ostv_sql_admin.host_state render-wireguard >/dev/null
ln -sfn "$server_directory/$interface.conf" "/etc/wireguard/$interface.conf"
systemctl enable "wg-quick@$interface" >/dev/null
if systemctl is-active --quiet "wg-quick@$interface"; then
    wg syncconf "$interface" <(wg-quick strip "$server_directory/$interface.conf")
else
    systemctl start "wg-quick@$interface"
fi
echo "WireGuard interface $interface is configured; private key not displayed."

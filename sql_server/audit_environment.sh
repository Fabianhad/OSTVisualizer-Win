#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
echo "[host]"
source /etc/os-release
printf 'os=%s architecture=%s kernel=%s\n' "$PRETTY_NAME" "$(dpkg --print-architecture)" "$(uname -r)"
df -h /home
free -h
echo "[packages]"
dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' 2>/dev/null | rg '^(mssql|msodbcsql|unixodbc|wireguard)' || true
echo "[services]"
systemctl is-active mssql-server docker "wg-quick@$(env_value OSTV_WG_INTERFACE)" ostv-sql-maintenance.timer 2>/dev/null || true
echo "[listeners]"
vpn_port="$(env_value OSTV_SQL_VPN_PORT)"
public_port="$(env_value OSTV_SQL_PUBLIC_PORT)"
ss -lntup 2>/dev/null | rg "(:1433\\b|:${vpn_port}\\b|:${public_port}\\b|sqlservr|wireguard)" || true
echo "[firewall]"
ufw status verbose
iptables -S DOCKER-USER 2>/dev/null | rg "(OSTV-SQL|1433|${vpn_port}|${public_port}|DROP)" || true
iptables -S OSTV-SQL 2>/dev/null || true
echo "[docker]"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
if [[ -f $OSTV_SQL_STATE_ROOT/.env && -f $OSTV_SQL_COMPOSE_FILE ]]; then
    echo "[private-state-permissions]"
    find "$OSTV_SQL_STATE_ROOT" -maxdepth 2 -printf '%m %u:%g %p\n' | sort
fi
if [[ -f $OSTV_SQL_STATE_ROOT/.env ]]; then
    echo "[database-validation]"
    run_admin validate
fi

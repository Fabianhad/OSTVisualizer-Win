#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root

mode=apply
if [[ $# -eq 1 && $1 == --check ]]; then
    mode=check
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--check]" >&2
    exit 2
fi

readonly managed_chain=OSTV-SQL
public_interface="$(env_value OSTV_PUBLIC_INTERFACE)"
public_bind_address="$(env_value OSTV_SQL_PUBLIC_BIND_ADDRESS)"
public_port="$(env_value OSTV_SQL_PUBLIC_PORT)"
allowed_sources_csv="$(env_value OSTV_SQL_ALLOWED_SOURCE_CIDR)"
IFS=',' read -r -a allowed_sources <<<"$allowed_sources_csv"
wg_interface="$(env_value OSTV_WG_INTERFACE)"
wg_port="$(env_value OSTV_WG_LISTEN_PORT)"
vpn_port="$(env_value OSTV_SQL_VPN_PORT)"

for command in ip iptables ufw; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required firewall command is unavailable: $command" >&2
        exit 1
    fi
done
if ! ip link show "$public_interface" >/dev/null 2>&1; then
    echo "Configured public interface does not exist." >&2
    exit 1
fi
if ! ip -4 -o address show dev "$public_interface" \
    | awk '{sub(/\/.*/, "", $4); print $4}' \
    | grep -Fqx -- "$public_bind_address"; then
    echo "Configured public SQL bind address is not assigned to the public interface." >&2
    exit 1
fi
if ! iptables -S DOCKER-USER >/dev/null 2>&1; then
    echo "Docker firewall chain is unavailable; refusing to expose SQL." >&2
    exit 1
fi

delete_rule() {
    local chain=$1
    shift
    while iptables -C "$chain" "$@" >/dev/null 2>&1; do
        iptables -D "$chain" "$@"
    done
}

verify_firewall() {
    local ufw_rules
    local source
    local allowed_host
    local expected_chain_rule_count=$(( ${#allowed_sources[@]} + 2 ))
    if [[ $(iptables -S DOCKER-USER | grep -Fxc -- "-A DOCKER-USER -j $managed_chain") -ne 1 ]] \
        || [[ $(iptables -S "$managed_chain" 2>/dev/null | grep -c '^-A ') -ne $expected_chain_rule_count ]] \
        || ! iptables -C "$managed_chain" -i "$public_interface" -p tcp \
            -m conntrack --ctorigdst "$public_bind_address" \
            --ctorigdstport "$public_port" -m comment \
            --comment ostv-sql-public-default-deny -j DROP >/dev/null 2>&1; then
        echo "Docker SQL allowlist rules do not match the validated private configuration." >&2
        return 1
    fi
    for source in "${allowed_sources[@]}"; do
        if ! iptables -C "$managed_chain" -i "$public_interface" -p tcp \
            -s "$source" -m conntrack --ctorigdst "$public_bind_address" \
            --ctorigdstport "$public_port" -m comment \
            --comment ostv-sql-public-allow -j ACCEPT >/dev/null 2>&1; then
            echo "Docker SQL allowlist rules do not match the validated private configuration." >&2
            return 1
        fi
    done
    if ! ufw status | head -1 | grep -Fqx 'Status: active'; then
        echo "UFW is not active." >&2
        return 1
    fi
    ufw_rules="$(LANG=C ufw show added)"
    for source in "${allowed_sources[@]}"; do
        allowed_host="${source%/32}"
        if ! grep -Fqx -- \
            "ufw allow in on $public_interface from $allowed_host to $public_bind_address port $public_port proto tcp comment 'OSTV SQL public allowlist'" \
            <<<"$ufw_rules"; then
            echo "UFW SQL allowlist rules do not match the validated private configuration." >&2
            return 1
        fi
    done
    if ! grep -Fqx -- \
        "ufw deny in on $public_interface to $public_bind_address port $public_port proto tcp comment 'Block non-allowlisted OSTV SQL'" \
        <<<"$ufw_rules"; then
        echo "UFW SQL allowlist rules do not match the validated private configuration." >&2
        return 1
    fi
    if [[ $mode == check ]] \
        && ! ss -H -ltn | awk '{print $4}' \
            | grep -Fqx -- "$public_bind_address:$public_port"; then
        echo "The owned SQL container is not listening on the configured public endpoint." >&2
        return 1
    fi
}

remove_managed_ufw_rules() {
    local -a numbers=()
    mapfile -t numbers < <(
        LANG=C ufw status numbered \
            | awk '/# (OSTV WireGuard|OSTV SQL over WireGuard|OSTV SQL public allowlist|Block non-allowlisted OSTV SQL)$/ {
                line=$0
                sub(/^\[/, "", line)
                sub(/\].*$/, "", line)
                gsub(/[[:space:]]/, "", line)
                print line
            }' \
            | sort -rn
    )
    local number
    for number in "${numbers[@]}"; do
        ufw --force delete "$number" >/dev/null
    done
}

if [[ $mode == check ]]; then
    verify_firewall
    echo "SQL public listener and source-IP allowlist policy are valid."
    exit 0
fi

# Install a temporary fail-closed rule before rebuilding the owned chain. If
# any later step fails, non-WireGuard public SQL access remains blocked.
temporary_drop=(
    -i "$public_interface" -p tcp
    -m conntrack --ctorigdst "$public_bind_address" --ctorigdstport "$public_port"
    -m comment --comment ostv-sql-temporary-fail-closed -j DROP
)
delete_rule DOCKER-USER "${temporary_drop[@]}"
iptables -I DOCKER-USER 1 "${temporary_drop[@]}"

if ! iptables -S "$managed_chain" >/dev/null 2>&1; then
    iptables -N "$managed_chain"
fi
iptables -F "$managed_chain"
for source in "${allowed_sources[@]}"; do
    iptables -A "$managed_chain" -i "$public_interface" -p tcp -s "$source" \
        -m conntrack --ctorigdst "$public_bind_address" --ctorigdstport "$public_port" \
        -m comment --comment ostv-sql-public-allow -j ACCEPT
done
iptables -A "$managed_chain" -i "$public_interface" -p tcp \
    -m conntrack --ctorigdst "$public_bind_address" --ctorigdstport "$public_port" \
    -m comment --comment ostv-sql-public-default-deny -j DROP
iptables -A "$managed_chain" -j RETURN

delete_rule DOCKER-USER -j "$managed_chain"
iptables -I DOCKER-USER 1 -j "$managed_chain"

delete_rule DOCKER-USER "${temporary_drop[@]}"

remove_managed_ufw_rules
ufw allow in on "$public_interface" proto udp to any port "$wg_port" \
    comment 'OSTV WireGuard' >/dev/null
for source in "${allowed_sources[@]}"; do
    ufw allow in on "$public_interface" proto tcp from "$source" \
        to "$public_bind_address" port "$public_port" \
        comment 'OSTV SQL public allowlist' >/dev/null
done
ufw deny in on "$public_interface" proto tcp from any \
    to "$public_bind_address" port "$public_port" \
    comment 'Block non-allowlisted OSTV SQL' >/dev/null
ufw allow in on "$wg_interface" proto tcp to any port "$vpn_port" \
    comment 'OSTV SQL over WireGuard' >/dev/null

verify_firewall
echo "SQL public access is restricted to the configured IPv4 /32 allowlist and exact destination."

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root
require_ubuntu_amd64
umask 077

migration_backup=""
source_marker=""
expected_fingerprint=""
if [[ $# -eq 6 && $1 == --migration-backup && $3 == --source-marker && $5 == --expected-fingerprint ]]; then
    migration_backup=$2
    source_marker=$4
    expected_fingerprint=$6
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--migration-backup PATH --source-marker PATH --expected-fingerprint PATH]" >&2
    exit 2
fi

install -d -m 0700 "$OSTV_SQL_STATE_ROOT"
if [[ ! -f $OSTV_SQL_STATE_ROOT/.env ]]; then
    install -m 0600 "$SCRIPT_ROOT/templates/server.env.example" "$OSTV_SQL_STATE_ROOT/.env"
    echo "A placeholder configuration was installed at $OSTV_SQL_STATE_ROOT/.env; replace every angle-bracket value and rerun." >&2
    exit 1
fi
require_private_file "$OSTV_SQL_STATE_ROOT/.env"
python3 -m ostv_sql_admin.common validate

for directory in config secrets secrets/container tls tls/server wireguard wireguard/server \
    wireguard/peers data backups logs logs/sqlserver ownership temporary; do
    install -d -m 0700 "$OSTV_SQL_STATE_ROOT/$directory"
done
install -m 0600 "$SCRIPT_ROOT/templates/docker-compose.yml" "$OSTV_SQL_COMPOSE_FILE"
install -m 0600 "$SCRIPT_ROOT/templates/mssql.conf" "$OSTV_SQL_STATE_ROOT/config/mssql.conf"

python3 -m ostv_sql_admin.host_state verify-public-dns >/dev/null

"$SCRIPT_ROOT/create_credentials.sh" >/dev/null
python3 -m ostv_sql_admin.host_state sync-credential-endpoint >/dev/null
if [[ -f $OSTV_SQL_STATE_ROOT/secrets/container/bootstrap.json ]]; then
    python3 -m ostv_sql_admin.host_state sync-bootstrap-password >/dev/null
fi

if ! command -v wg >/dev/null 2>&1; then
    apt-get update
    apt-get install -y wireguard-tools
fi
"$SCRIPT_ROOT/deploy_tls.sh"
"$SCRIPT_ROOT/configure_wireguard.sh"
"$SCRIPT_ROOT/configure_firewall.sh"

chown 10001:0 "$OSTV_SQL_STATE_ROOT/data" "$OSTV_SQL_STATE_ROOT/backups" \
    "$OSTV_SQL_STATE_ROOT/logs/sqlserver" "$OSTV_SQL_STATE_ROOT/config/mssql.conf"
find "$OSTV_SQL_STATE_ROOT/data" "$OSTV_SQL_STATE_ROOT/backups" "$OSTV_SQL_STATE_ROOT/logs/sqlserver" \
    -exec chown 10001:0 {} +
find "$OSTV_SQL_STATE_ROOT/data" "$OSTV_SQL_STATE_ROOT/backups" "$OSTV_SQL_STATE_ROOT/logs/sqlserver" \
    -type d -exec chmod 0700 {} +
find "$OSTV_SQL_STATE_ROOT/backups" -type f -exec chown 10001:0 {} +
find "$OSTV_SQL_STATE_ROOT/backups" -type f -exec chmod 0600 {} +

compose pull
compose up -d
container_name="$(env_value OSTV_CONTAINER_NAME)"
for _attempt in $(seq 1 60); do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)"
    if [[ $health == healthy ]]; then
        break
    fi
    sleep 2
done
if [[ ${health:-} != healthy ]]; then
    echo "SQL Server container did not become healthy; inspect private logs." >&2
    exit 1
fi
require_container_identity
if [[ -f $OSTV_SQL_STATE_ROOT/secrets/container/bootstrap.json ]]; then
    bootstrap_output="$OSTV_SQL_STATE_ROOT/temporary/bootstrap-result.json"
    bootstrap_error="$OSTV_SQL_STATE_ROOT/temporary/bootstrap-error.log"
    bootstrap_ready=false
    for _attempt in $(seq 1 30); do
        if run_admin bootstrap-admin >"$bootstrap_output" 2>"$bootstrap_error"; then
            bootstrap_ready=true
            break
        fi
        sleep 2
    done
    if [[ $bootstrap_ready != true ]]; then
        echo "SQL became TCP-healthy but did not accept the protected bootstrap credential." >&2
        tail -20 "$bootstrap_error" >&2
        exit 1
    fi
    cat "$bootstrap_output"
    unlink "$bootstrap_output"
    unlink "$bootstrap_error"
fi
if [[ -n $migration_backup ]]; then
    require_private_file "$source_marker"
    require_private_file "$expected_fingerprint"
    OSTV_CONFIRM_DESTRUCTIVE="restore-migration-$(env_value OSTV_SQL_DATABASE)" \
        run_admin restore-migration "$migration_backup" "$source_marker" "$expected_fingerprint"
else
    run_admin provision
fi
run_admin validate
run_admin lifecycle-test

firewall_unit=/etc/systemd/system/ostv-sql-firewall.service
maintenance_service=/etc/systemd/system/ostv-sql-maintenance.service
docker_dropin=/etc/systemd/system/docker.service.d/ostv-sql-firewall.conf
install -d -m 0755 /etc/systemd/system/docker.service.d
install -m 0644 "$SCRIPT_ROOT/systemd/ostv-sql-firewall.service" "$firewall_unit"
install -m 0644 "$SCRIPT_ROOT/systemd/docker-ostv-firewall.conf" "$docker_dropin"
install -m 0644 "$SCRIPT_ROOT/systemd/ostv-sql-maintenance.service" "$maintenance_service"
install -m 0644 "$SCRIPT_ROOT/systemd/ostv-sql-maintenance.timer" /etc/systemd/system/ostv-sql-maintenance.timer
sed -i "s|@@SQLSERVER_ROOT@@|$SCRIPT_ROOT|g; s|@@WG_INTERFACE@@|$(env_value OSTV_WG_INTERFACE)|g" "$firewall_unit"
sed -i "s|@@SQLSERVER_ROOT@@|$SCRIPT_ROOT|g" "$docker_dropin"
sed -i "s|@@SQLSERVER_ROOT@@|$SCRIPT_ROOT|g" "$maintenance_service"
systemctl daemon-reload
systemctl enable --now ostv-sql-firewall.service ostv-sql-maintenance.timer >/dev/null
echo "Container deployment is healthy with a single-source public allowlist; native SQL was not changed."

#!/usr/bin/env bash
set -euo pipefail

SQLSERVER_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
REPO_ROOT="$(cd -- "$SQLSERVER_ROOT/.." && pwd -P)"
readonly OSTV_SQL_STATE_ROOT=/home/SQLServer
readonly OSTV_SQL_COMPOSE_FILE="$OSTV_SQL_STATE_ROOT/docker-compose.yml"
export OSTV_SQL_STATE_ROOT
export PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$SQLSERVER_ROOT/python:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

run_admin() {
    python3 -m ostv_sql_admin.admin "$@"
}

require_root() {
    if [[ $(id -u) -ne 0 ]]; then
        echo "This operation requires root (use sudo)." >&2
        exit 1
    fi
}

require_ubuntu_amd64() {
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ ${ID:-} != ubuntu || $(dpkg --print-architecture) != amd64 ]]; then
        echo "This deployment requires Ubuntu on an amd64 host." >&2
        exit 1
    fi
}

require_private_file() {
    local path=$1
    if [[ ! -f $path || -L $path || $(stat -c '%a' "$path") != 600 ]]; then
        echo "Required private file is missing, symbolic, or not mode 0600: $path" >&2
        exit 1
    fi
}

require_private_directory() {
    local path=$1
    if [[ ! -d $path || -L $path || $(stat -c '%a' "$path") != 700 ]]; then
        echo "Required private directory is missing, symbolic, or not mode 0700: $path" >&2
        exit 1
    fi
}

env_value() {
    local key=$1
    python3 -m ostv_sql_admin.common get "$key"
}

compose() {
    require_private_file "$OSTV_SQL_STATE_ROOT/.env"
    require_private_file "$OSTV_SQL_COMPOSE_FILE"
    docker compose --project-directory "$OSTV_SQL_STATE_ROOT" \
        --env-file "$OSTV_SQL_STATE_ROOT/.env" -f "$OSTV_SQL_COMPOSE_FILE" "$@"
}

require_container_identity() {
    python3 -m ostv_sql_admin.host_state require-container-identity >/dev/null
}

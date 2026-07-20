#!/usr/bin/env bash
set -euo pipefail
readonly expected_lineage=/etc/letsencrypt/live/@@CERTIFICATE_NAME@@
if [[ ${RENEWED_LINEAGE:-} != "$expected_lineage" ]]; then
    exit 0
fi
exec @@SQLSERVER_ROOT@@/deploy_tls.sh --renewal

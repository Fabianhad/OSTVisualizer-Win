#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_ROOT/lib/common.sh"
require_root

mode=install
if [[ $# -eq 1 && $1 == --renewal ]]; then
    mode=renewal
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--renewal]" >&2
    exit 2
fi

for command in certbot csplit docker openssl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required public-certificate command is unavailable: $command" >&2
        exit 1
    fi
done
require_private_directory "$OSTV_SQL_STATE_ROOT"
require_private_directory "$OSTV_SQL_STATE_ROOT/temporary"

certificate_name="$(env_value OSTV_SQL_CERTIFICATE_NAME)"
lineage="/etc/letsencrypt/live/$certificate_name"
server_directory="$OSTV_SQL_STATE_ROOT/tls/server"
temporary_directory="$(mktemp -d --tmpdir="$OSTV_SQL_STATE_ROOT/temporary" public-tls.XXXXXX)"
cleanup_tls_temporaries() {
    if [[ -d $temporary_directory ]]; then
        rm -r -- "$temporary_directory"
    fi
}
trap cleanup_tls_temporaries EXIT
chmod 0700 "$temporary_directory"
install -d -m 0700 -o 10001 -g 0 "$server_directory"

for file in cert.pem chain.pem fullchain.pem privkey.pem; do
    if [[ ! -r $lineage/$file ]]; then
        echo "The expected Certbot lineage is incomplete for the configured SQL hostname." >&2
        exit 1
    fi
done
if ! openssl x509 -in "$lineage/cert.pem" -noout -checkhost "$certificate_name" \
    | grep -Fq 'does match certificate'; then
    echo "The public certificate does not contain the configured SQL hostname." >&2
    exit 1
fi
if ! openssl x509 -in "$lineage/cert.pem" -noout -checkend 86400 >/dev/null; then
    echo "The public certificate expires in less than 24 hours." >&2
    exit 1
fi
openssl verify -CApath /etc/ssl/certs -untrusted "$lineage/chain.pem" \
    "$lineage/cert.pem" >/dev/null

certificate_key_hash="$(
    openssl x509 -in "$lineage/cert.pem" -pubkey -noout \
        | openssl pkey -pubin -outform DER 2>/dev/null \
        | sha256sum | awk '{print $1}'
)"
private_key_hash="$(
    openssl pkey -in "$lineage/privkey.pem" -pubout -outform DER 2>/dev/null \
        | sha256sum | awk '{print $1}'
)"
if [[ $certificate_key_hash != "$private_key_hash" ]]; then
    echo "The public certificate and private key do not match." >&2
    exit 1
fi

install -m 0644 -o 10001 -g 0 "$lineage/fullchain.pem" \
    "$temporary_directory/server.pem"
install -m 0600 -o 10001 -g 0 "$lineage/privkey.pem" \
    "$temporary_directory/server.key"
issuer_directory="$temporary_directory/ca-path"
install -d -m 0755 -o 10001 -g 0 "$issuer_directory"
csplit -s -z -f "$issuer_directory/issuer-" -b '%02d.crt' \
    "$lineage/chain.pem" '/-----BEGIN CERTIFICATE-----/' '{*}'
issuer_count=0
for issuer in "$issuer_directory"/*.crt; do
    if [[ $(grep -c 'BEGIN CERTIFICATE' "$issuer") -ne 1 ]] \
        || ! openssl x509 -in "$issuer" -noout >/dev/null 2>&1; then
        echo "The Certbot issuer chain could not be split into individual certificates." >&2
        exit 1
    fi
    chmod 0644 "$issuer"
    chown 10001:0 "$issuer"
    issuer_count=$((issuer_count + 1))
done
if [[ $issuer_count -lt 1 ]]; then
    echo "The Certbot lineage has no issuer certificate." >&2
    exit 1
fi
openssl rehash "$issuer_directory" >/dev/null
install -m 0644 -o 10001 -g 0 /etc/ssl/certs/ca-certificates.crt \
    "$temporary_directory/ca-certificates.crt"
for issuer in "$issuer_directory"/*.crt; do
    openssl x509 -in "$issuer" -outform PEM \
        >>"$temporary_directory/ca-certificates.crt"
done

hook_path=/etc/letsencrypt/renewal-hooks/deploy/ostv-sql
hook_temporary="$temporary_directory/ostv-sql-hook"
sed \
    -e "s|@@SQLSERVER_ROOT@@|$SCRIPT_ROOT|g" \
    -e "s|@@CERTIFICATE_NAME@@|$certificate_name|g" \
    "$SCRIPT_ROOT/templates/certbot-deploy-hook.sh" >"$hook_temporary"
install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
install -m 0755 -o root -g root "$hook_temporary" "$hook_path"

if [[ -f $server_directory/server.pem && -f $server_directory/server.key ]] \
    && cmp -s "$temporary_directory/server.pem" "$server_directory/server.pem" \
    && cmp -s "$temporary_directory/server.key" "$server_directory/server.key" \
    && cmp -s "$temporary_directory/ca-certificates.crt" \
        "$server_directory/ca-certificates.crt" \
    && [[ -d $server_directory/ca-path ]] \
    && diff -qr "$issuer_directory" "$server_directory/ca-path" >/dev/null; then
    echo "The publicly trusted SQL certificate and renewal hook are already current."
    exit 0
fi
if [[ -e $server_directory/server.pem || -e $server_directory/server.key ]]; then
    if [[ ! -f $server_directory/server.pem || ! -f $server_directory/server.key ]]; then
        echo "The deployed SQL certificate pair is incomplete; refusing replacement." >&2
        exit 1
    fi
    install -m 0644 -o 10001 -g 0 "$server_directory/server.pem" \
        "$temporary_directory/previous.pem"
    install -m 0600 -o 10001 -g 0 "$server_directory/server.key" \
        "$temporary_directory/previous.key"
    if [[ -d $server_directory/ca-path ]]; then
        cp -a -- "$server_directory/ca-path" "$temporary_directory/previous-ca-path"
    fi
    if [[ -f $server_directory/ca-certificates.crt ]]; then
        install -m 0644 -o 10001 -g 0 "$server_directory/ca-certificates.crt" \
            "$temporary_directory/previous-ca-certificates.crt"
    fi
fi

install -m 0644 -o 10001 -g 0 "$temporary_directory/server.pem" \
    "$server_directory/.server.pem.next"
install -m 0600 -o 10001 -g 0 "$temporary_directory/server.key" \
    "$server_directory/.server.key.next"
mv -f -- "$server_directory/.server.pem.next" "$server_directory/server.pem"
mv -f -- "$server_directory/.server.key.next" "$server_directory/server.key"
install -m 0644 -o 10001 -g 0 "$temporary_directory/ca-certificates.crt" \
    "$server_directory/.ca-certificates.crt.next"
mv -f -- "$server_directory/.ca-certificates.crt.next" \
    "$server_directory/ca-certificates.crt"
rm -rf -- "$server_directory/.ca-path.next"
cp -a -- "$issuer_directory" "$server_directory/.ca-path.next"
chown -R 10001:0 "$server_directory/.ca-path.next"
if [[ -d $server_directory/ca-path ]]; then
    rm -r -- "$server_directory/ca-path"
fi
mv -- "$server_directory/.ca-path.next" "$server_directory/ca-path"

if [[ $mode == renewal ]]; then
    require_container_identity
    compose restart sqlserver >/dev/null
    healthy=false
    for _attempt in $(seq 1 60); do
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
            "$(env_value OSTV_CONTAINER_NAME)" 2>/dev/null || true)"
        if [[ $health == healthy ]]; then
            healthy=true
            break
        fi
        sleep 2
    done
    validation_error="$temporary_directory/validation-error.log"
    if [[ $healthy != true ]] || ! run_admin validate >/dev/null 2>"$validation_error"; then
        if [[ ! -f $temporary_directory/previous.pem || ! -f $temporary_directory/previous.key ]]; then
            echo "Public certificate deployment failed and no previous pair is available." >&2
            exit 1
        fi
        install -m 0644 -o 10001 -g 0 "$temporary_directory/previous.pem" \
            "$server_directory/server.pem"
        install -m 0600 -o 10001 -g 0 "$temporary_directory/previous.key" \
            "$server_directory/server.key"
        if [[ -d $temporary_directory/previous-ca-path ]]; then
            rm -rf -- "$server_directory/ca-path"
            cp -a -- "$temporary_directory/previous-ca-path" "$server_directory/ca-path"
            chown -R 10001:0 "$server_directory/ca-path"
        fi
        if [[ -f $temporary_directory/previous-ca-certificates.crt ]]; then
            install -m 0644 -o 10001 -g 0 \
                "$temporary_directory/previous-ca-certificates.crt" \
                "$server_directory/ca-certificates.crt"
        fi
        compose restart sqlserver >/dev/null
        echo "Public certificate validation failed; the previous certificate was restored." >&2
        exit 1
    fi
fi

echo "A publicly trusted SQL certificate was deployed without displaying private key material."

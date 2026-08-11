from __future__ import annotations
import argparse
import ipaddress
import json
import os
import re
import socket
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from .common import (
    PRIVATE_STATE_ROOT,
    atomic_write_private,
    load_environment,
    read_secret,
    redact_text,
    require_private_directory,
    require_marker,
    require_private_file,
    write_secret,
)

SAFE_PEER_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,62}\Z", re.ASCII)
WIREGUARD_KEY = re.compile(r"\A[A-Za-z0-9+/]{43}=\Z", re.ASCII)


def verify_public_dns() -> dict[str, object]:
    values = load_environment()
    name = values["OSTV_SQL_CERTIFICATE_NAME"]
    expected = values["OSTV_SQL_PUBLIC_BIND_ADDRESS"]
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(name, None)}
    except socket.gaierror as exc:
        raise RuntimeError("The public SQL certificate name does not resolve.") from exc
    if addresses != {expected}:
        raise RuntimeError(
            "The public SQL certificate name does not resolve exclusively to the configured bind address."
        )
    return {"status": "public-dns-valid", "address": expected}


def sync_credential_endpoint() -> dict[str, object]:
    values = load_environment()
    directory = PRIVATE_STATE_ROOT / "secrets" / "container"
    require_private_directory(directory, label="container credential directory")
    paths = {
        "admin": directory / "admin.json",
        "client": directory / "client.json",
    }
    secrets = {role: read_secret(path) for role, path in paths.items()}
    admin = secrets["admin"]
    expected_port = int(values["OSTV_SQL_HOST_PORT"])
    expected_database = values["OSTV_SQL_DATABASE"]
    expected_users = {
        "admin": values["OSTV_SQL_ADMIN_LOGIN"],
        "client": values["OSTV_SQL_CLIENT_LOGIN"],
    }
    for role, secret in secrets.items():
        require_marker(secret.ownership_marker, admin.ownership_marker, "credential")
        if (
            secret.database != expected_database
            or secret.username != expected_users[role]
            or secret.encrypt is not True
            or secret.trust_server_certificate is not False
        ):
            raise RuntimeError(
                f"The protected {role} credential does not match this deployment."
            )
    replacements = {
        role: replace(
            secret,
            server=values["OSTV_SQL_CERTIFICATE_NAME"],
            port=expected_port,
        )
        for role, secret in secrets.items()
    }
    changed_roles = [role for role in paths if replacements[role] != secrets[role]]
    written: list[str] = []
    try:
        for role in changed_roles:
            write_secret(paths[role], replacements[role])
            written.append(role)
    except Exception as update_error:
        rollback_errors: list[Exception] = []
        for role in reversed(written):
            try:
                write_secret(paths[role], secrets[role])
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            raise ExceptionGroup(
                "Credential endpoint synchronization and rollback both failed.",
                (update_error, *rollback_errors),
            )
        raise
    return {
        "status": "credential-endpoint-synchronized",
        "changed": len(changed_roles),
        "secret_printed": False,
    }


def sync_bootstrap_password() -> dict[str, object]:
    values = load_environment()
    env_path = PRIVATE_STATE_ROOT / ".env"
    bootstrap_path = PRIVATE_STATE_ROOT / "secrets" / "container" / "bootstrap.json"
    admin_path = PRIVATE_STATE_ROOT / "secrets" / "container" / "admin.json"
    bootstrap = read_secret(bootstrap_path)
    admin = read_secret(admin_path)
    if bootstrap.username != "sa" or bootstrap.database != "master":
        raise RuntimeError("The bootstrap credential is invalid.")
    require_marker(bootstrap.ownership_marker, admin.ownership_marker, "credential")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    found = False
    for line in lines:
        if line.startswith("OSTV_SA_PASSWORD="):
            found = True
            if values["OSTV_SA_PASSWORD"] not in {
                "<GENERATED_BY_SETUP>",
                bootstrap.password,
            }:
                raise RuntimeError(
                    "The protected bootstrap credential disagrees with the private configuration."
                )
            line = "OSTV_SA_PASSWORD=" + bootstrap.password
        result.append(line)
    if not found:
        raise RuntimeError(
            "OSTV_SA_PASSWORD is missing from the private configuration."
        )
    atomic_write_private(env_path, "\n".join(result) + "\n")
    return {"status": "bootstrap-synchronized", "secret_printed": False}


def reset_sa_password() -> dict[str, object]:
    values = load_environment()
    require_container_identity(values)
    bootstrap = read_secret(
        PRIVATE_STATE_ROOT / "secrets" / "container" / "bootstrap.json"
    )
    admin = read_secret(PRIVATE_STATE_ROOT / "secrets" / "container" / "admin.json")
    if bootstrap.username != "sa" or bootstrap.database != "master":
        raise RuntimeError("The bootstrap credential is invalid.")
    require_marker(bootstrap.ownership_marker, admin.ownership_marker, "credential")
    environment = os.environ.copy()
    environment["MSSQL_SA_PASSWORD"] = bootstrap.password
    _run_command(
        (
            "docker",
            "exec",
            "--user",
            "0:0",
            "--env",
            "MSSQL_SA_PASSWORD",
            values["OSTV_CONTAINER_NAME"],
            "/opt/mssql/bin/mssql-conf",
            "set-sa-password",
        ),
        environment=environment,
        secrets=(bootstrap.password,),
    )
    return {"status": "sa-password-reset", "secret_printed": False}


def require_container_identity(
    values: dict[str, str] | None = None,
) -> dict[str, object]:
    deployment = load_environment() if values is None else values
    output = _run_command(
        (
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Labels}}",
            deployment["OSTV_CONTAINER_NAME"],
        )
    )
    try:
        labels = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Docker returned an invalid ownership label inventory."
        ) from exc
    if not isinstance(labels, dict) or (
        labels.get("com.ostvisualizer.deployment-id")
        != deployment["OSTV_DEPLOYMENT_ID"]
        or labels.get("com.ostvisualizer.component") != "sqlserver"
    ):
        raise RuntimeError(
            "Container ownership labels do not match private deployment state."
        )
    return {"status": "container-identity-valid"}


def render_wireguard_config() -> dict[str, object]:
    values = load_environment()
    interface = values["OSTV_WG_INTERFACE"]
    server_directory = PRIVATE_STATE_ROOT / "wireguard" / "server"
    peers_directory = PRIVATE_STATE_ROOT / "wireguard" / "peers"
    private_path = server_directory / "private.key"
    output_path = server_directory / f"{interface}.conf"
    require_private_directory(server_directory, label="WireGuard server directory")
    require_private_directory(peers_directory, label="WireGuard peers directory")
    require_private_file(private_path, label="WireGuard server private key")
    private_key = _read_wireguard_key(private_path)
    network = ipaddress.ip_interface(
        f'{values["OSTV_WG_SERVER_ADDRESS"]}/{values["OSTV_WG_PREFIX_LENGTH"]}'
    )
    blocks = [
        "[Interface]",
        f"Address = {network}",
        f'ListenPort = {int(values["OSTV_WG_LISTEN_PORT"])}',
        f"PrivateKey = {private_key}",
        "",
    ]
    used_addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for path in sorted(peers_directory.glob("*.json")):
        require_private_file(path, label="WireGuard peer record")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid WireGuard peer record: {path.name}") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "name",
            "public_key",
            "allowed_ip",
        }:
            raise RuntimeError(f"Invalid WireGuard peer record: {path.name}")
        name = payload["name"]
        public_key = payload["public_key"]
        if not isinstance(name, str) or not SAFE_PEER_NAME.fullmatch(name):
            raise RuntimeError(f"Invalid WireGuard peer name: {path.name}")
        if path.name != f"{name}.json":
            raise RuntimeError(
                f"WireGuard peer filename does not match its name: {path.name}"
            )
        if not isinstance(public_key, str) or not WIREGUARD_KEY.fullmatch(public_key):
            raise RuntimeError(f"Invalid WireGuard public key: {path.name}")
        try:
            allowed = ipaddress.ip_address(payload["allowed_ip"])
        except ValueError as exc:
            raise RuntimeError(f"Invalid WireGuard peer address: {path.name}") from exc
        if (
            allowed not in network.network
            or allowed == network.ip
            or allowed in used_addresses
            or allowed
            in {network.network.network_address, network.network.broadcast_address}
        ):
            raise RuntimeError(
                f"Invalid or duplicate WireGuard peer address: {path.name}"
            )
        used_addresses.add(allowed)
        blocks.extend(
            (
                f"# peer: {name}",
                "[Peer]",
                f"PublicKey = {public_key}",
                f"AllowedIPs = {allowed}/32",
                "",
            )
        )
    atomic_write_private(output_path, "\n".join(blocks))
    return {"status": "wireguard-rendered", "peer_count": len(used_addresses)}


def create_wireguard_peer(
    name: str,
    peer_ip: str,
    private_key_path: Path,
    public_key_path: Path,
) -> dict[str, object]:
    if not SAFE_PEER_NAME.fullmatch(name):
        raise RuntimeError("The WireGuard peer name is invalid.")
    values = load_environment()
    network = ipaddress.ip_interface(
        f'{values["OSTV_WG_SERVER_ADDRESS"]}/{values["OSTV_WG_PREFIX_LENGTH"]}'
    )
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError as exc:
        raise RuntimeError("The WireGuard peer address is invalid.") from exc
    if peer not in network.network or peer in {
        network.ip,
        network.network.network_address,
        network.network.broadcast_address,
    }:
        raise RuntimeError(
            "The WireGuard peer address is not usable in the private subnet."
        )
    require_private_file(private_key_path, label="temporary WireGuard private key")
    require_private_file(public_key_path, label="temporary WireGuard public key")
    private_key = _read_wireguard_key(private_key_path)
    public_key = _read_wireguard_key(public_key_path)
    server_public_path = PRIVATE_STATE_ROOT / "wireguard" / "server" / "public.key"
    server_public = _read_public_wireguard_key(server_public_path)
    peers_directory = PRIVATE_STATE_ROOT / "wireguard" / "peers"
    require_private_directory(peers_directory, label="WireGuard peers directory")
    require_private_directory(
        PRIVATE_STATE_ROOT / "temporary", label="private temporary directory"
    )
    record_path = peers_directory / f"{name}.json"
    config_path = PRIVATE_STATE_ROOT / "temporary" / f"wireguard-{name}.conf"
    if record_path.exists() or config_path.exists():
        raise RuntimeError(
            "The peer or an undelivered client configuration already exists."
        )
    for path in sorted(peers_directory.glob("*.json")):
        require_private_file(path, label="WireGuard peer record")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid WireGuard peer record: {path.name}") from exc
        if isinstance(existing, dict) and existing.get("allowed_ip") == str(peer):
            raise RuntimeError("The WireGuard peer address is already authorized.")
    record = {"name": name, "public_key": public_key, "allowed_ip": str(peer)}
    endpoint = values["OSTV_PUBLIC_ENDPOINT"]
    if ":" in endpoint:
        endpoint = f"[{endpoint}]"
    client_config = "\n".join(
        (
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {peer}/32",
            "",
            "[Peer]",
            f"PublicKey = {server_public}",
            f'Endpoint = {endpoint}:{int(values["OSTV_WG_LISTEN_PORT"])}',
            f"AllowedIPs = {network.ip}/32",
            "PersistentKeepalive = 25",
            "",
            f'# SQL Server: {network.ip},{int(values["OSTV_SQL_VPN_PORT"])}',
            f'# Certificate name: {values["OSTV_SQL_CERTIFICATE_NAME"]}',
            "",
        )
    )
    record_created = False
    try:
        atomic_write_private(
            record_path, json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
        record_created = True
        atomic_write_private(config_path, client_config)
    except Exception:
        if record_created:
            record_path.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)
        raise
    return {
        "status": "wireguard-peer-created",
        "client_config": str(config_path),
        "sql_server": str(network.ip),
        "sql_port": int(values["OSTV_SQL_VPN_PORT"]),
        "certificate_name": values["OSTV_SQL_CERTIFICATE_NAME"],
    }


def _read_wireguard_key(path: Path) -> str:
    value = path.read_text(encoding="ascii").strip()
    if not WIREGUARD_KEY.fullmatch(value):
        raise RuntimeError(f"Invalid WireGuard key file: {path.name}")
    return value


def _read_public_wireguard_key(path: Path) -> str:
    if path.is_symlink():
        raise RuntimeError(
            "The WireGuard server public key must not be a symbolic link."
        )
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) not in {
        0o600,
        0o644,
    }:
        raise RuntimeError("The WireGuard server public key permissions are invalid.")
    if metadata.st_uid != 0:
        raise RuntimeError("The WireGuard server public key must be owned by root.")
    return _read_wireguard_key(path)


def _run_command(
    command: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
    secrets: tuple[str, ...] = (),
) -> str:
    result = subprocess.run(
        command,
        check=False,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = redact_text(result.stderr.strip(), secrets)
        raise RuntimeError(
            f"Host command failed without changing the requested target: {detail}"
        )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain private SQL host state.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-public-dns")
    subparsers.add_parser("sync-credential-endpoint")
    subparsers.add_parser("sync-bootstrap-password")
    subparsers.add_parser("reset-sa-password")
    subparsers.add_parser("require-container-identity")
    subparsers.add_parser("render-wireguard")
    peer = subparsers.add_parser("create-wireguard-peer")
    peer.add_argument("name")
    peer.add_argument("peer_ip")
    peer.add_argument("private_key_path", type=Path)
    peer.add_argument("public_key_path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-public-dns":
            result = verify_public_dns()
        elif args.command == "sync-credential-endpoint":
            result = sync_credential_endpoint()
        elif args.command == "sync-bootstrap-password":
            result = sync_bootstrap_password()
        elif args.command == "reset-sa-password":
            result = reset_sa_password()
        elif args.command == "require-container-identity":
            result = require_container_identity()
        elif args.command == "render-wireguard":
            result = render_wireguard_config()
        else:
            result = create_wireguard_peer(
                args.name,
                args.peer_ip,
                args.private_key_path,
                args.public_key_path,
            )
    except (OSError, RuntimeError) as exc:
        print(f"Host-state error: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

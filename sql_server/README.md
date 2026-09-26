# OST Visualizer SQL Server deployment

This directory contains reusable Ubuntu server tooling. Machine-specific state,
credentials, certificates, WireGuard keys, active Compose configuration, data,
backups, and logs belong exclusively under `/home/SQLServer` and must never be
committed.

OST Visualizer itself remains a Windows application. These tools import the
canonical schema, checksum, inspector, validator, database creator, client
permission contract, and collaboration implementation from the parent
repository; there is no duplicate schema or Linux application runtime.

## Creating a database from the Windows application

Use **File > New > Database > Microsoft SQL Server** to open
**Database Properties (SQL Server)** directly. Enter the SQL Server at the top,
select Windows or SQL authentication for normal access, and enter the new name
in the Database text box. Finding an existing database through Open Files keeps
its separate **Connect to SQL Server** step. The dialogs retain their configured
width and calculate height from their contents. Certificate settings appear
in the form; there are no tabs, Options button, or duplicate application-user fields.
On **OK**, creation reuses the
Connect dialog with the title **Connect to SQL Server - Database Creator** to
request a separate temporary setup account. This prompt starts with empty login
fields; its server and transport settings are fixed to the selected connection.
Cancelling it returns to Properties without provisioning or registering anything.
Both identities use
the same server and connection security settings. New database names must fit
within 75 UTF-16 code units because the complete name is stored in the canonical
`dbo.Settings.Name` field; names are never truncated.

The creator needs effective `CREATE DATABASE` in `master`, `CREATE ANY DATABASE`,
or `ALTER ANY DATABASE`. `sysadmin` is not required. The creator remains the
database owner and performs initialization and user provisioning. Ownership and
server privileges are never transferred or removed by this workflow.

Normal access requires a **different, existing individual login** without server
administration or database-creation privileges. Normal access uses the account
selected in Properties: Windows authentication uses the account
running OST Visualizer without a password or impersonation; SQL authentication
uses the selected SQL login. The creator prompt also supports Windows or SQL
authentication, but using the same identity for both roles is rejected. IT must
provision both server logins first; the desktop app creates only the runtime
database user. Group-only Windows login access
is rejected before creation rather than assumed to satisfy the client gate.

Before creation the application authenticates both identities, checks creation
authority, and rejects an elevated or identical runtime identity. It then creates
and initializes canonical schema v1, maps the existing runtime login, and calls
the same `apply_sql_client_permissions()` used by deployment tooling. A fresh
connection with runtime credentials must pass the production client editing gate,
including collaboration permissions and protected-table write restrictions,
before registration. Only runtime credentials are returned to the desktop
handler. Both creation and Open Files save the selected normal-access identity.
For SQL authentication only its password goes to Windows Credential Manager,
never `file_state.json`; Windows authentication saves no password. The creator
password is used only for setup and is cleared from the temporary prompt. Shared
provisioning services and deployment tooling use the same permission contract.

If runtime provisioning or verification fails, the initialized database remains
on the server and no descriptor is registered. The error identifies the failed
stage. IT can repair the selected login's mapping/permissions and the user can
add the database through **Open Files**, without repeating database creation.
Successful registration starts collaboration with one initial attempt. The
creation workflow waits for initial reconciliation, change-feed catch-up, the
normal capability check, and main-thread `HEALTHY` publication before reporting
success. Startup failure retains the saved runtime connection and reports that
the database is not ready for editing; retry through Open Files. A bounded opening
wait can expire without cancelling the underlying connection attempt. A terminal
result received before the progress dialog closes takes precedence over that
timeout. Setup results are discarded if the owning Properties workflow has been
cleaned up. The wait is
at least 30 seconds, otherwise the login timeout plus four command timeouts.

Permission checks, creation, schema initialization, and runtime provisioning run
in the existing desktop progress worker. Stage messages cross the Qt signal
bridge. Cancel works before submission; active SQL setup cannot be cancelled.
Application shutdown waits until the creation/opening workflow returns. Saving
the connection stays on the main thread after successful runtime verification.

Additional users, Windows groups, administrative ownership policy, backups, and
future upgrades remain IT responsibilities. This change does not add schema
migrations or change desktop TLS defaults. Deployment tooling retains its existing
TLS and provisioning policy.

## Schema upgrade design recommendation (not implemented)

The current production contract is canonical schema v1, including an exact
`SchemaMigrations.Checksum`, application/physical-database identity, and the
collaboration object/permission contract. `SqlSchemaValidator`, discovery, and the
editing gate reject older, unversioned, or noncanonical databases. The ledger
records successful bootstrap; it is not an executable migration system. There
are no Alembic runtime/configuration/revisions in this checkout.

Recommend explicit, ordered native SQL Server migrations using that ledger when
the first schema change is designed. This fits the existing pyodbc DDL, inspector,
validator, checksum, and SQL Server-specific collaboration objects. Alembic's
revision graph/runner could be useful if multiple dialects, branches, or an
SQLAlchemy metadata model become requirements; it would not replace the custom
schema, Change Tracking, seed, permission, or collaboration validation. No
migration dependency or executor is added by this pass.

The proposed implementation contract is:

- Retain the published v1 contract/checksum as an immutable migration source.
  Every migration declares its exact source and target versions/checksums and
  preconditions. Never stamp an arbitrary/unversioned database as trusted.
- Use explicit temporary administrative credentials, separate from the saved
  runtime identity. A database owner is a practical supported starting contract;
  derive narrower grants from each migration's actual DDL, DML, metadata, grants,
  and database-option statements and verify them with disposable principals.
  `db_ddladmin` alone is not a complete contract for protected metadata writes or
  permission provisioning. No normal-client grants should be broadened.
- Require an IT-controlled maintenance window: drain accepted mutations, resolve
  pending operation journals, and quiesce all application and external writers.
  The existing schema application lock alone does not exclude normal writers.
  Acquire the schema lock and revalidate database identity/version immediately
  before changing anything.
- Use one explicit transaction with `XACT_ABORT ON` for eligible schema/data
  changes, validation, and final ledger/version updates. Publish the new version
  only after validation succeeds. Failure rolls back those transactional changes.
  Database options or other nontransactional operations need separately reviewed
  stages, preconditions, and restart/repair rules; never assume rollback covers
  them.
- Require a recent server-side backup and a tested restore procedure before
  upgrade, with DBA confirmation of the intended database and recovery point.
  Restoration is the fallback for irreversible/data-changing failures; automatic
  down-migrations and desktop backup scheduling are outside this proposal.
- Initially support one exact client/schema version during the maintenance
  transition. Old clients must reject the upgraded database. A mixed-version
  window would require explicit read/write, resource-token, feed, and projection
  compatibility tests before it could be offered.
- Test fresh target-version creation against migrated v1 for complete schema,
  reference data, checksums, permissions, collaboration, preserved user data, and
  close/reopen parity. Include interrupted execution, failed validation,
  insufficient permissions, and disposable live restore/retry acceptance.

Microsoft documents the distinction between database-owner, DDL, DML, and
permission-management roles in its [database-level role reference](https://learn.microsoft.com/en-us/sql/relational-databases/security/authentication-access/database-level-roles).

## Architecture

The private deployment uses the official non-root Microsoft SQL Server 2025
Ubuntu container, pinned to a specific cumulative-update image digest. It binds
SQL to loopback, the dedicated WireGuard address, and one explicit public IPv4
address. The public endpoint, including standard TCP port 1433 when selected,
is admitted only from one or more configured global IPv4 `/32` addresses.
Docker ownership labels, SQL extended
properties, and private marker files are all required before destructive
actions.

The source-IP allowlist is the zero-client-software access boundary. WireGuard
remains available as a stronger per-device path and for rollback. SQL
authentication, validated TLS, and canonical least-privilege permissions remain
mandatory on both paths.

The native SQL service is a migration rollback source. Do not disable it until
the container has passed server validation and an authorized Windows client
has completed the acceptance checklist through the selected network path. Do
not uninstall the native package without separate explicit authorization.

## File classification

| Files | Classification |
|---|---|
| `setup.sh`, operational shell scripts, `lib/common.sh` | `PORTABLE_REPOSITORY_TOOL` |
| `python/ostv_sql_admin/` | `PORTABLE_REPOSITORY_TOOL` |
| `templates/`, `systemd/` | `PORTABLE_TEMPLATE` |
| `README.md` | `DOCUMENTATION` |
| `.env`, active Compose/config, credentials, keys, data, backups, logs | `PRIVATE_HOST_STATE` under `/home/SQLServer` |
| Python caches, virtual environments, temporary peer delivery files | `GENERATED_FILE`; never commit and remove after use |
| Native-package installer, repository-local secrets/config, Linux GUI test harness | `OBSOLETE`; removed |

## Private state layout and permissions

```text
/home/SQLServer/
  docker-compose.yml
  .env
  config/
  secrets/container/
  secrets/native/
  tls/server/
  tls/retired-private-ca/
  wireguard/server/
  wireguard/peers/
  data/
  backups/
  logs/
  ownership/
  temporary/
```

Private directories use mode 0700. Password files, private keys, marker files,
active configuration, and generated client configurations use mode 0600.
Public certificates and public keys may use 0644 inside their private parent
directory. SQL bind-mounted storage is owned by the container's non-root
`mssql` UID.

The active private-state root is fixed at `/home/SQLServer`. The tools reject
environment overrides and legacy generated `container.env`/native deployment
formats so an operator cannot redirect a destructive command into the
repository or toward another SQL instance.

## Initial configuration

Install the placeholder file, edit it as root, and replace every placeholder.
Do not place the edited file in the repository:

```bash
sudo install -d -m 0700 /home/SQLServer
sudo install -m 0600 sql_server/templates/server.env.example /home/SQLServer/.env
sudoedit /home/SQLServer/.env
```

Use a supported digest-pinned image such as an official
`mcr.microsoft.com/mssql/server:2025-CU*-ubuntu-24.04@sha256:...` image. Choose
and license `Express`, `Developer`, `Standard`, or `Enterprise` appropriately.
Developer edition is not licensed for production; Express has resource and
database-size limits.

Select nonoverlapping WireGuard and Docker subnets. During migration, use a
temporary SQL port so the native service can remain active. Standard port 1433
may be selected only after every other host listener on that port has been
stopped. Leave
`OSTV_SA_PASSWORD=<GENERATED_BY_SETUP>`; setup replaces it atomically with a
random one-use bootstrap value without displaying it.

Set `OSTV_SQL_PUBLIC_BIND_ADDRESS` to an IPv4 address actually assigned to the
configured public interface. Set `OSTV_SQL_ALLOWED_SOURCE_CIDR` to one or more
unique stable global IPv4 `/32` values separated by commas, for example
`<CLIENT_PUBLIC_IPV4>/32,<SECOND_CLIENT_PUBLIC_IPV4>/32`. Broader networks,
private/reserved addresses, duplicate entries, unresolved placeholders, and
automatic address discovery are rejected.

## New database setup

```bash
sudo sql_server/audit_environment.sh
sudo sql_server/setup.sh
```

Before setup, create the configured public DNS A record and obtain its
publicly trusted RSA certificate with the host's existing Certbot installation:

```bash
sudo certbot certonly --webroot -w /var/www/html \
  --cert-name <PUBLIC_SQL_DNS_NAME> -d <PUBLIC_SQL_DNS_NAME> \
  --key-type rsa --rsa-key-size 3072 --non-interactive --agree-tos
```

Setup installs WireGuard tools if needed, validates and securely copies the
matching Certbot certificate, installs a lineage-scoped renewal deployment
hook, creates unique SQL credentials and ownership markers, configures
WireGuard/UFW/Docker containment, starts the digest-pinned container, disables
`sa` after the separate provisioning administrator reconnects, creates the
canonical database directly, applies canonical client permissions, validates
the schema/feed, and runs a clean collaboration lifecycle.

## Native-to-container migration

First create and verify a checksummed native backup and record the canonical
source fingerprint. Copy both into private state. Never stop the native service
at this stage.

Start and migrate to the temporary container endpoint:

```bash
sudo sql_server/setup.sh \
  --migration-backup /home/SQLServer/backups/native/<SOURCE>.bak \
  --source-marker /home/SQLServer/ownership/native-marker \
  --expected-fingerprint /home/SQLServer/ownership/native-fingerprint.json
```

Migration refuses an existing target database, verifies backup checksums,
requires the exact source marker, and compares deterministic row counts and
SHA-256 fingerprints for every canonical table before changing restored state.
It then transactionally re-keys the five GUID-linked collaboration tables to
the restored SQL database incarnation, validates the canonical schema, and
adopts the database into the container ownership identity.

After server validation, test the temporary container from Windows through the
selected allowlisted or WireGuard path. Only after the full Windows checklist
succeeds should a maintenance window stop and disable native SQL. To use the
default SQL port, set the private host and public ports to 1433 and rerun setup:

```bash
sudo systemctl disable --now mssql-server
sudoedit /home/SQLServer/.env
sudo sql_server/setup.sh
```

Rollback before or after cutover keeps the native data intact: stop only the
owned container, restore the previous private port configuration and firewall
policy, re-enable `mssql-server`, and validate the native database against its
preserved backup, fingerprint, and ownership marker. The container
administration CLI intentionally rejects the retired native configuration
format. Test rollback
during the maintenance window; never uninstall either copy merely to test it.

## WireGuard peers

Create one key pair and `/32` address per client:

```bash
sudo sql_server/create_wireguard_peer.sh <PEER_NAME> <UNUSED_TUNNEL_IP>
```

The command writes the server's public-key authorization under
`/home/SQLServer/wireguard/peers` and creates one mode-0600 client configuration
under `/home/SQLServer/temporary`. Import that file directly on the intended
Windows client, then securely delete the server copy. Do not reuse it for
another client and do not retain the client's private key on the server.

Revoke immediately by name:

```bash
sudo OSTV_CONFIRM_REVOKE=<PEER_NAME> \
  sql_server/revoke_wireguard_peer.sh <PEER_NAME>
```

Revocation removes the authorized public key and synchronizes the live
interface. Lost devices should also have their temporary delivery file removed.

## Source-IP allowlisted public access

Docker publishes the configured SQL port on the exact public IPv4 address. UFW
allows that endpoint from only the configured `/32` addresses, followed by a
default-deny rule for every other source. A dedicated `OSTV-SQL` chain in
`DOCKER-USER` independently enforces the same original destination IP, original
destination port, public interface, and source `/32` addresses, because Docker-published
ports can bypass ordinary UFW input handling. The chain returns without acting
on every unrelated Docker flow.

`configure_firewall.sh` installs a temporary destination-scoped drop before
rebuilding its managed rules, so a partial update fails closed. It also installs
the standalone `/usr/local/sbin/configure-ostv-sql-firewall` helper and writes
its validated non-secret settings to `/etc/default/ostv-sql-firewall`. The
systemd service and Docker drop-in use that stable host path to reapply the
policy after restarts. Never add an unrestricted public SQL rule, including for
standard port 1433.

Each allowlisted address must be a client's outward-facing IPv4 address. Every
device behind an allowlisted NAT address passes the network boundary and still
needs a valid least-privilege SQL credential. If an address changes, access
correctly fails until an administrator explicitly updates
`/home/SQLServer/.env` and reruns `configure_firewall.sh`.

## TLS and Windows connection

`deploy_tls.sh` requires a complete Certbot lineage whose certificate contains
the configured public SQL DNS name, is valid for at least 24 hours, chains to
the system trust store, and matches its private key. It atomically copies only
that pair and an OpenSSL-hashed issuer chain into protected private state. The
issuer path is mounted alongside the container's normal trust directory so SQL
Server can present complete multi-intermediate public chains. A protected CA
bundle combines the image-compatible Ubuntu root set with only those public
lineage intermediates and is mounted over the container's default CA bundle.
The renewal hook
ignores every other Certbot lineage, verifies exact container ownership,
restarts only the OSTV SQL service, validates hostname-trusted encrypted SQL
connectivity independently of application schema state, and
restores the previous certificate, key, and issuer path if validation fails.
Private key material is never printed.

Windows needs no private CA installation or hosts-file entry. Public DNS must
resolve the configured certificate name to the public bind address. Never set
`TrustServerCertificate=yes` as a shortcut.

Install Microsoft ODBC Driver 18 on Windows and configure OST Visualizer:

```text
Server: <SQL_CERTIFICATE_DNS_NAME>[,<NONDEFAULT_PUBLIC_SQL_PORT>]
Database: <DATABASE_NAME>
Authentication: SQL Server authentication
Username: <CLIENT_LOGIN>
Encrypt: yes
Trust server certificate: no
```

In the desktop connection dialog or SQL Properties form, leave
**Encrypt connection** selected and clear **Trust server certificate** to select
this policy. Clearing trust bypass requires a trusted certificate matching the
entered server hostname. These controls apply equally to creator and runtime
connections. Existing saved values and both timeouts are retained; new desktop
connections retain the existing `Encrypt=yes;TrustServerCertificate=yes` default
for compatibility, so deployment users must explicitly clear trust bypass.

Transfer the client password from the private `client.json` through an approved
secret channel. Never print it, place it in a command argument, or put it in an
OST Visualizer descriptor file.

Windows acceptance requires all of the following:

1. The client's observed public IPv4 address exactly matches the configured
   source `/32` (or its unique WireGuard key is authorized).
2. Validated TLS connection with `TrustServerCertificate=no`.
3. The database appears in the project tree.
4. Initial reconciliation succeeds.
5. Normal read/write and collaboration operations succeed.
6. Application close leaves zero active sessions, presence rows, and locks.
7. A client from any other public source address cannot reach SQL.

## Validation and backup

```bash
sudo sql_server/validate.sh
sudo sql_server/validate.sh --with-backup-restore
sudo sql_server/audit_environment.sh
```

Validation verifies the exact public listener and both firewall layers against
the configured `/32`, then verifies exact container and SQL ownership, SQL
Server major version/edition, encrypted hostname-validated ODBC connectivity,
the canonical schema/checksum, snapshot isolation, seven-day Change Tracking
retention and automatic cleanup, tracking on `ostv.ChangeTransactions`, feed
versions, and the exact least-privilege client contract.

Backups are copy-only full backups with `CHECKSUM`, followed by `RESTORE
VERIFYONLY`. Validation restore uses a unique marked database, validates its
schema after transactionally adopting the disposable restored incarnation, and
removes only that exact database:

```bash
sudo sql_server/backup.sh
sudo sql_server/restore.sh /home/SQLServer/backups/<BACKUP>.bak
```

No backup is deleted automatically. Copy verified backups to protected off-host
storage before defining retention. Validation is an explicit operator action;
the deployment does not install a daily validation timer.

`audit_environment.sh` additionally requires the deployed certificate and key
to match the configured Certbot lineage. The Certbot deploy hook intentionally
executes this checkout's `deploy_tls.sh --renewal`; keep the repository at its
documented absolute path while this deployment is installed.

## Permissions, credentials, and recovery

```bash
sudo sql_server/repair_permissions.sh
sudo sql_server/rotate_client_password.sh
```

The client receives only canonical data and collaboration access. It must not
receive server roles, `db_owner`, DDL, database create/drop, login management,
or protected schema-ledger writes.

Administrator recovery is independent and requires the exact administrator
name opt-in:

```bash
sudo OSTV_CONFIRM_ADMIN_RECOVERY=recover-<ADMIN_LOGIN> \
  sql_server/recover_admin.sh
```

It creates a one-use `sa` recovery secret, resets the dedicated administrator,
verifies it as sysadmin, disables `sa` again, deletes the temporary secret, and
validates the deployment.

## Upgrades and uninstall

Before changing the image digest, run backup/restore validation and copy the
backup off-host. Edit only private `.env`, pull/start with setup, then repeat all
server and Windows validation.

Changing the public certificate hostname or host port is also a guarded setup
operation. Obtain and validate the replacement certificate first, make a
verified backup, close every Windows client, edit only `/home/SQLServer/.env`,
and rerun `setup.sh`. Setup atomically synchronizes both protected connection
credentials to the configured hostname and host port and restores their prior
endpoint metadata if either file update fails.

Guarded uninstall removes only the ownership-verified database/client login,
creates a final recovery backup, and removes the owned container without
deleting bind-mounted private state or touching native SQL:

```bash
sudo OSTV_CONFIRM_DESTRUCTIVE=uninstall-<DATABASE> \
  sql_server/uninstall.sh --confirm-destructive
```

Deleting `/home/SQLServer`, removing the native package, or deleting backups is
a separate destructive decision and is never performed by this script.
The firewall unit is disabled, but its installed unit, Docker drop-in, stable
helper/default file, WireGuard configuration, Certbot hook, and existing
firewall rules are retained as rebuild infrastructure. Removing those host
assets is a separate full-decommission operation.

## Troubleshooting and limitations

- A certificate error must be fixed by correcting public DNS, the Certbot
  lineage/SAN, the certificate chain, or the system clock. Do not enable
  certificate trust bypass.
- A schema or ownership mismatch fails closed. Do not edit the ledger or marker.
- Docker and the configured host addresses must be restored before the
  container can bind its endpoints after reboot; the installed systemd service
  enforces firewall containment.
- Source-IP admission identifies a public NAT address, not a person or device.
  Use WireGuard instead when per-device revocation is required.
- Retired private-CA material is retained only under protected private state for
  rollback auditing; it is not used by the active deployment or transferred to
  clients.
- A server-side WireGuard namespace test does not replace the Windows client
  acceptance checklist.

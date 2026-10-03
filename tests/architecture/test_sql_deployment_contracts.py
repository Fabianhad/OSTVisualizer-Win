from __future__ import annotations
import re
import unittest
from tests.paths import REPO_ROOT
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    SQL_SERVER_ROOT as _environment_support_SQL_SERVER_ROOT,
)


def _shell_sources():
    """Every deployment shell script the cleanup/configuration contracts cover."""
    root = _environment_support_SQL_SERVER_ROOT
    return [
        *sorted(root.glob("*.sh")),
        root / "lib" / "common.sh",
        root / "templates" / "certbot-deploy-hook.sh",
        root / "systemd" / "configure-ostv-sql-firewall",
    ]


# These contracts only read the repository's deployment files as text, so they
# run on every platform (no POSIX API, subprocess or file permission is used).
class SqlDeploymentContractTests(unittest.TestCase):
    def test_old_repository_directory_name_is_absent(self):
        obsolete = "/client/" + "SQL" + "Server"
        matches = []
        scanned = 0
        for path in _environment_support_SQL_SERVER_ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeError:
                    continue
                scanned += 1
                if obsolete in text:
                    matches.append(str(path))
        # Positive control: sql_server holds 31 text files (counted with find).
        self.assertGreaterEqual(scanned, 25)
        self.assertEqual(matches, [])

    def test_private_state_has_no_environment_or_repository_fallback(self):
        common_source = (
            _environment_support_SQL_SERVER_ROOT / "python/ostv_sql_admin/common.py"
        ).read_text(encoding="utf-8")
        shell_source = (
            _environment_support_SQL_SERVER_ROOT / "lib/common.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('PRIVATE_STATE_ROOT = Path("/home/SQLServer")', common_source)
        self.assertNotIn("OSTV_SQL_CONFIG", common_source + shell_source)
        self.assertNotIn("OSTV_SQL_STATE_ROOT:-", shell_source)
        self.assertNotIn("native-rollback", common_source)

    def test_public_sql_firewall_is_destination_scoped(self):
        firewall = (
            _environment_support_SQL_SERVER_ROOT / "configure_firewall.sh"
        ).read_text(encoding="utf-8")
        compose = (
            _environment_support_SQL_SERVER_ROOT / "templates/docker-compose.yml"
        ).read_text(encoding="utf-8")
        # "--ctorigdst" is a prefix of "--ctorigdstport", so each is counted with its own
        # terminator: every destination-scoped rule must carry the address AND the port.
        addresses = re.findall(r"--ctorigdst\s", firewall)
        ports = re.findall(r"--ctorigdstport\s", firewall)
        self.assertGreaterEqual(len(addresses), 3)
        self.assertEqual(len(addresses), len(ports))
        self.assertIn("OSTV_SQL_ALLOWED_SOURCE_CIDR", firewall)
        self.assertIn("readonly managed_chain=OSTV-SQL", firewall)
        self.assertIn(
            "${OSTV_SQL_PUBLIC_BIND_ADDRESS}:${OSTV_SQL_PUBLIC_PORT}:1433", compose
        )
        self.assertNotIn(
            'ufw deny in on "$public_interface" proto tcp to any port 1433', firewall
        )
        destination = r'to "\$public_bind_address" port "\$public_port"'
        for action, source in (("allow", r'from "\$source"'), ("deny", r"from any")):
            with self.subTest(action=action):
                self.assertRegex(
                    firewall,
                    rf'ufw {action} in on "\$public_interface" proto tcp {source}\s*\\\s*'
                    rf"{destination}",
                )
        self.assertNotRegex(firewall, r"ufw (?:allow|deny) [^\n]*port 1433")

    def test_tls_deployment_uses_certbot_and_has_a_scoped_renewal_hook(self):
        deployment = (_environment_support_SQL_SERVER_ROOT / "deploy_tls.sh").read_text(
            encoding="utf-8"
        )
        hook = (
            _environment_support_SQL_SERVER_ROOT / "templates/certbot-deploy-hook.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("/etc/letsencrypt/live/$certificate_name", deployment)
        self.assertIn("openssl verify", deployment)
        self.assertIn("require_container_identity", deployment)
        self.assertIn("RENEWED_LINEAGE", hook)
        self.assertNotIn("genpkey", deployment)
        self.assertNotIn("TrustServerCertificate=yes", deployment + hook)

    def test_shell_and_python_use_one_canonical_configuration(self):
        shell_files = _shell_sources()
        # Positive control: 15 top-level scripts plus three more (found with
        # find), so the scan cannot be running over an empty list.
        self.assertGreaterEqual(len(shell_files), 15)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in shell_files)
        self.assertNotIn("config/container.env", combined)
        self.assertNotIn('sed -n "s/^${key}=', combined)
        self.assertIn("ostv_sql_admin.common get", combined)
        self.assertFalse(
            any("<<'PY'" in path.read_text(encoding="utf-8") for path in shell_files)
        )

    def test_backups_and_unrelated_docker_resources_have_no_cleanup_target(self):
        shell_files = _shell_sources()
        self.assertGreaterEqual(len(shell_files), 15)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in shell_files)
        # Positive control: the scripts really manage the container with compose.
        self.assertIn("compose down", combined)
        for forbidden in (
            "docker system prune",
            "docker container prune",
            "docker rm",
            "docker network rm",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertNotIn("backups -delete", combined)
        uninstall = (_environment_support_SQL_SERVER_ROOT / "uninstall.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            uninstall.index("require_container_identity"),
            uninstall.index("compose down"),
        )

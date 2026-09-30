from __future__ import annotations
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from tests.paths import REPO_ROOT
from sql_server.python.ostv_sql_admin import admin, common, host_state

SQL_SERVER_ROOT = REPO_ROOT / "sql_server"


def _environment_text(state_root: Path) -> str:
    values = {
        "OSTV_STATE_ROOT": str(state_root),
        "OSTV_SQL_IMAGE": (
            "mcr.microsoft.com/mssql/server:2025-CU7-ubuntu-24.04@sha256:" + "a" * 64
        ),
        "OSTV_CONTAINER_NAME": "ostv-sql-test",
        "OSTV_DEPLOYMENT_ID": "00000000-0000-4000-8000-000000000001",
        "OSTV_SQL_EDITION": "Express",
        "OSTV_SA_PASSWORD": "<GENERATED_BY_SETUP>",
        "OSTV_SQL_DATABASE": "OSTVisualizer",
        "OSTV_SQL_ADMIN_LOGIN": "OSTV_PROVISIONER",
        "OSTV_SQL_CLIENT_LOGIN": "OSTV_CLIENT",
        "OSTV_SQL_HOST_PORT": "11433",
        "OSTV_SQL_VPN_PORT": "11433",
        "OSTV_SQL_PUBLIC_BIND_ADDRESS": "8.8.8.8",
        "OSTV_SQL_PUBLIC_PORT": "11433",
        "OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/32",
        "OSTV_SQL_CERTIFICATE_NAME": "sql.example.internal",
        "OSTV_WG_INTERFACE": "wg-ostv",
        "OSTV_WG_SERVER_ADDRESS": "10.250.240.1",
        "OSTV_WG_PREFIX_LENGTH": "24",
        "OSTV_WG_LISTEN_PORT": "51820",
        "OSTV_PUBLIC_INTERFACE": "eth0",
        "OSTV_PUBLIC_ENDPOINT": "vpn.example.invalid",
        "OSTV_DOCKER_NETWORK": "ostv_sql_private",
        "OSTV_DOCKER_SUBNET": "172.29.240.0/24",
        "OSTV_SQL_CONTAINER_ADDRESS": "172.29.240.10",
    }
    return "".join(f"{key}={value}\n" for key, value in values.items())

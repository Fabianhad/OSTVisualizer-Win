"""Print a sanitized SQL Server schema inventory as JSON.

The password is accepted only through OSTV_SQL_PASSWORD. It is never included
in the generated inventory, command-line arguments, or error text.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector
from ost_visualizer.infrastructure.sql.schema_definition import LATEST_SQL_SCHEMA
from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--username", default="")
    parser.add_argument(
        "--sql-auth",
        action="store_true",
        help="Use SQL authentication; read the password from OSTV_SQL_PASSWORD.",
    )
    parser.add_argument("--connection-timeout", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    auth = (
        SqlAuthenticationMode.SQL_SERVER
        if args.sql_auth
        else SqlAuthenticationMode.WINDOWS
    )
    if auth == SqlAuthenticationMode.SQL_SERVER and not args.username:
        print("--username is required with --sql-auth.", file=sys.stderr)
        return 2
    password = os.environ.get("OSTV_SQL_PASSWORD", "")
    if auth == SqlAuthenticationMode.SQL_SERVER and not password:
        print("OSTV_SQL_PASSWORD is required with --sql-auth.", file=sys.stderr)
        return 2
    location = SqlServerDatabaseLocation(
        server=args.server,
        database=args.database,
        authentication_mode=auth,
        username=args.username,
        connection_timeout_seconds=args.connection_timeout,
    )
    try:
        inventory = SqlSchemaInspector().inspect(location, password)
        validation = SqlSchemaValidator(LATEST_SQL_SCHEMA.core_schema).validate(
            inventory
        )
    except SqlInfrastructureError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    output = {
        "database_guid": inventory.database_guid,
        "schema_version": inventory.schema_version,
        "compatibility": validation.compatibility.value,
        "problems": validation.problems,
        "tables": [
            {"schema": schema, "name": name}
            for schema, name in sorted(inventory.tables)
        ],
        "columns": [dataclasses.asdict(item) for item in inventory.columns],
        "foreign_keys": [dataclasses.asdict(item) for item in inventory.foreign_keys],
        "indexes": [dataclasses.asdict(item) for item in inventory.indexes],
        "views": [dataclasses.asdict(item) for item in inventory.views],
        "triggers": [dataclasses.asdict(item) for item in inventory.triggers],
        "procedures": [dataclasses.asdict(item) for item in inventory.procedures],
        "functions": [dataclasses.asdict(item) for item in inventory.functions],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations
import json
import os
from pathlib import Path
import pyodbc


def main() -> int:
    connection = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER={tcp:localhost};DATABASE={master};Trusted_Connection=yes;"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
        "MARS_Connection=no;APP=OSTV SQL Integration Auditor;",
        autocommit=True,
        timeout=10,
    )
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')), "
                "CONVERT(nvarchar(128), SERVERPROPERTY('Edition')), "
                "(SELECT COUNT(*) FROM sys.databases WHERE "
                "name COLLATE Latin1_General_100_BIN2 LIKE N'OSTV_IT[_]%'), "
                "(SELECT COUNT(*) FROM sys.server_principals WHERE "
                "name COLLATE Latin1_General_100_BIN2 LIKE N'OSTV_IT_TMP[_]%'), "
                "(SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE "
                "program_name=N'OST Visualizer'), "
                "(SELECT COUNT(*) FROM sys.dm_exec_cursors(0) c JOIN "
                "sys.dm_exec_sessions s ON s.session_id=c.session_id "
                "WHERE s.program_name=N'OST Visualizer'), "
                "(SELECT COUNT(*) FROM sys.extended_properties WHERE class=0 "
                "AND name=N'OSTVisualizerDisposableTestServer'), "
                "(SELECT COUNT(*) FROM sys.procedures p JOIN sys.schemas s "
                "ON s.schema_id=p.schema_id WHERE s.name=N'ostv_it'), "
                "(SELECT COUNT(DISTINCT p.object_id) FROM sys.procedures p "
                "JOIN sys.schemas s ON s.schema_id=p.schema_id "
                "JOIN sys.crypt_properties cp ON cp.major_id=p.object_id "
                "WHERE s.name=N'ostv_it' AND cp.thumbprint=(SELECT thumbprint "
                "FROM sys.certificates WHERE "
                "name=N'OSTV_IT_ProvisioningCertificate')), "
                "(SELECT COUNT(*) FROM [ostv_it].[PendingRestores]), "
                "(SELECT COUNT(*) FROM sys.server_principals WHERE "
                "name=N'OSTV_IT_EXECUTOR'), "
                "(SELECT COUNT(*) FROM sys.certificates WHERE "
                "name=N'OSTV_IT_ProvisioningCertificate'), "
                "(SELECT COUNT(*) FROM sys.server_principals WHERE "
                "name=N'OSTV_IT_ProvisioningCertificateLogin'), "
                "(SELECT COUNT(*) FROM sys.database_permissions dp WHERE "
                "dp.grantee_principal_id=USER_ID(N'OSTV_IT_EXECUTOR') AND "
                "dp.class=3 AND dp.major_id=SCHEMA_ID(N'ostv_it') AND "
                "dp.permission_name=N'EXECUTE' AND dp.state IN ('G','W')), "
                "(SELECT COUNT(*) FROM sys.database_permissions dp JOIN "
                "sys.objects o ON o.object_id=dp.major_id WHERE "
                "dp.grantee_principal_id=USER_ID(N'OSTV_IT_EXECUTOR') AND "
                "dp.class=1 AND dp.permission_name=N'EXECUTE' AND "
                "dp.state IN ('G','W') AND "
                "o.schema_id=SCHEMA_ID(N'ostv_it')), "
                "(SELECT COUNT(*) FROM sys.sql_modules m JOIN sys.objects o "
                "ON o.object_id=m.object_id WHERE "
                "o.schema_id=SCHEMA_ID(N'ostv_it') AND "
                "m.execute_as_principal_id IS NOT NULL), "
                "(SELECT COUNT(*) FROM sys.databases WHERE "
                "name=N'OSTV_CLIENT_TEST'), "
                "(SELECT COUNT(*) FROM [OSTV_CLIENT_TEST].sys.extended_properties "
                "WHERE class=0 AND "
                "name=N'OSTVisualizerSqlDevelopmentDatabase'), "
                "(SELECT COUNT(*) FROM sys.server_principals WHERE "
                "name=N'OSTV_CLIENT_TEST_USER'), "
                "(SELECT COUNT(*) FROM [OSTV_CLIENT_TEST].[ostv].[Sessions] "
                "WHERE [DisconnectedAt] IS NULL), "
                "(SELECT COUNT(*) FROM [OSTV_CLIENT_TEST].[ostv].[Presence]), "
                "(SELECT COUNT(*) FROM [OSTV_CLIENT_TEST].[ostv].[Locks])"
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()
    backup_root = (
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "OSTVisualizer"
        / "SqlIntegrationBackups"
    )
    backup_count = sum(1 for path in backup_root.iterdir() if path.is_file())
    result = {
        "version": str(row[0]),
        "edition": str(row[1]),
        "test_databases": int(row[2]),
        "temporary_logins": int(row[3]),
        "active_application_sessions": int(row[4]),
        "active_application_cursors": int(row[5]),
        "server_markers": int(row[6]),
        "guarded_procedures": int(row[7]),
        "signed_guarded_procedures": int(row[8]),
        "pending_restores": int(row[9]),
        "executor_logins": int(row[10]),
        "provisioning_certificates": int(row[11]),
        "provisioning_certificate_logins": int(row[12]),
        "executor_schema_execute_grants": int(row[13]),
        "executor_object_execute_grants": int(row[14]),
        "execute_as_modules": int(row[15]),
        "persistent_client_databases": int(row[16]),
        "persistent_client_markers": int(row[17]),
        "persistent_client_logins": int(row[18]),
        "active_client_collaboration_sessions": int(row[19]),
        "client_presence_rows": int(row[20]),
        "client_lock_rows": int(row[21]),
        "backup_files": backup_count,
    }
    print(json.dumps(result, sort_keys=True))
    return (
        0
        if all(
            result[key] == expected
            for key, expected in {
                "test_databases": 0,
                "temporary_logins": 0,
                "active_application_sessions": 0,
                "active_application_cursors": 0,
                "server_markers": 1,
                "guarded_procedures": 4,
                "signed_guarded_procedures": 4,
                "pending_restores": 0,
                "backup_files": 0,
                "executor_logins": 1,
                "provisioning_certificates": 1,
                "provisioning_certificate_logins": 1,
                "executor_schema_execute_grants": 0,
                "executor_object_execute_grants": 4,
                "execute_as_modules": 0,
                "persistent_client_databases": 1,
                "persistent_client_markers": 1,
                "persistent_client_logins": 1,
                "active_client_collaboration_sessions": 0,
                "client_presence_rows": 0,
                "client_lock_rows": 0,
            }.items()
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

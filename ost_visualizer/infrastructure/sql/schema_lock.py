import json
from ...application.dtos.collaboration_dtos import ResourceRef
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError

SQL_SCHEMA_LOCK_RESOURCE = "OSTVisualizer.SchemaInitialization"


def acquire_schema_transaction_lock(cursor) -> None:
    cursor.execute(
        "DECLARE @result int; EXEC @result=sys.sp_getapplock "
        "@Resource=?, "
        "@LockMode=N'Exclusive', @LockOwner=N'Transaction', "
        "@LockTimeout=10000; SELECT @result",
        SQL_SCHEMA_LOCK_RESOURCE,
    )
    row = cursor.fetchone()
    if row is None or int(row[0]) < 0:
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.LOCKED,
                "Another client is initializing this database schema.",
            )
        )


def acquire_resource_transaction_locks(
    cursor, resources: tuple[tuple[ResourceRef, str], ...]
) -> None:
    if any(mode not in {"Shared", "Exclusive"} for _resource, mode in resources):
        raise ValueError("Unsupported SQL application-lock mode")
    payload = json.dumps(
        [
            {
                "ordinal": ordinal,
                "resource": f"OSTV:{resource.resource_type}:{resource.resource_id}",
                "mode": mode,
            }
            for ordinal, (resource, mode) in enumerate(resources)
        ],
        separators=(",", ":"),
    )
    cursor.execute(
        "SET NOCOUNT ON; DECLARE @RequestedLocks TABLE ("
        "[Ordinal] int NOT NULL PRIMARY KEY, [Resource] nvarchar(255) NOT NULL, "
        "[Mode] nvarchar(16) NOT NULL); INSERT INTO @RequestedLocks SELECT "
        "[Ordinal], [Resource], [Mode] FROM OPENJSON(?) WITH ("
        "[Ordinal] int '$.ordinal', [Resource] nvarchar(255) '$.resource', "
        "[Mode] nvarchar(16) '$.mode'); "
        "DECLARE @Results TABLE ([Ordinal] int NOT NULL PRIMARY KEY, "
        "[Result] int NOT NULL); DECLARE @Ordinal int=0, @Count int, "
        "@Resource nvarchar(255), @Mode nvarchar(16), @Result int; "
        "SELECT @Count=COUNT(*) FROM @RequestedLocks; WHILE @Ordinal < @Count "
        "BEGIN SELECT @Resource=[Resource], @Mode=[Mode] FROM @RequestedLocks "
        "WHERE [Ordinal]=@Ordinal; EXEC @Result=sys.sp_getapplock "
        "@Resource=@Resource, @LockMode=@Mode, @LockOwner=N'Transaction', "
        "@LockTimeout=10000; INSERT INTO @Results VALUES (@Ordinal, @Result); "
        "IF @Result < 0 BREAK; SET @Ordinal=@Ordinal+1; END; "
        "SELECT [Ordinal], [Result] FROM @Results ORDER BY [Ordinal]",
        payload,
    )
    rows = cursor.fetchall()
    if len(rows) != len(resources) or any(int(row[1]) < 0 for row in rows):
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.LOCKED,
                "Another session is changing the same SQL resource.",
            )
        )


def acquire_operation_transaction_lock(cursor, operation_id: str) -> None:
    cursor.execute(
        "DECLARE @result int; EXEC @result=sys.sp_getapplock "
        "@Resource=?, @LockMode=N'Exclusive', @LockOwner=N'Transaction', "
        "@LockTimeout=10000; SELECT @result",
        f"OSTV:operation:{operation_id}",
    )
    row = cursor.fetchone()
    if row is None or int(row[0]) < 0:
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.LOCKED,
                "Another session is resolving the same SQL operation.",
            )
        )

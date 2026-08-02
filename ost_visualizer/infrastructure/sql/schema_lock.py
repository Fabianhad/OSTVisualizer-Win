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


def acquire_resource_transaction_lock(
    cursor, resource: ResourceRef, mode: str = "Exclusive"
) -> None:
    if mode not in {"Shared", "Exclusive"}:
        raise ValueError("Unsupported SQL application-lock mode")
    cursor.execute(
        "DECLARE @result int; EXEC @result=sys.sp_getapplock "
        "@Resource=?, @LockMode=?, @LockOwner=N'Transaction', "
        "@LockTimeout=10000; SELECT @result",
        f"OSTV:{resource.resource_type}:{resource.resource_id}",
        mode,
    )
    row = cursor.fetchone()
    if row is None or int(row[0]) < 0:
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

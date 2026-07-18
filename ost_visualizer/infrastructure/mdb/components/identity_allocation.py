class AccessIdentityAllocationMixin:
    @staticmethod
    def _next_uid(cursor, table: str) -> int:
        cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
        result = cursor.fetchone()[0]
        return int(result) + 1 if result is not None else 1

DATABASE_METADATA_SINGLETON_PREDICATE = (
    "m.[Product]=N'OST Visualizer' AND "
    "(SELECT COUNT_BIG(*) FROM [ostv].[DatabaseMetadata] metadata_count "
    "WHERE metadata_count.[Product]=N'OST Visualizer')=1"
)
DATABASE_METADATA_CURRENT_DATABASE_PREDICATE = (
    DATABASE_METADATA_SINGLETON_PREDICATE
    + " AND m.[DatabaseGuid]=(SELECT database_guid "
    "FROM sys.database_recovery_status WHERE database_id=DB_ID())"
)

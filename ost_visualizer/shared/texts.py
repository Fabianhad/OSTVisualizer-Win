# Domain: domain.aggregates.license_aggregate
LICENSE_AGGREGATE_MESSAGE_THE_HARDWARE_IDENTITY_PROVIDER_RETURNED_AN = (
    "The hardware identity provider returned an invalid HWID."
)
LICENSE_AGGREGATE_MESSAGE_THE_MACHINE_HWID_DOES_NOT_MATCH = (
    "The machine HWID does not match the cached license."
)
# Domain: domain.entities.ai_changeset
AI_CHANGESET_LABEL_AI_SLAB = "AI Slab"
AI_CHANGESET_MESSAGE_AI_TAKEOFF_CHANGES_CANNOT_BE_APPLIED = (
    "AI takeoff changes cannot be applied to SQL Server bids yet. Read tools and "
    "proposals still work; enter the change by hand or use an Access bid."
)
AI_CHANGESET_MESSAGE_THE_DATABASE_OF_THIS_AI_TAKEOFF = (
    "The database of this AI takeoff change is not open in OST Visualizer, so it "
    "cannot be applied or undone. Open the database and propose the change again."
)
AI_CHANGESET_MESSAGE_A_POLYGON_NEEDS_AT_LEAST_THREE = (
    "A polygon needs at least three points."
)
AI_CHANGESET_MESSAGE_POLYGON_COORDINATES_MUST_BE_FINITE = (
    "Polygon coordinates must be finite."
)
AI_CHANGESET_MESSAGE_THE_POLYGON_AREA_IS_TOO_LARGE = "The polygon area is too large."
AI_CHANGESET_MESSAGE_A_POLYGON_MUST_ENCLOSE_AN_AREA = "A polygon must enclose an area."
AI_CHANGESET_MESSAGE_A_POLYGON_MAY_HAVE_AT_MOST = (
    "A polygon may have at most {max_polygon_vertices} vertices."
)
AI_CHANGESET_MESSAGE_A_CHANGESET_MAY_HOLD_AT_MOST = (
    "A changeset may hold at most {max_changeset_takeoffs} takeoffs."
)
AI_CHANGESET_MESSAGE_A_CHANGESET_MAY_CREATE_AT_MOST = (
    "A changeset may create at most {max_changeset_new_conditions} conditions."
)
AI_CHANGESET_MESSAGE_A_CHANGESET_MAY_HOLD_AT_MOST_2 = (
    "A changeset may hold at most {max_changeset_vertices} vertices."
)
AI_CHANGESET_MESSAGE_HIGH_IMPACT_ASSUMPTIONS_MUST_BE_ACCEPTED = (
    "High-impact assumptions must be accepted or overridden first."
)
AI_CHANGESET_MESSAGE_THIS_CHANGESET_HAS_NO_SCALE = "This changeset has no scale."
AI_CHANGESET_MESSAGE_EVERY_HOLE_MUST_LIE_INSIDE_ITS = (
    "Every hole must lie inside its slab outline."
)
AI_CHANGESET_MESSAGE_EVERY_SLAB_NEEDS_A_THICKNESS_ABOVE = (
    "Every slab needs a thickness above 0 and at most {max_slab_thickness_in:g} in."
)
AI_CHANGESET_MESSAGE_TOP_ELEVATIONS_MUST_BE_WITHIN_IN = (
    "Top elevations must be within {max_abs_top_elevation_in:g} in."
)
# Domain: domain.entities.page
PAGE_LABEL_PAGE = "Page {uid}"
PAGE_LABEL_ITEMS_WITHOUT_PAGE = "Items Without Page"
# Domain: domain.services.page_selection_service
PAGE_SELECTION_SERVICE_LABEL_ITEMS_WITHOUT_PAGE = "Items Without Page"
# Domain: domain.services.uom_service
UOM_SERVICE_LABEL_AREA = "Area"
UOM_SERVICE_LABEL_COUNT = "Count"
UOM_SERVICE_LABEL_LENGTH = "Length"
UOM_SERVICE_LABEL_PERIMETER = "Perimeter"
UOM_SERVICE_LABEL_VOLUME = "Volume"
UOM_SERVICE_LABEL_TOTAL_HEIGHT = "Total Height"
UOM_SERVICE_LABEL_SURFACE_AREA_TOP_OR_BOTTOM = "Surface area (top or bottom)"
UOM_SERVICE_LABEL_SURFACE_AREA_TOP_AND_BOTTOM = "Surface area (top and bottom)"
UOM_SERVICE_LABEL_SURFACE_AREA_SINGLE_WIDTH_SIDE = "Surface area (single width side)"
UOM_SERVICE_LABEL_SURFACE_AREA_BOTH_WIDTH_SIDES = "Surface area (both width sides)"
UOM_SERVICE_LABEL_SURFACE_AREA_ALL_SIDES = "Surface area (all sides)"
UOM_SERVICE_LABEL_SURFACE_AREA_ALL_SIDES_TOP_AND = (
    "Surface area (all sides + top and bottom)"
)
UOM_SERVICE_LABEL_SEGMENT_COUNT = "Segment count"
UOM_SERVICE_LABEL_SURFACE_AREA_SINGLE_SIDE = "Surface area (single side)"
UOM_SERVICE_LABEL_SURFACE_AREA_BOTH_SIDES = "Surface area (both sides)"
UOM_SERVICE_LABEL_SURFACE_AREA_SINGLE_END = "Surface area (single end)"
UOM_SERVICE_LABEL_SURFACE_AREA_BOTH_ENDS = "Surface area (both ends)"
UOM_SERVICE_LABEL_SURFACE_AREA_ALL_SIDE_DUCT = "Surface area (all side/duct)"
UOM_SERVICE_LABEL_AREA_IGNORE_BACKOUT_AREAS = "Area (Ignore Backout Areas)"
UOM_SERVICE_LABEL_AREA_MINUS_ATTACHMENTS = "Area (minus Attachments)"
UOM_SERVICE_LABEL_PERIMETER_WITHOUT_BACKOUT_PERIMETERS = (
    "Perimeter (without Backout Perimeters)"
)
UOM_SERVICE_LABEL_PERIMETER_PLUS_ATTACHMENTS_PERIMETER = (
    "Perimeter (plus Attachments Perimeter)"
)
UOM_SERVICE_LABEL_GRID_LENGTH_VISIBLE = "Grid length (visible)"
UOM_SERVICE_LABEL_TILE_COUNT_AVERAGE = "Tile count (average)"
UOM_SERVICE_LABEL_TILE_COUNT_VISIBLE = "Tile count (visible)"
UOM_SERVICE_LABEL_AREA_COUNTS = "Area counts"
UOM_SERVICE_LABEL_VOLUME_IGNORE_BACKOUT_VOLUME = "Volume (Ignore Backout Volume)"
UOM_SERVICE_LABEL_VOLUME_MINUS_ATTACHMENTS = "Volume (minus Attachments)"
# Application: application.dtos.annotation_caption_dto
ANNOTATION_CAPTION_DTO_LABEL_WALL_AREA = "Wall Area"
# Application: application.dtos.collaboration_dtos
COLLABORATION_DTOS_MESSAGE_THE_ACTIVE_BID_IS_LOCKED = "The active bid is locked."
COLLABORATION_DTOS_MESSAGE_A_GRANTED_EDIT_LEASE_REQUIRES_ITS = (
    "A granted edit lease requires its handle, and a denial cannot carry a handle."
)
COLLABORATION_DTOS_MESSAGE_OBSERVED_AND_HYDRATED_SQL_CHANGE_BATCHES = (
    "Observed and hydrated SQL change batches must match."
)
# Application: application.dtos.condition_summary_dtos
CONDITION_SUMMARY_DTOS_LABEL_ITEMS_WITHOUT_PAGE = "Items Without Page"
CONDITION_SUMMARY_DTOS_LABEL_MULTI_AREA_TOTAL = "Multi-Area Total"
# Application: application.dtos.condition_takeoff_reassignment
CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_A_PAGE_AND = (
    "Condition reassignment requires a page and takeoffs."
)
CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_DISTINCT_TAKEOFF = (
    "Condition reassignment requires distinct takeoff identities."
)
# Application: application.dtos.create_condition_spec_dto
CREATE_CONDITION_SPEC_DTO_LABEL_UNTITLED = "Untitled"
CREATE_CONDITION_SPEC_DTO_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY = (
    "Condition name cannot be empty."
)
CREATE_CONDITION_SPEC_DTO_MESSAGE_THE_CONDITION_WAS_NOT_CREATED_BECAUSE = (
    "The condition was not created because one of its values is not a finite number."
)
# Application: application.dtos.file_import_args
FILE_IMPORT_ARGS_MESSAGE_UNSUPPORTED_FILE_TYPE_ONLY_OST_AND = (
    "Unsupported file type. Only .ost and .osp files can be imported."
)
FILE_IMPORT_ARGS_MESSAGE_FILE_DOES_NOT_EXIST = "File does not exist."
# Application: application.dtos.license_view_model_dto
LICENSE_VIEW_MODEL_DTO_LABEL_NO_ACTIVE_LICENSE = "No active license"
# Application: application.orchestrators.license_orchestrator
LICENSE_ORCHESTRATOR_MESSAGE_THIS_COMPUTER_S_HARDWARE_IDENTITY_IS = (
    "This computer's hardware identity is unavailable. Restart Windows and try "
    "again; if the problem continues, contact support."
)
LICENSE_ORCHESTRATOR_MESSAGE_ANOTHER_LICENSE_OPERATION_IS_IN_PROGRESS = (
    "Another license operation is in progress."
)
LICENSE_ORCHESTRATOR_MESSAGE_NO_ACTIVE_LICENSE = "No active license."
# Application: application.services.ai_changeset_store
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_IS_STILL_A_PROPOSAL = (
    "The changeset is still a proposal and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_IS_WAITING_FOR_APPROVAL = (
    "The changeset is waiting for approval and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_IS_BEING_APPLIED = (
    "The changeset is being applied and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_IS_ALREADY_APPLIED = (
    "The changeset is already applied and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_WAS_REJECTED = (
    "The changeset was rejected and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_WAS_DISCARDED = (
    "The changeset was discarded and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_FAILED_TO_APPLY = (
    "The changeset failed to apply and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_WAS_UNDONE = (
    "The changeset was undone and cannot do that."
)
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_CANNOT_DO_THAT_IN_ITS_CURRENT_STATE = (
    "The changeset cannot do that in its current state."
)
AI_CHANGESET_STORE_MESSAGE_UNKNOWN_ASSUMPTION_SUBJECT = "Unknown assumption subject."
AI_CHANGESET_STORE_MESSAGE_THE_AI_CHANGED_THIS_CHANGESET_WHILE = (
    "The AI changed this changeset while you were reviewing it. Check it again."
)
AI_CHANGESET_STORE_MESSAGE_UNKNOWN_ASSUMPTION_ID = "Unknown assumption_id."
AI_CHANGESET_STORE_MESSAGE_THE_CHANGESET_EXPIRED_OR_THE_OBJECTS = (
    "The changeset expired or the objects it touches changed. Propose it again."
)
AI_CHANGESET_STORE_MESSAGE_A_PAGE_OR_CONDITION_THIS_CHANGESET = (
    "A page or condition this changeset touches changed. Propose it again."
)
AI_CHANGESET_STORE_MESSAGE_AT_MOST_CHANGESETS_CAN_BE_OPEN = (
    "At most {max_open_changesets_per_bid} changesets can be open per bid. Discard "
    "or apply one first."
)
AI_CHANGESET_STORE_MESSAGE_UNKNOWN_CHANGESET_ID = "Unknown changeset_id."
AI_CHANGESET_STORE_MESSAGE_THE_AI_HAS_NOT_ASKED_TO = (
    "The AI has not asked to apply this changeset."
)
# Application: application.services.ai_takeoff_read_service
AI_TAKEOFF_READ_SERVICE_MESSAGE_OPEN_A_BID_IN_OST_VISUALIZER = (
    "Open a bid in OST Visualizer first."
)
AI_TAKEOFF_READ_SERVICE_MESSAGE_ONLY_THE_BID_OPEN_IN_OST = (
    "Only the bid open in OST Visualizer can be read."
)
# Application: application.services.annotation_caption_resolver
ANNOTATION_CAPTION_RESOLVER_LABEL_CU_YD = "cu yd"
# Application: application.services.database_maintenance_service
DATABASE_MAINTENANCE_SERVICE_MESSAGE_SELECT_A_DATABASE_FIRST = (
    "Select a database first."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY = (
    "Compact/Repair completed successfully."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_IS_ALREADY_RUNNING = (
    "Database maintenance is already running."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_MAINTENANCE_WAS = (
    "The selected database changed; maintenance was cancelled."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE = (
    "The selected database changed; start maintenance again."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_TEMPORARY_FILE_CLEANUP_FAILED = (
    "{message} Temporary-file cleanup failed: {cleanup_error}"
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_THE_RELOAD_FAILED = (
    "Compaction completed, but the reload failed. The database was unloaded; reopen it "
    "to retry."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_FAILED = (
    "Database maintenance failed."
)
DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_RELOAD_AND_UNLOAD = (
    "Compaction completed, but the reload and unload failed. Close and reopen the "
    "application before continuing."
)
# Application: application.services.database_session_registry
DATABASE_SESSION_REGISTRY_MESSAGE_DATABASE_AND_SESSION_IDS_ARE_REQUIRED = (
    "Database and session IDs are required."
)
DATABASE_SESSION_REGISTRY_MESSAGE_THIS_SQL_DATABASE_HAS_NO_ACTIVE = (
    "This SQL database has no active collaboration session and is read-only."
)
# Application: application.services.export_service
EXPORT_SERVICE_LABEL_UNKNOWN_FORMAT = "Unknown"
EXPORT_SERVICE_MESSAGE_THE_SELECTED_EXPORT_FORMAT_IS_NOT_AVAILABLE = (
    "The selected export format is not available."
)
EXPORT_SERVICE_MESSAGE_NO_FILE_WAS_WRITTEN = (
    "No file was written. Check that the selected pages have takeoffs this format can "
    "export, then try again or choose a different destination."
)
EXPORT_SERVICE_MESSAGE_AN_UNEXPECTED_ERROR_STOPPED_THE_EXPORT = (
    "An unexpected error stopped the export. Please try again or choose a different "
    "destination; if the problem continues, contact support."
)
EXPORT_SERVICE_MESSAGE_THE_FILE_COULD_NOT_BE_WRITTEN = (
    "The file could not be written. Please ensure you have write permissions to the "
    "destination folder and try again."
)
EXPORT_SERVICE_LABEL_BID = "Bid"
EXPORT_SERVICE_TITLE_3D_VIEW = "3D View"
EXPORT_SERVICE_MESSAGE_NO_TAKEOFFS_FOUND_FOR_ANY_OF = (
    "No takeoffs found for any of the selected pages."
)
# Application: application.services.import_service
IMPORT_SERVICE_MESSAGE_THE_IMPORT_SOURCE_CHANGED_AFTER_THE = (
    "The import source changed after the operation was queued."
)
# Application: application.services.local_draft_registry
LOCAL_DRAFT_REGISTRY_MESSAGE_A_LOCAL_EDIT_ALREADY_OWNS_ONE = (
    "A local edit already owns one of the requested resources."
)
# Application: application.services.navigation_load_service
NAVIGATION_LOAD_SERVICE_MESSAGE_A_NAVIGATION_READ_REQUIRES_A_DATABASE = (
    "A navigation read requires a database ID."
)
NAVIGATION_LOAD_SERVICE_MESSAGE_NAVIGATION_LOADING_HAS_STOPPED = (
    "Navigation loading has stopped."
)
# Application: application.services.project_operations_service
PROJECT_OPERATIONS_SERVICE_MESSAGE_THE_SQL_BID_COULD_NOT_BE = (
    "The SQL bid could not be loaded."
)
# Application: application.services.project_write_service
PROJECT_WRITE_SERVICE_LOG_COULD_NOT_READ_THE_STORED_CONDITION = (
    "Could not read the stored condition folders of bid {bid_uid}; the folder "
    "check uses the loaded bid"
)
PROJECT_WRITE_SERVICE_LOG_PAGE_WAS_RENAMED_IN_BUT_THE = (
    "Page {page_uid} was renamed in {db_path}, but the reload after the rename "
    "failed"
)
PROJECT_WRITE_SERVICE_MESSAGE_DATABASE_RELOAD_FAILED_AFTER_SAVING_CONDITION = (
    "Database reload failed after saving condition."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_SQL_MUTATION_RETURNED_AN_INCOMPLETE = (
    "The SQL mutation returned an incomplete authoritative identity set."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_RETURNED_AN_INCOMPLETE_AUTHORITATIVE = (
    "The paste returned an incomplete authoritative UID set."
)
PROJECT_WRITE_SERVICE_MESSAGE_REASSIGNMENT_REQUIRES_EXACTLY_THE_ORIGINAL_CONDI = (
    "Reassignment requires exactly the original condition."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_DUPLICATE_RETURNED_AN_INCOMPLETE = (
    "The condition duplicate returned an incomplete identity map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_UPDATE_COULD_NOT_BE = (
    "The condition update could not be completed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_DELETION = (
    "The database rejected deletion."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_GEOMETRY_UPDATE = (
    "The database rejected the geometry update."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROPERTY_MUTATION_NO_LONGER_OWNS = (
    "The property mutation no longer owns the current bid."
)
PROJECT_WRITE_SERVICE_MESSAGE_A_PROPERTY_MUTATION_TAKEOFF_IS_NO = (
    "A property mutation takeoff is no longer authoritative."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_PROPERTY_UPDATE = (
    "The database rejected the property update."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PLAN_PROPERTY_UPDATE_WAS_INCOMPLETE = (
    "The plan property update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_REQUIRES_ONE_UNIQUE_SOURCE = (
    "The paste requires one unique source UID per takeoff."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_PASTE = (
    "The database rejected paste."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_AI_TAKEOFF_INSERTION_WAS_INCOMPLETE = (
    "The AI takeoff insertion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_TAKEOFF_INSERTION_RETURNED_AN_INCOMPLETE = (
    "The takeoff insertion returned an incomplete authoritative identity set."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_ANNOTATION_DELETION_WAS_INCOMPLETE = (
    "The annotation deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_TAKEOFF_DELETION_WAS_INCOMPLETE = (
    "The takeoff deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DELETION_COMMITTED_BUT_THE_LOCAL = (
    "The deletion committed, but the local database projection could not be "
    "refreshed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_TAKEOFF_POSITION_UPDATE_WAS_INCOMPLETE = (
    "The takeoff position update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_TAKEOFF_ROTATION_UPDATE_WAS_INCOMPLETE = (
    "The takeoff rotation update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_ANNOTATION_POSITION_UPDATE_WAS_INCOMPLETE = (
    "The annotation position update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_GEOMETRY_UPDATE_COMMITTED_BUT_THE = (
    "The geometry update committed, but the local database projection could not be "
    "refreshed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROPERTY_UPDATE_COMMITTED_BUT_THE = (
    "The property update committed, but the local database projection could not be "
    "refreshed."
)
PROJECT_WRITE_SERVICE_MESSAGE_REFRESH_THE_BID_BEFORE_EDITING_TAKEOFF = (
    "Reload the bid before editing takeoff properties."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_CONTAINS_A_TAKEOFF_PARENT = (
    "The paste contains a takeoff parent cycle."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_RETURNED_AN_INCOMPLETE_TAKEOFF = (
    "The paste returned an incomplete takeoff UID map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_COMMITTED_BUT_THE_LOCAL = (
    "The paste committed, but the local database projection could not be refreshed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PREVIOUS_PAGE_SCALE_COULD_NOT = (
    "The previous page scale could not be restored."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PREVIOUS_TAKEOFF_POSITIONS_COULD_NOT = (
    "The previous takeoff positions could not be restored."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_IS_LOCKED = "The bid is locked."
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_CHANGE = (
    "The database rejected the change."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_AI_TAKEOFFS_COULD_NOT_BE = (
    "The AI takeoffs could not be removed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_AI_CONDITIONS_COULD_NOT_BE = (
    "The AI conditions could not be removed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_AI_CONDITION_FOLDER_COULD_NOT = (
    "The AI condition folder could not be removed."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROJECT_IMPORT_DID_NOT_RETURN = (
    "The project import did not return authoritative identities."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROJECT_CREATION_WAS_INCOMPLETE = (
    "The project creation was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_CREATION_WAS_INCOMPLETE = (
    "The bid creation was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROJECT_RENAME_WAS_INCOMPLETE = (
    "The project rename was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_MOVE_WAS_INCOMPLETE = (
    "The bid move was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DUPLICATED_BID_ASSIGNMENT_WAS_INCOMPLETE = (
    "The duplicated bid assignment was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_DELETION_WAS_INCOMPLETE = (
    "The bid deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROJECT_DELETION_WAS_INCOMPLETE = (
    "The project deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_JOB_STATUS_UPDATE_WAS = (
    "The bid job-status update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_AREA_UPDATE_WAS_INCOMPLETE = (
    "The bid-area update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_AREA_UPDATE_RETURNED_AN = (
    "The bid-area update returned an incomplete identity map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_COVER_SHEET_UPDATE_WAS_INCOMPLETE = (
    "The cover-sheet update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_A_CONDITION_TYPE_IS_STILL_REFERENCED = (
    "A condition type is still referenced by a condition."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_TYPE_UPDATE_WAS_INCOMPLETE = (
    "The condition-type update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_TYPE_UPDATE_RETURNED_AN = (
    "The condition-type update returned an incomplete identity map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DEFAULT_LAYER_CREATION_WAS_INCOMPLETE = (
    "The default-layer creation was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DEFAULT_LAYER_UPDATE_WAS_INCOMPLETE = (
    "The default-layer update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_MASTER_DATA_UPDATE_WAS_INCOMPLETE = (
    "The master-data update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_MASTER_DATA_UPDATE_RETURNED_AN = (
    "The master-data update returned an incomplete identity map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PAGE_DELETION_WAS_INCOMPLETE = (
    "The page deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_INSERTION_WAS_INCOMPLETE = (
    "The condition insertion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_DELETION_WAS_INCOMPLETE = (
    "The condition deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_REFRESH_THE_BID_BEFORE_DUPLICATING_AND = (
    "Reload the bid before duplicating and reassigning takeoffs."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_REORDER_WAS_INCOMPLETE = (
    "The condition reorder was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_FOLDER_INSERTION_WAS_INCOMPLETE = (
    "The condition folder insertion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_FOLDER_RENAME_WAS_INCOMPLETE = (
    "The condition folder rename was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_FOLDER_DELETION_WAS_INCOMPLETE = (
    "The condition folder deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_LAYER_INSERTION_WAS_INCOMPLETE = (
    "The layer insertion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_LAYER_REORDER_WAS_INCOMPLETE = (
    "The layer reorder was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BULK_LAYER_VISIBILITY_UPDATE_WAS = (
    "The bulk layer visibility update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_LAYER_RENAME_WAS_INCOMPLETE = (
    "The layer rename was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_DID_NOT_CREATE_EVERY = (
    "The paste did not create every required condition."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_RETURNED_AN_INCOMPLETE_NAMED = (
    "The paste returned an incomplete named-view UID map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PASTE_RETURNED_AN_INCOMPLETE_ANNOTATION = (
    "The paste returned an incomplete annotation UID map."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_AI_CONDITION_FOLDER_COULD_NOT_2 = (
    "The AI condition folder could not be created."
)
PROJECT_WRITE_SERVICE_MESSAGE_AN_AI_CONDITION_COULD_NOT_BE = (
    "An AI condition could not be created."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PAGE_SETTING_UPDATE_WAS_INCOMPLETE = (
    "The page setting update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_PROJECT_IMPORT_RESULT_IS_MISSING = (
    "The project import result is missing {result_name}."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_BID_DUPLICATION_WAS_INCOMPLETE = (
    "The bid duplication was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DEFAULT_LAYER_DELETION_WAS_INCOMPLETE = (
    "The default-layer deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_LAYER_DELETION_WAS_INCOMPLETE = (
    "The layer deletion was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DUPLICATED_CONDITION_TARGET_UPDATE_WAS = (
    "The duplicated condition target update was incomplete."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_PLACEMENT = (
    "The database rejected the placement."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_PAGE_SETTING = (
    "The database rejected the page setting update."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_DATABASE_REJECTED_THE_PROJECT_UPDATE = (
    "The database rejected the project update."
)
PROJECT_WRITE_SERVICE_MESSAGE_THE_CONDITION_UPDATE_WAS_INCOMPLETE = (
    "The condition update was incomplete."
)
# Application: application.services.sql_collaboration_coordinator
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_CLEANUP_FAILED_FOR = (
    "SQL collaboration cleanup failed for {database_id}."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_STOPPED_BEFORE_THE_MUTATION = (
    "SQL collaboration stopped before the mutation was queued."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_RECOVERING_THE_AUTHORITATIVE_SQL_STATE = (
    "Recovering the authoritative SQL state."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_DATABASE_OPENING_WAS_STOPPED = (
    "SQL database opening was stopped."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_IS_CLOSING = (
    "SQL collaboration is closing."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_PENDING_REMOTE_TRANSACTION_OVERLAPS_AN = (
    "A pending remote transaction overlaps an active local draft."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_COMMITTED_BUT_ITS = (
    "The SQL mutation committed, but its local projection failed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_STOPPED_BEFORE_THE_EDIT = (
    "SQL collaboration stopped before the edit lease became active."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_STOPPED_BEFORE_THE_QUEUED = (
    "SQL collaboration stopped before the queued mutation was executed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_TRUST_WAS_LOST_BEFORE = (
    "SQL collaboration trust was lost before the edit lease was acquired."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_OPERATION_COULD_NOT_BE = (
    "The SQL operation could not be recorded safely before queueing."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_AN_EDIT_LEASE_REQUIRES_AT_LEAST = (
    "An edit lease requires at least one resource."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_IS_NOT_AVAILABLE_FOR = (
    "SQL collaboration is not available for this database."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_IS_NOT_READY_FOR = (
    "SQL collaboration is not ready for editing."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_STOPPED_BEFORE_THE_EDIT_2 = (
    "SQL collaboration stopped before the edit could be queued."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_OPERATION_JOURNAL_IS_UNAVAILABLE = (
    "The SQL operation journal is unavailable."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_COMMITTED_AFTER_ITS = (
    "The SQL mutation committed after its UI runtime changed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_RUNTIME_CHANGED_BEFORE_THE = (
    "The SQL runtime changed before the mutation completed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_LOCAL_EDIT_WAS_CANCELLED_BEFORE = (
    "The local edit was cancelled before its lease became active."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_CHANGE_FEED_WAS_RESET = (
    "The SQL change feed was reset."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_CHANGE_TRACKING_CHECKPOINT_IS = (
    "The SQL Change Tracking checkpoint is no longer valid."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_DURABLE_SQL_OPERATION_DOES_NOT = (
    "A durable SQL operation does not match its local recovery record."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_NAVIGATION_REPLACED_THE_LOADED_BID_WHILE = (
    "Navigation replaced the loaded bid while SQL session-start hydration was "
    "pending."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_NAVIGATION_REPLACED_THE_LOADED_BID_WHILE_2 = (
    "Navigation replaced the loaded bid while a SQL snapshot was pending."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_WORKER_COULD_NOT = (
    "The SQL collaboration worker could not reject queued mutations."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_WORKER_COULD_NOT_2 = (
    "The SQL collaboration worker could not reject pending edits."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_WORKER_DID_NOT = (
    "The SQL collaboration worker did not stop before the configured "
    "database-operation timeout."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_QUEUE_IS_FULL = (
    "The SQL mutation queue is full; wait for pending edits to finish."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_COLLABORATION_STOPPED_AFTER_AN_UNEXPECTED = (
    "SQL collaboration stopped after an unexpected internal error."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_WORKER_COULD_NOT_3 = (
    "The SQL collaboration worker could not complete session cleanup."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_COLLABORATION_SESSION_EXPIRED_WHILE_THE = (
    "The collaboration session expired while the computer was suspended."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_COMMITTED_SQL_MUTATION_COULD_NOT = (
    "A committed SQL mutation could not be projected locally."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_SESSION_START_RECONCILIATION_PAYLOAD = (
    "The SQL session-start reconciliation payload was malformed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_DATABASE_COULD_NOT_BE = (
    "The SQL database could not be reconciled at session start."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_RECOVERED_SQL_OPERATION_RESULT_WAS = (
    "A recovered SQL operation result was malformed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_MALFORMED_SQL_RECONCILIATION_PAYLOAD_REQUIRES = (
    "A malformed SQL reconciliation payload requires a controlled database reload."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_REMOTE_SQL_CATCH_UP_CHANGE = (
    "A remote SQL catch-up change requires a controlled database reload."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_SESSION_COULD_NOT = (
    "The SQL collaboration session could not be closed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_WORKER_COULD_NOT_4 = (
    "The SQL collaboration worker could not publish edit-lease loss."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_FAILED_SQL_COLLABORATION_WORKER_COULD = (
    "The failed SQL collaboration worker could not reset its session."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_SQL_EDIT_PERMISSIONS_OR_SCHEMA_TRUST = (
    "SQL edit permissions or schema trust changed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_OPERATION_JOURNAL_COULD_NOT = (
    "The SQL operation journal could not record the mutation before execution."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_S_COMMIT_STATUS = (
    "The SQL mutation's commit status must be resolved after reconnecting."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_FAILED_BEFORE_IT = (
    "The SQL mutation failed before it could be committed."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_S_COMMIT_STATUS_2 = (
    "The SQL mutation's commit status is not yet known."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_LIFECYCLE_CRITICAL_SQL_MUTATION_DID = (
    "A lifecycle-critical SQL mutation did not complete."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_ONE_OF_THE_REQUESTED_RESOURCES_IS = (
    "One of the requested resources is already being edited."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_COMMITTED_SQL_OPERATION_HAS_NO = (
    "The committed SQL operation has no valid authoritative result."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_A_SQL_COLLABORATION_EDIT_LOCK_COULD = (
    "A SQL collaboration edit lock could not be released."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_QUEUED_SQL_MUTATION_WAS_CANCELLED = (
    "The queued SQL mutation was cancelled before execution."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_GEOMETRY_EDIT_LEASE_EXPIRED_BEFORE = (
    "The geometry edit lease expired before the mutation started."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_COMMITTED_WITHOUT_AN = (
    "The SQL mutation committed without an authoritative projection result."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_COMMITTED_BUT_ITS_2 = (
    "The SQL mutation committed, but its recovery record could not be updated."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_COLLABORATION_SESSION_IS_NOT = (
    "The SQL collaboration session is not available."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_OPERATION_DID_NOT_COMMIT = (
    "The SQL operation did not commit before the connection was lost."
)
SQL_COLLABORATION_COORDINATOR_MESSAGE_THE_SQL_MUTATION_COMMITTED_BUT_ITS_3 = (
    "The SQL mutation committed, but its authoritative result could not be loaded."
)
# Application: application.services.summary_csv_export_service
SUMMARY_CSV_EXPORT_SERVICE_LABEL_BID = "Bid"
SUMMARY_CSV_EXPORT_SERVICE_LABEL_SUMMARY_FILE = "{bid_name} Summary{extension}"
SUMMARY_CSV_EXPORT_SERVICE_LABEL_TOTAL = "Total"
SUMMARY_CSV_EXPORT_SERVICE_LABEL_SUMMARY_CSV = "Summary CSV"
SUMMARY_CSV_EXPORT_SERVICE_MESSAGE_NO_SUMMARY_ROWS_ARE_AVAILABLE_TO = (
    "No summary rows are available to export."
)
# Application: application.services.visualization_service
VISUALIZATION_SERVICE_MESSAGE_MESH_GENERATION_WORKER_DID_NOT_STOP = (
    "Mesh generation worker did not stop within 3 seconds; visualization "
    "dependencies were retained for worker safety."
)
# Application: application.use_cases.license.activate_license_use_case
ACTIVATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_PLEASE = (
    "Cannot connect to license server. Please check your internet connection and "
    "try again."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_IS_MISSING_OR_TOO = (
    "License key is missing or too long."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S = (
    "Failed to determine this computer's hardware ID."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATED_VALID_UNTIL = (
    "License activated successfully. It is valid until {expiry_date}."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_IDENTIFY_THE_CURRENT_WINDOWS = (
    "Failed to identify the current Windows user and computer for license activation. "
    "Please contact support."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT = (
    "The license server response could not be verified. Please contact support."
)
ACTIVATE_LICENSE_USE_CASE_MESSAGE_ACTIVATION_SUCCEEDED_BUT_THE_LICENSE_COULD = (
    "Activation succeeded, but the license could not be saved or verified locally. "
    "Please contact support."
)
# Application: application.use_cases.license.deactivate_license_use_case
DEACTIVATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONTACT_THE_LICENSE_SERVER_PLEASE = (
    "Cannot contact the license server.\n\nPlease check your internet connection "
    "and try again."
)
DEACTIVATE_LICENSE_USE_CASE_MESSAGE_NO_ACTIVE_LICENSE_TO_DEACTIVATE = (
    "No active license to deactivate."
)
DEACTIVATE_LICENSE_USE_CASE_MESSAGE_STORED_LICENSE_DATA_IS_INVALID_PLEASE = (
    "Stored license data is invalid. Please contact support."
)
# Application: application.use_cases.license.utils.license_use_case
LICENSE_USE_CASE_LOG_NETWORK_ERROR = "Network error"
LICENSE_USE_CASE_LOG_ACTIVATION_FAILED = "Activation failed"
LICENSE_USE_CASE_LOG_VALIDATION_FAILED = "Validation failed"
LICENSE_USE_CASE_LOG_DEACTIVATION_FAILED = "Deactivation failed"
LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_NOT_FOUND_PLEASE_CHECK = (
    "License key not found. Please check the key and try again, or contact support."
)
LICENSE_USE_CASE_MESSAGE_LICENSE_DEACTIVATED_SUCCESSFULLY = (
    "License deactivated successfully."
)
LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID = (
    "The license server returned an invalid response. Please contact support."
)
LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_KEY_HAS_EXPIRED_PLEASE = (
    "This license key has expired. Please contact support to renew your license."
)
LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_EXPIRED_AND_CANNOT = (
    "This license has expired and cannot be deactivated. Please contact support "
    "for assistance."
)
LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_BEEN_REVOKED_PLEASE = (
    "This license has been revoked. Please contact support for more information."
)
LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID_2 = (
    "The license server returned an invalid expiry date."
)
LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATION_LIMIT_REACHED_THIS_LICENSE = (
    "License activation limit reached. This license is active on the maximum "
    "number of devices."
)
LICENSE_USE_CASE_MESSAGE_THIS_DEVICE_IS_NOT_CURRENTLY_ACTIVATED = (
    "This device is not currently activated for this license."
)
LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THIS_COMPUTER = (
    "The license server rejected this computer's hardware ID. Please contact "
    "support."
)
LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THE_WINDOWS = (
    "The license server rejected the Windows activation identity. Please contact "
    "support."
)
# Application: application.use_cases.license.validate_license_use_case
VALIDATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_YOUR = (
    "Cannot connect to license server. Your license could not be validated. Please "
    "check your internet connection."
)
VALIDATE_LICENSE_USE_CASE_MESSAGE_NO_LICENSE_KEY_PROVIDED = "No license key provided."
VALIDATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S = (
    "Failed to determine this computer's hardware ID."
)
VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_IS_VALID_UNTIL = (
    "The license is valid until {expiry_date}."
)
VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT = (
    "The license server response could not be verified. Please contact support."
)
VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_WAS_ACCEPTED_BY_THE = (
    "The license was accepted by the server, but it could not be saved or verified "
    "locally. Please contact support."
)
# Application: application.use_cases.project.import_project_files_from_args_use_case
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_IMPORT_FAILED = "Import failed."
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_NO_ENABLED_DATABASE_IS_AVAILABLE_ENABLE = (
    "No enabled database is available. Enable or store a database before importing "
    ".ost or .osp files from Windows Explorer."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_PENDING_DATABASE_CHANGES_COULD_NOT_BE = (
    "Pending database changes could not be saved before import."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_IMPORTED_SUCCESSFULLY = (
    "Imported successfully."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_FILE_DOES_NOT_EXIST = (
    "File does not exist."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_THE_FILE_COULD_NOT_BE_IMPORTED = (
    "The file could not be imported."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_THE_FILE_COULD_NOT_BE_QUEUED = (
    "The file could not be queued."
)
IMPORT_PROJECT_FILES_FROM_ARGS_USE_CASE_MESSAGE_IMPORTED_BUT_THE_DATABASE_COULD_NOT = (
    "Imported, but the database could not be reloaded. Reopen the database to see the "
    "imported project."
)
# Application: application.use_cases.project.load_file_use_case
LOAD_FILE_USE_CASE_MESSAGE_FAILED_TO_LOAD_FILE = "Failed to load file."
# Application: application.use_cases.project.update_condition_use_case
UPDATE_CONDITION_USE_CASE_MESSAGE_FAILED_TO_SAVE_CONDITION_TO_DATABASE = (
    "Failed to save condition to database."
)
UPDATE_CONDITION_USE_CASE_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY = (
    "Condition name cannot be empty."
)
UPDATE_CONDITION_USE_CASE_MESSAGE_DISPLAY_SIZE_MUST_BE_BETWEEN_10 = (
    "Display Size must be between 10% and 500%."
)
# Infrastructure: infrastructure.database.bid_owned_identity
BID_OWNED_IDENTITY_MESSAGE_A_TAKEOFF_AND_ITS_PARENT_MUST = (
    "A takeoff and its parent must belong to the same page."
)
BID_OWNED_IDENTITY_MESSAGE_THE_PLAN_OWNERSHIP_SNAPSHOT_MUST_COVER = (
    "The Plan ownership snapshot must cover every validation target exactly once."
)
BID_OWNED_IDENTITY_MESSAGE_THE_TAKEOFF_OWNERSHIP_CHANGED_BEFORE_THE = (
    "The takeoff ownership changed before the Plan mutation started."
)
BID_OWNED_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE = (
    "{table} has no row for UID {missing}; the requested authoritative owner does "
    "not exist."
)
BID_OWNED_IDENTITY_MESSAGE_MUTATION_REQUIRES_AT_LEAST_ONE_AUTHORITATIVE = (
    "{table} mutation requires at least one authoritative target."
)
BID_OWNED_IDENTITY_MESSAGE_MUTATION_TARGETS_DO_NOT_BELONG_TO = (
    "{table} mutation targets do not belong to one authoritative bid."
)
BID_OWNED_IDENTITY_MESSAGE_CONTAINS_MALFORMED_UID_AUTHORITATIVE_BID_OWNED = (
    "{table} contains malformed UID {rendered}; authoritative bid-owned UIDs must "
    "be positive integers."
)
BID_OWNED_IDENTITY_MESSAGE_CONTAINS_DUPLICATE_UID_AUTHORITATIVE_BID_OWNED = (
    "{table} contains duplicate UID {canonical_uid}; authoritative bid-owned UIDs "
    "must be unique."
)
# Infrastructure: infrastructure.database.descriptor_registry
DESCRIPTOR_REGISTRY_MESSAGE_THE_DATABASE_DESCRIPTOR_IS_NOT_REGISTERED = (
    "The database descriptor is not registered."
)
# Infrastructure: infrastructure.database.master_data_identity
MASTER_DATA_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE = (
    "{table} has no row for UID {uid}; the referenced authoritative master-data "
    "record does not exist."
)
MASTER_DATA_IDENTITY_MESSAGE_IMPORTED_MASTER_DATA_IDENTITY_IS_AMBIGUOUS = (
    "Imported master-data identity is ambiguous for {identity_label}: matching "
    "UIDs {joined}."
)
MASTER_DATA_IDENTITY_MESSAGE_CONTAINS_DUPLICATE_UID_AUTHORITATIVE_MASTER_DATA = (
    "{table} contains duplicate UID {uid}; authoritative master-data UIDs must be "
    "unique."
)
# Infrastructure: infrastructure.database.reader_router
READER_ROUTER_MESSAGE_DATABASE_READER_OPERATION_HAS_NO_ACTIVE = (
    "Database reader operation has no active backend scope."
)
READER_ROUTER_MESSAGE_THE_SQL_SERVER_DATABASE_DESCRIPTOR_IS = (
    "The SQL Server database descriptor is not registered."
)
READER_ROUTER_MESSAGE_DATABASE_READER_ERROR_HANDLING_REQUIRES_AN = (
    "Database reader error handling requires an active backend scope or explicit "
    "locator."
)
# Infrastructure: infrastructure.database.settings_cardinality
SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT = (
    "This database can be read but cannot create bids because the Settings table "
    "is unavailable."
)
SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT_2 = (
    "This database can be read but cannot create bids because Settings.NextBidNo "
    "is unavailable."
)
SETTINGS_CARDINALITY_MESSAGE_SETTINGS_HAS_MULTIPLE_ROWS_EXPECTED_AT = (
    "Settings has multiple rows; expected at most one."
)
# Infrastructure: infrastructure.database.writer_router
WRITER_ROUTER_MESSAGE_DATABASE_WRITER_OPERATION_HAS_NO_ACTIVE = (
    "Database writer operation has no active backend scope."
)
# Infrastructure: infrastructure.hardware.hwid_generator
HWID_GENERATOR_MESSAGE_THE_PINNED_SMBIOS_SYSTEM_UUID_IS = (
    "The pinned SMBIOS System UUID is temporarily unavailable."
)
HWID_GENERATOR_MESSAGE_THE_SMBIOS_SYSTEM_UUID_DOES_NOT = (
    "The SMBIOS System UUID does not match the pinned machine identity."
)
HWID_GENERATOR_MESSAGE_THE_PINNED_MACHINE_IDENTITY_IS_UNAVAILABLE = (
    "The pinned machine identity is unavailable or invalid."
)
# Infrastructure: infrastructure.mdb.components.annotation_operations
ANNOTATION_OPERATIONS_MESSAGE_ANNOTATION_MUTATION_TARGETS_DO_NOT_BELONG = (
    "Annotation mutation targets do not belong to one authoritative bid."
)
ANNOTATION_OPERATIONS_MESSAGE_NAMED_VIEW_DELETION_MUST_INCLUDE_EVERY = (
    "Named View deletion must include every dependent hotlink."
)
# Infrastructure: infrastructure.mdb.components.bid_data_reader
BID_DATA_READER_MESSAGE_A_TAKEOFF_AND_ITS_PARENT_MUST = (
    "A takeoff and its parent must belong to the same page."
)
# Infrastructure: infrastructure.mdb.components.bid_operations
BID_OPERATIONS_MESSAGE_NEW_BID_CONTAINS_DUPLICATE_PAGE_FOLDER = (
    "New bid contains duplicate page-folder identity {local_uid}."
)
BID_OPERATIONS_MESSAGE_NEW_BID_PAGE_FOLDER_REFERENCES_UNAVAILABLE = (
    "New bid page folder {local_uid} references unavailable page folder {parent_uid}."
)
BID_OPERATIONS_MESSAGE_NEW_BID_PAGE_REFERENCES_UNAVAILABLE_PAGE = (
    "New bid page references unavailable page folder {folder_uid}."
)
BID_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT = (
    "This OST database does not support page-folder persistence."
)
BID_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_2 = (
    "This OST database does not support page-folder hierarchy persistence."
)
# Infrastructure: infrastructure.mdb.components.bulk_write_helpers
BULK_WRITE_HELPERS_MESSAGE_NO_VALUES_SUPPLIED_FOR_CHUNKED_UID = (
    "No values supplied for chunked UID update."
)
BULK_WRITE_HELPERS_MESSAGE_NEW_CORRELATION_UID_MUST_BE_PRESENT = (
    "New {label} correlation UID {correlation_uid} must be present and unique within "
    "one save."
)
# Infrastructure: infrastructure.mdb.components.condition_folder_operations
CONDITION_FOLDER_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT = (
    "This OST database does not support condition folder hierarchy persistence."
)
# Infrastructure: infrastructure.mdb.components.condition_operations
CONDITION_OPERATIONS_MESSAGE_CANNOT_ADD_ONE_CONDITION = (
    "Cannot add {count} condition: the new condition numbers would reach "
    "{last_ref_no}, past {max_condition_number}, the highest condition number."
)
CONDITION_OPERATIONS_MESSAGE_CANNOT_ADD_CONDITIONS = (
    "Cannot add {count} conditions: the new condition numbers would reach "
    "{last_ref_no}, past {max_condition_number}, the highest condition number."
)
CONDITION_OPERATIONS_MESSAGE_CONDITION_NUMBER_CANNOT_BE_USED_THE = (
    "Condition number {new_ref_no} cannot be used: the conditions numbered "
    "{new_ref_no} and up would move up by one, and one of them is already "
    "{max_condition_number}, the highest condition number."
)
CONDITION_OPERATIONS_MESSAGE_CANNOT_RENUMBER_THE_CONDITIONS_NO_TEMPORARY = (
    "Cannot renumber the conditions: no temporary numbers are free above or below "
    "the existing ones."
)
# Infrastructure: infrastructure.mdb.components.layer_operations
LAYER_OPERATIONS_MESSAGE_THE_BULK_LAYER_VISIBILITY_UPDATE_AFFECTED = (
    "The bulk layer visibility update affected {affected_rows} of {chunk_count} "
    "captured layers in a {normalized_uids_count}-layer operation."
)
LAYER_OPERATIONS_MESSAGE_THE_BULK_LAYER_VISIBILITY_UPDATE_COULD = (
    "The bulk layer visibility update could verify only {verified_uid_rows_count} of "
    "{chunk_count} captured layers in a {normalized_uids_count}-layer operation."
)
# Infrastructure: infrastructure.mdb.components.page_operations
PAGE_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT = (
    "This OST database does not support page area settings."
)
PAGE_OPERATIONS_MESSAGE_THE_SCALE_WAS_NOT_CHANGED_BECAUSE = (
    "The scale was not changed because the takeoffs and annotations on the page "
    "cannot be stored at that scale."
)
# Infrastructure: infrastructure.mdb.components.settings_operations
SETTINGS_OPERATIONS_LABEL_NEW_FOLDER = "New Folder"
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT = (
    "This OST database does not support page-folder persistence."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_2 = (
    "This OST database does not support page-folder hierarchy persistence."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_3 = (
    "This OST database does not support bid area hierarchy persistence."
)
SETTINGS_OPERATIONS_MESSAGE_BIDPAGEFOLDERS_CONTAINS_DUPLICATE_PENDING_IDENTI = (
    "BidPageFolders contains duplicate pending identity {local_uid}."
)
SETTINGS_OPERATIONS_MESSAGE_BIDAREAS_CONTAINS_DUPLICATE_PENDING_IDENTITY = (
    "BidAreas contains duplicate pending identity {pending_identity}."
)
SETTINGS_OPERATIONS_MESSAGE_BIDPAGEFOLDERS_PARENT_IS_NOT_AUTHORITATIVE = (
    "BidPageFolders parent {raw_key} is not authoritative."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_4 = (
    "This OST database does not support job statuses."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_5 = (
    "This OST database does not support employees."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_6 = (
    "This OST database does not support pay classes."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_7 = (
    "This OST database does not support condition types."
)
SETTINGS_OPERATIONS_MESSAGE_NEW_BID_AREA_PARENT_GRAPH_CONTAINS = (
    "New bid area parent graph contains a cycle."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_8 = (
    "This OST database does not support bid areas."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_9 = (
    "This OST database does not support selected page persistence."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_10 = (
    "This OST database does not support Job Status selection because JobStatuses "
    "is unavailable."
)
SETTINGS_OPERATIONS_MESSAGE_THIS_OST_DATABASE_DOES_NOT_SUPPORT_11 = (
    "This OST database does not support Estimator selection because Employees is "
    "unavailable."
)
SETTINGS_OPERATIONS_MESSAGE_NEW_PAGE_FOLDER_PARENT_GRAPH_CONTAINS = (
    "New page folder parent graph contains a cycle."
)
# Infrastructure: infrastructure.mdb.connection_manager
CONNECTION_MANAGER_MESSAGE_MICROSOFT_ACCESS_CANNOT_OPEN_ANOTHER_DATABASE = (
    "Microsoft Access cannot open another database connection in this OST "
    "Visualizer session. Save any work in other applications, restart OST "
    "Visualizer, and try again."
)
CONNECTION_MANAGER_MESSAGE_CLOSE_ON_SCREEN_TAKEOFF_BEFORE_DATABASE = (
    "Close On-Screen Takeoff before database maintenance."
)
CONNECTION_MANAGER_MESSAGE_THE_DATABASE_HAS_ACTIVE_OPERATIONS_TRY = (
    "The database has active operations; try again when they finish."
)
CONNECTION_MANAGER_MESSAGE_THE_DATABASE_IS_TEMPORARILY_CLOSED_FOR = (
    "The database is temporarily closed for maintenance."
)
# Infrastructure: infrastructure.mdb.database_maintenance
DATABASE_MAINTENANCE_MESSAGE_SELECT_AN_EXISTING_MICROSOFT_ACCESS_MDB = (
    "Select an existing Microsoft Access MDB database."
)
DATABASE_MAINTENANCE_MESSAGE_COM_COULD_NOT_BE_INITIALISED_HRESULT = (
    "COM could not be initialized (HRESULT 0x{hresult:08X})."
)
DATABASE_MAINTENANCE_MESSAGE_CLOSE_ON_SCREEN_TAKEOFF_BEFORE_DATABASE = (
    "Close On-Screen Takeoff before database maintenance."
)
DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY = (
    "Compact/Repair completed successfully."
)
DATABASE_MAINTENANCE_MESSAGE_COMPACTED_DATABASE_VALIDATION_FAILED_THE_ORIGINA = (
    "Compacted database validation failed; the original was not replaced."
)
DATABASE_MAINTENANCE_MESSAGE_THIS_MAINTENANCE_RESULT_IS_NO_LONGER = (
    "This maintenance result is no longer pending."
)
DATABASE_MAINTENANCE_MESSAGE_MAINTENANCE_WAS_INTERRUPTED_BY_ON_SCREEN = (
    "Maintenance was interrupted by On-Screen Takeoff; the original was not "
    "replaced."
)
DATABASE_MAINTENANCE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE = (
    "The selected database changed; start maintenance again."
)
DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_DATABASE_CHANGED_DURING_MAINTENANCE = (
    "The source database changed during maintenance; it was not replaced."
)
DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_ITS = (
    "The source changed during replacement; its newer contents were restored."
)
DATABASE_MAINTENANCE_MESSAGE_ACCESS_REPORTED_REPAIR_ERRORS_THE_ORIGINAL = (
    "Access reported repair errors; the original database was not replaced."
)
DATABASE_MAINTENANCE_MESSAGE_REPLACEMENT_RECOVERY_FAILED_THE_ORIGINAL_DATABAS = (
    "Replacement recovery failed. The original database is preserved at {backup}."
)
DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_RECOVERY = (
    "The source changed during replacement. Recovery files are preserved at {work}."
)
# Infrastructure: infrastructure.mdb.importers.ost_importer
OST_IMPORTER_MESSAGE_THE_SQL_IMPORT_WRITER_DID_NOT = (
    "The SQL import writer did not return authoritative identities."
)
OST_IMPORTER_MESSAGE_THE_SQL_IMPORT_WRITER_DID_NOT_2 = (
    "The SQL import writer did not return exactly one imported bid."
)
OST_IMPORTER_MESSAGE_THE_IMPORTED_PROJECT_CONTAINS_INVALID_REFERENCES = (
    "The imported project contains invalid references."
)
OST_IMPORTER_MESSAGE_THE_OST_FILE_CONTAINS_NO_BID = (
    "The OST file contains no bid, so it cannot be imported."
)
OST_IMPORTER_MESSAGE_SOME_TAKEOFFS_IN_THE_OST_FILE_ARE_INVALID = (
    "Some takeoffs in the OST file are invalid, so it cannot be imported."
)
OSP_IMPORTER_MESSAGE_THE_OSP_PACKAGE_IS_DAMAGED = (
    "The OSP package is damaged or uses an unsupported format, so it cannot be "
    "imported."
)
# Infrastructure: infrastructure.mdb.mdb_writer
MDB_WRITER_MESSAGE_THIS_OST_DATABASE_IS_MISSING_REQUIRED = (
    "This OST database is missing required writable columns {table}.{join} for "
    "{operation}."
)
MDB_WRITER_MESSAGE_THIS_OST_DATABASE_HAS_NO_WRITABLE = (
    "This OST database has no writable columns for {operation}."
)
MDB_WRITER_MESSAGE_A_TAKEOFF_WAS_DELETED_OR_REPLACED = (
    "A takeoff was deleted or replaced before reassignment started."
)
MDB_WRITER_MESSAGE_AN_ANNOTATION_CHANGED_OR_WAS_DELETED = (
    "An annotation changed or was deleted before the Plan mutation started."
)
MDB_WRITER_MESSAGE_A_TAKEOFF_CHANGED_PAGE_OR_CONDITION = (
    "A takeoff changed page or condition before reassignment started."
)
MDB_WRITER_MESSAGE_THE_TAKEOFF_RELATIONSHIP_GRAPH_CHANGED_BEFORE = (
    "The takeoff relationship graph changed before the Plan mutation started."
)
# Infrastructure: infrastructure.mdb.schema_compatibility
SCHEMA_COMPATIBILITY_MESSAGE_THIS_OST_DATABASE_IS_MISSING_REQUIRED = (
    "This OST database is missing required table {table_name} and cannot be loaded."
)
SCHEMA_COMPATIBILITY_MESSAGE_THIS_OST_DATABASE_IS_MISSING_REQUIRED_2 = (
    "This OST database is missing required column {key} and cannot be loaded."
)
# Infrastructure: infrastructure.monitoring.transaction_monitor
TRANSACTION_MONITOR_LABEL_REALTIME_SERVICE_NOT_INSTALLED = (
    "Realtime Service Not Installed"
)
TRANSACTION_MONITOR_MESSAGE_REALTIME_MONITORING_IS_NOT_AVAILABLE_BECAUSE = (
    "Realtime monitoring is not available because the realtime service "
    "(as2port.dll) is not installed or failed to load.\n\nTo enable realtime "
    "monitoring:\n1. Close On-Screen Takeoff\n2. Run RealtimeService\\install.cmd "
    "as Administrator\n3. Restart On-Screen Takeoff\n\nThe install script will "
    "install the DLL to the On-Screen Takeoff directory."
)
TRANSACTION_MONITOR_LABEL_REALTIME_MONITORING_ACTIVE = "Realtime Monitoring Active"
TRANSACTION_MONITOR_MESSAGE_REALTIME_MONITORING_IS_ENABLED = (
    "Realtime monitoring is enabled."
)
TRANSACTION_MONITOR_LABEL_REALTIME_MONITORING_STOPPED = "Realtime Monitoring Stopped"
TRANSACTION_MONITOR_MESSAGE_REALTIME_MONITORING_IS_DISABLED = (
    "Realtime monitoring is disabled."
)
# Infrastructure: infrastructure.persistence.repositories.file_project_repository
FILE_PROJECT_REPOSITORY_MESSAGE_THE_DATABASE_IS_NO_LONGER_OPEN = (
    "The database {file_path} is no longer open, so it could not be reloaded."
)
FILE_PROJECT_REPOSITORY_MESSAGE_IF_THIS_IS_AN_OLDER_OST = (
    "{exc} If this is an older OST database, test only on a backup copy."
)
FILE_PROJECT_REPOSITORY_MESSAGE_FAILED_TO_RELOAD_DATABASE_FILE = (
    "Failed to reload database file: {exc}"
)
FILE_PROJECT_REPOSITORY_MESSAGE_THE_NAVIGATION_DATABASE_WAS_UNLOADED_WHILE = (
    "The navigation database was unloaded while reading."
)
FILE_PROJECT_REPOSITORY_MESSAGE_THE_NAVIGATION_DATABASE_WAS_UNLOADED_REOPENED = (
    "The navigation database was unloaded, reopened, or reloaded again while reloading."
)
# Infrastructure: infrastructure.sql.catalog
CATALOG_MESSAGE_THE_SELECTED_DATABASE_IS_NO_LONGER = (
    "The selected database is no longer available to this login."
)
CATALOG_MESSAGE_DATABASE_IS_NOT_AVAILABLE_TO_THIS = (
    "Database is not available to this login."
)
CATALOG_MESSAGE_THE_CURRENT_LOGIN_DOES_NOT_HAVE = (
    "The current login does not have permission to read bids in this database."
)
CATALOG_MESSAGE_THIS_DATABASE_COULD_NOT_BE_INSPECTED = (
    "This database could not be inspected with the current login."
)
# Infrastructure: infrastructure.sql.client_permissions
CLIENT_PERMISSIONS_MESSAGE_THIS_SQL_DATABASE_IS_NOT_WRITABLE = (
    "This SQL database is not writable by this OST Visualizer version."
)
CLIENT_PERMISSIONS_MESSAGE_SQL_EDITING_REQUIRES_THE_CONFIGURED_USER = (
    "SQL editing requires the configured user to belong to the required SQL "
    "database roles, use dbo as its default schema, and have the canonical schema "
    "visibility grants."
)
CLIENT_PERMISSIONS_MESSAGE_SQL_EDITING_REQUIRES_THE_CANONICAL_COLLABORATION = (
    "SQL editing requires the canonical collaboration permissions and workspace "
    "permissions."
)
# Infrastructure: infrastructure.sql.collaboration_store
COLLABORATION_STORE_MESSAGE_SQL_COLLABORATION_METADATA_IS_MISSING_DUPLICATED = (
    "SQL collaboration metadata is missing, duplicated, or does not identify the "
    "current database."
)
COLLABORATION_STORE_MESSAGE_THE_SAVED_SQL_CONNECTION_HAS_NO = (
    "The saved SQL connection has no valid database identity. Remove it from "
    "Open Files and add it again."
)
COLLABORATION_STORE_MESSAGE_THE_SQL_DATABASE_WAS_REPLACED_SINCE = (
    "The SQL database was replaced since this connection was saved. Remove it "
    "from Open Files and add the replacement database explicitly."
)
COLLABORATION_STORE_MESSAGE_THE_SQL_COLLABORATION_SESSION_EXPIRED_RECONNECTING = (
    "The SQL collaboration session expired. Reconnecting is required before " "editing."
)
COLLABORATION_STORE_MESSAGE_THE_SQL_COLLABORATION_SESSION_EXPIRED_RECONNECT = (
    "The SQL collaboration session expired. Reconnect before editing."
)
COLLABORATION_STORE_MESSAGE_THE_EDIT_LOCK_EXPIRED_AND_CAN = (
    "The edit lock expired and can no longer be renewed."
)
COLLABORATION_STORE_MESSAGE_SQL_CHANGE_FEED_METADATA_IS_MISSING = (
    "SQL change-feed metadata is missing."
)
COLLABORATION_STORE_MESSAGE_A_COMMITTED_SQL_TRANSACTION_MARKER_HAS = (
    "A committed SQL transaction marker has no ChangeLog records."
)
COLLABORATION_STORE_MESSAGE_A_COMMITTED_SQL_TRANSACTION_CONTAINS_DUPLICATE = (
    "A committed SQL transaction contains duplicate resource payloads."
)
COLLABORATION_STORE_MESSAGE_SQL_EDIT_LOCK_ACQUISITION_RETURNED_NO = (
    "SQL edit-lock acquisition returned no result."
)
COLLABORATION_STORE_MESSAGE_SQL_EDIT_LOCK_ACQUISITION_RETURNED_AN = (
    "SQL edit-lock acquisition returned an incomplete result."
)
COLLABORATION_STORE_MESSAGE_SQL_CHANGE_TRACKING_METADATA_IS_UNAVAILABLE = (
    "SQL Change Tracking metadata is unavailable."
)
COLLABORATION_STORE_MESSAGE_THE_COMMITTED_SQL_OPERATION_MARKER_IS = (
    "The committed SQL operation marker is missing."
)
COLLABORATION_STORE_MESSAGE_ANOTHER_SESSION_IS_CHANGING_THE_SAME = (
    "Another session is changing the same SQL resource."
)
COLLABORATION_STORE_MESSAGE_SQL_TRANSACTION_MARKER_HISTORY_CONTAINS_AN = (
    "SQL transaction-marker history contains an invalid change."
)
COLLABORATION_STORE_MESSAGE_SQL_TRANSACTION_MARKER_HISTORY_CONTAINS_A = (
    "SQL transaction-marker history contains a duplicate transaction identity."
)
# Infrastructure: infrastructure.sql.database_creator
DATABASE_CREATOR_LABEL_CONNECTING_AND_CHECKING_CREATION_PERMISSIONS = (
    "Connecting and checking creation permissions"
)
DATABASE_CREATOR_LABEL_AUTHENTICATING_APPLICATION_USER = (
    "Authenticating application user"
)
DATABASE_CREATOR_LABEL_CREATING_DATABASE = "Creating database"
DATABASE_CREATOR_MESSAGE_CREATOR_AND_NORMAL_USE_ACCESS_MUST = (
    "Creator and normal-use access must be different logins on the same SQL "
    "Server. The creator remains database owner; choose a separate normal-use "
    "login or different creator credentials."
)
DATABASE_CREATOR_LABEL_PROVISIONING_APPLICATION_USER = "Provisioning application user"
DATABASE_CREATOR_LABEL_VERIFYING_RUNTIME_PERMISSIONS = "Verifying runtime permissions"
DATABASE_CREATOR_LABEL_INITIALIZING_SCHEMA_AND_REFERENCE_DATA = (
    "Initializing schema and reference data"
)
DATABASE_CREATOR_MESSAGE_THE_NORMAL_USE_CONNECTION_COULD_NOT = (
    "The normal-use connection could not be prepared."
)
DATABASE_CREATOR_MESSAGE_THE_DATABASE_CONTAINER_WAS_CREATED_BUT = (
    "The database container was created, but initialization failed. No automatic drop "
    'was attempted; an administrator should inspect "{database_name}" before removing '
    "it."
)
DATABASE_CREATOR_MESSAGE_CANNOT_CREATE_A_DATABASE_ON_THIS = (
    "Cannot create a database on this SQL Server. Ask your SQL administrator for "
    "database-creation permission in master or CREATE ANY DATABASE permission."
)
DATABASE_CREATOR_MESSAGE_A_DATABASE_WITH_THAT_NAME_ALREADY = (
    "A database with that name already exists."
)
DATABASE_CREATOR_MESSAGE_THE_SELECTED_DATABASE_IS_NOT_BLANK = (
    "The selected database is not blank. Select an empty database or create a new "
    "one."
)
DATABASE_CREATOR_MESSAGE_SQL_SERVER_CHANGE_TRACKING_MUST_USE = (
    "SQL Server Change Tracking must use seven-day retention with automatic "
    "cleanup enabled."
)
DATABASE_CREATOR_MESSAGE_THE_EXACT_SQL_DATABASE_TARGET_COULD = (
    "The exact SQL database target could not be resolved."
)
DATABASE_CREATOR_MESSAGE_SQL_SERVER_SNAPSHOT_ISOLATION_COULD_NOT = (
    "SQL Server snapshot isolation could not be enabled."
)
DATABASE_CREATOR_MESSAGE_AUTHENTICATION_PREFLIGHT_FAILED = (
    "Normal-use authentication preflight failed. {detail}"
)
DATABASE_CREATOR_MESSAGE_RUNTIME_USER_PROVISIONING_FAILED_DATABASE_RETAINED = (
    'Runtime user provisioning failed. Database "{database_name}" was created and its '
    "schema initialized, but no connection was saved. The database was retained. Ask "
    "your SQL administrator to check the selected login's mapping and canonical client "
    "permissions, then add it through Open Files. {detail}"
)
DATABASE_CREATOR_MESSAGE_RUNTIME_PERMISSION_VERIFICATION_FAILED_DATABASE_RETAINED = (
    'Runtime permission verification failed. Database "{database_name}" was created '
    "and its schema initialized, but no connection was saved. The database was "
    "retained. Ask your SQL administrator to check the selected login's mapping and "
    "canonical client permissions, then add it through Open Files. {detail}"
)
DATABASE_CREATOR_MESSAGE_INITIALIZATION_DID_NOT_FINISH = (
    "{detail} The database container was created, but initialization did not "
    "finish. No automatic drop was attempted; an administrator should inspect it "
    "before removing it."
)
# Infrastructure: infrastructure.sql.database_maintenance
DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_IS_NOT_AVAILABLE_FOR = (
    "Compact/Repair is not available for SQL Server. SQL Server manages space "
    "differently; OST Visualizer will not shrink databases or remove collaboration "
    "history."
)
# Infrastructure: infrastructure.sql.descriptor_connection
DESCRIPTOR_CONNECTION_MESSAGE_THE_SAVED_SQL_SERVER_DATABASE_CONNECTION = (
    "The saved SQL Server database connection was not found."
)
DESCRIPTOR_CONNECTION_MESSAGE_THE_SAVED_SQL_SERVER_CREDENTIAL_IS = (
    "The saved SQL Server credential is missing. Reconnect to this database and "
    "enter the password again."
)
# Infrastructure: infrastructure.sql.errors
SQL_ERRORS_MESSAGE_SQL_SERVER_RETURNED_AN_UNEXPECTED_ERROR = (
    "SQL Server returned an unexpected error."
)
SQL_ERRORS_MESSAGE_THE_SQL_SERVER_IS_AVAILABLE_BUT = (
    "The SQL Server is available, but the selected database is missing or cannot "
    "be opened."
)
SQL_ERRORS_MESSAGE_THE_SQL_LOGIN_DOES_NOT_HAVE = (
    "The SQL login does not have permission to perform this operation."
)
SQL_ERRORS_MESSAGE_THE_SQL_SERVER_CONNECTION_TIMED_OUT = (
    "The SQL Server connection timed out."
)
SQL_ERRORS_MESSAGE_THE_REQUESTED_CHANGE_VIOLATES_A_SQL = (
    "The requested change violates a SQL data-integrity rule."
)
SQL_ERRORS_MESSAGE_SQL_SERVER_REJECTED_THE_SUPPLIED_AUTHENTICATION = (
    "SQL Server rejected the supplied authentication credentials."
)
SQL_ERRORS_MESSAGE_SQL_SERVER_PRESENTED_A_CERTIFICATE_THAT = (
    "SQL Server presented a certificate that Windows does not trust. OST "
    "Visualizer normally trusts the certificate supplied by configured SQL Server "
    "connections; reconnect the database or ask an administrator to install a "
    "trusted certificate."
)
SQL_ERRORS_MESSAGE_THE_SQL_SERVER_COULD_NOT_BE = (
    "The SQL Server could not be reached. Check the server name, network, and SQL "
    "Server service."
)
# Infrastructure: infrastructure.sql.reader
READER_MESSAGE_THE_SQL_SERVER_DATABASE_DESCRIPTOR_IS = (
    "The SQL Server database descriptor is not registered."
)
# Infrastructure: infrastructure.sql.remote_change_reader
REMOTE_CHANGE_READER_MESSAGE_THE_SQL_HYDRATION_REPLAY_QUERY_ORDER = (
    "The SQL hydration replay query order changed."
)
REMOTE_CHANGE_READER_MESSAGE_THE_SQL_HYDRATION_REPLAY_HAS_NO = (
    "The SQL hydration replay has no result set remaining."
)
REMOTE_CHANGE_READER_MESSAGE_THE_SQL_HYDRATION_REPLAY_LEFT_UNUSED = (
    "The SQL hydration replay left unused result sets."
)
REMOTE_CHANGE_READER_MESSAGE_A_SQL_HYDRATION_QUERY_EXCEEDS_THE = (
    "A SQL hydration query exceeds the safe parameter batch limit."
)
REMOTE_CHANGE_READER_MESSAGE_THE_SQL_TAKEOFF_HYDRATION_BATCH_RETURNED = (
    "The SQL takeoff hydration batch returned too few result sets."
)
REMOTE_CHANGE_READER_MESSAGE_SQL_CHANGE_TRACKING_METADATA_IS_UNAVAILABLE = (
    "SQL Change Tracking metadata is unavailable."
)
REMOTE_CHANGE_READER_MESSAGE_THE_INITIAL_SQL_CHECKPOINT_IS_AHEAD = (
    "The initial SQL checkpoint is ahead of the database."
)
# Infrastructure: infrastructure.sql.schema_lock
SCHEMA_LOCK_MESSAGE_ANOTHER_CLIENT_IS_INITIALIZING_THIS_DATABASE = (
    "Another client is initializing this database schema."
)
SCHEMA_LOCK_MESSAGE_ANOTHER_SESSION_IS_CHANGING_THE_SAME = (
    "Another session is changing the same SQL resource."
)
SCHEMA_LOCK_MESSAGE_ANOTHER_SESSION_IS_RESOLVING_THE_SAME = (
    "Another session is resolving the same SQL operation. Reconnect to the "
    "database to finish resolving it."
)
# Infrastructure: infrastructure.sql.writer
WRITER_MESSAGE_THIS_SQL_ITEM_CHANGED_IN_ANOTHER = (
    "This SQL item changed in another session. Reload it before saving."
)
WRITER_MESSAGE_THIS_OST_DATABASE_IS_MISSING_REQUIRED = (
    "This OST database is missing required writable columns {table}.{columns} "
    "for {operation}."
)
WRITER_MESSAGE_THIS_OST_DATABASE_HAS_NO_WRITABLE = (
    "This OST database has no writable columns for {operation}."
)
WRITER_MESSAGE_THE_CURRENT_SQL_SCHEMA_IS_MISSING = (
    "The current SQL schema is missing {table}.{columns}."
)
WRITER_MESSAGE_THIS_ITEM_IS_BEING_EDITED_BY = "This item is being edited by {owner}."
WRITER_MESSAGE_THIS_BID_IS_BEING_CHANGED_BY = "This bid is being changed by {owner}."
WRITER_MESSAGE_THIS_BID_CONTAINS_AN_ITEM_BEING = (
    "This bid contains an item being edited by {owner}."
)
WRITER_MESSAGE_THIS_BID_IS_ACTIVELY_BEING_EDITED = (
    "This bid is actively being edited by {owner}."
)
WRITER_MESSAGE_A_REQUIRED_SQL_EDIT_LOCK_EXPIRED = (
    "A required SQL edit lock expired before the write."
)
WRITER_MESSAGE_A_SQL_EDIT_LOCK_DOES_NOT = (
    "A SQL edit lock does not belong to this mutation."
)
WRITER_MESSAGE_THE_MUTATION_DID_NOT_PRESENT_ITS = (
    "The mutation did not present its owned SQL edit lock."
)
WRITER_MESSAGE_SQL_EDIT_LOCK_VALIDATION_FAILED = "SQL edit-lock validation failed."
WRITER_MESSAGE_SQL_WRITES_MUST_RUN_THROUGH_A = (
    "SQL writes must run through a collaboration mutation transaction."
)
WRITER_MESSAGE_THE_SQL_VERSION_FEED_BATCH_RETURNED = (
    "The SQL version/feed batch returned an incomplete authoritative result."
)
WRITER_MESSAGE_THE_SQL_VERSION_FEED_BATCH_RETURNED_2 = (
    "The SQL version/feed batch returned duplicate resource identities."
)
WRITER_MESSAGE_A_COMMITTED_SQL_OPERATION_CANNOT_RECONSTRUCT = (
    "A committed SQL operation cannot reconstruct its result payload."
)
WRITER_MESSAGE_A_SQL_MUTATION_CANNOT_SWITCH_DATABASES = (
    "A SQL mutation cannot switch databases inside its transaction."
)
WRITER_MESSAGE_SQL_PLAN_ITEM_VALIDATION_RETURNED_NO = (
    "SQL plan-item validation returned no result."
)
WRITER_MESSAGE_SQL_PLAN_ITEM_VALIDATION_RETURNED_AN = (
    "SQL plan-item validation returned an invalid result."
)
WRITER_MESSAGE_SQL_TAKEOFF_DELETION_RETURNED_NO_RESULT = (
    "SQL takeoff deletion returned no result."
)
WRITER_MESSAGE_THE_SQL_COLLABORATION_SESSION_CHANGED_BEFORE = (
    "The SQL collaboration session changed before the write."
)
WRITER_MESSAGE_THE_SQL_ROWVERSION_VALIDATION_BATCH_RETURNED = (
    "The SQL rowversion validation batch returned an invalid ordinal."
)
WRITER_MESSAGE_THE_SQL_VERSION_FEED_BATCH_RETURNED_3 = (
    "The SQL version/feed batch returned an invalid resource ordinal."
)
WRITER_MESSAGE_THE_SQL_VERSION_FEED_BATCH_RETURNED_4 = (
    "The SQL version/feed batch returned a duplicate resource ordinal."
)
WRITER_MESSAGE_A_COMMITTED_SQL_OPERATION_ID_WAS = (
    "A committed SQL operation ID was reused with a different request."
)
WRITER_MESSAGE_A_COMMITTED_SQL_OPERATION_HAS_AN = (
    "A committed SQL operation has an invalid result payload."
)
WRITER_MESSAGE_THE_SQL_MUTATION_DID_NOT_RECORD = (
    "The SQL mutation did not record an affected resource."
)
WRITER_MESSAGE_ANOTHER_SESSION_IS_RESOLVING_THE_SAME = (
    "Another session is resolving the same SQL operation."
)
WRITER_MESSAGE_THE_SQL_COLLABORATION_SESSION_EXPIRED_BEFORE = (
    "The SQL collaboration session expired before the write."
)
WRITER_MESSAGE_IMPORTED_EMPLOYEE_REFERENCES_AN_UNKNOWN = (
    "Imported employee references an unknown {column}."
)
WRITER_MESSAGE_IMPORTED_BID_IDENTITY_WAS_NOT_ALLOCATED = (
    "Imported bid identity was not allocated before child rows."
)
WRITER_MESSAGE_AN_ANNOTATION_CHANGED_OR_WAS_DELETED = (
    "An annotation changed or was deleted before this operation started."
)
WRITER_MESSAGE_A_TAKEOFF_CHANGED_OR_WAS_DELETED = (
    "A takeoff changed or was deleted before this operation started."
)
WRITER_MESSAGE_THE_TAKEOFF_RELATIONSHIP_GRAPH_CHANGED_BEFORE = (
    "The takeoff relationship graph changed before the Plan mutation started."
)
# Infrastructure: infrastructure.visualization_provider
VISUALIZATION_PROVIDER_LABEL_EXPORT_PAGES = "Export_{page_count}_pages.{extension}"
VISUALIZATION_PROVIDER_LABEL_ONE_PAGE_FILE_NAME = "{bid_name} - {page_name}.{extension}"
VISUALIZATION_PROVIDER_LABEL_TWO_PAGES_FILE_NAME = (
    "{bid_name} - {first_page_name} + {second_page_name}.{extension}"
)
VISUALIZATION_PROVIDER_LABEL_MORE_PAGES_FILE_NAME = (
    "{bid_name} - {first_page_name} + {second_page_name} + {remaining_count} "
    "more.{extension}"
)
VISUALIZATION_PROVIDER_MESSAGE_EXPORT_PAGES_AS = (
    "Export {page_count} pages as {format_name}"
)
VISUALIZATION_PROVIDER_MESSAGE_EXPORT_PAGE_AS = "Export page as {format_name}"
# Domain: domain.entities.database_descriptor
DATABASE_DESCRIPTOR_MESSAGE_DATABASE_NAMES_MUST_BE_1_TO = (
    "Database names must be 1 to 128 characters without leading or trailing spaces."
)
DATABASE_DESCRIPTOR_MESSAGE_DATABASE_NAME_CONTAINS_A_CONTROL_CHARACTER = (
    "Database name contains a control character."
)
DATABASE_DESCRIPTOR_MESSAGE_DATABASE_NAME_CANNOT_CONTAIN_THE_CHARACTER = (
    'Database name cannot contain the "{identity_separator}" character.'
)
DATABASE_DESCRIPTOR_MESSAGE_A_SQL_SERVER_SYSTEM_DATABASE_CANNOT = (
    "A SQL Server system database cannot be used."
)
DATABASE_DESCRIPTOR_MESSAGE_NEW_DATABASE_NAMES_MUST_FIT_WITHIN = (
    "New database names must fit within 75 UTF-16 characters because the complete "
    "name is stored in the database settings."
)
DATABASE_DESCRIPTOR_MESSAGE_SQL_SERVER_CONNECTION_DETAILS_CANNOT_CONTAIN = (
    'SQL Server connection details cannot contain the "{identity_separator}" '
    "character without a database id."
)
# Application: application.services.mcp_read_service
MCP_READ_SERVICE_MESSAGE_THE_LIVE_SELECTION_CONTAINS_UNIQUE_TAKEOFF = (
    "The live selection contains {total_count} unique takeoff IDs; only the first "
    "{returned_count} were summarized."
)
MCP_READ_SERVICE_MESSAGE_THE_LIVE_SELECTION_CONTAINS_UNIQUE_PAGE = (
    "The live selection contains {total_count} unique page IDs; only the first "
    "{returned_count} were summarized."
)
MCP_READ_SERVICE_MESSAGE_NO_TAKEOFFS_ARE_SELECTED_IN_THE = (
    "No takeoffs are selected in the live OST Visualizer context."
)
MCP_READ_SERVICE_MESSAGE_NO_PAGES_ARE_SELECTED_FOR_THE = (
    "No pages are selected for the live OST Visualizer context."
)
MCP_READ_SERVICE_MESSAGE_THE_LIVE_SELECTED_TAKEOFF_IDS_WERE = (
    "The live selected takeoff IDs were not found in the loaded bid."
)
MCP_READ_SERVICE_MESSAGE_THE_LIVE_SELECTED_PAGE_IDS_WERE = (
    "The live selected page IDs were not found in the loaded bid."
)
# Application: application.services.remote_change_reconciliation_service
REMOTE_CHANGE_RECONCILIATION_SERVICE_MESSAGE_THIS_ITEM_CHANGED_IN_ANOTHER_SESSION = (
    "This item changed in another session while it was being edited. Reload it "
    "before saving again."
)
# Infrastructure: infrastructure.windows.file_associations
FILE_ASSOCIATIONS_MESSAGE_WINDOWS_FILE_ASSOCIATIONS_CAN_ONLY_BE = (
    "Windows file associations can only be registered on Windows."
)
# Application: application.services.ai_takeoff_proposal_service
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_LEAK_CHECK_SKIPPED = "leak check skipped"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_THIS_REGION_WAS_NOT_CHECKED_FOR = (
    "This region was not checked for openings into neighboring areas because "
    "the check would pass the 20,000-segment cap, so it may merge two areas; "
    "check the outline, or search a smaller box or with a larger min_width."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_NO_WALL_WIDTH_FILTER = "no wall-width filter"
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_NO_STROKE_WIDTH_STANDS_CLEARLY_ABOVE = (
    "No stroke width stands clearly above the page's lightest lines, so no width "
    "filter was applied; thin lines may split or close the region."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_FEW_LINES_ARE_DRAWN_HEAVIER_THAN = (
    "Few lines are drawn heavier than the page's thin lines, so a width filter "
    "could remove the walls and none was applied; check the outline."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_PAGE_SCALE = "Page scale {sf1:g} : {sf2:g}"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_SLAB_THICKNESS = "Slab {thickness:g} in"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_SLAB = "Slab"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_ON_PAGE = "{base} on page {page_uid}"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_UP_TO_IN = "up to {length_in:.2f} in"
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_FILL_MAY_HAVE_CLOSED_OPENINGS = (
    "The fill may have closed openings up to {length_in:.2f} in that could not "
    "be located; check the outline."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_GAP_IN = "{length_in:.2f} in"
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_OUTLINE_WAS_CLOSED_ACROSS_A = (
    "The outline was closed across a {length_in:.2f} in gap in the drawing from "
    "({x1:.1f}, {y1:.1f}) to ({x2:.1f}, {y2:.1f}) page points."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_IN_OPENING_NOT_CLOSED = (
    "{length_in:.2f} in opening not closed"
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_REGION_RUNS_THROUGH_A = (
    "The region runs through a {length_in:.2f} in opening from ({x1:.1f}, "
    "{y1:.1f}) to ({x2:.1f}, {y2:.1f}) page points without closing it, so it may "
    "merge two areas; check the outline."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_DASHED_OUTLINE_IGNORED = "dashed outline ignored"
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_SEED_IS_INSIDE_A_CLOSED = (
    "The seed is inside a closed dashed outline of {area_sf:.1f} SF that this "
    "region does not follow. Dashed lines often mark mat, footing or below-grade "
    "edges; compare with the callouts."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_SLAB_THICKNESS_WAS_NOT_GIVEN = (
    "The slab thickness was not given."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_THE_TOP_ELEVATION_WAS_NOT_GIVEN = (
    "The top elevation was not given."
)
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_ONE_HOLE_LEFT_OUT = "1 hole left out"
AI_TAKEOFF_PROPOSAL_SERVICE_LABEL_HOLES_LEFT_OUT = "{hole_count} holes left out"
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_ONE_TRACED_HOLE_CROSSED_THE_OUTLINE = (
    "1 traced hole crossed the slab outline and was left out; check the outline."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_TRACED_HOLES_CROSSED_THE_OUTLINE = (
    "{hole_count} traced holes crossed the slab outline and were left out; check "
    "the outline."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_SCALE_PROPOSED_BY_THE_AI_FROM = (
    "Scale proposed by the AI from a measured distance."
)
AI_TAKEOFF_PROPOSAL_SERVICE_MESSAGE_A_DIMENSION_NEAR_THE_MEASURED_POINTS = (
    "{reason} A dimension near the measured points reads {real_in:g} in, but this "
    "scale gives {scaled_in:.4g} in ({error_pct:.1f}% off)."
)
# Infrastructure: infrastructure.sql.connection_manager
CONNECTION_MANAGER_MESSAGE_MICROSOFT_ODBC_DRIVER_18_FOR = (
    "Microsoft ODBC Driver 18 for SQL Server is required."
)
# Infrastructure: infrastructure.sql.client_provisioning
CLIENT_PROVISIONING_MESSAGE_NORMAL_DATABASE_ACCESS_REQUIRES_AN_EXISTING = (
    "Normal database access requires an existing individual SQL or Windows "
    "login. Ask your SQL administrator to provision that login first. Group-only "
    "Windows access is not supported by this creation workflow."
)
CLIENT_PROVISIONING_MESSAGE_THE_NORMAL_USE_LOGIN_CHANGED_DURING = (
    "The normal-use login changed during creation. Ask your SQL administrator to "
    "check its user mapping."
)
CLIENT_PROVISIONING_MESSAGE_THE_NORMAL_USE_CONNECTION_MUST_USE = (
    "The normal-use connection must use the provisioned restricted user, without "
    "database ownership or DDL rights."
)
CLIENT_PROVISIONING_MESSAGE_THE_NEWLY_INITIALIZED_DATABASE_WAS_REPLACED = (
    "The newly initialized database was replaced or its identity changed. No "
    "runtime connection will be saved."
)
CLIENT_PROVISIONING_MESSAGE_CHOOSE_A_SEPARATE_NORMAL_USE_LOGIN = (
    "Choose a separate normal-use login without server roles, database-creation "
    "rights, or server administration permissions. The creator's privileges will "
    "not be changed."
)
# Infrastructure: infrastructure.sql.write_schema
WRITE_SCHEMA_MESSAGE_THE_CURRENT_SQL_SCHEMA_DOES_NOT = (
    "The current SQL schema does not support {resource}."
)
# Domain: domain.services.notes_tags
NOTES_TAGS_MESSAGE_IS_NOT_A_KEY_VALUE_ARGUMENT = (
    '{label}: "{token}" is not a key=value argument and is ignored.'
)
NOTES_TAGS_MESSAGE_UNKNOWN_KEY_IS_IGNORED = (
    '{label}: unknown key "{raw_key}" is ignored (keys: {known_keys}).'
)
NOTES_TAGS_MESSAGE_IS_GIVEN_MORE_THAN_ONCE = (
    "{label}: {key_name} is given more than once; the first valid value is used."
)
NOTES_TAGS_MESSAGE_IS_NOT_A_KNOWN_TAG = (
    "[{tag_name} ...] is not a known tag (known: {known_tags})."
)
NOTES_TAGS_MESSAGE_MORE_THAN_ONE_TAG_THE_FIRST_IS_USED = (
    "More than one [{tag_name}] tag; the first one is used."
)
NOTES_TAGS_MESSAGE_IS_MISSING_ITS_CLOSING_BRACKET = (
    '[{tag_name} is missing its closing "]" and is ignored.'
)
NOTES_TAGS_MESSAGE_NOT_SECTIONS_USING_THE_DEFAULT = (
    "{label}: {token} is not a whole number of sections, or a length with ft or m; "
    "using {default_text}."
)
NOTES_TAGS_MESSAGE_NOT_SECTIONS_IGNORED = (
    "{label}: {token} is not a whole number of sections, or a length with ft or m; it "
    "is ignored."
)
NOTES_TAGS_MESSAGE_NOT_PERCENT_OR_LENGTH_USING_THE_DEFAULT = (
    "{label}: {token} is not a percentage, or a distance in feet (a plain number, or a "
    "number with ft or m); using {default_text}."
)
NOTES_TAGS_MESSAGE_NOT_PERCENT_OR_LENGTH_IGNORED = (
    "{label}: {token} is not a percentage, or a distance in feet (a plain number, or a "
    "number with ft or m); it is ignored."
)
NOTES_TAGS_MESSAGE_NOT_LENGTH_USING_THE_DEFAULT = (
    "{label}: {token} is not a length in feet (a plain number, or a number with ft or "
    "m); using {default_text}."
)
NOTES_TAGS_MESSAGE_NOT_LENGTH_IGNORED = (
    "{label}: {token} is not a length in feet (a plain number, or a number with ft or "
    "m); it is ignored."
)
NOTES_TAGS_MESSAGE_NOT_A_CHOICE_USING_THE_DEFAULT = (
    "{label}: {token} is not one of {choices}; using {default_text}."
)
NOTES_TAGS_MESSAGE_NOT_A_CHOICE_IGNORED = (
    "{label}: {token} is not one of {choices}; it is ignored."
)
NOTES_TAGS_MESSAGE_OUTSIDE_SECTIONS_USING_THE_DEFAULT = (
    "{label}: {token} is outside {minimum} to {maximum} sections; using {default_text}."
)
NOTES_TAGS_MESSAGE_OUTSIDE_SECTIONS_IGNORED = (
    "{label}: {token} is outside {minimum} to {maximum} sections; it is ignored."
)
NOTES_TAGS_MESSAGE_BELOW_SECTIONS_USING_THE_DEFAULT = (
    "{label}: {token} is less than {minimum} sections; using {default_text}."
)
NOTES_TAGS_MESSAGE_BELOW_SECTIONS_IGNORED = (
    "{label}: {token} is less than {minimum} sections; it is ignored."
)
NOTES_TAGS_MESSAGE_ABOVE_SECTIONS_USING_THE_DEFAULT = (
    "{label}: {token} is more than {maximum} sections; using {default_text}."
)
NOTES_TAGS_MESSAGE_ABOVE_SECTIONS_IGNORED = (
    "{label}: {token} is more than {maximum} sections; it is ignored."
)
NOTES_TAGS_MESSAGE_OUTSIDE_LENGTH_USING_THE_DEFAULT = (
    "{label}: {token} is outside {minimum:g} ft to {maximum:g} ft; using "
    "{default_text}."
)
NOTES_TAGS_MESSAGE_OUTSIDE_LENGTH_IGNORED = (
    "{label}: {token} is outside {minimum:g} ft to {maximum:g} ft; it is ignored."
)
NOTES_TAGS_MESSAGE_BELOW_LENGTH_USING_THE_DEFAULT = (
    "{label}: {token} is less than {minimum:g} ft; using {default_text}."
)
NOTES_TAGS_MESSAGE_BELOW_LENGTH_IGNORED = (
    "{label}: {token} is less than {minimum:g} ft; it is ignored."
)
NOTES_TAGS_MESSAGE_ABOVE_LENGTH_USING_THE_DEFAULT = (
    "{label}: {token} is more than {maximum:g} ft; using {default_text}."
)
NOTES_TAGS_MESSAGE_ABOVE_LENGTH_IGNORED = (
    "{label}: {token} is more than {maximum:g} ft; it is ignored."
)
NOTES_TAGS_LABEL_ONE_SECTION_REACH = (
    "{label}: {token} → 1 section ({reach:.1f} ft reach)."
)
NOTES_TAGS_LABEL_SECTIONS_REACH = (
    "{label}: {token} → {count} sections ({reach:.1f} ft reach)."
)
NOTES_TAGS_LABEL_ONE_SECTION_LENGTH = "{label}: {token} → 1 section ({length:.1f} ft)."
NOTES_TAGS_LABEL_SECTIONS_LENGTH = (
    "{label}: {token} → {count} sections ({length:.1f} ft)."
)
# Application: application.services.bid_comparison_service
BID_COMPARISON_SERVICE_MESSAGE_AFFECTED_PAGES_TRUNCATED_TO_OF_PAGES = (
    "{group_name} affected pages truncated to {page_limit} of {page_count} pages."
)
BID_COMPARISON_SERVICE_MESSAGE_CONTAINS_MIXED_UOM_LABELS_REPORTING = (
    "{group_name} qty{quantity_number} contains mixed UOM labels: {labels}; "
    "reporting {selected_label}."
)
BID_COMPARISON_SERVICE_MESSAGE_ADDITIONAL_WARNINGS_OMITTED = (
    "{count} additional warnings omitted."
)
# Application: application.use_cases.project.condition_summary_service
CONDITION_SUMMARY_SERVICE_LABEL_CONDITIONS = "Conditions"
CONDITION_SUMMARY_SERVICE_LABEL_CONDITIONS_PROJECT = "Conditions - {project_name}"
# Domain: domain.services.project_data_service
PROJECT_DATA_SERVICE_LABEL_UNKNOWN = "Unknown"
# Application: application.services.file_loading_service
FILE_LOADING_SERVICE_MESSAGE_NO_FILE_PATH_PROVIDED = "No file path provided."
FILE_LOADING_SERVICE_MESSAGE_FAILED_TO_UNLOAD_FILE = "Failed to unload file."
FILE_LOADING_SERVICE_MESSAGE_FAILED_TO_RELOAD_DATABASE = "Failed to reload database."
# Infrastructure: infrastructure.mdb.database_creator
ACCESS_DATABASE_CREATOR_LABEL_CREATING_DATABASE_FILE = "Creating database file"
ACCESS_DATABASE_CREATOR_LABEL_CREATING_SCHEMA_TABLES = "Creating schema tables"
ACCESS_DATABASE_CREATOR_LABEL_WRITING_SCHEMA_FIELD_METADATA = (
    "Writing schema field metadata"
)
ACCESS_DATABASE_CREATOR_LABEL_CREATING_SCHEMA_INDEXES = "Creating schema indexes"
ACCESS_DATABASE_CREATOR_LABEL_CREATING_SCHEMA_RELATIONSHIPS = (
    "Creating schema relationships"
)
ACCESS_DATABASE_CREATOR_LABEL_ADDING_DEFAULT_DATA = "Adding default data"
ACCESS_DATABASE_CREATOR_LABEL_FINALIZING_DATABASE = "Finalizing database"
# Infrastructure: infrastructure.mdb.exporters.ost_exporter
OST_EXPORTER_MESSAGE_CANNOT_EXPORT_OST_BECAUSE_SOME_DATABASE_REFERENCES = (
    "Cannot export OST because some database references are invalid. See the log for "
    "details."
)
OST_EXPORTER_LABEL_WRITING_OST = "Writing OST"
# Domain: domain.entities.employee
EMPLOYEE_LABEL_EMPLOYEE = "Employee {uid}"
# Domain: domain.entities.project_factory
PROJECT_FACTORY_LABEL_PROJECT = "Project {uid}"
PROJECT_FACTORY_LABEL_UNASSIGNED_BIDS = "Unassigned Bids"
PROJECT_FACTORY_LABEL_BIDS_WITHOUT_A_PROJECT = "Bids without a project"
# Domain: domain.entities.tower_crane_spec
TOWER_CRANE_SPEC_MESSAGE_HOOKHEIGHT_IS_NOT_A_LENGTH_USING_THE_HOOK_ROPE = (
    "{label}: {token} is not a length in feet (a plain number, or a number with ft or "
    "m); using the hook rope length."
)
TOWER_CRANE_SPEC_MESSAGE_HOOKHEIGHT_IS_LESS_THAN_USING_THE_HOOK_ROPE = (
    "{label}: {token} is less than {minimum:g} ft; using the hook rope length."
)
TOWER_CRANE_SPEC_MESSAGE_TROLLEY_POSITION_OUTSIDE_ITS_TRAVEL = (
    "[crane]: a trolley position of {percent:g}% is outside 0% to 100% of its travel; "
    "the jib tip end is used."
)
TOWER_CRANE_SPEC_MESSAGE_TROLLEY_DISTANCE_OUTSIDE_ITS_TRAVEL = (
    "[crane]: a trolley distance of {distance_ft:.1f} ft is outside its travel "
    "({low_ft:.1f} ft to {high_ft:.1f} ft from the mast); the nearest end is used."
)
TOWER_CRANE_SPEC_MESSAGE_HOOK_AND_HOOKHEIGHT_ARE_BOTH_GIVEN = (
    "[crane]: hook and hookheight are both given; hookheight is used."
)
TOWER_CRANE_SPEC_MESSAGE_HOOK_HEIGHT_IS_ABOVE_THE_HIGHEST_POSITION = (
    "[crane]: a hook height of {height_ft:.1f} ft is above the highest hook position "
    "({highest_ft:.1f} ft); the hook is raised as far as it goes."
)
TOWER_CRANE_SPEC_MESSAGE_HOOK_ROPE_IS_LONGER_THAN_THE_CRANE = (
    "[crane]: a hook rope of {length_ft:.1f} ft is longer than the crane is tall "
    "({longest_ft:.1f} ft); the hook rests at the footing."
)
# Application: application.utils.path_probe
PATH_PROBE_MESSAGE_ACCESS_IS_DENIED = "Cannot access the file: access is denied."
PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND = (
    "Cannot access the file: the network path {location} was not found."
)
PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND_NO_LOCATION = (
    "Cannot access the file: the network path was not found."
)
PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST = (
    "Cannot access the file: the network connection to {location} was lost."
)
PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST_NO_LOCATION = (
    "Cannot access the file: the network connection was lost."
)
PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND = (
    "Cannot access the file: the network share on {location} was not found."
)
PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND_NO_LOCATION = (
    "Cannot access the file: the network share was not found."
)
PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS = (
    "Cannot access the file: {location} is already connected with different network "
    "credentials."
)
PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS_NO_LOCATION = (
    "Cannot access the file: the file location is already connected with different "
    "network credentials."
)
PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE = (
    "Cannot access the file: no logon server is available to check the network "
    "credentials for {location}."
)
PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE_NO_LOCATION = (
    "Cannot access the file: no logon server is available to check the network "
    "credentials."
)
PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED = (
    "Cannot access the file: the network credentials for {location} were rejected."
)
PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED_NO_LOCATION = (
    "Cannot access the file: the network credentials were rejected."
)
PATH_PROBE_MESSAGE_CANNOT_ACCESS_THE_FILE = "Cannot access the file: {system_reason}"
# Log texts (developer log explanations, not shown to users)
BASE_WRITE_SERVICE_LOG_DATABASE_MUTATION_REJECTED_BECAUSE_EDITING_IS = (
    "Database mutation rejected because editing is unavailable."
)
BASE_WRITE_SERVICE_LOG_DATABASE_MUTATION_REJECTED_BECAUSE_ITS_RESOURCE = (
    "Database mutation rejected because its resource is unavailable."
)
BID_DATA_READER_LOG_COULD_NOT_READ_THE_SAVED_PAGE = "Could not read the saved page for bid {bid_uid}; treating the bid as having no saved page: {exc}"
CONFIG_AGGREGATE_LOG_INVALID_IN_CONFIG_USING_CANONICAL_DEFAULT = (
    "Invalid {field_name} '{configured_value}' in config; using canonical default"
)
CONFIG_AGGREGATE_LOG_INVALID_IN_CONFIG_USING_DEFAULT = (
    "Invalid {field_name} '{configured_value}' in config; using default '{default}'"
)
CONFIG_AGGREGATE_LOG_INVALID_MOUSE_SNAP_ANGLE_IN_CONFIG = (
    "Invalid mouse snap angle '{configured_value}' in config; using default '{default}'"
)
CONFIG_AGGREGATE_LOG_INVALID_OR_DUPLICATE_PDF_ANNOTATION_CAPTION = "Invalid or duplicate PDF annotation caption identifiers in config; using the supported identifiers in canonical order"
CONNECTION_MANAGER_LOG_THE_MDB_READ_LEASE_ON_THE = "The MDB read lease on the writer connection could not be rolled back after {error_type}."
DATABASE_MAINTENANCE_LOG_COULD_NOT_RESTORE_THE_ORIGINAL_DATABASE = "Could not restore the original database after {error_type}; it is preserved at {backup}."
DATABASE_MAINTENANCE_LOG_MAINTENANCE_CLEANUP_FAILED_AFTER_THE_INTERRUPT = (
    "Maintenance cleanup failed after {error_type}; the interrupt is re-raised."
)
LICENSE_AGGREGATE_LOG_CANONICAL_HWID_VALIDATION_FAILED_CLEARING_INVALID = (
    "Canonical HWID validation failed. Clearing invalid cached license."
)
LICENSE_ORCHESTRATOR_LOG_ERROR_IN_LICENSE_ORCHESTRATOR_CLEANUP_THE = "Error in license orchestrator cleanup; the original {error_type} is re-raised: {error}"
LICENSE_ORCHESTRATOR_LOG_LICENSE_SERVER_UNAVAILABLE_USING_CACHED_LICENSE = "License server unavailable; using cached license within {offline_grace_hours}-hour offline grace"
LICENSE_THREAD_MANAGER_LOG_ERROR_JOINING_A_LICENSE_WORKER_DURING = "Error joining a license worker during cleanup; the original {error_type} is re-raised: {error}"
LICENSE_THREAD_MANAGER_MESSAGE_OPERATION_FAILED = "Operation failed: {error}"
MDB_WRITER_LOG_THE_MDB_TRANSACTION_COULD_NOT_BE = (
    "The MDB transaction could not be rolled back after {error_type}."
)
OSP_IMPORTER_LOG_OSP_IMPORT_COULD_NOT_RESOLVE_REFERENCED = "OSP import could not resolve {missing_path_count} referenced image(s) in the package. Import will continue and preserve those original paths. First missing source path: {first_missing_path}"
OST_IMPORTER_LOG_DISCARDED_STALE_NAMED_VIEW_S_AND = "Discarded {stale_uid_count} stale Named View(s) and {discarded_link_count} dependent Hot Link(s) during OST import for Bid {bid_uid}; absent Page references: {issues}"
OST_IMPORTER_LOG_REJECTING_OST_IMPORT_BECAUSE_IT_CONTAINS = (
    "Rejecting OST import because it contains invalid database references: {issues}"
)
OST_IMPORTER_LOG_SKIPPING_INVALID_TAKEOFF_S_DURING_OST = "Skipping {skipped_count} invalid takeoff(s) during OST import; missing-parent roots: {issues}{descendant_diagnostic}"
PAGE_OPERATIONS_LOG_SKIPPING_PAGE_SCALE_RESCALE_FOR_UID = (
    "Skipping page-scale rescale for {table} UID {uid} because Position is not numeric"
)
PROJECT_READ_SERVICE_LOG_JOB_STATUS_OF_A_BID_IN = "Job status {bid_status_uid!r} of a bid in {file_path} could not be resolved; treating the bid as locked"
SQL_COLLABORATION_COORDINATOR_LOG_SQL_COLLABORATION_WORKER_STOPPED_AFTER_AN = (
    "SQL collaboration worker stopped after an unexpected {error_type}."
)
TAKEOFF_OPERATIONS_LOG_ACCESS_RESOURCE_LIMIT_WHILE_DELETING_TAKEOFFS = "Access resource limit while deleting {takeoff_count} takeoffs with chunk size {chunk_size}; retrying row-by-row in a fresh transaction."
TAKEOFF_OPERATIONS_LOG_ACCESS_RESOURCE_LIMIT_WHILE_SAVING_FOR = "Access resource limit while saving {label} for {takeoff_count} takeoffs with chunk size {chunk_size}; retrying row-by-row in a fresh transaction."
TRANSACTION_MONITOR_LOG_THE_TRANSACTION_MONITOR_WORKER_DID_NOT = (
    "The transaction-monitor worker did not stop within 1.5 seconds."
)
WRITER_LOG_THE_SQL_SESSION_CONTEXT_COULD_NOT = (
    "The SQL session context could not be cleared after {error_type}."
)
WRITER_LOG_THE_SQL_TRANSACTION_COULD_NOT_BE = (
    "The SQL transaction could not be rolled back after {error_type}."
)

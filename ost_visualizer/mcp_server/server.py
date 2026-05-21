import logging
from typing import Optional
from ..application.dtos.mcp_context_dtos import (
    McpResultMetaDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
)
from ..application.services.mcp_read_service import McpReadError, McpReadService
from ..infrastructure.mdb.mdb_reader import MdbReader
from ..infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    MdbFileParser,
)
from .bridge_client import McpBridgeClient
from .internal_server import OstMcpServer
from .registry import DatabaseRegistry
from .serializers import error, ok, to_jsonable

LOGGER = logging.getLogger(__name__)


def create_read_service(
    registry: DatabaseRegistry, logger: Optional[logging.Logger] = None
) -> McpReadService:
    base_logger = logger or LOGGER
    reader_logger = base_logger.getChild("MdbReader")
    reader = MdbReader(logger=reader_logger)
    parser = MdbFileParser(logger=reader_logger.getChild("Parser"), parser=reader)
    repository = FileProjectRepository(
        parsers={"mdb": parser},
        logger=reader_logger.getChild("Repository"),
    )
    return McpReadService(
        project_repository=repository,
        databases=registry.databases,
    )


def build_mcp_server(
    registry: DatabaseRegistry,
    logger: Optional[logging.Logger] = None,
    name: str = "ost-visualizer",
) -> OstMcpServer:
    log = logger or LOGGER
    read_service = create_read_service(registry, log)
    mcp = OstMcpServer(name)

    def run_read(fn, *args, **kwargs) -> dict:
        try:
            return ok(fn(*args, **kwargs))
        except McpReadError as exc:
            return error(str(exc), code=_read_error_code(str(exc)))
        except Exception as exc:
            log.exception("MCP read failed")
            return error(str(exc), code="unexpected_error")

    def run_limited_read(fn, limit: int, *args, **kwargs) -> dict:
        try:
            result = fn(*args, limit=limit, **kwargs)
            meta = _result_meta(result, limit)
            status = _result_status(result, meta)
            return ok(result, status=status, meta=meta)
        except McpReadError as exc:
            return error(str(exc), code=_read_error_code(str(exc)))
        except Exception as exc:
            log.exception("MCP read failed")
            return error(str(exc), code="unexpected_error")

    @mcp.tool()
    def list_databases() -> dict:
        """List checked OST databases visible to the read-only MCP helper."""
        registry.reload()
        read_service.set_databases(registry.databases)
        databases = read_service.list_databases()
        return ok(
            databases,
            status="ok" if databases else "no_checked_database",
            meta=McpResultMetaDto(
                returned_count=len(databases),
                total_count=len(databases),
            ),
        )

    @mcp.tool()
    def get_current_context() -> dict:
        """Return live app context when available, otherwise saved workspace context."""
        registry.reload()
        read_service.set_databases(registry.databases)
        bridge_client = McpBridgeClient(log)
        live_context = bridge_client.get_context()
        if live_context is not None:
            return ok(_with_database_ids(live_context, registry), status="live_context")
        selection = registry.workspace_selection
        payload = to_jsonable(selection)
        payload["source"] = "saved_workspace"
        payload["bridge_status"] = bridge_client.last_status
        if selection.database_id and selection.bid_uid:
            try:
                page = read_service.get_current_page(
                    selection.database_id, selection.bid_uid
                )
                payload["selected_page_uid"] = page.uid if page else None
            except Exception:
                payload["selected_page_uid"] = None
        if not registry.databases:
            return ok(payload, status="no_checked_database")
        return ok(payload, status="saved_context")

    @mcp.tool()
    def list_projects(database_id: str) -> dict:
        """List projects in a checked database before selecting bids."""
        return run_read(read_service.list_projects, database_id)

    @mcp.tool()
    def list_bids(database_id: str, project_uid: Optional[str] = None) -> dict:
        """List bids in a checked database, optionally scoped to one project."""
        return run_read(read_service.list_bids, database_id, project_uid)

    @mcp.tool()
    def get_bid_summary(database_id: str, bid_uid: str) -> dict:
        """Return identifying and count metadata for a single bid."""
        return run_read(read_service.get_bid_summary, database_id, bid_uid)

    @mcp.tool()
    def list_pages(database_id: str, bid_uid: str) -> dict:
        """List page inventory for a bid; use get_page_context for page details."""
        return run_read(read_service.list_pages, database_id, bid_uid)

    @mcp.tool()
    def get_current_page(database_id: str, bid_uid: str) -> dict:
        """Return the saved current page for a bid, or the first page fallback."""
        return run_read(read_service.get_current_page, database_id, bid_uid)

    @mcp.tool()
    def get_page_pdf_info(database_id: str, bid_uid: str, page_uid: str) -> dict:
        """Return basic page and PDF metadata already stored for one page."""
        return run_read(read_service.get_page_pdf_info, database_id, bid_uid, page_uid)

    @mcp.tool()
    def list_conditions(database_id: str, bid_uid: str) -> dict:
        """List condition inventory for a bid; use search_conditions for lookup."""
        return run_read(read_service.list_conditions, database_id, bid_uid)

    @mcp.tool()
    def search_conditions(
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> dict:
        """Search conditions by name, ref, notes, type, or UID with a bounded limit."""
        return run_limited_read(
            read_service.search_conditions,
            limit,
            database_id,
            bid_uid,
            query,
        )

    @mcp.tool()
    def get_condition_summary(
        database_id: str,
        bid_uid: str,
        condition_uid: str,
    ) -> dict:
        """Summarize one condition's quantities, pages, and takeoff counts."""
        return run_read(
            read_service.get_condition_summary,
            database_id,
            bid_uid,
            condition_uid,
        )

    @mcp.tool()
    def list_takeoffs(
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        visible_only: bool = True,
        include_geometry: bool = False,
        limit: int = 500,
    ) -> dict:
        """List takeoffs for browsing, optionally scoped by page or condition."""
        return run_limited_read(
            read_service.list_takeoffs,
            limit,
            database_id,
            bid_uid,
            page_uid,
            condition_uid,
            visible_only,
            include_geometry,
        )

    @mcp.tool()
    def get_selected_takeoffs_summary(limit: int = 500) -> dict:
        """Resolve live selected takeoff IDs into read-only estimator summary data."""
        registry.reload()
        read_service.set_databases(registry.databases)
        bridge_client = McpBridgeClient(log)
        live_context = bridge_client.get_context()
        if live_context is None:
            return ok(
                McpSelectedTakeoffsSummaryDto(
                    status=bridge_client.last_status,
                    message=(
                        "OST Visualizer is not running or the live context bridge "
                        "is unavailable."
                    ),
                )
            )
        context = _with_database_ids(live_context, registry)
        database_id = context.get("database_id")
        bid_uid = context.get("bid_uid")
        selected_takeoff_uids = context.get("selected_takeoff_uids")
        if not database_id or not bid_uid:
            return ok(
                McpSelectedTakeoffsSummaryDto(
                    status="no_active_bid",
                    message="The live OST Visualizer context has no active bid.",
                )
            )
        if not isinstance(selected_takeoff_uids, list) or not selected_takeoff_uids:
            return ok(
                McpSelectedTakeoffsSummaryDto(
                    status="no_selection",
                    message="No takeoffs are selected in OST Visualizer.",
                    database_id=str(database_id),
                    bid_uid=str(bid_uid),
                )
            )
        return run_read(
            read_service.get_selected_takeoffs_summary,
            str(database_id),
            str(bid_uid),
            selected_takeoff_uids,
            limit,
        )

    @mcp.tool()
    def get_selected_pages_summary() -> dict:
        """Resolve live selected page IDs into read-only page summary data."""
        registry.reload()
        read_service.set_databases(registry.databases)
        bridge_client = McpBridgeClient(log)
        live_context = bridge_client.get_context()
        if live_context is None:
            return ok(
                McpSelectedPagesSummaryDto(
                    status=bridge_client.last_status,
                    message=(
                        "OST Visualizer is not running or the live context bridge "
                        "is unavailable."
                    ),
                )
            )
        context = _with_database_ids(live_context, registry)
        database_id = context.get("database_id")
        bid_uid = context.get("bid_uid")
        selected_page_uids = context.get("selected_page_uids")
        active_view = str(context.get("active_view") or "")
        active_page_uid = context.get("active_page_uid")
        if not database_id or not bid_uid:
            return ok(
                McpSelectedPagesSummaryDto(
                    status="no_active_bid",
                    message="The live OST Visualizer context has no active bid.",
                    active_view=active_view,
                    active_page_uid=active_page_uid,
                )
            )
        if not isinstance(selected_page_uids, list) or not selected_page_uids:
            return ok(
                McpSelectedPagesSummaryDto(
                    status="no_selection",
                    message="No pages are selected in OST Visualizer.",
                    database_id=str(database_id),
                    bid_uid=str(bid_uid),
                    active_view=active_view,
                    active_page_uid=active_page_uid,
                )
            )
        return run_read(
            read_service.get_selected_pages_summary,
            str(database_id),
            str(bid_uid),
            selected_page_uids,
            active_view,
            str(active_page_uid) if active_page_uid else None,
        )

    @mcp.tool()
    def summarize_quantities(
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
    ) -> dict:
        """Return quantity totals for a bid, optionally scoped by page or condition."""
        return run_read(
            read_service.summarize_quantities,
            database_id,
            bid_uid,
            page_uid,
            condition_uid,
        )

    @mcp.tool()
    def get_page_quantity_summary(
        database_id: str, bid_uid: str, page_uid: str
    ) -> dict:
        """Return quantity totals for one page in a bid."""
        return run_read(
            read_service.get_page_quantity_summary,
            database_id,
            bid_uid,
            page_uid,
        )

    @mcp.tool()
    def search_takeoffs(
        database_id: str,
        bid_uid: str,
        query: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """Search visible takeoffs by IDs, condition name, page name, or area UID."""
        return run_limited_read(
            read_service.search_takeoffs,
            limit,
            database_id,
            bid_uid,
            query,
            page_uid,
            condition_uid,
        )

    @mcp.tool()
    def get_bid_quantity_summary(
        database_id: str,
        bid_uid: str,
        limit: int = 250,
    ) -> dict:
        """Return bounded condition-level quantity summaries for a bid."""
        return run_read(
            read_service.get_bid_quantity_summary, database_id, bid_uid, limit
        )

    @mcp.tool()
    def review_scope_gaps(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Aggregate bounded read-only scope gap checks for a bid."""
        return run_read(read_service.review_scope_gaps, database_id, bid_uid, limit)

    @mcp.tool()
    def find_duplicate_conditions(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find duplicate condition names using a conservative name-only heuristic."""
        return run_read(
            read_service.find_duplicate_conditions, database_id, bid_uid, limit
        )

    @mcp.tool()
    def find_zero_quantity_conditions(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find conditions with takeoffs but zero computed visible quantity."""
        return run_read(
            read_service.find_zero_quantity_conditions,
            database_id,
            bid_uid,
            limit,
        )

    @mcp.tool()
    def find_unplaced_takeoffs(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find takeoffs with missing or invalid page links; no geometry guessing."""
        return run_read(
            read_service.find_unplaced_takeoffs, database_id, bid_uid, limit
        )

    @mcp.tool()
    def get_page_context(database_id: str, bid_uid: str, page_uid: str) -> dict:
        """Return detailed stored metadata for one page; page text is deferred."""
        return run_read(read_service.get_page_context, database_id, bid_uid, page_uid)

    @mcp.tool()
    def find_pages_without_takeoffs(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find pages with no takeoffs; use review_scope_gaps for aggregate review."""
        return run_limited_read(
            read_service.find_pages_without_takeoffs,
            limit,
            database_id,
            bid_uid,
        )

    @mcp.tool()
    def find_conditions_without_takeoffs(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find conditions with no takeoffs; use review_scope_gaps for aggregate review."""
        return run_limited_read(
            read_service.find_conditions_without_takeoffs,
            limit,
            database_id,
            bid_uid,
        )

    @mcp.prompt()
    def review_current_estimator_context() -> str:
        """Guide a read-only review of the currently active OST Visualizer context."""
        return (
            "Review the current OST Visualizer estimator context using only "
            "read-only MCP tools. Start with get_current_context and "
            "get_selected_takeoffs_summary. If a live bid is available, inspect "
            "pages, conditions, takeoffs, condition summaries, and quantity "
            "summaries before drawing conclusions. Do not assume quantities that "
            "were not returned by tools, and do not suggest database edits."
        )

    @mcp.prompt()
    def review_takeoff_scope(database_id: str, bid_uid: str) -> str:
        """Guide a read-only bid scope review using summary and gap tools."""
        return (
            "Review the OST takeoff scope for database_id="
            f"{database_id} and bid_uid={bid_uid}. Use list_pages, "
            "list_conditions, search_conditions, list_takeoffs, "
            "get_condition_summary, get_bid_quantity_summary, review_scope_gaps, "
            "find_duplicate_conditions, find_zero_quantity_conditions, "
            "find_unplaced_takeoffs, and get_page_context. "
            "Call out pages with unusually low or high takeoff counts, "
            "conditions without takeoffs, hidden-layer conditions, and major "
            "quantity drivers. Do not suggest edits unless the user explicitly "
            "asks for a separate write-capable workflow."
        )

    @mcp.resource("ost://databases")
    def databases_resource() -> dict:
        """Resource view of checked databases visible to MCP clients."""
        return list_databases()

    @mcp.resource("ost://database/{database_id}/hierarchy")
    def hierarchy_resource(database_id: str) -> dict:
        """Resource template for project and bid hierarchy in one checked database."""
        return run_read(read_service.get_hierarchy, database_id)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/pages")
    def pages_resource(database_id: str, bid_uid: str) -> dict:
        """Resource template for page inventory in a bid."""
        return list_pages(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/conditions")
    def conditions_resource(database_id: str, bid_uid: str) -> dict:
        """Resource template for condition inventory in a bid."""
        return list_conditions(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/quantities")
    def quantities_resource(database_id: str, bid_uid: str) -> dict:
        """Resource template for bid quantity totals."""
        return summarize_quantities(database_id, bid_uid)

    return mcp


def run_stdio_server(
    app_data_dir=None,
    logger: Optional[logging.Logger] = None,
) -> None:
    registry = DatabaseRegistry(
        app_data_dir=app_data_dir,
        logger=logger,
    )
    server = build_mcp_server(registry, logger=logger)
    server.run_stdio()


def _with_database_ids(payload: dict, registry: DatabaseRegistry) -> dict:
    result = dict(payload)
    selected_bid_ref = _with_database_id(result.get("selected_bid_ref"), registry)
    current_bid_ref = _with_database_id(result.get("current_bid_ref"), registry)
    result["selected_bid_ref"] = selected_bid_ref
    result["current_bid_ref"] = current_bid_ref
    selected_file_path = result.get("selected_file_path")
    selected_bid_refs = result.get("selected_bid_refs")
    if isinstance(selected_bid_refs, list):
        result["selected_bid_refs"] = [
            _with_database_id(ref, registry) for ref in selected_bid_refs
        ]
    source_ref = (
        selected_bid_ref if isinstance(selected_bid_ref, dict) else current_bid_ref
    )
    if isinstance(source_ref, dict):
        result["database_id"] = source_ref.get("database_id")
        result["bid_uid"] = source_ref.get("bid_uid")
    elif selected_file_path:
        result["database_id"] = registry.get_database_id_for_path(
            str(selected_file_path)
        )
    result["selected_page_uid"] = result.get("active_page_uid")
    return result


def _with_database_id(value, registry: DatabaseRegistry):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    result["database_id"] = registry.get_database_id_for_path(
        str(result.get("file_path", ""))
    )
    return result


def _read_error_code(message: str) -> str:
    if message.startswith("Unknown database_id"):
        return "invalid_database_id"
    if message.startswith("Unknown "):
        return "not_found"
    return "read_error"


def _result_meta(result, limit: int) -> McpResultMetaDto:
    if isinstance(result, list):
        clean_limit = _clean_tool_limit(limit)
        returned_count = len(result)
        return McpResultMetaDto(
            limit=clean_limit,
            returned_count=returned_count,
            total_count=returned_count,
            truncated=False,
        )
    meta = getattr(result, "meta", None)
    if isinstance(meta, McpResultMetaDto):
        return meta
    return McpResultMetaDto()


def _result_status(result, meta: McpResultMetaDto) -> str:
    status = getattr(result, "status", None)
    if status:
        return str(status)
    if meta.truncated:
        return "truncated"
    if meta.returned_count == 0:
        return "empty"
    return "ok"


def _clean_tool_limit(limit: int, default: int = 500) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 5000))

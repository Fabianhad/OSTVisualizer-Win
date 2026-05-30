import logging
from typing import Optional
from ..application.dtos.mcp_context_dtos import (
    McpAreaSummaryDto,
    McpBidQuantitySummaryDto,
    McpDuplicateConditionSummaryDto,
    McpPdfTextSummaryDto,
    McpPdfVectorsSummaryDto,
    McpResultMetaDto,
    McpScopeGapSummaryDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpUnplacedTakeoffSummaryDto,
    McpZeroQuantitySummaryDto,
)
from ..application.services.mcp_read_service import (
    McpLimitedList,
    McpReadError,
    McpReadService,
)
from ..infrastructure.mdb.mdb_reader import MdbReader
from ..infrastructure.pdf_metadata_provider import NativePdfMetadataProvider
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
        pdf_metadata_provider=NativePdfMetadataProvider(
            logger=base_logger.getChild("PdfMetadataProvider")
        ),
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
        """List checked OST databases as safe IDs and basenames, never full paths."""
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
            context = _with_database_ids(live_context, registry)
            _add_selected_area_name(context, read_service, log)
            return ok(context, status="live_context")
        selection = registry.workspace_selection
        payload = to_jsonable(selection)
        saved_file_path = payload.get("file_path")
        if saved_file_path:
            payload["file_basename"] = _basename(str(saved_file_path))
        payload.pop("file_path", None)
        payload["source"] = "saved_workspace"
        payload["bridge_status"] = bridge_client.last_status
        payload["selected_area_name"] = None
        if selection.database_id and selection.bid_uid:
            try:
                page = read_service.get_current_page(
                    selection.database_id, selection.bid_uid
                )
                payload["selected_page_uid"] = page.uid if page else None
            except McpReadError:
                payload["selected_page_uid"] = None
            except Exception:
                log.exception("Failed to resolve saved MCP current page")
                payload["selected_page_uid"] = None
        if not registry.databases:
            return ok(payload, status="no_checked_database")
        return ok(payload, status="saved_context")

    @mcp.tool()
    def list_projects(database_id: str) -> dict:
        """List projects in a checked database by database_id."""
        return run_read(read_service.list_projects, database_id)

    @mcp.tool()
    def list_bids(database_id: str, project_uid: Optional[str] = None) -> dict:
        """List bids in a checked database, optionally scoped to one project."""
        return run_read(read_service.list_bids, database_id, project_uid)

    @mcp.tool()
    def get_bid_summary(database_id: str, bid_uid: str) -> dict:
        """Return read-only bid metadata and current page selection."""
        return run_read(read_service.get_bid_summary, database_id, bid_uid)

    @mcp.tool()
    def list_pages(database_id: str, bid_uid: str, limit: int = 500) -> dict:
        """List redacted page metadata for a bid with bounded results."""
        return run_limited_read(read_service.list_pages, limit, database_id, bid_uid)

    @mcp.tool()
    def get_current_page(database_id: str, bid_uid: str) -> dict:
        """Return the bid's selected page metadata with local paths redacted."""
        return run_read(read_service.get_current_page, database_id, bid_uid)

    @mcp.tool()
    def get_page_metadata(database_id: str, bid_uid: str, page_uid: str) -> dict:
        """Return general redacted metadata for one page."""
        return run_read(read_service.get_page_metadata, database_id, bid_uid, page_uid)

    @mcp.tool()
    def get_page_pdf_text_summary(
        database_id: str,
        bid_uid: str,
        page_uid: str,
        source: str = "auto",
        include_text: bool = False,
        limit: int = 10,
    ) -> dict:
        """Return bounded embedded PDF text metadata and snippets for one page."""
        return run_read(
            read_service.get_page_pdf_text_summary,
            database_id,
            bid_uid,
            page_uid,
            source,
            include_text,
            limit,
        )

    @mcp.tool()
    def get_page_pdf_vectors_summary(
        database_id: str,
        bid_uid: str,
        page_uid: str,
        source: str = "auto",
        limit: int = 20,
    ) -> dict:
        """Return bounded PDF vector line metadata used for snapping."""
        return run_read(
            read_service.get_page_pdf_vectors_summary,
            database_id,
            bid_uid,
            page_uid,
            source,
            limit,
        )

    @mcp.tool()
    def list_conditions(database_id: str, bid_uid: str, limit: int = 500) -> dict:
        """List bid conditions with bounded read-only metadata."""
        return run_limited_read(
            read_service.list_conditions,
            limit,
            database_id,
            bid_uid,
        )

    @mcp.tool()
    def list_areas(database_id: str, bid_uid: str, limit: int = 500) -> dict:
        """List bid areas with usage counts and bounded result metadata."""
        return run_limited_read(
            read_service.list_areas,
            limit,
            database_id,
            bid_uid,
        )

    @mcp.tool()
    def get_area_summary(
        database_id: str,
        bid_uid: str,
        area_uid: str,
        limit: int = 250,
    ) -> dict:
        """Summarize one bid area, its child areas, and page takeoff counts."""
        return run_read(
            read_service.get_area_summary,
            database_id,
            bid_uid,
            area_uid,
            limit,
        )

    @mcp.tool()
    def search_conditions(
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> dict:
        """Search bid conditions by safe text fields such as name, type, and notes."""
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
        """Summarize one condition with quantities and page usage."""
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
        """List takeoffs with optional geometry; geometry requests are tightly capped."""
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
        """Summarize takeoffs currently selected in the live desktop app."""
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
        """Summarize pages currently selected in the live desktop app."""
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
        limit: int = 500,
    ) -> dict:
        """Summarize visible quantities with bounded condition rows."""
        return run_limited_read(
            read_service.summarize_quantities,
            limit,
            database_id,
            bid_uid,
            page_uid,
            condition_uid,
        )

    @mcp.tool()
    def search_pages(
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> dict:
        """Search pages by name, sheet number, sequence, or UID."""
        return run_limited_read(
            read_service.search_pages,
            limit,
            database_id,
            bid_uid,
            query,
        )

    @mcp.tool()
    def list_layers(database_id: str, bid_uid: str, limit: int = 500) -> dict:
        """List summarized bid layers and usage counts without raw table data."""
        return run_limited_read(read_service.list_layers, limit, database_id, bid_uid)

    @mcp.tool()
    def list_named_views(
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        limit: int = 250,
    ) -> dict:
        """List named views as page navigation summaries with bounds."""
        return run_limited_read(
            read_service.list_named_views,
            limit,
            database_id,
            bid_uid,
            page_uid,
        )

    @mcp.tool()
    def list_hotlinks(
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        limit: int = 250,
    ) -> dict:
        """List hotlinks and resolved target views without raw annotation details."""
        return run_limited_read(
            read_service.list_hotlinks,
            limit,
            database_id,
            bid_uid,
            page_uid,
        )

    @mcp.tool()
    def get_page_quantity_summary(
        database_id: str, bid_uid: str, page_uid: str
    ) -> dict:
        """Summarize visible quantities for one page."""
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
        """Search visible takeoffs by safe page, condition, area, and ID fields."""
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
        """Return bounded per-condition quantity summaries for a bid."""
        return run_read(
            read_service.get_bid_quantity_summary, database_id, bid_uid, limit
        )

    @mcp.tool()
    def review_scope_gaps(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Review common read-only scope gaps such as unused pages and conditions."""
        return run_read(read_service.review_scope_gaps, database_id, bid_uid, limit)

    @mcp.tool()
    def find_duplicate_conditions(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find conditions with duplicate normalized names."""
        return run_read(
            read_service.find_duplicate_conditions, database_id, bid_uid, limit
        )

    @mcp.tool()
    def find_zero_quantity_conditions(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find conditions that have takeoffs but compute to zero quantity."""
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
        """Find takeoffs that are not associated with a valid page."""
        return run_read(
            read_service.find_unplaced_takeoffs, database_id, bid_uid, limit
        )

    @mcp.tool()
    def get_page_context(database_id: str, bid_uid: str, page_uid: str) -> dict:
        """Return task-oriented page context with redacted source path metadata."""
        return run_read(read_service.get_page_context, database_id, bid_uid, page_uid)

    @mcp.tool()
    def find_pages_without_takeoffs(
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> dict:
        """Find pages that have no takeoffs, with bounded results."""
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
        """Find conditions that have no takeoffs, with bounded results."""
        return run_limited_read(
            read_service.find_conditions_without_takeoffs,
            limit,
            database_id,
            bid_uid,
        )

    @mcp.prompt()
    def review_current_estimator_context() -> str:
        """Guide an AI client through a read-only review of the current context."""
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
        """Guide an AI client through read-only scope and quantity review."""
        return (
            "Review the OST takeoff scope for database_id="
            f"{database_id} and bid_uid={bid_uid}. Use list_pages, "
            "get_page_metadata, get_page_pdf_text_summary, "
            "get_page_pdf_vectors_summary, list_conditions, "
            "search_conditions, list_takeoffs, "
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
        """Checked database IDs and redacted basenames available to MCP clients."""
        return list_databases()

    @mcp.resource("ost://database/{database_id}/hierarchy")
    def hierarchy_resource(database_id: str) -> dict:
        """Project and bid hierarchy for one checked database."""
        return run_read(read_service.get_hierarchy, database_id)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/pages")
    def pages_resource(database_id: str, bid_uid: str) -> dict:
        """Bounded redacted page metadata for one bid."""
        return list_pages(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/conditions")
    def conditions_resource(database_id: str, bid_uid: str) -> dict:
        """Bounded condition metadata for one bid."""
        return list_conditions(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/quantities")
    def quantities_resource(database_id: str, bid_uid: str) -> dict:
        """Bounded visible quantity summary for one bid."""
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
    if selected_file_path:
        result["selected_file_basename"] = _basename(str(selected_file_path))
        result["database_id"] = registry.get_database_id_for_path(
            str(selected_file_path)
        )
    result.pop("selected_file_path", None)
    result.pop("file_path", None)
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
    result["selected_page_uid"] = result.get("active_page_uid")
    return result


def _add_selected_area_name(
    payload: dict,
    read_service: McpReadService,
    log: logging.Logger,
) -> None:
    payload["selected_area_name"] = None
    area_uid = payload.get("selected_area_uid")
    database_id = payload.get("database_id")
    bid_uid = payload.get("bid_uid")
    if area_uid in (None, "", "0", 0) or not database_id or not bid_uid:
        return
    try:
        payload["selected_area_name"] = read_service.resolve_area_name(
            str(database_id),
            str(bid_uid),
            str(area_uid),
        )
    except McpReadError:
        payload["selected_area_name"] = None
    except Exception:
        log.exception("Failed to resolve selected MCP area name")
        payload["selected_area_name"] = None


def _with_database_id(value, registry: DatabaseRegistry):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    file_path = result.get("file_path")
    if file_path:
        result["database_id"] = registry.get_database_id_for_path(str(file_path))
        result["file_basename"] = _basename(str(file_path))
    result.pop("file_path", None)
    return result


def _basename(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").split("/")[-1]


def _read_error_code(message: str) -> str:
    if message.startswith("Unknown database_id"):
        return "invalid_database_id"
    if message.startswith("Unknown "):
        return "not_found"
    return "read_error"


def _result_meta(result, limit: int) -> McpResultMetaDto:
    if isinstance(result, McpLimitedList):
        return result.meta
    if isinstance(result, list):
        clean_limit = _clean_tool_limit(limit)
        returned_count = len(result)
        return McpResultMetaDto(
            limit=clean_limit,
            returned_count=returned_count,
            total_count=returned_count,
            truncated=False,
            has_more=False,
        )
    if _has_summary_meta(result):
        return result.meta
    return McpResultMetaDto()


def _result_status(result, meta: McpResultMetaDto) -> str:
    if isinstance(result, McpLimitedList):
        return result.status
    if _has_summary_meta(result):
        return result.status
    if meta.truncated:
        return "truncated"
    if meta.returned_count == 0:
        return "empty"
    return "ok"


def _has_summary_meta(result) -> bool:
    return isinstance(
        result,
        (
            McpBidQuantitySummaryDto,
            McpAreaSummaryDto,
            McpPdfTextSummaryDto,
            McpPdfVectorsSummaryDto,
            McpScopeGapSummaryDto,
            McpDuplicateConditionSummaryDto,
            McpZeroQuantitySummaryDto,
            McpUnplacedTakeoffSummaryDto,
        ),
    )


def _clean_tool_limit(limit: int, default: int = 500) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 5000))

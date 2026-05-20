import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP
from ..application.dtos.mcp_context_dtos import (
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
) -> FastMCP:
    log = logger or LOGGER
    read_service = create_read_service(registry, log)
    mcp = FastMCP(name)

    def run_read(fn, *args, **kwargs) -> dict:
        try:
            return ok(fn(*args, **kwargs))
        except McpReadError as exc:
            return error(str(exc), code="read_error")
        except Exception as exc:
            log.exception("MCP read failed")
            return error(str(exc), code="unexpected_error")

    @mcp.tool()
    def list_databases() -> dict:
        registry.reload()
        read_service.set_databases(registry.databases)
        return run_read(read_service.list_databases)

    @mcp.tool()
    def get_current_context() -> dict:
        registry.reload()
        read_service.set_databases(registry.databases)
        live_context = McpBridgeClient(log).get_context()
        if live_context is not None:
            return ok(_with_database_ids(live_context, registry))
        selection = registry.workspace_selection
        payload = to_jsonable(selection)
        if selection.database_id and selection.bid_uid:
            try:
                page = read_service.get_current_page(
                    selection.database_id, selection.bid_uid
                )
                payload["selected_page_uid"] = page.uid if page else None
            except Exception:
                payload["selected_page_uid"] = None
        return ok(payload)

    @mcp.tool()
    def list_projects(database_id: str) -> dict:
        return run_read(read_service.list_projects, database_id)

    @mcp.tool()
    def list_bids(database_id: str, project_uid: Optional[str] = None) -> dict:
        return run_read(read_service.list_bids, database_id, project_uid)

    @mcp.tool()
    def get_bid_summary(database_id: str, bid_uid: str) -> dict:
        return run_read(read_service.get_bid_summary, database_id, bid_uid)

    @mcp.tool()
    def list_pages(database_id: str, bid_uid: str) -> dict:
        return run_read(read_service.list_pages, database_id, bid_uid)

    @mcp.tool()
    def get_current_page(database_id: str, bid_uid: str) -> dict:
        return run_read(read_service.get_current_page, database_id, bid_uid)

    @mcp.tool()
    def get_page_pdf_info(database_id: str, bid_uid: str, page_uid: str) -> dict:
        return run_read(read_service.get_page_pdf_info, database_id, bid_uid, page_uid)

    @mcp.tool()
    def list_conditions(database_id: str, bid_uid: str) -> dict:
        return run_read(read_service.list_conditions, database_id, bid_uid)

    @mcp.tool()
    def search_conditions(
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> dict:
        return run_read(
            read_service.search_conditions,
            database_id,
            bid_uid,
            query,
            limit,
        )

    @mcp.tool()
    def get_condition_summary(
        database_id: str,
        bid_uid: str,
        condition_uid: str,
    ) -> dict:
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
        return run_read(
            read_service.list_takeoffs,
            database_id,
            bid_uid,
            page_uid,
            condition_uid,
            visible_only,
            include_geometry,
            limit,
        )

    @mcp.tool()
    def get_selected_takeoffs_summary(limit: int = 500) -> dict:
        registry.reload()
        read_service.set_databases(registry.databases)
        live_context = McpBridgeClient(log).get_context()
        if live_context is None:
            return ok(
                McpSelectedTakeoffsSummaryDto(
                    status="bridge_unavailable",
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
        registry.reload()
        read_service.set_databases(registry.databases)
        live_context = McpBridgeClient(log).get_context()
        if live_context is None:
            return ok(
                McpSelectedPagesSummaryDto(
                    status="bridge_unavailable",
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
        return run_read(
            read_service.search_takeoffs,
            database_id,
            bid_uid,
            query,
            page_uid,
            condition_uid,
            limit,
        )

    @mcp.tool()
    def find_pages_without_takeoffs(database_id: str, bid_uid: str) -> dict:
        return run_read(
            read_service.find_pages_without_takeoffs,
            database_id,
            bid_uid,
        )

    @mcp.tool()
    def find_conditions_without_takeoffs(database_id: str, bid_uid: str) -> dict:
        return run_read(
            read_service.find_conditions_without_takeoffs,
            database_id,
            bid_uid,
        )

    @mcp.prompt()
    def review_current_estimator_context() -> str:
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
        return (
            "Review the OST takeoff scope for database_id="
            f"{database_id} and bid_uid={bid_uid}. Use list_pages, "
            "list_conditions, search_conditions, list_takeoffs, "
            "get_condition_summary, summarize_quantities, "
            "find_pages_without_takeoffs, and find_conditions_without_takeoffs. "
            "Call out pages with unusually low or high takeoff counts, "
            "conditions without takeoffs, hidden-layer conditions, and major "
            "quantity drivers. Do not suggest edits unless the user explicitly "
            "asks for a separate write-capable workflow."
        )

    @mcp.resource("ost://databases")
    def databases_resource() -> dict:
        return list_databases()

    @mcp.resource("ost://database/{database_id}/hierarchy")
    def hierarchy_resource(database_id: str) -> dict:
        return run_read(read_service.get_hierarchy, database_id)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/pages")
    def pages_resource(database_id: str, bid_uid: str) -> dict:
        return list_pages(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/conditions")
    def conditions_resource(database_id: str, bid_uid: str) -> dict:
        return list_conditions(database_id, bid_uid)

    @mcp.resource("ost://database/{database_id}/bid/{bid_uid}/quantities")
    def quantities_resource(database_id: str, bid_uid: str) -> dict:
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
    server.run(transport="stdio")


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

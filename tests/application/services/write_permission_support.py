import logging
from contextlib import nullcontext
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
)
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


class _EventBus:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.subscriptions.remove((event_type, callback))

    def publish(self, event_type, **call_options):
        self.published.append((event_type, call_options))


class _TransactionMonitor:
    def is_ost_active(self):
        return False


class _DatabaseCapability:
    def __init__(self, editable=True):
        self.editable = editable
        self.locators = []

    def is_editable(self, locator, _resource=None):
        self.locators.append(locator)
        return self.editable


class _MutationRecorder:
    def record(self, resource, operation, *, changed_fields=(), payload=""):
        pass


class _MutationExecutor:
    def execute(self, request, operation):
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=operation(_MutationRecorder()),
        )


class _SessionRegistry:
    def get(self, _database_id):
        return ""

    def lock_tokens(self, _database_id, _resources):
        return ()


class _ConcurrencyTokens:
    def mutation_scope(self, _database_id):
        return nullcontext()

    def ensure_resources_loaded(self, _database_id, _resources):
        pass

    def expected_versions(self, _database_id, _resources):
        return ()

    def apply_result(self, _database_id, _versions):
        pass


class _ProjectData:
    def __init__(self):
        self.locked = False
        self.bid_ref = BidRef(file_path="C:/jobs/test.mdb", bid_uid="7")
        self.project_uid = "project-1"
        self.annotation_layer_visible = True
        self.conditions = {}
        self.takeoffs = []
        self.bid = SimpleNamespace(uid="7")

    def is_current_bid_locked(self):
        return self.locked

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid(self, bid_ref):
        return self.bid if bid_ref == self.bid_ref else None

    def get_bid_conditions(self):
        return dict(self.conditions)

    def get_all_takeoffs(self):
        return list(self.takeoffs)

    def replace_condition_family(self, bid_ref, conditions, folders):
        if bid_ref != self.bid_ref:
            return False
        self.conditions = dict(conditions)
        self.condition_folders = dict(folders)
        return True

    def is_annotation_layer_visible(self):
        return self.annotation_layer_visible

    def find_project_uid_for_bid(self, bid_ref):
        if bid_ref == self.bid_ref:
            return self.project_uid
        return None

    def get_hierarchy(self):
        return _hierarchy_with_bids(self.bid_ref.bid_uid)


def _hierarchy_with_bids(*bid_uids, file_path="C:/jobs/test.mdb"):
    return HierarchyData(
        loaded_files=[
            HierarchyFileEntry(
                file_path=file_path,
                bid_projects={
                    "project-1": HierarchyProjectInfo(
                        name="Project 1",
                        bids=[HierarchyBidInfo(uid=uid) for uid in bid_uids],
                    )
                },
            )
        ]
    )


class _UseCase:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def execute(self, *args, **call_options):
        self.calls.append((args, call_options))
        return self.result


class _SequenceUseCase:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, *args, **call_options):
        self.calls.append((args, call_options))
        if self.results:
            return self.results.pop(0)
        return False


class _ForbiddenUseCase:
    def execute(self, *args, **call_options):
        raise AssertionError("locked bid guard did not block the write")


def _write_service(
    project_data,
    reload_success=True,
    save_takeoffs_condition=None,
    database_capability=None,
    event_bus=None,
    insert_takeoffs=None,
    mutation_executor=None,
):
    logger = logging.Logger(__name__ + ".write_service")
    logger.addHandler(logging.NullHandler())
    forbidden = _ForbiddenUseCase()
    delete_bids = _UseCase(True)
    duplicate_bid = _UseCase("new-bid")
    update_bid_job_status = _UseCase(True)

    def read_condition_family(_file_path, _bid_uid):
        if not reload_success:
            raise OSError("Condition read failed")
        return project_data.get_bid_conditions(), {}

    service = ProjectWriteService(
        condition_family_reader=read_condition_family,
        delete_bids=delete_bids,
        delete_projects=forbidden,
        create_project=forbidden,
        rename_project=forbidden,
        move_bids=forbidden,
        duplicate_bid=duplicate_bid,
        create_bid=forbidden,
        delete_conditions=forbidden,
        duplicate_conditions=forbidden,
        update_condition=forbidden,
        renumber_conditions=forbidden,
        insert_condition=forbidden,
        insert_condition_folder=forbidden,
        rename_condition_folder=forbidden,
        delete_condition_folders=forbidden,
        save_takeoff_positions=forbidden,
        save_takeoff_rotations=forbidden,
        save_takeoff_text_properties=forbidden,
        save_takeoffs_area=forbidden,
        save_takeoffs_condition=save_takeoffs_condition or forbidden,
        set_takeoffs_negative=forbidden,
        set_takeoff_curve=forbidden,
        insert_takeoffs=insert_takeoffs or forbidden,
        delete_takeoffs=forbidden,
        delete_pages=forbidden,
        save_cover_sheet=forbidden,
        update_bid_job_status=update_bid_job_status,
        save_job_statuses=forbidden,
        save_bid_areas=forbidden,
        save_page_name=forbidden,
        save_page_scale=forbidden,
        save_page_show_mode=forbidden,
        save_page_overlay_image=forbidden,
        save_page_overlay_rect=forbidden,
        save_page_invert=forbidden,
        save_page_bitonal=forbidden,
        save_page_image_adjustments=forbidden,
        save_page_area=forbidden,
        save_employees=forbidden,
        save_pay_classes=forbidden,
        save_condition_types=forbidden,
        update_layer_show=forbidden,
        update_all_layers_show=forbidden,
        update_layer_name=forbidden,
        insert_layer=forbidden,
        delete_layer=forbidden,
        swap_layer_sequence=forbidden,
        save_bid_selected_page=forbidden,
        save_page_view_state=forbidden,
        delete_annotations=forbidden,
        insert_annotations=forbidden,
        save_annotation_positions=forbidden,
        save_annotation_text_properties=forbidden,
        save_annotation_styles=forbidden,
        reload_database=lambda _file_path: reload_success,
        event_bus=event_bus or _EventBus(),
        logger=logger,
        bid_write_guard=ActiveBidWriteGuard(project_data, logger),
        project_data_service=project_data,
        mutation_executor=mutation_executor or _MutationExecutor(),
        session_registry=_SessionRegistry(),
        concurrency_tokens=_ConcurrencyTokens(),
        database_capability_service=database_capability or _DatabaseCapability(),
        sql_collaboration_provider=lambda: SimpleNamespace(
            uses_sql_collaboration=lambda _database_id: False,
        ),
    )
    return service, update_bid_job_status, delete_bids, duplicate_bid

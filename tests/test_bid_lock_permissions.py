import logging
import unittest
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    UIAccessManager,
)


class _EventBus:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.subscriptions.remove((event_type, callback))

    def publish(self, event_type, **kwargs):
        pass


class _License:
    def has_valid_license(self):
        return True


class _TransactionMonitor:
    def is_ost_active(self):
        return False


class _ProjectData:
    def __init__(self):
        self.locked = False
        self.bid_ref = BidRef(file_path="C:/jobs/test.mdb", bid_uid="7")
        self.project_uid = "project-1"

    def is_current_bid_locked(self):
        return self.locked

    def get_current_bid_ref(self):
        return self.bid_ref

    def find_project_uid_for_bid(self, bid_ref):
        if bid_ref == self.bid_ref:
            return self.project_uid
        return None


class _UiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.place_condition_uid = None

    def get_selected_bid_ref(self):
        return self._bid_ref

    def is_database_selected(self):
        return True


class _UseCase:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class _ForbiddenUseCase:
    def execute(self, *args, **kwargs):
        raise AssertionError("locked bid guard did not block the write")


def _write_service(project_data):
    logger = logging.getLogger(__name__ + ".write_service")
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    forbidden = _ForbiddenUseCase()
    delete_bids = _UseCase(True)
    duplicate_bid = _UseCase("new-bid")
    update_bid_job_status = _UseCase(True)
    service = ProjectWriteService(
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
        save_takeoffs_area=forbidden,
        save_takeoffs_condition=forbidden,
        set_takeoffs_negative=forbidden,
        set_takeoff_curve=forbidden,
        insert_takeoffs=forbidden,
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
        reload_database=lambda _file_path: True,
        event_bus=_EventBus(),
        logger=logger,
        bid_write_guard=ActiveBidWriteGuard(project_data, logger),
    )
    return service, update_bid_job_status, delete_bids, duplicate_bid


class BidLockPermissionTests(unittest.TestCase):
    def test_bid_lock_applies_and_unlocks_immediately_in_access_manager(self):
        project_data = _ProjectData()
        manager = UIAccessManager(
            _EventBus(),
            _License(),
            _TransactionMonitor(),
            project_data,
            _UiState(project_data.bid_ref),
        )
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.SELECT_TAKEOFFS))
        project_data.locked = True
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertFalse(manager.is_allowed(Feature.SELECT_TAKEOFFS))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))
        self.assertTrue(manager.is_allowed(Feature.EDIT_BID_JOB_STATUS))
        project_data.locked = False
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.SELECT_TAKEOFFS))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))

    def test_locked_bid_blocks_condition_edits_at_write_service(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, _, _, _ = _write_service(project_data)
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            UpdateConditionDto(),
        )
        self.assertFalse(result.success)
        self.assertEqual("The active bid is locked", result.error)

    def test_locked_bid_blocks_bid_internal_mutations_but_allows_status_change(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, update_bid_job_status, _, _ = _write_service(project_data)
        self.assertEqual(
            [],
            service.insert_takeoffs(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                [],
            ),
        )
        self.assertFalse(
            service.save_cover_sheet(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                {"job_status_uid": 2},
            )
        )
        self.assertFalse(
            service.save_takeoffs_condition(
                project_data.bid_ref.file_path,
                ["12"],
                "34",
            )
        )
        self.assertTrue(
            service.update_bid_job_status(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                "2",
            )
        )
        self.assertEqual(1, len(update_bid_job_status.calls))

    def test_locked_bid_allows_bid_delete_and_duplicate(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, _, delete_bids, duplicate_bid = _write_service(project_data)
        self.assertTrue(
            service.delete_bids(
                project_data.bid_ref.file_path, [project_data.bid_ref.bid_uid]
            )
        )
        self.assertEqual(
            "new-bid",
            service.duplicate_bid(
                project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
            ),
        )
        self.assertEqual(1, len(delete_bids.calls))
        self.assertEqual(1, len(duplicate_bid.calls))


if __name__ == "__main__":
    unittest.main()

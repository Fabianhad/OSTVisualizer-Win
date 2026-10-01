import unittest
from copy import deepcopy
from unittest.mock import Mock, create_autospec
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.use_cases.project.delete_annotations_use_case import (
    DeleteAnnotationsUseCase,
)
from ost_visualizer.application.use_cases.project.insert_annotations_use_case import (
    InsertAnnotationsUseCase,
)
from ost_visualizer.application.use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
from ost_visualizer.application.use_cases.project.save_annotation_styles_use_case import (
    SaveAnnotationStylesUseCase,
)
from ost_visualizer.application.use_cases.project.save_annotation_text_properties_use_case import (
    SaveAnnotationTextPropertiesUseCase,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from tests.application.services.write_access_support import (
    _CapabilityService,
    _ConcurrencyTokens,
    _EventBus,
    _MutationExecutor,
    _SessionRegistry,
)

DATABASE = "c:/jobs/CURRENT.mdb"


class _Harness:
    def __init__(self):
        self.writer = create_autospec(IMdbWriter, instance=True, spec_set=True)
        self.writer.save_annotation_positions.return_value = True
        self.writer.save_annotation_styles.return_value = True
        self.writer.save_annotation_text_properties.return_value = True
        self.writer.insert_annotations.return_value = ["101", "102"]
        self.writer.delete_annotations.return_value = True
        self.guard = create_autospec(ActiveBidWriteGuard, instance=True, spec_set=True)
        self.guard.blocks_active_locked_bid_write.return_value = False
        self.data = create_autospec(ProjectDataService, instance=True, spec_set=True)
        self.data.get_current_bid_ref.return_value = BidRef(
            r"C:\Jobs\Current.mdb", "41"
        )
        self.executor = _MutationExecutor()
        self.tokens = _ConcurrencyTokens()
        self.events = _EventBus()
        self.reload = Mock(return_value=True)
        self.arguments = dict(
            save_annotation_positions=SaveAnnotationPositionsUseCase(self.writer),
            save_annotation_text_properties=SaveAnnotationTextPropertiesUseCase(
                self.writer
            ),
            save_annotation_styles=SaveAnnotationStylesUseCase(self.writer),
            insert_annotations=InsertAnnotationsUseCase(self.writer),
            delete_annotations=DeleteAnnotationsUseCase(self.writer),
            mutation_executor=self.executor,
            session_registry=_SessionRegistry(),
            concurrency_tokens=self.tokens,
            database_capability_service=_CapabilityService(True),
            reload_database=self.reload,
            event_bus=self.events,
            bid_write_guard=self.guard,
            project_data_service=self.data,
        )
        self.service = AnnotationWriteService(**self.arguments)

    def operations(self):
        return [
            (
                self.service.save_annotation_positions,
                (DATABASE, [("7", "text", [1.25, 2.5])]),
                False,
            ),
            (
                self.service.save_annotation_text_properties,
                (DATABASE, [("7", "text", {"Text": "Draft"})]),
                False,
            ),
            (
                self.service.save_annotation_styles,
                (DATABASE, [("7", "text", {"color": "#112233"})]),
                False,
            ),
            (self.service.delete_annotations, (DATABASE, [("7", "text")]), False),
            (self.service.insert_annotations, (DATABASE, "41", _specs()), []),
        ]


def _specs():
    return [
        InsertAnnotationSpec(
            "21", "namedview", [1.25, 2.5, 10.0, 20.0], "#112233", 1.0
        ),
        InsertAnnotationSpec(
            "21", "hotlink", [3.0, 4.0], "#445566", 2.0, {"BidPageViewUID": "9"}
        ),
    ]


class AnnotationWriteServiceTests(unittest.TestCase):
    def assert_refreshed_once(self, harness):
        harness.reload.assert_called_once_with(DATABASE)
        self.assertEqual(
            harness.events.published,
            [
                (
                    AppEvents.DATABASE_REFRESHED,
                    dict(
                        file_path=DATABASE,
                        image_sources_unchanged=False,
                        mesh_scene_unchanged=False,
                        page_scale_uids=(),
                    ),
                )
            ],
        )

    def test_annotation_resources_keep_bid_identity_for_equivalent_windows_path(self):
        harness = _Harness()
        updates = [("7", "text", [1.25, 2.5]), ("7", "rect", [3.0, 4.0, 5.0, 6.0])]
        self.assertTrue(harness.service.save_annotation_positions(DATABASE, updates))
        resources = (
            ResourceRef("annotation", "text/7", 41),
            ResourceRef("annotation", "rect/7", 41),
        )
        self.assertEqual(harness.executor.calls, 1)
        self.assertEqual(harness.executor.requests[0].database_id, DATABASE)
        self.assertEqual(harness.executor.requests[0].resources, resources)
        self.assertEqual(
            harness.executor.recorder.changes,
            [(resource, ChangeOperation.UPDATE, (), "") for resource in resources],
        )
        harness.writer.save_annotation_positions.assert_called_once_with(
            DATABASE, updates
        )
        self.assert_refreshed_once(harness)

    def test_foreign_database_or_absent_bid_does_not_borrow_active_bid_identity(self):
        for bid in (None, BidRef("other.mdb", "41")):
            with self.subTest(bid=bid):
                harness = _Harness()
                harness.data.get_current_bid_ref.return_value = bid
                self.assertTrue(
                    harness.service.save_annotation_styles(
                        DATABASE,
                        [("7", "rect", {"color": "#112233"})],
                        False,
                    )
                )
                self.assertEqual(
                    harness.executor.requests[0].resources,
                    (ResourceRef("annotation", "rect/7"),),
                )
                self.assertEqual(harness.events.published, [])
                harness.reload.assert_not_called()

    def test_each_update_routes_exact_payload_and_records_one_typed_batch(self):
        for index in range(3):
            with self.subTest(operation=index):
                harness = _Harness()
                operation, arguments, _failure = harness.operations()[index]
                original = deepcopy(arguments)
                self.assertIs(operation(*arguments), True)
                target = (
                    harness.writer.save_annotation_positions,
                    harness.writer.save_annotation_text_properties,
                    harness.writer.save_annotation_styles,
                )[index]
                target.assert_called_once_with(*original)
                self.assertEqual(len(harness.writer.mock_calls), 1)
                self.assertEqual(arguments, original)
                self.assertEqual(harness.executor.calls, 1)
                self.assertEqual(
                    harness.executor.recorder.changes,
                    [
                        (
                            ResourceRef("annotation", "text/7", 41),
                            ChangeOperation.UPDATE,
                            (),
                            "",
                        )
                    ],
                )
                self.assertEqual(harness.tokens.applied, [(DATABASE, {})])
                self.assert_refreshed_once(harness)

    def test_empty_updates_do_not_create_mutations_or_publish(self):
        harness = _Harness()
        for operation in (
            harness.service.save_annotation_positions,
            harness.service.save_annotation_text_properties,
            harness.service.save_annotation_styles,
        ):
            self.assertIs(operation(DATABASE, []), False)
        self.assertEqual(harness.executor.calls, 0)
        self.assertEqual(harness.writer.mock_calls, [])
        self.assertEqual(harness.events.published, [])
        harness.reload.assert_not_called()

    def test_locked_bid_blocks_every_write_before_mutation(self):
        for index in range(5):
            with self.subTest(operation=index):
                harness = _Harness()
                harness.guard.blocks_active_locked_bid_write.return_value = True
                operation, arguments, failure = harness.operations()[index]
                self.assertEqual(operation(*arguments), failure)
                expected = (DATABASE, "41") if index == 4 else (DATABASE,)
                harness.guard.blocks_active_locked_bid_write.assert_called_once_with(
                    *expected
                )
                self.assertEqual(harness.executor.calls, 0)
                self.assertEqual(harness.writer.mock_calls, [])
                self.assertEqual(harness.events.published, [])
                harness.reload.assert_not_called()

    def test_rejected_or_uncertain_mutations_do_not_write_or_announce_success(self):
        for status in MutationOutcomeStatus:
            if status == MutationOutcomeStatus.COMMITTED:
                continue
            for index in range(5):
                with self.subTest(status=status, operation=index):
                    harness = _Harness()
                    harness.executor.status = status
                    operation, arguments, failure = harness.operations()[index]
                    self.assertEqual(operation(*arguments), failure)
                    self.assertEqual(harness.executor.calls, 1)
                    self.assertEqual(harness.executor.recorder.changes, [])
                    self.assertEqual(harness.writer.mock_calls, [])
                    self.assertEqual(harness.tokens.applied, [])
                    self.assertEqual(harness.events.published, [])
                    harness.reload.assert_not_called()

    def test_writer_failure_records_no_changes_and_does_not_refresh(self):
        for index in range(5):
            with self.subTest(operation=index):
                harness = _Harness()
                operation, arguments, failure = harness.operations()[index]
                target = (
                    harness.writer.save_annotation_positions,
                    harness.writer.save_annotation_text_properties,
                    harness.writer.save_annotation_styles,
                    harness.writer.delete_annotations,
                    harness.writer.insert_annotations,
                )[index]
                target.return_value = failure
                self.assertEqual(operation(*arguments), failure)
                self.assertEqual(target.call_count, 1)
                self.assertEqual(harness.executor.recorder.changes, [])
                self.assertEqual(harness.events.published, [])
                harness.reload.assert_not_called()

    def test_insert_records_created_typed_identities_and_one_collection_change(self):
        harness = _Harness()
        specs = _specs()
        remap = PasteRefRemap(namedview_uids={"9": "101"})
        before = deepcopy((specs, remap))
        self.assertEqual(
            harness.service.insert_annotations(DATABASE, "41", specs, remap),
            ["101", "102"],
        )
        harness.writer.insert_annotations.assert_called_once_with(
            DATABASE, "41", specs, ref_remap=remap
        )
        collection = ResourceRef("annotations_collection", "41", 41)
        self.assertEqual(harness.executor.calls, 1)
        self.assertEqual(harness.executor.requests[0].resources, (collection,))
        self.assertEqual(
            harness.executor.recorder.changes,
            [
                (
                    ResourceRef("annotation", "namedview/101", 41),
                    ChangeOperation.CREATE,
                    (),
                    "",
                ),
                (
                    ResourceRef("annotation", "hotlink/102", 41),
                    ChangeOperation.CREATE,
                    (),
                    "",
                ),
                (collection, ChangeOperation.UPDATE, (), ""),
            ],
        )
        self.assertEqual((specs, remap), before)
        self.assert_refreshed_once(harness)

    def test_delete_records_each_typed_identity_in_one_mutation(self):
        harness = _Harness()
        annotations = [("7", "text"), ("7", "rect")]
        self.assertTrue(harness.service.delete_annotations(DATABASE, annotations))
        harness.writer.delete_annotations.assert_called_once_with(DATABASE, annotations)
        resources = (
            ResourceRef("annotation", "text/7", 41),
            ResourceRef("annotation", "rect/7", 41),
        )
        self.assertEqual(harness.executor.calls, 1)
        self.assertEqual(harness.executor.requests[0].resources, resources)
        self.assertEqual(
            harness.executor.recorder.changes,
            [(resource, ChangeOperation.DELETE, (), "") for resource in resources],
        )
        self.assert_refreshed_once(harness)

    def test_write_success_is_independent_of_optional_refresh_success(self):
        for index in range(5):
            for publish in (False, True):
                with self.subTest(operation=index, publish=publish):
                    harness = _Harness()
                    harness.reload.return_value = False
                    operation, arguments, _failure = harness.operations()[index]
                    self.assertEqual(
                        operation(
                            *arguments, publish_database_refreshed_after_write=publish
                        ),
                        ["101", "102"] if index == 4 else True,
                    )
                    self.assertEqual(harness.executor.calls, 1)
                    self.assertEqual(len(harness.writer.mock_calls), 1)
                    self.assertEqual(harness.events.published, [])
                    if publish:
                        harness.reload.assert_called_once_with(DATABASE)
                    else:
                        harness.reload.assert_not_called()

    def test_writer_exception_unwinds_scope_without_recording_or_refresh(self):
        harness = _Harness()
        error = OSError("storage disconnected")
        harness.writer.save_annotation_positions.side_effect = error
        with self.assertRaises(OSError) as raised:
            harness.service.save_annotation_positions(
                DATABASE, [("7", "text", [1.0, 2.0])]
            )
        self.assertIs(raised.exception, error)
        self.assertEqual(
            harness.tokens.scope, [("enter", DATABASE), ("exit", DATABASE)]
        )
        self.assertEqual(harness.executor.recorder.changes, [])
        self.assertEqual(harness.tokens.applied, [])
        self.assertEqual(harness.events.published, [])
        harness.reload.assert_not_called()

    def test_required_mutation_contracts_cannot_be_omitted(self):
        harness = _Harness()
        for name in (
            "bid_write_guard",
            "mutation_executor",
            "session_registry",
            "concurrency_tokens",
            "project_data_service",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                AnnotationWriteService(**(harness.arguments | {name: None}))
        self.assertEqual(harness.executor.calls, 0)
        self.assertEqual(harness.writer.mock_calls, [])

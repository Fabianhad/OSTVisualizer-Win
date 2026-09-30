import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page


class FakeDetachedPlanView:
    def __init__(self, annotations=None):
        self.selection_revision = 0
        self.tool_revision = 0
        self.annotations = {ann.uid: ann for ann in annotations or []}
        self.annotation_place_type = ""
        self.current_page_uid = "p1"
        self.snap_increments = 1.0
        self.intelligent_paste_enabled = True
        self.mouse_ost_position = None
        self.restored_positions = []
        self.restored_text_properties = []
        self.selected_uids = set()
        self.annotation_key_map = {}
        self.activate_calls = []
        self.cancel_place_mode_calls = 0
        self.clipboard_emit_count = 0
        self.intelligent_paste_calls = []
        self.pending_mutation_uids = set()
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()
        self.clipboard_changed = SimpleNamespace(emit=self._emit_clipboard_changed)
        self.selection_enabled = True
        self.editing_enabled = True
        self.inline_edit_enabled = True

    def restore_flushed_positions(self, takeoff_changes, ann_changes):
        self.restored_positions.append((list(takeoff_changes), list(ann_changes)))

    def restore_annotation_text_properties(self, changes):
        self.restored_text_properties.append(list(changes))

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles = list(changes)

    def get_annotation(self, uid):
        return self.annotations.get(uid)

    def get_selected_uids(self):
        return sorted(self.selected_uids)

    def set_geometry_edit_lease_pending(self, uids):
        self.geometry_lease_pending = set(uids)
        self.geometry_lease_granted = set()

    def set_geometry_edit_lease_granted(self, uids):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set(uids)

    def disable_geometry_edit_leasing(self):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()

    def set_selection_enabled(self, enabled):
        self.selection_enabled = bool(enabled)

    def set_editing_enabled(self, enabled):
        self.editing_enabled = bool(enabled)

    def is_text_annotation_inline_edit_active(self):
        return False

    def set_text_annotation_inline_edit_enabled(self, enabled):
        self.inline_edit_enabled = bool(enabled)

    def set_selected_uids(self, uids):
        if self.selected_uids != set(uids):
            self.selection_revision += 1
        self.selected_uids = set(uids)

    def begin_deferred_selection(self):
        self.selection_revision += 1
        return self.selection_revision

    def clear_selection(self):
        self.set_selected_uids(set())

    def set_pending_mutation_uids(self, uids):
        self.pending_mutation_uids = set(uids)

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }

    def activate_annotation_placement(self, annotation_type):
        self.activate_calls.append(annotation_type)
        self.annotation_place_type = annotation_type
        return True

    def cancel_place_mode(self):
        self.cancel_place_mode_calls += 1
        self.annotation_place_type = ""

    def is_text_annotation_inline_edit_active(self):
        return False

    def current_mouse_ost_position(self):
        return self.mouse_ost_position

    def mark_intelligent_paste_drag_pending(self, pasted_uids, source_anchor_ost):
        self.intelligent_paste_calls.append((list(pasted_uids), source_anchor_ost))
        return True

    def _emit_clipboard_changed(self):
        self.clipboard_emit_count += 1


class FakeDetachedLoadPlanView:
    def __init__(
        self,
        *,
        current_page_uid="p1",
        stable=True,
        view_state=(2.5, 40.0, 60.0),
    ):
        self.current_page_uid = current_page_uid
        self._stable = stable
        self._view_state = view_state
        self.load_calls = []
        self.prefetch_calls = []
        self.clear_calls = 0

    @property
    def is_view_state_stable(self):
        return self._stable

    def get_view_state(self):
        return self._view_state

    def load_page(
        self,
        page,
        takeoffs,
        conditions,
        color_map,
        bid_ref=None,
        annotations=None,
        page_area_selections=None,
        hidden_layer_uids=None,
    ):
        page_options = {
            "page": page,
            "takeoffs": takeoffs,
            "conditions": conditions,
            "color_map": color_map,
            "bid_ref": bid_ref,
            "annotations": annotations,
            "page_area_selections": page_area_selections,
            "hidden_layer_uids": hidden_layer_uids,
        }
        self.load_calls.append(page_options)
        return True

    def prefetch_nearby_pages(self, current_page, ordered_pages, bid_ref=None):
        self.prefetch_calls.append((current_page, ordered_pages, bid_ref))

    def clear(self):
        self.clear_calls += 1


class FakeAnnotationWriteService:
    def __init__(self):
        self.insert_calls = []
        self.insert_reload_flags = []
        self.position_calls = []
        self.position_reload_flags = []
        self.text_property_calls = []
        self.text_property_reload_flags = []
        self.style_calls = []
        self.style_reload_flags = []
        self.delete_calls = []
        self.edit_lease_requests = []
        self.ended_edit_leases = []
        self.delete_reload_flags = []
        self.next_uids = ["ann-1"]
        self.next_uid_batches = []

    def insert_annotations(
        self,
        db_path,
        bid_uid,
        specs,
        ref_remap=None,
        publish_database_refreshed_after_write=True,
    ):
        self.insert_calls.append((db_path, bid_uid, specs, ref_remap))
        self.insert_reload_flags.append(publish_database_refreshed_after_write)
        if self.next_uid_batches:
            return list(self.next_uid_batches.pop(0)[: len(specs)])
        return list(self.next_uids[: len(specs)])

    def save_annotation_positions(
        self, db_path, positions, publish_database_refreshed_after_write=True
    ):
        self.position_calls.append((db_path, positions))
        self.position_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def save_annotation_text_properties(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.text_property_calls.append((db_path, updates))
        self.text_property_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def save_annotation_styles(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.style_calls.append((db_path, updates))
        self.style_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def delete_annotations(
        self, db_path, annotation_keys, publish_database_refreshed_after_write=True
    ):
        self.delete_calls.append((db_path, list(annotation_keys)))
        self.delete_reload_flags.append(publish_database_refreshed_after_write)
        return True


class FakeQueuedProjectWriteService:
    def __init__(self):
        self.geometry_calls = []
        self.property_calls = []
        self.paste_calls = []
        self.delete_calls = []
        self.edit_lease_requests = []
        self.ended_edit_leases = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return True

    def queue_plan_geometry(self, *args, **kwargs):
        self.geometry_calls.append((args, kwargs))
        return len(self.geometry_calls)

    def queue_plan_properties(self, *args, **kwargs):
        self.property_calls.append((args, kwargs))
        return len(self.property_calls)

    def queue_plan_items_paste(self, *args, **kwargs):
        self.paste_calls.append((args, kwargs))
        return len(self.paste_calls)

    def queue_plan_items_delete(self, *args, **kwargs):
        self.delete_calls.append((args, kwargs))
        return len(self.delete_calls)

    def request_plan_edit_lease(
        self, database_id, resources, dependencies, callback, **options
    ):
        self.edit_lease_requests.append(
            (database_id, resources, dependencies, options, callback)
        )

    def end_plan_edit_lease(self, handle):
        self.ended_edit_leases.append(handle)


class FakeAnnotationProjectData:
    def __init__(self, annotations=None):
        self.annotations = list(annotations or [])
        self.named_view_updates = []
        self.pages = {
            "p1": Page(uid="p1", name="Page 1", scale_factor1=1, scale_factor2=1)
        }

    def get_page(self, uid):
        return self.pages.get(uid)

    def get_current_bid_ref(self):
        return BidRef("bid.mdb", "7")

    def get_annotation_layer_uid(self):
        return "detached-annotation-layer"

    def get_bid_annotation_layer_uid(self, _bid_ref):
        return "detached-annotation-layer"

    def get_all_annotations(self):
        return list(self.annotations)

    def add_annotations(self, annotations):
        self.annotations.extend(annotations)

    def remove_annotations_by_keys(self, annotation_keys):
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        page_uids = []
        retained = []
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in wanted:
                if annotation.page_uid not in page_uids:
                    page_uids.append(annotation.page_uid)
            else:
                retained.append(annotation)
        self.annotations = retained
        return page_uids

    def get_page_uids_for_annotation_keys(self, annotation_keys):
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        page_uids = []
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in wanted and annotation.page_uid not in page_uids:
                page_uids.append(annotation.page_uid)
        return page_uids

    def update_annotation_positions(self, positions):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _position in positions
        )
        by_key = {
            (str(uid), str(annotation_type)): list(position)
            for uid, annotation_type, position in positions
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in by_key:
                annotation.position = list(by_key[key])
        return page_uids

    def update_annotation_text_properties(self, updates):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _properties in updates
        )
        by_key = {
            (str(uid), str(annotation_type)): dict(properties)
            for uid, annotation_type, properties in updates
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in by_key:
                annotation.properties.update(by_key[key])
        return page_uids

    def update_annotation_styles(self, updates):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _style in updates
        )
        by_key = {
            (str(uid), str(annotation_type)): dict(style)
            for uid, annotation_type, style in updates
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            style = by_key.get(key)
            if style is None:
                continue
            if "Color" in style:
                annotation.color = str(style["Color"])
            if "Width" in style:
                annotation.width = float(style["Width"])
        return page_uids

    def update_named_view_names(self, updates):
        self.named_view_updates.extend(list(updates))


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **event_payload):
        self.events.append((event_type, event_payload))


class FakeUndoService:
    def __init__(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )

        self.history = UndoRedoService()
        self.history.set_active_bid(BidRef("bid.mdb", "7"))
        self.pushes = []
        self.async_pushes = []
        self.forward_mutations = []

    def push_local(self, undo, redo, *, annotation_targets=()):
        self.pushes.append((undo, redo))
        self.history.push_local(undo, redo, annotation_targets=annotation_targets)

    def push(self, undo, redo):
        self.async_pushes.append((undo, redo))

    def push_for_bid(self, bid_ref, undo, redo, *, annotation_targets=()):
        self.push(undo, redo)
        self.history.push_for_bid(
            bid_ref, undo, redo, annotation_targets=annotation_targets
        )

    def is_forward_mutation_current(self, token):
        return any(item[0] is token for item in self.forward_mutations)

    def suspend_deleted_annotations(self, bid_ref, deleted):
        return self.history.suspend_deleted_annotations(bid_ref, deleted)

    def rebind_restored_annotations(self, bid_ref, restored, targets):
        self.history.rebind_restored_annotations(bid_ref, restored, targets)

    def notify_annotation_deletion(self, bid_ref, identities):
        self.history.notify_annotation_deletion(bid_ref, identities)

    def begin_forward_mutation(self, bid_ref):
        token = object()
        self.forward_mutations.append((token, bid_ref))
        return token

    def finish_forward_mutation(self, token):
        self.forward_mutations = [
            item for item in self.forward_mutations if item[0] is not token
        ]

    def bind_latest_history_to_forward_mutation(self, _token):
        pass

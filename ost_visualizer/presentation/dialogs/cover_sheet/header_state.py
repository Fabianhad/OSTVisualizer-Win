from PySide6 import QtCore
from ...utils.qt_state import decode_byte_array, encode_byte_array


def load_cover_sheet_plan_header_state(workspace_state_model) -> QtCore.QByteArray:
    return decode_byte_array(
        workspace_state_model.state.cover_sheet.plan_header_state_b64
    )


def save_cover_sheet_plan_header_state(
    workspace_state_model, state: QtCore.QByteArray
) -> None:
    workspace_state = workspace_state_model.state
    workspace_state.cover_sheet.plan_header_state_b64 = encode_byte_array(state)
    workspace_state_model.update_state(workspace_state)

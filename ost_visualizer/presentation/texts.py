# Application windows
MAIN_WINDOW_TITLE = "OST Visualizer"
MESH_WINDOW_TITLE = "3D View"
ANNOTATION_WINDOW_TITLE = "Annotation Window"
VIEW_WINDOW_TITLE = "View Window"
ANNOTATION_VIEW_WINDOW_ACTION_LABEL = "Annotation and View Window"
DETACH_3D_VIEW_TOOLTIP = "Detach 3D view"
# Toolbars
SHOW_TOOLBARS_MENU_TITLE = "Show Toolbars"
MAIN_TOOLBAR_LABEL = "Main"
VIEW_TOOLBAR_LABEL = "View"
PLAN_TOOLS_TOOLBAR_LABEL = "Plan Tools"
OVERLAY_TOOLS_TOOLBAR_LABEL = "Overlay Tools"
# 3D view
VIEWER_2D_LABEL = "2D View"
VIEWER_3D_LABEL = "3D View"
VIEWER_2D_TOOLTIP = "2D plan view"
VIEWER_3D_TOOLTIP = "3D mesh view"
SECTION_CUT_NORTH_SOUTH_LABEL = "Cut north-south"
SECTION_CUT_EAST_WEST_LABEL = "Cut east-west"
SECTION_CUT_NORTH_SOUTH_TOOLTIP = (
    "Cut the 3D view with a plane across the plan's north-south axis; "
    "drag to the right end to turn it off."
)
SECTION_CUT_EAST_WEST_TOOLTIP = (
    "Cut the 3D view with a plane across the plan's east-west axis; "
    "drag to the right end to turn it off."
)
SECTION_CUT_OFF_TEXT = "off"
EDGES_TOGGLE_LABEL = "Edges"
EDGES_TOGGLE_TOOLTIP = "Draw object edges in the 3D view and in HTML exports."
TOWER_CRANE_TOGGLE_LABEL = "Tower crane"
TOWER_CRANE_TOGGLE_TOOLTIP = (
    "Show the tower crane on count takeoffs whose condition notes contain "
    '"[crane]". The crane is visual only; the footing counts as usual.'
)
# Plan view tools and navigation
ACTION_PREVIOUS_PAGE_LABEL = "Previous Page"
ACTION_NEXT_PAGE_LABEL = "Next Page"
ACTION_PREVIOUS_PAGE_TOOLTIP = "Previous page"
ACTION_NEXT_PAGE_TOOLTIP = "Next page"
ACTION_SELECT_LABEL = "Select"
ACTION_PLACE_LABEL = "Place"
ACTION_ORBIT_LABEL = "Orbit"
ACTION_PAN_LABEL = "Pan"
ACTION_DIMENSION_LABEL = "Dimension"
ACTION_HOTLINK_LABEL = "Hotlink"
ACTION_NAMED_VIEW_LABEL = "Named View"
ACTION_TEXT_ANNOTATION_LABEL = "Text"
ACTION_HIGHLIGHT_ANNOTATION_LABEL = "Highlight"
ACTION_ARROW_ANNOTATION_LABEL = "Arrow"
ACTION_LINE_ANNOTATION_LABEL = "Line"
ACTION_RECTANGLE_ANNOTATION_LABEL = "Rectangle"
ACTION_OVAL_ANNOTATION_LABEL = "Oval"
ACTION_POLYGON_ANNOTATION_LABEL = "Polygon"
ACTION_CLOUD_ANNOTATION_LABEL = "Cloud"
ACTION_INK_ANNOTATION_LABEL = "Ink"
ACTION_ZOOM_LABEL = "Zoom"
ACTION_RESET_VIEW_LABEL = "Reset View"
ACTION_ZOOM_IN_LABEL = "Zoom In"
ACTION_ZOOM_OUT_LABEL = "Zoom Out"
ACTION_MOVE_OVERLAY_IMAGE_LABEL = "Move Overlay Image"
ACTION_SELECT_OVERLAY_IMAGE_LABEL = "Select Overlay Image..."
ACTION_SHOW_OVERLAY_IMAGE_LABEL = "Show Overlay Image"
ACTION_SHOW_ORIGINAL_IMAGE_LABEL = "Show Original Image"
ACTION_SELECT_TOOLTIP = "Select"
ACTION_PLACE_TOOLTIP = "Takeoff"
ACTION_ORBIT_TOOLTIP = "Orbit"
ACTION_PAN_TOOLTIP = "Pan"
ACTION_DIMENSION_TOOLTIP = "Dimension"
ACTION_HOTLINK_TOOLTIP = "Hotlink"
ACTION_NAMED_VIEW_TOOLTIP = "Named view"
ACTION_TEXT_ANNOTATION_TOOLTIP = "Text"
ACTION_HIGHLIGHT_ANNOTATION_TOOLTIP = "Highlight"
ACTION_ARROW_ANNOTATION_TOOLTIP = "Arrow"
ACTION_LINE_ANNOTATION_TOOLTIP = "Line"
ACTION_RECTANGLE_ANNOTATION_TOOLTIP = "Rectangle"
ACTION_OVAL_ANNOTATION_TOOLTIP = "Oval"
ACTION_POLYGON_ANNOTATION_TOOLTIP = "Polygon"
ACTION_CLOUD_ANNOTATION_TOOLTIP = "Cloud"
ACTION_INK_ANNOTATION_TOOLTIP = "Ink"
ACTION_ZOOM_TOOLTIP = "Zoom"
ACTION_RESET_VIEW_TOOLTIP = "Reset view"
ACTION_ZOOM_IN_TOOLTIP = "Zoom in"
ACTION_ZOOM_OUT_TOOLTIP = "Zoom out"
ACTION_MOVE_OVERLAY_IMAGE_TOOLTIP = "Move overlay image"
NAMED_VIEWS_TOOLTIP = "Named views"
SCALE_LABEL = "Scale"
SCALE_TOOLTIP = "Scale"
VIEW_LABEL = "View"
# Conditions
NOTES_TAG_WARNING_TITLE = "Notes Tag"
# Options dialog
OPTIONS_DIALOG_TITLE = "Options"
OPTIONS_TAB_OPTIONS = "Options"
OPTIONS_TAB_TAKEOFF_TOOLBAR = "Takeoff Toolbar"
OPTIONS_TAB_FONTS_COLORS = "Fonts/Colors"
OPTIONS_TAB_EXPORT = "Export"
OPTIONS_TAB_MCP_SETUP = "MCP Setup"
OPTIONS_GROUP_PREFERENCES = "Preferences"
OPTIONS_GROUP_SNAP_ANGLE = "Snap Settings"
OPTIONS_GROUP_CONFIRMATIONS = "Confirmations"
OPTIONS_GROUP_AUTO_ZOOM = "Default Auto-Zoom Level"
OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS = "PDF Annotation Captions"
OPTIONS_GROUP_ELEVATION_CALLOUTS = "Elevation Callouts"
OPTIONS_GROUP_CONDITION_NAMES = "Condition Names"
OPTIONS_DEFERRED_TOOLTIP = "This option is planned but is not available yet."
OPTIONS_LABEL_RESET_ALL_SETTINGS = "Reset All Settings"
OPTIONS_LABEL_ENABLE_PDF_ANNOTATION_CAPTIONS = "Enable PDF annotation captions"
OPTIONS_LABEL_INCLUDE_HTML_ELEVATION_CALLOUTS = (
    "Include elevation callouts in HTML export"
)
OPTIONS_LABEL_INCLUDE_PDF_ELEVATION_CALLOUTS = (
    "Include elevation callouts in PDF export"
)
OPTIONS_LABEL_OST_OSP_DROP_ELEVATION = (
    "Drop elevations from condition names in OST/OSP exports"
)
OPTIONS_LABEL_CSV_DROP_ELEVATION = (
    "Drop elevations from condition names in Summary CSV exports"
)
OPTIONS_WARNING_TITLE_DROP_ELEVATION = "Drop Elevations from Condition Names"
OPTIONS_WARNING_OST_OSP_DROP_ELEVATION = (
    "Exported OST and OSP files will lose all elevation data: every condition "
    "name is written without its elevation. Importing such a file back into a "
    "project leaves every element without its elevation.\n\n"
    "This option is intended for On-Screen Takeoff users who expect condition "
    "names without elevations. 3D (OBJ, DXF, FBX), HTML and PDF exports are "
    "unchanged.\n\n"
    "Turn this option on?"
)
OPTIONS_WARNING_CSV_DROP_ELEVATION = (
    "Summary CSV exports will write condition names without their elevation. "
    "Use this only for templates that expect CSV data without elevations.\n\n"
    "OST/OSP exports, 3D (OBJ, DXF, FBX), HTML and PDF exports are unchanged by "
    "this option.\n\n"
    "Turn this option on?"
)
OPTIONS_LABEL_ELEVATION_CALLOUT_CONDITION = "Condition"
OPTIONS_LABEL_ELEVATION_CALLOUT_TOP = "Top elevation"
OPTIONS_LABEL_ELEVATION_CALLOUT_BOTTOM = "Bottom elevation"
OPTIONS_LABEL_ELEVATION_CALLOUT_CUBIC_YARDS = "Cubic yards"
OPTIONS_LABEL_HTML_ELEVATION_CALLOUT_COLOR = "HTML text color"
OPTIONS_LABEL_PDF_ELEVATION_CALLOUT_COLOR = "PDF text color"
OPTIONS_LABEL_SHOW_TOOLBAR_TEXT = "Show text on selected toolbars"
OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_SYNC = "Sync 2D/3D display modes"
OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_3D = "3D display mode:"
OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_2D = "2D display mode:"
OPTIONS_LABEL_DISPLAY_MODE_TRANSPARENT = "Transparent"
OPTIONS_LABEL_DISPLAY_MODE_SOLID = "Solid"
OPTIONS_LABEL_DISPLAY_MODE_ORIGINAL = "Original"
OPTIONS_LABEL_GRAYSCALE = "Grayscale"
OPTIONS_LABEL_EDGES = "Edges"
OPTIONS_TOOLTIP_EDGES = "Draw object edges in the 3D view and in HTML exports."
OPTIONS_LABEL_TOWER_CRANE = "Tower crane"
OPTIONS_TOOLTIP_TOWER_CRANE = (
    "Show the tower crane on count takeoffs whose condition notes contain "
    '"[crane]" in the 3D view and in HTML exports.'
)
OPTIONS_LABEL_ROPING_METHOD = "Roping method for object selection:"
OPTIONS_LABEL_ROPING_TOUCHING = "Touching"
OPTIONS_LABEL_ROPING_INCLUSIVE = "Inclusive"
OPTIONS_LABEL_HOTLINK_TARGET = "Open hotlinks in:"
OPTIONS_LABEL_HOTLINK_VIEW = "View"
OPTIONS_LABEL_HOTLINK_ANNOTATION = "Annotation"
OPTIONS_LABEL_HOTLINK_MAIN = "Main"
OPTIONS_LABEL_PAGE_INDEX = "Display page index with sheet name"
OPTIONS_LABEL_SHEET_NUMBER = "Display sheet number with sheet name"
OPTIONS_LABEL_DISABLE_HIGH_RESOLUTION_IMAGES = "Disable high resolution images"
OPTIONS_LABEL_INTELLIGENT_PASTE = "Enable intelligent paste"
OPTIONS_LABEL_ADVANCED_MOUSE_CONTROLS = "Enable advanced mouse controls"
OPTIONS_LABEL_FULL_WINDOW_CROSSHAIRS = "Use full-window crosshairs for mouse takeoff"
OPTIONS_LABEL_CROSSHAIR_COLOR = "Crosshair color:"
OPTIONS_LABEL_CROSSHAIR_LINE_THICKNESS = "Crosshair line thickness:"
OPTIONS_LABEL_ALLOW_ADD_PAGE_FROM_TAKEOFF = "Allow adding new page from Takeoff tab"
OPTIONS_LABEL_AUTO_ZOOM_OFF = "Set to zero to turn off"
OPTIONS_LABEL_SNAP_TO_GRID = "Snap to grid"
OPTIONS_LABEL_SNAP_TO_PDF_LINES = "Snap to PDF lines"
OPTIONS_LABEL_SNAP_TO_TAKEOFFS = "Snap to takeoffs"
OPTIONS_LABEL_SNAP_TO_RIGHT_ANGLE = "Snap to right angle"
OPTIONS_LABEL_SNAP_THRESHOLD_PX = "Threshold"
OPTIONS_DEFERRED_PREFERENCE_CHECKS = ("Enable Active Area filter in Print Preview",)
OPTIONS_MOUSE_SNAP_ANGLE_LABELS = (
    "Mouse unpressed angle:",
    "Mouse pressed angle:",
)
OPTIONS_DEFERRED_CONFIRMATION_CHECKS = ("Turn on all confirmation dialogs",)
# Dialogs: dialogs.about_dialog
ABOUT_DIALOG_TITLE_ABOUT_OST_VISUALIZER = "About OST Visualizer"
ABOUT_DIALOG_LABEL_LEARN_MORE_ABOUT_OST_VISUALIZER = "Learn more about OST Visualizer"
ABOUT_DIALOG_BUTTON_CLOSE = "Close"
# Dialogs: dialogs.adjust_images_dialog
ADJUST_IMAGES_DIALOG_TITLE_ADJUST_IMAGES = "Adjust Images"
ADJUST_IMAGES_DIALOG_OPTION_APPLY_TO_ALL_PAGES = "Apply to all pages"
ADJUST_IMAGES_DIALOG_GROUP_ORIENTATION = "Orientation"
ADJUST_IMAGES_DIALOG_OPTION_FLIP_HORIZONTALLY = "Flip horizontally"
ADJUST_IMAGES_DIALOG_OPTION_FLIP_VERTICALLY = "Flip vertically"
ADJUST_IMAGES_DIALOG_GROUP_VISUALIZATION = "Visualization"
ADJUST_IMAGES_DIALOG_OPTION_INVERT = "Invert"
ADJUST_IMAGES_DIALOG_OPTION_BITONAL = "Bitonal"
ADJUST_IMAGES_DIALOG_BUTTON_OK = "OK"
ADJUST_IMAGES_DIALOG_BUTTON_CANCEL = "Cancel"
ADJUST_IMAGES_DIALOG_BUTTON_APPLY = "Apply"
ADJUST_IMAGES_DIALOG_TITLE_SAVE_FAILED = "Save Failed"
ADJUST_IMAGES_DIALOG_MESSAGE_FAILED_TO_SAVE_IMAGE_ADJUSTMENTS = (
    "Failed to save image adjustments."
)
# Dialogs: dialogs.ai_changeset_review_dialog
AI_CHANGESET_REVIEW_DIALOG_PLACEHOLDER_VALUE = "Value"
AI_CHANGESET_REVIEW_DIALOG_SUMMARY_SET_PAGE_SCALE = (
    "Set the page scale to {sf1:g} : {sf2:g} (was {previous_sf1:g} : {previous_sf2:g})."
)
AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_ONE_CONDITION = (
    "Add {takeoff_count} takeoff in {condition_count} new condition."
)
AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_ONE_CONDITION = (
    "Add {takeoff_count} takeoffs in {condition_count} new condition."
)
AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_CONDITIONS = (
    "Add {takeoff_count} takeoff in {condition_count} new conditions."
)
AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_CONDITIONS = (
    "Add {takeoff_count} takeoffs in {condition_count} new conditions."
)
AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_VALUE_IN_INCHES = (
    "Enter a valid value in inches."
)
AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_NUMBER = "Enter a valid number."
# Dialogs: dialogs.areas_dialog
AREAS_DIALOG_HEADER_AREA_NAME = "Area Name"
AREAS_DIALOG_BUTTON_NEW = "New"
AREAS_DIALOG_BUTTON_DELETE = "Delete"
AREAS_DIALOG_BUTTON_INDENT = "Indent >>"
AREAS_DIALOG_BUTTON_OUTDENT = "<< Outdent"
AREAS_DIALOG_BUTTON_MOVE_UP = "Move Up"
AREAS_DIALOG_BUTTON_MOVE_DOWN = "Move Down"
AREAS_DIALOG_BUTTON_OK = "OK"
AREAS_DIALOG_TITLE_DUPLICATE_AREA = "Duplicate Area"
AREAS_DIALOG_MESSAGE_AREA_ALREADY_EXISTS = "Area {name} already exists."
AREAS_DIALOG_TITLE_DELETE_BID_AREA = "Delete Bid Area"
AREAS_DIALOG_BUTTON_SELECT = "Select"
AREAS_DIALOG_BUTTON_CANCEL = "Cancel"
AREAS_DIALOG_MESSAGE_FAILED_TO_VALIDATE_AREA_USAGE = "Failed to validate area usage."
AREAS_DIALOG_TITLE_BID_AREAS = "Bid Areas"
# Dialogs: dialogs.condition_types_dialog
CONDITION_TYPES_DIALOG_TITLE_CONDITION_TYPES = "Condition Types"
CONDITION_TYPES_DIALOG_HEADER_CONDITION_TYPE = "Condition Type"
CONDITION_TYPES_DIALOG_TITLE_DELETE_CONDITION_TYPE = "Delete Condition Type"
CONDITION_TYPES_DIALOG_LABEL_FIND = "Find:"
CONDITION_TYPES_DIALOG_TITLE_DUPLICATE_CONDITION_TYPE = "Duplicate Condition Type"
CONDITION_TYPES_DIALOG_MESSAGE_CONDITION_TYPE_ALREADY_EXISTS = (
    "Condition type {name} already exists."
)
CONDITION_TYPES_DIALOG_MESSAGE_FAILED_TO_RENAME_CONDITION_TYPE = (
    "Failed to rename condition type."
)
CONDITION_TYPES_DIALOG_MESSAGE_FAILED_TO_CREATE_CONDITION_TYPE = (
    "Failed to create condition type."
)
CONDITION_TYPES_DIALOG_MESSAGE_FAILED_TO_DELETE_CONDITION_TYPE = (
    "Failed to delete condition type."
)
CONDITION_TYPES_DIALOG_MESSAGE_FAILED_TO_VALIDATE_CONDITION_TYPE_DELETION = (
    "Failed to validate condition type deletion."
)
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_TAB_PLAN_ORGANIZER = "Plan Organizer"
COVER_SHEET_DIALOG_TAB_PREFERENCES = "Preferences"
COVER_SHEET_DIALOG_LABEL_NOTES = "Notes:"
COVER_SHEET_DIALOG_BUTTON_OK = "OK"
COVER_SHEET_DIALOG_BUTTON_CANCEL = "Cancel"
COVER_SHEET_DIALOG_BUTTON_AREAS = "Areas"
COVER_SHEET_DIALOG_HEADER_SHEET_NO = "Sheet No."
COVER_SHEET_DIALOG_HEADER_SHEET_NAME = "Sheet Name"
COVER_SHEET_DIALOG_HEADER_PAGE_SIZE = "Page Size"
COVER_SHEET_DIALOG_HEADER_SCALE = "Scale"
COVER_SHEET_DIALOG_HEADER_IMAGE_FILE = "Image File"
COVER_SHEET_DIALOG_HEADER_OVERLAY_IMAGE = "Overlay Image"
COVER_SHEET_DIALOG_HEADER_INDEX = "Index"
COVER_SHEET_DIALOG_HEADER_SHOW = "Show"
COVER_SHEET_DIALOG_GROUP_GENERAL = "General"
COVER_SHEET_DIALOG_OPTION_INCHES = "Inches"
COVER_SHEET_DIALOG_OPTION_MILLIMETERS = "Millimeters"
COVER_SHEET_DIALOG_LABEL_BASE_MEASUREMENT = "Base measurement:"
COVER_SHEET_DIALOG_LABEL_INCHES = "inches"
COVER_SHEET_DIALOG_LABEL_TAKEOFF_IN_INCREMENTS_OF = "Takeoff in increments of:"
COVER_SHEET_DIALOG_GROUP_NEW_PAGE_DEFAULTS = "New Page Defaults"
COVER_SHEET_DIALOG_LABEL_PAGE_SIZE = "Page size:"
COVER_SHEET_DIALOG_CHOICE_ARCHITECTURAL = "Architectural"
COVER_SHEET_DIALOG_CHOICE_CIVIL = "Civil"
COVER_SHEET_DIALOG_CHOICE_METRIC = "Metric"
COVER_SHEET_DIALOG_LABEL_SCALE_STYLE = "Scale style:"
COVER_SHEET_DIALOG_LABEL_SCALE = "Scale:"
COVER_SHEET_DIALOG_TOOLTIP_WAS_NOT_FOUND = "{label} was not found:\n{path}"
COVER_SHEET_DIALOG_TITLE_SELECT_IMAGE_FILES = "Select Image Files"
COVER_SHEET_DIALOG_LABEL_MILLIMETERS = "millimeters"
COVER_SHEET_DIALOG_TITLE_SELECT_IMAGE = "Select Image"
COVER_SHEET_DIALOG_TITLE_COVER_SHEET = "Cover Sheet"
COVER_SHEET_DIALOG_TITLE_REFRESH_ERROR = "Refresh Error"
COVER_SHEET_DIALOG_MESSAGE_THE_BID_AREA_CHANGES_WERE_SAVED = (
    "The bid area changes were saved, but the area list could not be refreshed. "
    "Reopen the database to see the latest bid areas."
)
COVER_SHEET_DIALOG_TITLE_DELETE_VERIFICATION = "Delete Verification"
COVER_SHEET_DIALOG_MESSAGE_CANNOT_DELETE_BECAUSE_IT_IS_NOT = (
    "Cannot delete {folder_name} because it is not empty.\n\nPlease remove all pages from "
    "a folder before attempting to delete it."
)
COVER_SHEET_DIALOG_MESSAGE_THE_COVER_SHEET_COULD_NOT_BE = (
    "The cover sheet could not be saved. Your changes are still in this "
    "dialog.\n\n{exc}"
)
COVER_SHEET_DIALOG_TITLE_BID_AREAS_UNAVAILABLE = "Bid Areas Unavailable"
COVER_SHEET_DIALOG_MESSAGE_THE_BID_AREAS_COULD_NOT_BE = (
    "The bid areas could not be loaded. Close and reopen the database, then try "
    "again."
)
# Dialogs: dialogs.create_database_dialog
CREATE_DATABASE_DIALOG_TITLE_CREATE_A_DATABASE_FOR_ME = "Create a Database for Me"
CREATE_DATABASE_DIALOG_LABEL_CLICK_HERE_IF_YOU_WOULD_LIKE = (
    "Click here if you would like OST Visualizer to create a database for you.\nIt "
    "will be stored in the default location."
)
CREATE_DATABASE_DIALOG_BUTTON_CREATE_A_DATABASE_FOR_ME = "Create a Database for Me"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_TITLE_EDIT_CONDITION_PROPERTIES = "Edit Condition Properties"
EDIT_CONDITION_DIALOG_TAB_GENERAL = "General"
EDIT_CONDITION_DIALOG_TAB_ADVANCED = "Advanced"
EDIT_CONDITION_DIALOG_BUTTON_TOP = "Top"
EDIT_CONDITION_DIALOG_BUTTON_BOTTOM = "Bottom"
EDIT_CONDITION_DIALOG_BUTTON_PREVIOUS = "Previous"
EDIT_CONDITION_DIALOG_BUTTON_NEXT = "Next"
EDIT_CONDITION_DIALOG_BUTTON_OK = "OK"
EDIT_CONDITION_DIALOG_BUTTON_CANCEL = "Cancel"
EDIT_CONDITION_DIALOG_BUTTON_APPLY = "Apply"
EDIT_CONDITION_DIALOG_GROUP_DIMENSIONS = "Dimensions"
EDIT_CONDITION_DIALOG_GROUP_APPEARANCE = "Appearance"
EDIT_CONDITION_DIALOG_GROUP_RESULTS = "Results"
EDIT_CONDITION_DIALOG_GROUP_NOTES = "Notes"
EDIT_CONDITION_DIALOG_CHOICE_UNKNOWN = "Unknown ({condition_type})"
EDIT_CONDITION_DIALOG_TITLE_CONDITION_TYPES = "Condition Types"
EDIT_CONDITION_DIALOG_MESSAGE_FAILED_TO_CREATE_CONDITION_TYPE = (
    "Failed to create condition type."
)
EDIT_CONDITION_DIALOG_TITLE_LAYER_NOT_FOUND = "Layer Not Found"
EDIT_CONDITION_DIALOG_MESSAGE_LAYER_WAS_NOT_FOUND = (
    'Layer "{layer_name}" was not found.'
)
EDIT_CONDITION_DIALOG_TITLE_UNSAVED_CHANGES = "Unsaved Changes"
EDIT_CONDITION_DIALOG_MESSAGE_DO_YOU_WANT_TO_SAVE_YOUR = (
    "Do you want to save your changes?"
)
EDIT_CONDITION_DIALOG_LABEL_THICKNESS = "Thickness"
EDIT_CONDITION_DIALOG_LABEL_HEIGHT = "Height"
EDIT_CONDITION_DIALOG_LABEL_WIDTH = "Width"
EDIT_CONDITION_DIALOG_CHOICE_NONE = "(none)"
EDIT_CONDITION_DIALOG_GROUP_PROPERTIES = "Properties"
EDIT_CONDITION_DIALOG_OPTION_DISPLAY_NAME = "Display name"
EDIT_CONDITION_DIALOG_TITLE_AMBIGUOUS_CONDITION_TYPE = "Ambiguous Condition Type"
EDIT_CONDITION_DIALOG_MESSAGE_MATCHES_MORE_THAN_ONE_CONDITION_TYPE = (
    '"{type_name}" matches more than one condition type. Select the intended item '
    "from the list."
)
EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE = "Invalid Value"
EDIT_CONDITION_DIALOG_MESSAGE_IS_NOT_A_VALID_DIMENSION_FOR = (
    '"{entered_value}" is not a valid dimension for {label}.'
)
EDIT_CONDITION_DIALOG_TITLE_VALIDATION_ERROR = "Validation Error"
EDIT_CONDITION_DIALOG_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY = (
    "Condition name cannot be empty."
)
EDIT_CONDITION_DIALOG_MESSAGE_CONDITION_NUMBER_MUST_BE_A_POSITIVE = (
    "Condition number must be a positive whole number."
)
EDIT_CONDITION_DIALOG_MESSAGE_CONDITION_NUMBER_MUST_BE_BETWEEN_1 = (
    "Condition number must be between 1 and {max_condition_number}."
)
EDIT_CONDITION_DIALOG_TITLE_SAVE_FAILED = "Save Failed"
EDIT_CONDITION_DIALOG_GROUP_MEASUREMENT = "Measurement"
EDIT_CONDITION_DIALOG_OPTION_ROUND_QUANTITY = "Round quantity"
EDIT_CONDITION_DIALOG_OPTION_DROP_RUN = "Drop/Run"
EDIT_CONDITION_DIALOG_OPTION_TRIM = "Trim"
EDIT_CONDITION_DIALOG_OPTION_SET_AS_CURVED_SEGMENT = "Set as curved segment"
EDIT_CONDITION_DIALOG_OPTION_GRID = "Grid"
EDIT_CONDITION_DIALOG_OPTION_DISPLAY_PATTERN_WHILE_DRAWING = (
    "Display pattern while drawing"
)
EDIT_CONDITION_DIALOG_OPTION_DISPLAY_DIMENSION = "Display dimension"
EDIT_CONDITION_DIALOG_MESSAGE_IS_NOT_A_VALID_ELEVATION = (
    '"{elev_value}" is not a valid elevation. {hint}'
)
EDIT_CONDITION_DIALOG_LABEL_X = "x"
EDIT_CONDITION_DIALOG_MESSAGE_IS_NOT_A_VALID_NUMBER_FOR = (
    '"{ds_text}" is not a valid number for Display Size.'
)
EDIT_CONDITION_DIALOG_MESSAGE_DISPLAY_SIZE_MUST_BE_BETWEEN_10 = (
    "Display Size must be between 10% and 500%."
)
EDIT_CONDITION_DIALOG_MESSAGE_RISE_MUST_BE_A_FINITE_NUMBER = (
    "Rise must be a finite number."
)
EDIT_CONDITION_DIALOG_MESSAGE_RUN_MUST_BE_A_FINITE_NUMBER = (
    "Run must be a finite number."
)
EDIT_CONDITION_DIALOG_MESSAGE_RISE_MUST_BE_A_NUMBER = "Rise must be a number."
EDIT_CONDITION_DIALOG_MESSAGE_RUN_MUST_BE_A_NUMBER = "Run must be a number."
# Dialogs: dialogs.employee_detail_dialog
EMPLOYEE_DETAIL_DIALOG_TITLE_EMPLOYEE_DETAIL = "Employee Detail"
EMPLOYEE_DETAIL_DIALOG_BUTTON_OK = "OK"
EMPLOYEE_DETAIL_DIALOG_BUTTON_CANCEL = "Cancel"
EMPLOYEE_DETAIL_DIALOG_BUTTON_PREVIOUS = "Previous"
EMPLOYEE_DETAIL_DIALOG_BUTTON_NEXT = "Next"
# Dialogs: dialogs.employees_dialog
EMPLOYEES_DIALOG_TITLE_EMPLOYEES = "Employees"
EMPLOYEES_DIALOG_HEADER_EMP_NO = "Emp. No."
EMPLOYEES_DIALOG_HEADER_NAME = "Name"
EMPLOYEES_DIALOG_HEADER_HOME_PHONE = "Home Phone"
EMPLOYEES_DIALOG_HEADER_MOBILE_PHONE = "Mobile Phone"
EMPLOYEES_DIALOG_BUTTON_NEW = "New"
EMPLOYEES_DIALOG_BUTTON_CHANGE = "Change"
EMPLOYEES_DIALOG_BUTTON_DELETE = "Delete"
EMPLOYEES_DIALOG_TITLE_DELETE_EMPLOYEE = "Delete Employee"
EMPLOYEES_DIALOG_BUTTON_CANCEL = "Cancel"
EMPLOYEES_DIALOG_MESSAGE_FAILED_TO_CREATE_EMPLOYEE = "Failed to create employee."
EMPLOYEES_DIALOG_MESSAGE_FAILED_TO_VALIDATE_USAGE = "Failed to validate usage."
EMPLOYEES_DIALOG_MESSAGE_THESE_RECORDS_CHANGED_WHILE_SAVING_REVIEW = (
    "These records changed while saving. Review the current values and try again."
)
# Dialogs: dialogs.job_statuses_dialog
JOB_STATUSES_DIALOG_HEADER_LOCK_PROJECT = "Lock Project"
JOB_STATUSES_DIALOG_HEADER_DESCRIPTION = "Description"
JOB_STATUSES_DIALOG_BUTTON_MOVE_UP = "Move Up"
JOB_STATUSES_DIALOG_BUTTON_MOVE_DOWN = "Move Down"
# Dialogs: dialogs.layers_dialog
LAYERS_DIALOG_TITLE_LAYERS = "Layers"
LAYERS_DIALOG_HEADER_SHOW = "Show"
LAYERS_DIALOG_HEADER_LAYER = "Layer"
LAYERS_DIALOG_TITLE_DELETE_LAYER = "Delete Layer"
LAYERS_DIALOG_TITLE_DUPLICATE_LAYER = "Duplicate Layer"
LAYERS_DIALOG_MESSAGE_LAYER_ALREADY_EXISTS = "Layer {name} already exists."
LAYERS_DIALOG_TITLE_RENAME_LAYER = "Rename Layer"
LAYERS_DIALOG_TITLE_NEW_LAYER = "New Layer"
LAYERS_DIALOG_MESSAGE_FAILED_TO_CREATE_LAYER = "Failed to create layer."
LAYERS_DIALOG_MESSAGE_FAILED_TO_DELETE_LAYER = "Failed to delete layer."
LAYERS_DIALOG_TITLE_LAYER_VISIBILITY = "Layer Visibility"
LAYERS_DIALOG_MESSAGE_LAYER_IS_NO_LONGER_AVAILABLE = "Layer is no longer available."
LAYERS_DIALOG_TITLE_MOVE_LAYER = "Move Layer"
LAYERS_DIALOG_TITLE_LAYER_UPDATE = "Layer Update"
LAYERS_DIALOG_MESSAGE_FAILED_TO_VALIDATE_LAYER_USAGE = "Failed to validate layer usage."
# Dialogs: dialogs.license_dialog
LICENSE_DIALOG_TITLE_LICENSE_AUTHORIZATION = "License Authorization"
LICENSE_DIALOG_LABEL_LICENSE_OVERVIEW = "License overview"
LICENSE_DIALOG_LABEL_STATUS_UNKNOWN = "Status: Unknown"
LICENSE_DIALOG_LABEL_EXPIRES_N_A = "Expires: N/A"
LICENSE_DIALOG_LABEL_LICENSE_KEY = "License key:"
LICENSE_DIALOG_BUTTON_ACTIVATE = "Activate"
LICENSE_DIALOG_BUTTON_CLOSE = "Close"
LICENSE_DIALOG_LABEL_STATUS = "Status: {status_text}"
LICENSE_DIALOG_LABEL_EXPIRES = "Expires: {formatted}"
LICENSE_DIALOG_LABEL_PROCESSING = "Processing..."
LICENSE_DIALOG_TITLE_MISSING_LICENSE_KEY = "Missing License Key"
LICENSE_DIALOG_MESSAGE_PLEASE_ENTER_A_LICENSE_KEY = "Please enter a license key."
LICENSE_DIALOG_TITLE_DEACTIVATE_LICENSE = "Deactivate License"
LICENSE_DIALOG_MESSAGE_ARE_YOU_SURE_YOU_WANT_TO = (
    "Are you sure you want to deactivate the current license?"
)
LICENSE_DIALOG_TITLE_LICENSE_ACTIVATED = "License Activated"
LICENSE_DIALOG_MESSAGE_YOUR_LICENSE_HAS_BEEN_SUCCESSFULLY_ACTIVATED = (
    "Your license has been successfully activated."
)
LICENSE_DIALOG_TITLE_ACTIVATION_FAILED = "Activation Failed"
LICENSE_DIALOG_TITLE_LICENSE_DEACTIVATED = "License Deactivated"
LICENSE_DIALOG_MESSAGE_LICENSE_HAS_BEEN_DEACTIVATED = "License has been deactivated."
LICENSE_DIALOG_TITLE_DEACTIVATION_FAILED = "Deactivation Failed"
# Dialogs: dialogs.new_database_type_dialog
NEW_DATABASE_TYPE_DIALOG_TITLE_NEW_DATABASE_TYPE = "New Database Type"
# Dialogs: dialogs.open_files_dialog
OPEN_FILES_DIALOG_TITLE_OPEN_DATABASES = "Open Databases"
OPEN_FILES_DIALOG_HEADER_OPEN = "Open"
OPEN_FILES_DIALOG_HEADER_TYPE = "Type"
OPEN_FILES_DIALOG_HEADER_DATABASE = "Database"
OPEN_FILES_DIALOG_HEADER_LOCATION = "Location"
OPEN_FILES_DIALOG_HEADER_DATE_MODIFIED = "Date Modified"
OPEN_FILES_DIALOG_HEADER_SIZE = "Size"
OPEN_FILES_DIALOG_BUTTON_CLOSE = "Close"
OPEN_FILES_DIALOG_BUTTON_FIND = "Find..."
OPEN_FILES_DIALOG_BUTTON_REMOVE = "Remove"
OPEN_FILES_DIALOG_GROUP_DATABASE_ACTIONS = "Database Actions"
OPEN_FILES_DIALOG_BUTTON_COMPACT_REPAIR = "Compact/Repair"
OPEN_FILES_DIALOG_TITLE_SELECT_DATABASE_FILE = "Select Database File"
OPEN_FILES_DIALOG_TITLE_CONFIRM_REMOVAL = "Confirm Removal"
OPEN_FILES_DIALOG_TITLE_SQL_SERVER = "SQL Server"
OPEN_FILES_DIALOG_MESSAGE_SQL_SERVER_SUPPORT_IS_UNAVAILABLE_IN = (
    "SQL Server support is unavailable in this installation."
)
OPEN_FILES_DIALOG_TITLE_DATABASE_CONNECTION_UPDATED = "Database Connection Updated"
OPEN_FILES_DIALOG_MESSAGE_THE_SAVED_SQL_SERVER_CONNECTION_WAS = (
    "The saved SQL Server connection was updated."
)
OPEN_FILES_DIALOG_TITLE_FILE_ALREADY_ADDED = "File Already Added"
OPEN_FILES_DIALOG_MESSAGE_THIS_FILE_IS_ALREADY_IN_THE = (
    "This file is already in the list."
)
OPEN_FILES_DIALOG_MESSAGE_THE_SQL_SERVER_CONNECTION_COULD_NOT = (
    "The SQL Server connection could not be saved."
)
# Dialogs: dialogs.options.dialog
OPTIONS_DIALOG_MESSAGE_FAILED_TO_RESET_SETTINGS_REOPEN_OPTIONS = (
    "Failed to reset settings. Reopen Options and try again."
)
OPTIONS_DIALOG_MESSAGE_FAILED_TO_APPLY_SETTINGS_REOPEN_OPTIONS = (
    "Failed to apply settings. Reopen Options and try again."
)
# Dialogs: dialogs.options.font_dialog
FONT_DIALOG_TITLE_FONT = "Font"
FONT_DIALOG_BUTTON_OK = "OK"
FONT_DIALOG_BUTTON_CANCEL = "Cancel"
FONT_DIALOG_GROUP_SAMPLE = "Sample"
FONT_DIALOG_LABEL_FONT = "Font:"
FONT_DIALOG_LABEL_FONT_STYLE = "Font style:"
FONT_DIALOG_LABEL_SIZE = "Size:"
# Dialogs: dialogs.options.fonts_colors_tab
FONTS_COLORS_TAB_GROUP_DEFAULT_FONT = "Default Font"
FONTS_COLORS_TAB_BUTTON_CHANGE_FONT = "Change Font..."
FONTS_COLORS_TAB_GROUP_DEFAULT_COLOR = "Default Color"
FONTS_COLORS_TAB_BUTTON_CHANGE_COLOR = "Change Color..."
FONTS_COLORS_TAB_LABEL_AABBYYZZ_PT = "AaBbYyZz\n{family}, {style_name}, {point_size} pt"
FONTS_COLORS_TAB_TITLE_COLOR = "Color"
# Dialogs: dialogs.options.mcp_setup_tab
MCP_SETUP_TAB_LABEL_CONNECT_AI_TOOLS = "Connect AI tools"
MCP_SETUP_TAB_LABEL_COPY_ONE_SETUP_OPTION_BELOW_THEN = (
    "Copy one setup option below, then restart that AI tool."
)
MCP_SETUP_TAB_LABEL_CODEX_CONNECTS_TO_THE_LOCAL_STDIO = (
    "Codex connects to the local stdio helper and sees checked files or live "
    "context from OST Visualizer."
)
MCP_SETUP_TAB_LABEL_LETS_AN_AI_TOOL_READ_SHEETS = (
    "Lets an AI tool read sheets, drawing text, linework and quantities of the bid "
    "open in this window and propose slabs or a page scale. Nothing changes until "
    "you accept a proposal in this window. Drawing text is passed to the AI as "
    "data only."
)
MCP_SETUP_TAB_OPTION_ALLOW_AI_TAKEOFF_TOOLS_WHILE_OST = (
    "Allow AI takeoff tools while OST Visualizer is open"
)
# Dialogs: dialogs.options.takeoff_toolbar_tab
TAKEOFF_TOOLBAR_TAB_BUTTON_RESTORE_DEFAULT_TOOLBAR = "Restore Default Toolbar"
# Dialogs: dialogs.payroll_class_dialog
PAYROLL_CLASS_DIALOG_HEADER_PAYROLL_CLASS = "Payroll Class"
# Dialogs: dialogs.rename_page_dialog
RENAME_PAGE_DIALOG_TITLE_RENAME_PAGE = "Rename Page"
RENAME_PAGE_DIALOG_BUTTON_OK = "OK"
RENAME_PAGE_DIALOG_BUTTON_CANCEL = "Cancel"
RENAME_PAGE_DIALOG_BUTTON_PREVIOUS_PAGE = "Previous Page"
RENAME_PAGE_DIALOG_BUTTON_NEXT_PAGE = "Next Page"
RENAME_PAGE_DIALOG_LABEL_OLD_NAME = "Old name:"
RENAME_PAGE_DIALOG_LABEL_NEW_NAME = "New name:"
RENAME_PAGE_DIALOG_TITLE_VALIDATION_ERROR = "Validation Error"
RENAME_PAGE_DIALOG_MESSAGE_PAGE_NAME_CANNOT_BE_EMPTY = "Page name cannot be empty."
RENAME_PAGE_DIALOG_TITLE_SAVE_FAILED = "Save Failed"
RENAME_PAGE_DIALOG_MESSAGE_FAILED_TO_RENAME_PAGE = "Failed to rename page."
# Dialogs: dialogs.select_database_type_dialog
SELECT_DATABASE_TYPE_DIALOG_TITLE_SELECT_DATABASE_TYPE = "Select Database Type"
SELECT_DATABASE_TYPE_DIALOG_OPTION_MICROSOFT_ACCESS = "Microsoft Access"
SELECT_DATABASE_TYPE_DIALOG_OPTION_MICROSOFT_SQL_SERVER = "Microsoft SQL Server"
SELECT_DATABASE_TYPE_DIALOG_LABEL_SELECT_DATABASE_TYPE = "Select database type:"
# Dialogs: dialogs.select_named_view_dialog
SELECT_NAMED_VIEW_DIALOG_TITLE_SELECT_NAMED_VIEW = "Select Named View"
SELECT_NAMED_VIEW_DIALOG_OPTION_TO_AN_EXISTING_NAMED_VIEW = "To an existing Named View"
SELECT_NAMED_VIEW_DIALOG_OPTION_CREATE_A_NEW_NAMED_VIEW = "Create a new Named View"
SELECT_NAMED_VIEW_DIALOG_LABEL_CONNECT_HOTLINK = "Connect Hotlink"
# Dialogs: dialogs.set_scale_dialog
SET_SCALE_DIALOG_TITLE_SET_SCALE = "Set Scale"
SET_SCALE_DIALOG_LABEL_SCALE_STYLE = "Scale style:"
SET_SCALE_DIALOG_OPTION_PRE_DEFINED_SCALE = "Predefined scale"
SET_SCALE_DIALOG_OPTION_CUSTOM_SCALE = "Custom scale"
SET_SCALE_DIALOG_OPTION_APPLY_TO_ALL_PAGES = "Apply to all pages"
SET_SCALE_DIALOG_BUTTON_OK = "OK"
SET_SCALE_DIALOG_BUTTON_CANCEL = "Cancel"
SET_SCALE_DIALOG_BUTTON_APPLY = "Apply"
SET_SCALE_DIALOG_MESSAGE_CUSTOM_SCALE_VALUES_CANNOT_BE_EMPTY = (
    "Custom scale values cannot be empty."
)
SET_SCALE_DIALOG_MESSAGE_CUSTOM_SCALE_VALUES_MUST_BE_POSITIVE = (
    "Custom scale values must be positive."
)
SET_SCALE_DIALOG_TITLE_SAVE_FAILED = "Save Failed"
SET_SCALE_DIALOG_MESSAGE_FAILED_TO_SAVE_PAGE_SCALE = "Failed to save page scale."
SET_SCALE_DIALOG_MESSAGE_SELECT_A_PREDEFINED_SCALE = "Select a predefined scale."
SET_SCALE_DIALOG_MESSAGE_THE_CUSTOM_SCALE_VALUE_IS_NOT = (
    'The {label} custom scale value "{entered_value}" is not a valid number.'
)
# Dialogs: dialogs.sql_connection_dialog
SQL_CONNECTION_DIALOG_PLACEHOLDER_LOCALHOST_SERVER_INSTANCE_OR_HOST_PORT = (
    "localhost, server\\instance, or host,port"
)
SQL_CONNECTION_DIALOG_LABEL_SQL_SERVER = "SQL Server:"
SQL_CONNECTION_DIALOG_OPTION_WINDOWS_AUTHENTICATION = "Windows authentication"
SQL_CONNECTION_DIALOG_OPTION_SQL_SERVER_AUTHENTICATION = "SQL Server authentication"
SQL_CONNECTION_DIALOG_LABEL_LOGIN_NAME = "Login name:"
SQL_CONNECTION_DIALOG_LABEL_PASSWORD = "Password:"
SQL_CONNECTION_DIALOG_OPTION_ENCRYPT_CONNECTION = "Encrypt connection"
SQL_CONNECTION_DIALOG_OPTION_TRUST_SERVER_CERTIFICATE = "Trust server certificate"
SQL_CONNECTION_DIALOG_TOOLTIP_CLEAR_THIS_TO_VALIDATE_THE_SERVER = (
    "Clear this to validate the server certificate and hostname. Keep encryption "
    "enabled for the deployment's validated TLS policy."
)
SQL_CONNECTION_DIALOG_BUTTON_CONNECT = "Connect"
SQL_CONNECTION_DIALOG_LABEL_CONNECT_USING = "Connect using:"
SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER = "SQL Server"
SQL_CONNECTION_DIALOG_MESSAGE_ENTER_A_SQL_SERVER_NAME = "Enter a SQL Server name."
SQL_CONNECTION_DIALOG_LABEL_USE_A_SEPARATE_ACCOUNT_WITH_PERMISSION = (
    "Use a separate account with permission to create databases. These credentials "
    "are used only for setup."
)
SQL_CONNECTION_DIALOG_TITLE_SQL_SERVER_AUTHENTICATION = "SQL Server Authentication"
SQL_CONNECTION_DIALOG_MESSAGE_ENTER_BOTH_A_LOGIN_NAME_AND = (
    "Enter both a login name and password."
)
# Dialogs: dialogs.sql_database_dialog
SQL_DATABASE_DIALOG_TITLE_DATABASE_PROPERTIES_SQL_SERVER = (
    "Database Properties (SQL Server)"
)
SQL_DATABASE_DIALOG_LABEL_DATABASE = "Database:"
SQL_DATABASE_DIALOG_TOOLTIP_THE_ACCOUNT_SELECTED_HERE_IS_USED = (
    "The account selected here is used for normal access. You will be asked for "
    "separate temporary database-creator credentials."
)
SQL_DATABASE_DIALOG_TITLE_SQL_SERVER = "SQL Server"
SQL_DATABASE_DIALOG_MESSAGE_SELECT_A_DATABASE = "Select a database."
SQL_DATABASE_DIALOG_MESSAGE_YOU_DO_NOT_HAVE_PERMISSION_TO = (
    "You do not have permission to create a database."
)
SQL_DATABASE_DIALOG_MESSAGE_DATABASE_SETUP_DID_NOT_COMPLETE_INSPECT = (
    "Database setup did not complete. Inspect the server before retrying creation."
)
# Dialogs: dialogs.synchronization_conflict_dialog
SYNCHRONIZATION_CONFLICT_DIALOG_TITLE_SQL_EDIT_CONFLICT = "SQL Edit Conflict"
# Dialogs: dialogs.update_dialog
UPDATE_DIALOG_TITLE_UPDATE_AVAILABLE = "Update Available"
UPDATE_DIALOG_LABEL_UPDATE_AVAILABLE = "Update Available"
UPDATE_DIALOG_LABEL_A_NEW_VERSION_OF_OST_VISUALIZER = (
    "A new version of OST Visualizer is available!\n\nYour version: "
    "{your_version}\nLatest version: {current_version}{release_date_text}\n\nWould "
    "you like to download the latest version now?"
)
UPDATE_DIALOG_BUTTON_YES_DOWNLOAD = "Yes, Download"
UPDATE_DIALOG_BUTTON_NO_LATER = "No, Later"
UPDATE_DIALOG_LABEL_CHANGELOG = "Changelog"
UPDATE_DIALOG_LABEL_A_HREF_VIEW_FULL_RELEASE_NOTES = (
    '<a href="{escape}">View full release notes</a>'
)
# Handlers: handlers.condition_action_handler
CONDITION_ACTION_HANDLER_TITLE_REFRESH_ERROR = "Refresh Error"
CONDITION_ACTION_HANDLER_MESSAGE_THE_LAYER_WAS_CREATED_BUT_THE = (
    "The layer was created, but the layer list could not be refreshed. Reopen the "
    "database to see the new layer."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_TYPE_CHANGES_WERE_SAVED = (
    "The condition type changes were saved, but the condition type list could not "
    "be refreshed. Reopen the database to see the latest condition types."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_WAS_DUPLICATED_BUT_THE_CONDITIONS = (
    "The condition was duplicated, but the conditions list could not be refreshed. "
    "Reopen the database to see the latest conditions."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_WAS_MOVED_BUT_THE_CONDITIONS = (
    "The condition was moved, but the conditions list could not be refreshed. Reopen "
    "the database to see the latest conditions."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_FOLDER_WAS_CREATED_BUT_THE_CONDITIONS = (
    "The folder was created, but the conditions list could not be refreshed. "
    "Reopen the database to see the latest conditions."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_WAS_UPDATED_BUT_THE_CONDITIONS = (
    "The condition was updated, but the conditions list could not be refreshed. "
    "Reopen the database to see the latest conditions."
)
CONDITION_ACTION_HANDLER_TITLE_DELETE_FOLDER = "Delete Folder"
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_WAS_CREATED_BUT_THE = (
    "The condition was created, but the conditions list could not be refreshed. "
    "Reopen the database to see the new condition."
)
CONDITION_ACTION_HANDLER_TITLE_RENUMBER_CONDITIONS = "Renumber Conditions"
CONDITION_ACTION_HANDLER_MESSAGE_RENUMBER_ALL_THE_CONDITIONS_USING_THE = (
    "Renumber all the conditions using the current sort order?\nThis cannot be "
    "undone."
)
CONDITION_ACTION_HANDLER_MESSAGE_FAILED_TO_RENUMBER_CONDITIONS = (
    "Failed to renumber conditions. {db_locked_hint}"
)
CONDITION_ACTION_HANDLER_TITLE_DUPLICATE_AND_REASSIGN_TAKEOFF = (
    "Duplicate and Reassign Takeoff"
)
CONDITION_ACTION_HANDLER_TITLE_PASTE_CONDITIONS = "Paste Conditions"
CONDITION_ACTION_HANDLER_TITLE_DUPLICATE_CONDITIONS = "Duplicate Conditions"
# Handlers: handlers.cover_sheet_handler
COVER_SHEET_HANDLER_TITLE_ADD_PAGE = "Add Page"
COVER_SHEET_HANDLER_MESSAGE_FAILED_TO_ADD_PAGE = "Failed to add page. {db_locked_hint}"
COVER_SHEET_HANDLER_TITLE_COVER_SHEET = "Cover Sheet"
COVER_SHEET_HANDLER_MESSAGE_FAILED_TO_SAVE_JOB_STATUS = (
    "Failed to save job status. {db_locked_hint}"
)
COVER_SHEET_HANDLER_MESSAGE_FAILED_TO_LOAD_COVER_SHEET_DATA = (
    "Failed to load cover sheet data. {db_locked_hint}"
)
COVER_SHEET_HANDLER_MESSAGE_FAILED_TO_VERIFY_PAGE_CONTENTS = (
    "Failed to verify page contents. {db_locked_hint}"
)
COVER_SHEET_HANDLER_MESSAGE_DO_YOU_WANT_TO_ADD_A = "Do you want to add a new page?"
COVER_SHEET_HANDLER_TITLE_NEW_PROJECT = "New Project"
COVER_SHEET_HANDLER_TITLE_BID_AREAS = "Bid Areas"
COVER_SHEET_HANDLER_MESSAGE_FAILED_TO_SAVE_COVER_SHEET_DATA = (
    "Failed to save cover sheet data. {db_locked_hint}"
)
# Handlers: handlers.export_handler
EXPORT_HANDLER_TITLE_EXPORT_CANCELLED = "Export Cancelled"
EXPORT_HANDLER_MESSAGE_ELEVATION_COLLISION = (
    "\n\nNote: after dropping elevations, 1 condition name became identical "
    "({shown}). Each condition was still exported as its own entry; none were merged."
)
EXPORT_HANDLER_MESSAGE_ELEVATION_COLLISIONS = (
    "\n\nNote: after dropping elevations, {collision_count} condition names became "
    "identical ({shown}). Each condition was still exported as its own entry; none "
    "were merged."
)
EXPORT_HANDLER_TEXT_NAMES_AND_MORE = "{shown} and {hidden_count} more"
EXPORT_HANDLER_MESSAGE_THE_SELECTED_BID_OR_PAGE_CHANGED = (
    "The selected bid or page changed while the save dialog was open. Please start "
    "the export again."
)
EXPORT_HANDLER_FILE_FILTER_PDF_FILES_PDF_ALL_FILES = (
    "PDF Files (*.pdf);;All Files (*.*)"
)
EXPORT_HANDLER_TITLE_EXPORT_SUMMARY_AS_CSV = "Export Summary as CSV"
EXPORT_HANDLER_FILE_FILTER_CSV_FILES_CSV_ALL_FILES = (
    "CSV Files (*.csv);;All Files (*.*)"
)
EXPORT_HANDLER_TITLE_EXPORT_ERROR = "Export Error"
EXPORT_HANDLER_MESSAGE_ERROR_CREATING_SUMMARY_CSV_EXPORT = (
    "Failed to create Summary CSV export: {error_message}"
)
EXPORT_HANDLER_FILE_FILTER_FILES_ALL_FILES = (
    "{format_name} Files (*.{extension});;All Files (*.*)"
)
EXPORT_HANDLER_MESSAGE_A_SELECTED_PAGE_CHANGED_BEFORE_THE = (
    "A selected page changed before the save dialog opened. Please start the "
    "export again."
)
EXPORT_HANDLER_TITLE_NO_VALID_PAGES = "No Valid Pages"
EXPORT_HANDLER_MESSAGE_NO_VALID_PAGES_SELECTED_FOR_EXPORT = (
    "No valid pages selected for export."
)
EXPORT_HANDLER_TITLE_INVALID_SAVE_LOCATION = "Invalid Save Location"
EXPORT_HANDLER_MESSAGE_CANNOT_SAVE_OVER_A_SELECTED_BASE = (
    "Cannot save over a selected base or overlay source file.\nPlease choose a "
    "different filename or location."
)
EXPORT_HANDLER_TITLE_EXPORT_COMPLETE = "Export Complete"
EXPORT_HANDLER_TITLE_NO_DATA = "No Data"
EXPORT_HANDLER_TITLE_NO_BID_SELECTED = "No Bid Selected"
EXPORT_HANDLER_MESSAGE_PLEASE_LOAD_A_DATABASE_AND_SELECT = (
    "Please load a database and select a bid before exporting."
)
EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_ONE_PAGE_TO = (
    "Successfully exported {page_count} page to {filename}"
)
EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_PAGES_TO = (
    "Successfully exported {page_count} pages to {filename}"
)
EXPORT_HANDLER_MESSAGE_ERROR_CREATING_EXPORT = (
    "Failed to create {format_name} export: {error_message}"
)
EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING = (
    "An unexpected error occurred while exporting the PDF. Please try again or "
    "choose a different destination."
)
EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING_2 = (
    "An unexpected error occurred while exporting the {format_name} file. Please "
    "try again or choose a different destination."
)
# Handlers: handlers.file_operation_handler
FILE_OPERATION_HANDLER_TITLE_SQL_DATABASE_NOT_READY = "SQL Database Not Ready"
FILE_OPERATION_HANDLER_TITLE_RECONNECT_SQL_SERVER_DATABASE = (
    "Reconnect SQL Server Database"
)
FILE_OPERATION_HANDLER_TITLE_DATABASE_OPERATION_PENDING = "Database Operation Pending"
FILE_OPERATION_HANDLER_MESSAGE_WAIT_FOR_THE_CURRENT_DATABASE_OPERATION = (
    "Wait for the current database operation to finish before changing Open Files "
    "again."
)
FILE_OPERATION_HANDLER_TITLE_SQL_SERVER = "SQL Server"
FILE_OPERATION_HANDLER_MESSAGE_SQL_SERVER_SUPPORT_IS_UNAVAILABLE_IN = (
    "SQL Server support is unavailable in this installation."
)
FILE_OPERATION_HANDLER_MESSAGE_THIS_SQL_SERVER_DATABASE_IS_ALREADY = (
    "This SQL Server database is already in Open Files."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_DATABASE_AND_CONNECTION_WERE_SAVED = (
    "The database and connection were saved, but opening could not start. "
    "Reconnect through Open Files. The server database was retained."
)
FILE_OPERATION_HANDLER_TITLE_UNLOAD_FILE = "Unload File"
FILE_OPERATION_HANDLER_TITLE_NO_FILE_LOADED = "No File Loaded"
FILE_OPERATION_HANDLER_MESSAGE_THERE_IS_NO_FILE_CURRENTLY_LOADED = (
    "There is no file currently loaded."
)
FILE_OPERATION_HANDLER_TITLE_COMPACT_REPAIR = "Compact/Repair"
FILE_OPERATION_HANDLER_MESSAGE_CLOSE_OTHER_EDITORS_BEFORE_DATABASE_MAINTENANCE = (
    "Close other editors before database maintenance. Unsaved drafts will not be "
    "discarded."
)
FILE_OPERATION_HANDLER_MESSAGE_COMPACT_AND_REPAIR_THE_SELECTED_DATABASE = (
    "Compact and repair the selected database? Close this database in other "
    "applications first. It will be unavailable during maintenance and reloaded "
    "afterward."
)
FILE_OPERATION_HANDLER_TITLE_OPEN_FILES = "Open Files"
FILE_OPERATION_HANDLER_MESSAGE_THE_CHECKED_SQL_STATE_COULD_NOT = (
    "The checked SQL state could not be preserved while critical writes drain, so "
    "no databases were unloaded."
)
FILE_OPERATION_HANDLER_MESSAGE_FAILED_TO_UNLOAD = "Failed to unload {raw}."
FILE_OPERATION_HANDLER_TITLE_ERROR_LOADING_FILE = "Error Loading File"
FILE_OPERATION_HANDLER_MESSAGE_FAILED_TO_LOAD = (
    "Failed to load {display_name}:\n{error_message}"
)
FILE_OPERATION_HANDLER_MESSAGE_A_CRITICAL_DATABASE_SETTING_COULD_NOT = (
    "A critical database setting could not be submitted before reconnecting."
)
FILE_OPERATION_HANDLER_TITLE_REMOVE_SQL_SERVER_CONNECTION = (
    "Remove SQL Server Connection"
)
FILE_OPERATION_HANDLER_MESSAGE_THE_SAVED_DATABASE_ENTRY_WAS_REMOVED = (
    "The saved database entry was removed, but its Windows credential could not be "
    "deleted."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_FINAL_CHECKED_DATABASE_STATE_COULD = (
    "The final checked database state could not be saved after applying Open Files "
    "changes."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_OPEN_FILES_STATE_COULD_NOT = (
    "The Open Files state could not be saved, so the database was not unloaded."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_OPEN_FILES_STATE_COULD_NOT_2 = (
    "The Open Files state could not be saved, so no database changes were applied."
)
FILE_OPERATION_HANDLER_MESSAGE_TEMPORARY_FILE_CLEANUP_FAILED = (
    "Temporary-file cleanup failed: {exc}"
)
FILE_OPERATION_HANDLER_MESSAGE_A_DATABASE_COULD_NOT_BE_LOADED = (
    "A database could not be loaded and its checked state could not be cleared."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_DATABASE_COULD_NOT_BE_UNLOADED = (
    "The database could not be unloaded and its saved Open Files state could not "
    "be restored."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_SQL_CREDENTIALS_COULD_NOT_BE = (
    "The SQL credentials could not be finalized, so no database changes were "
    "applied."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_SQL_CREDENTIALS_COULD_NOT_BE_2 = (
    "The SQL credentials could not be finalized and the previous Open Files state "
    "could not be restored."
)
# Handlers: handlers.import_handler
IMPORT_HANDLER_TITLE_IMPORT_FILE = "Import {format_name} File"
IMPORT_HANDLER_FILE_FILTER_FILES = "{format_name} Files (*.{extension})"
IMPORT_HANDLER_TITLE_IMPORT_ERROR = "Import Error"
IMPORT_HANDLER_TITLE_NO_DATABASE = "No Database"
IMPORT_HANDLER_MESSAGE_NO_DATABASE_IS_LOADED_PLEASE_OPEN = (
    "No database is loaded. Please open a database file before importing."
)
IMPORT_HANDLER_TITLE_IMPORT_CANCELLED = "Import Cancelled"
IMPORT_HANDLER_MESSAGE_THE_SELECTED_IMPORT_DESTINATION_IS_NO = (
    "The selected import destination is no longer available. Select the database "
    "or project again."
)
IMPORT_HANDLER_MESSAGE_THE_SELECTED_DATABASE_OR_PROJECT_CHANGED = (
    "The selected database or project changed while the file dialog was open. "
    "Select the destination again before importing."
)
IMPORT_HANDLER_TITLE_IMPORT_COMPLETE = "Import Complete"
IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_INTO_THE_DATABASE = (
    'Successfully imported "{filename}" into the database.'
)
IMPORT_HANDLER_TITLE_IMPORT_STATUS_UNKNOWN = "Import Status Unknown"
IMPORT_HANDLER_MESSAGE_THE_COMMIT_STATUS_FOR_IS_BEING = (
    'The commit status for "{filename}" is being recovered. Do not import the file '
    "again until recovery completes."
)
IMPORT_HANDLER_MESSAGE_FAILED_TO_IMPORT_FILE_THE_FILE = (
    "Failed to import {format_name} file. The file may be corrupted or in an "
    "unsupported format."
)
IMPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_IMPORTING = (
    "An unexpected error occurred while importing the {format_name} file. Please "
    "verify the file is valid and try again."
)
IMPORT_HANDLER_MESSAGE_THE_IMPORT_COULD_NOT_BE_QUEUED = (
    "The {format_name} import could not be queued."
)
IMPORT_HANDLER_TITLE_REFRESH_ERROR = "Refresh Error"
IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_BUT_THE_DATABASE_VIEW = (
    'Successfully imported "{filename}", but the database view could not be '
    "refreshed. Reopen the database to see the imported project."
)
# Handlers: handlers.plan_view_action_handler
PLAN_VIEW_ACTION_HANDLER_TITLE_DATABASE_WRITE = "Database Write"
PLAN_VIEW_ACTION_HANDLER_MESSAGE_THE_ANNOTATIONS_COULD_NOT_BE_SAVED = (
    "The annotations could not be saved. Reload the bid and verify its page and "
    "layer settings before trying again. See the log for details."
)
PLAN_VIEW_ACTION_HANDLER_TITLE_HOT_LINK_HISTORY = "Hotlink History"
PLAN_VIEW_ACTION_HANDLER_TITLE_PASTE = "Paste"
PLAN_VIEW_ACTION_HANDLER_TITLE_DELETE_NAMED_VIEW = "Delete Named View"
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_TITLE_PASTE_ERROR = "Paste Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_PASTE_BID = (
    "Failed to paste bid. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_ERROR = "Duplicate Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DUPLICATE_BID = (
    "Failed to duplicate bid. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_RENAME_ERROR = "Rename Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RENAME_PROJECT = (
    "Failed to rename project. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_JOB_STATUS = "Job Status"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_CHANGE_JOB_STATUS = (
    "Failed to change job status. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_PASTE_PARTIALLY_COMPLETED = "Paste Partially Completed"
PROJECT_WRITE_HANDLER_TITLE_CANNOT_DELETE_PROJECT = "Cannot Delete Project"
PROJECT_WRITE_HANDLER_MESSAGE_SOME_SELECTED_PROJECTS_STILL_HAVE_BIDS = (
    "Some selected projects still have bids inside.\nOnly empty projects can be "
    "deleted."
)
PROJECT_WRITE_HANDLER_TITLE_DELETE_PROJECTS = "Delete Projects"
PROJECT_WRITE_HANDLER_TITLE_DELETE_ERROR = "Delete Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_PROJECTS = (
    "Failed to delete projects. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR = "Refresh Error"
PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DUPLICATED_BUT_THE = (
    "The bid was duplicated, but the project tree could not be refreshed. Reopen "
    "the database to see the duplicated bid."
)
PROJECT_WRITE_HANDLER_TITLE_MOVE_ERROR = "Move Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS = (
    "Failed to move bids. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_PASTED_BUT_THE = (
    "The bid was pasted, but the project tree could not be refreshed. Reopen the "
    "database to see the pasted bid."
)
PROJECT_WRITE_HANDLER_TITLE_RESTORE_ERROR = "Restore Error"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RESTORE_BIDS = (
    "Failed to restore bids. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_TITLE_DELETE_BIDS = "Delete Bids"
PROJECT_WRITE_HANDLER_TITLE_MOVE_TO_DELETED_BIDS = "Move to Deleted Bids"
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_BIDS = (
    "Failed to delete bids. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DELETED_BUT_THE = (
    "The bid was deleted, but the project tree could not be refreshed. Reopen the "
    "database to see the change."
)
PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS_TO_DELETED = (
    "Failed to move bids to Deleted Bids. {db_locked_hint}"
)
PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_MOVED_TO_DELETED = (
    "The bid was moved to Deleted Bids, but the project tree could not be "
    "refreshed. Reopen the database to see the change."
)
# Components: components.condition_summary
CONDITION_SUMMARY_ACTION_COPY = "Copy"
CONDITION_SUMMARY_ACTION_DELETE = "Delete"
CONDITION_SUMMARY_ACTION_EXPAND_ALL = "Expand All"
CONDITION_SUMMARY_ACTION_COLLAPSE_ALL = "Collapse All"
# Components: components.conditions_sidebar
CONDITIONS_SIDEBAR_HEADER_NO = "No."
CONDITIONS_SIDEBAR_HEADER_NAME = "Name"
CONDITIONS_SIDEBAR_HEADER_QTY_1 = "Qty 1"
CONDITIONS_SIDEBAR_HEADER_QTY_2 = "Qty 2"
CONDITIONS_SIDEBAR_HEADER_QTY_3 = "Qty 3"
CONDITIONS_SIDEBAR_TOOLTIP_NEW_FOLDER = "New folder"
CONDITIONS_SIDEBAR_MENU_NEW = "New"
CONDITIONS_SIDEBAR_TITLE_DUPLICATE_CONDITION = "Duplicate Condition"
CONDITIONS_SIDEBAR_MESSAGE_CONDITION_ALREADY_EXISTS = "Condition {name} already exists."
CONDITIONS_SIDEBAR_TITLE_DUPLICATE_FOLDER = "Duplicate Folder"
CONDITIONS_SIDEBAR_MESSAGE_FOLDER_ALREADY_EXISTS = "Folder {name} already exists."
# Components: components.layers_sidebar
LAYERS_SIDEBAR_HEADER_SHOW = "Show"
LAYERS_SIDEBAR_HEADER_LAYER = "Layer"
LAYERS_SIDEBAR_TITLE_DELETE_LAYER = "Delete Layer"
LAYERS_SIDEBAR_TITLE_DUPLICATE_LAYER = "Duplicate Layer"
LAYERS_SIDEBAR_MESSAGE_LAYER_ALREADY_EXISTS = "Layer {name} already exists."
# Components: components.mesh_view
MESH_VIEW_ACTION_SET_AS_CURVED_SEGMENT = "Set as Curved Segment"
MESH_VIEW_ACTION_ASSIGN_TO_CURRENT_AREA = "Assign to Current Area"
MESH_VIEW_ACTION_COUNT_AS_NEGATIVE_QUANTITY = "Count as Negative Quantity"
# Components: components.page_settings_bar
PAGE_SETTINGS_BAR_CHOICE_CUSTOM_SCALE = "Custom scale"
PAGE_SETTINGS_BAR_TOOLTIP_AREA = "Area"
PAGE_SETTINGS_BAR_LABEL_AREA = "Area"
PAGE_SETTINGS_BAR_TITLE_BID_AREAS = "Bid Areas"
PAGE_SETTINGS_BAR_MESSAGE_THE_AREAS_WERE_SAVED_BUT_COULD = (
    "The areas were saved, but could not be refreshed. Reopen the bid to reload them."
)
# Components: components.plan_view.components.input_handler
INPUT_HANDLER_ACTION_COPY = "Copy"
INPUT_HANDLER_ACTION_SET_AS_CURVED_SEGMENT = "Set as Curved Segment"
INPUT_HANDLER_ACTION_ASSIGN_TO_CURRENT_AREA = "Assign to Current Area"
INPUT_HANDLER_ACTION_COUNT_AS_NEGATIVE_QUANTITY = "Count as Negative Quantity"
INPUT_HANDLER_ACTION_ADD_CONTROL_POINT = "Add Control Point"
INPUT_HANDLER_ACTION_SUBTRACT_CONTROL_POINT = "Subtract Control Point"
# Components: components.plan_view.view
PLAN_VIEW_VIEW_TOOLTIP_TEXT_COLOR = "Text color"
PLAN_VIEW_VIEW_LABEL_OVERLAY_IMAGE = "Overlay image"
PLAN_VIEW_VIEW_LABEL_PAGE_IMAGE_OR_OVERLAY = "Page image/PDF or overlay image"
PLAN_VIEW_VIEW_LABEL_PAGE_IMAGE = "Page image/PDF"
PLAN_VIEW_VIEW_MESSAGE_CANNOT_BE_ACCESSED = "{label} cannot be accessed."
PLAN_VIEW_VIEW_MESSAGE_CANNOT_BE_ACCESSED_FILE = (
    "{label} cannot be accessed: {filename}."
)
PLAN_VIEW_VIEW_MESSAGE_NOT_FOUND = "{label} was not found or could not be loaded."
PLAN_VIEW_VIEW_MESSAGE_NOT_FOUND_FILE = (
    "{label} was not found or could not be loaded: {filename}."
)
PLAN_VIEW_VIEW_TOOLTIP_TEXT_COLOR_2 = "Text color ({name})"
PLAN_VIEW_VIEW_TITLE_MOVE_OVERLAY_IMAGE = "Move Overlay Image"
PLAN_VIEW_VIEW_MESSAGE_THE_OVERLAY_POSITION_COULD_NOT_BE = (
    "The overlay position could not be saved."
)
PLAN_VIEW_VIEW_MESSAGE_THE_OVERLAY_POSITION_WAS_QUEUED_FOR = (
    "The overlay position was queued for saving, but the page could not be "
    "refreshed."
)
# Components: components.progress_dialog
PROGRESS_DIALOG_TITLE_WORKING = "Working..."
PROGRESS_DIALOG_LABEL_PROCESSING = "Processing <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_SQL_DATABASE_SETUP = "SQL database setup <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_COMPACTING_REPAIRING = "Compacting/repairing <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_OPENING_SQL_DATABASE = "Opening SQL database <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_DUPLICATING = "Duplicating <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_PASTING = "Pasting <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_IMPORTING = "Importing <b>{name}</b>..."
PROGRESS_DIALOG_LABEL_CREATING_DATABASE = "Creating database <b>{name}</b>..."
PROGRESS_DIALOG_NAME_NEW_DATABASE = "new database"
# Components: components.project_tree_view
PROJECT_TREE_VIEW_ACTION_RENAME = "Rename"
PROJECT_TREE_VIEW_ACTION_RENUMBER_CONDITIONS = "Renumber Conditions"
PROJECT_TREE_VIEW_ACTION_EMPTY_DELETED_BIDS_FOLDER = "Empty Deleted Bids Folder"
PROJECT_TREE_VIEW_ACTION_GROUP_BY_JOB_STATUS = "Group by Job Status"
PROJECT_TREE_VIEW_ACTION_EXPAND_ALL = "Expand All"
PROJECT_TREE_VIEW_ACTION_COLLAPSE_ALL = "Collapse All"
PROJECT_TREE_VIEW_MENU_NEW = "New"
PROJECT_TREE_VIEW_MENU_IMPORT = "Import"
PROJECT_TREE_VIEW_MENU_EXPORT = "Export"
PROJECT_TREE_VIEW_MENU_CHANGE_JOB_STATUS = "Change Job Status"
PROJECT_TREE_VIEW_ITEM_NO_PROJECTS_AVAILABLE = "No projects available"
PROJECT_TREE_VIEW_ACTION_COPY = "Copy"
PROJECT_TREE_VIEW_ACTION_PASTE = "Paste"
# Components: components.toolbar_overflow
TOOLBAR_OVERFLOW_LABEL_SCALE = "Scale"
TOOLBAR_OVERFLOW_LABEL_AREA = "Area"
# Utils: utils.combo_identity
COMBO_IDENTITY_MESSAGE_MATCHES_MORE_THAN_ONE_ITEM = '"{entered_name}" matches more than one item. Select the intended item from the list.'
# Utils: utils.annotation_style_controls
ANNOTATION_STYLE_CONTROLS_ACTION_SELECT_COLOR = "Select Color..."
ANNOTATION_STYLE_CONTROLS_TOOLTIP_FONT_FAMILY = "Font family"
ANNOTATION_STYLE_CONTROLS_MENU_FONT_SIZE = "Font Size"
ANNOTATION_STYLE_CONTROLS_ACTION_BOLD = "Bold"
ANNOTATION_STYLE_CONTROLS_ACTION_ITALIC = "Italic"
ANNOTATION_STYLE_CONTROLS_ACTION_UNDERLINE = "Underline"
ANNOTATION_STYLE_CONTROLS_TOOLTIP_DEFAULT_ANNOTATION_STYLE = "Default annotation style"
ANNOTATION_STYLE_CONTROLS_ACTION_PX = "{width} px"
ANNOTATION_STYLE_CONTROLS_MENU_ALIGNMENT = "Alignment"
# Utils: utils.dialog
UTILS_DIALOG_BUTTON_NEW = "New"
UTILS_DIALOG_BUTTON_DELETE = "Delete"
UTILS_DIALOG_LABEL_FIND = "Find:"
UTILS_DIALOG_BUTTON_CANCEL = "Cancel"
UTILS_DIALOG_MESSAGE_FAILED_TO_VALIDATE_USAGE = "Failed to validate usage."
UTILS_DIALOG_MESSAGE_THESE_RECORDS_CHANGED_WHILE_SAVING_REVIEW = (
    "These records changed while saving. Review the current values and try again."
)
# Utils: utils.messagebox
MESSAGEBOX_TITLE_DELETE_VERIFICATION = "Delete Verification"
MESSAGEBOX_TITLE_DELETE = 'Delete "{name}"?'
MESSAGEBOX_LABEL_DELETING_A_CONDITION_WILL_DELETE_ALL = (
    "Deleting a condition will delete all its takeoff on all pages within this "
    "bid.\n\nThis cannot be undone.\n\nAre you sure you want to delete this "
    "condition?"
)
MESSAGEBOX_BUTTON_YES_TO_ALL = "Yes to All"
MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM = "Delete {item_count} item?"
MESSAGEBOX_MESSAGE_DELETE_ITEMS = "Delete {item_count} items?"
# Utils: utils.named_view_validation
NAMED_VIEW_VALIDATION_TITLE_NAMED_VIEW = "Named View"
# Utils: utils.overlay_context_menu
OVERLAY_CONTEXT_MENU_TITLE_SELECT_OVERLAY_IMAGE = "Select Overlay Image"
# Utils: utils.view_context_menu
VIEW_CONTEXT_MENU_MENU_REASSIGN_CONDITION = "Reassign Condition"
VIEW_CONTEXT_MENU_MENU_LINE_WIDTH = "Line Width"
VIEW_CONTEXT_MENU_ACTION_PX = "{width} px"
VIEW_CONTEXT_MENU_ACTION_SELECT_COLOR = "Select Color..."
# Builders: builders.component_builder
COMPONENT_BUILDER_TAB_PROJECTS = "Projects"
COMPONENT_BUILDER_ACTION_BACKOUT_MODE = "Backout Mode"
COMPONENT_BUILDER_ACTION_PROJECT = "Project"
COMPONENT_BUILDER_TOOLTIP_NEW_PROJECT = "New project"
COMPONENT_BUILDER_ACTION_FOLDER = "Folder"
COMPONENT_BUILDER_TOOLTIP_NEW_FOLDER = "New folder"
COMPONENT_BUILDER_ACTION_DATABASE = "Database"
COMPONENT_BUILDER_TOOLTIP_NEW_DATABASE = "New database"
COMPONENT_BUILDER_LABEL_NEW = "New"
COMPONENT_BUILDER_ACTION_OPEN = "Open..."
COMPONENT_BUILDER_TOOLTIP_OPEN = "Open"
COMPONENT_BUILDER_ACTION_COPY = "Copy"
COMPONENT_BUILDER_TOOLTIP_COPY = "Copy"
COMPONENT_BUILDER_ACTION_CUT = "Cut"
COMPONENT_BUILDER_TOOLTIP_CUT = "Cut"
COMPONENT_BUILDER_ACTION_PASTE = "Paste"
COMPONENT_BUILDER_TOOLTIP_PASTE = "Paste"
COMPONENT_BUILDER_ACTION_DUPLICATE = "Duplicate"
COMPONENT_BUILDER_TOOLTIP_DUPLICATE = "Duplicate"
COMPONENT_BUILDER_ACTION_DELETE = "Delete"
COMPONENT_BUILDER_TOOLTIP_DELETE = "Delete"
COMPONENT_BUILDER_ACTION_UNDO = "Undo"
COMPONENT_BUILDER_TOOLTIP_UNDO = "Undo"
COMPONENT_BUILDER_ACTION_REDO = "Redo"
COMPONENT_BUILDER_TOOLTIP_REDO = "Redo"
COMPONENT_BUILDER_LABEL_COVER_SHEET = "Cover Sheet"
COMPONENT_BUILDER_TOOLTIP_SHOW_COVER_SHEET = "Show cover sheet"
COMPONENT_BUILDER_ACTION_LAYERS_SIDEBAR = "Layers Sidebar"
COMPONENT_BUILDER_TOOLTIP_HIDE_SHOW_LAYERS_SIDEBAR = "Hide/show layers sidebar"
COMPONENT_BUILDER_ACTION_CONDITIONS_SIDEBAR = "Conditions Sidebar"
COMPONENT_BUILDER_TOOLTIP_HIDE_SHOW_CONDITIONS_SIDEBAR = "Hide/show conditions sidebar"
COMPONENT_BUILDER_ACTION_PAN_SIDEBAR = "Pan Sidebar"
COMPONENT_BUILDER_TOOLTIP_HIDE_SHOW_PAN_SIDEBAR = "Hide/show pan sidebar"
COMPONENT_BUILDER_ACCESSIBLE_PAN_SIDEBAR = "Pan Sidebar"
COMPONENT_BUILDER_TAB_TAKEOFF = "Takeoff"
COMPONENT_BUILDER_TAB_SUMMARY = "Summary"
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_TITLE_SQL_SYNCHRONIZATION = "SQL Synchronization"
UI_EVENT_COORDINATOR_TITLE_REFRESH_ERROR = "Refresh Error"
UI_EVENT_COORDINATOR_MESSAGE_THE_BID_AREA_CHANGES_WERE_SAVED = (
    "The bid area changes were saved, but the area list could not be refreshed. "
    "Reopen the database to see the latest bid areas."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_EMPLOYEE_CHANGES_WERE_SAVED_BUT = (
    "The employee changes were saved, but the employee list could not be "
    "refreshed. Reopen the database to see the latest employees."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_CONDITION_TYPE_CHANGES_WERE_SAVED = (
    "The condition type changes were saved, but the condition type list could not "
    "be refreshed. Reopen the database to see the latest condition types."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_DEFAULT_LAYER_WAS_SAVED_BUT = (
    "The default layer was saved, but the default layer list could not be "
    "refreshed. Reopen the database to see the latest default layers."
)
UI_EVENT_COORDINATOR_TITLE_DELETE_PAGE = "Delete Page"
UI_EVENT_COORDINATOR_MESSAGE_FAILED_TO_VERIFY_PAGE_CONTENTS = (
    "Failed to verify page contents. {db_locked_hint}"
)
UI_EVENT_COORDINATOR_MESSAGE_FAILED_TO_DELETE_PAGE = (
    "Failed to delete page. {db_locked_hint}"
)
UI_EVENT_COORDINATOR_MESSAGE_CANNOT_DELETE_THE_LAST_PAGE_IN = (
    "Cannot delete the last page in the bid."
)
UI_EVENT_COORDINATOR_TITLE_OVERLAY_SELECTION_CANCELLED = "Overlay Selection Cancelled"
UI_EVENT_COORDINATOR_MESSAGE_THE_SELECTED_PAGE_CHANGED_WHILE_THE = (
    "The selected page changed while the file dialog was open. Please choose the "
    "overlay again."
)
UI_EVENT_COORDINATOR_TITLE_DELETE_LAYER = "Delete Layer"
UI_EVENT_COORDINATOR_MESSAGE_FAILED_TO_DELETE_LAYER = (
    "Failed to delete layer. {db_locked_hint}"
)
UI_EVENT_COORDINATOR_TITLE_EDITING_UNAVAILABLE = "Editing Unavailable"
UI_EVENT_COORDINATOR_TITLE_BID_AREAS = "Bid Areas"
UI_EVENT_COORDINATOR_TITLE_CONDITION_TYPES = "Condition Types"
UI_EVENT_COORDINATOR_TITLE_OPEN_SQL_BID = "Open SQL Bid"
UI_EVENT_COORDINATOR_TITLE_RENAME_PAGE = "Rename Page"
UI_EVENT_COORDINATOR_MESSAGE_THE_LAYER_WAS_CREATED_BUT_THE = (
    "The layer was created, but the layer list could not be refreshed. Reopen the "
    "database to see the new layer."
)
# Controllers: controllers.menu_controller
MENU_CONTROLLER_TITLE_SELECT_OBJECTS_IN_CURRENT_AREA = "Select Objects in Current Area"
MENU_CONTROLLER_MESSAGE_THE_ACTIVE_PLAN_VIEW_IS_NO = (
    "The active plan view is no longer available. Activate an open plan view and "
    "try again."
)
MENU_CONTROLLER_TITLE_REFRESH_ERROR = "Refresh Error"
MENU_CONTROLLER_MESSAGE_THE_PROJECT_WAS_CREATED_BUT_THE = (
    "The project was created, but the project tree could not be refreshed. Reopen "
    "the database to see the created project."
)
MENU_CONTROLLER_TITLE_NEW_PROJECT = "New Project"
MENU_CONTROLLER_MESSAGE_FAILED_TO_CREATE_PROJECT = (
    "Failed to create project. {db_locked_hint}"
)
MENU_CONTROLLER_TITLE_NEW_DATABASE = "New Database"
MENU_CONTROLLER_LABEL_DATABASE_NAME = "Database name:"
MENU_CONTROLLER_MESSAGE_FAILED_TO_CREATE_DATABASE_CHECK_LOGS = (
    "Failed to create database. Check logs for details."
)
MENU_CONTROLLER_MESSAGE_THE_BID_WAS_CREATED_BUT_THE = (
    "The bid was created, but the project tree could not be refreshed. Reopen the "
    "database to see the created bid."
)
MENU_CONTROLLER_MESSAGE_FAILED_TO_CREATE_BID = "Failed to create bid."
# Services: services.ai_undo_refusal_notice
AI_UNDO_REFUSAL_NOTICE_LABEL_COULD_NOT_BE_UNDONE = (
    "{action_label} could not be undone.\n\n{reason}"
)
# Windows: windows.components.window
COMPONENTS_WINDOW_TITLE_HOT_LINK_HISTORY = "Hotlink History"
COMPONENTS_WINDOW_TITLE_DELETE_NAMED_VIEW = "Delete Named View"
# Main window.py: main_window
MAIN_WINDOW_ACTION_SELECT_ALL = "Select All"
MAIN_WINDOW_ACTION_STATUS_BAR = "Status Bar"
MAIN_WINDOW_TITLE_IMPORT_COMPLETE = "Import Complete"
MAIN_WINDOW_TITLE_ERROR = "Error"
MAIN_WINDOW_MESSAGE_FAILED_TO_CREATE_DATABASE_CHECK_LOGS = (
    "Failed to create database. Check logs for details."
)
MAIN_WINDOW_TITLE_SHUTDOWN_INCOMPLETE = "Shutdown Incomplete"
MAIN_WINDOW_TITLE_SQL_COLLABORATION = "SQL Collaboration"
MAIN_WINDOW_MESSAGE_OST_VISUALIZER_WILL_CLOSE_NOW_SQL = (
    "{reason}\n\nOST Visualizer will close now. SQL Server releases this session "
    "and its edit locks automatically within about a minute."
)
MAIN_WINDOW_TITLE_IMPORT_ERROR = "Import Error"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_MESSAGE_FAILED_TO_SAVE_CONDITION = "Failed to save condition."
# Dialogs: dialogs.license_dialog
LICENSE_DIALOG_MESSAGE_UNABLE_TO_ACTIVATE_LICENSE = "Failed to activate license."
LICENSE_DIALOG_MESSAGE_UNABLE_TO_DEACTIVATE_LICENSE = "Failed to deactivate license."
# Handlers: handlers.condition_action_handler
CONDITION_ACTION_HANDLER_MESSAGE_FAILED_TO_CREATE_CONDITION = (
    "Failed to create condition."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_ACTIVE_BID_OR_EDIT_ACCESS = (
    "The active bid or edit access changed."
)
CONDITION_ACTION_HANDLER_MESSAGE_FAILED_TO_SAVE_PENDING_VISUAL_STATE = (
    "Failed to save pending visual state."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_OPERATION_COULD_NOT_COMPLETE_RELOAD = (
    "The operation could not complete. Reload the database before retrying."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_COMMITTED_CONDITION_RESULT_WAS_INCOMPLETE = (
    "The committed condition result was incomplete."
)
CONDITION_ACTION_HANDLER_MESSAGE_THE_ACTIVE_BID_OR_AUTHORITATIVE_CONDITION = (
    "The active bid or authoritative condition family changed."
)
# Handlers: handlers.cover_sheet_handler
COVER_SHEET_HANDLER_MESSAGE_THE_UPDATE_FAILED = "The update failed."
# Handlers: handlers.export_handler
EXPORT_HANDLER_MESSAGE_FAILED_TO_EXPORT_FILE_PLEASE_ENSURE = (
    "Failed to export {format_name} file. Please ensure you have write permissions "
    "to the destination folder and try again."
)
EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_SUMMARY_TO = (
    "Successfully exported Summary to {filename}{elevation_collision_note}"
)
EXPORT_HANDLER_MESSAGE_NO_SUMMARY_ROWS_ARE_AVAILABLE_TO = (
    "No summary rows are available to export."
)
EXPORT_HANDLER_MESSAGE_NO_TAKEOFFS_FOUND_FOR_ANY_OF = (
    "No takeoffs found for any of the selected pages."
)
EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_BID_TO = (
    "Successfully exported bid to {filename}{elevation_collision_note}"
)
# Handlers: handlers.file_operation_handler
FILE_OPERATION_HANDLER_MESSAGE_THE_DATABASE_WAS_CREATED_AND_ITS = (
    "The database was created and its connection saved, but it is not ready for "
    "editing. {detail} Reconnect through Open Files. The server database and saved "
    "runtime credentials were retained."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_EXISTING_SQL_COLLABORATION_SESSION_COULD = (
    "The existing SQL collaboration session could not be closed safely."
)
FILE_OPERATION_HANDLER_MESSAGE_A_CRITICAL_DATABASE_SETTING_COULD_NOT_2 = (
    "A critical database setting could not be saved before reconnecting."
)
FILE_OPERATION_HANDLER_MESSAGE_A_CRITICAL_DATABASE_SETTING_COULD_NOT_3 = (
    "A critical database setting could not be saved before unload."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_DATABASE_WAS_CREATED_BUT_ITS = (
    "The database was created, but its saved connection could not be stored. The "
    "server database was not deleted."
)
FILE_OPERATION_HANDLER_MESSAGE_THE_DATABASE_WAS_CREATED_BUT_ITS_CREDENTIAL = (
    "The database was created, but its saved connection could not be stored. The "
    "server database was not deleted. The temporary Windows credential could not be "
    "removed; remove it through Windows Credential Manager."
)
FILE_OPERATION_HANDLER_MESSAGE_DATABASE_MAINTENANCE_FAILED = (
    "Database maintenance failed."
)
# Utils: utils.messagebox
MESSAGEBOX_TITLE_NOT_FOUND = "Not Found"
MESSAGEBOX_MESSAGE_WAS_NOT_FOUND_WOULD_YOU_LIKE = (
    '"{name}" was not found.\n\nWould you like to add it?'
)
MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM = (
    "{in_use_lines}\n\nDelete the other {item_count} item?"
)
MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS = (
    "{in_use_lines}\n\nDelete the other {item_count} items?"
)
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_MESSAGE_THE_SQL_DATABASE_COULD_NOT_BE = (
    "The SQL database could not be reconciled safely."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_COMMITTED_UPDATE_REQUIRES_AUTHORITATIVE_SQL = (
    "The committed update requires authoritative SQL recovery."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_EDIT_LEASE_COULD_NOT_BE = (
    "The edit lease could not be acquired."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_EDIT_WAS_CANCELLED_WHILE_THE = (
    "The edit was cancelled while the view was closing."
)
UI_EVENT_COORDINATOR_MESSAGE_THE_EDIT_WAS_CANCELLED_BECAUSE_ITS = (
    "The edit was cancelled because its original context changed."
)
# Services: services.modal_edit_lease_session
MODAL_EDIT_LEASE_SESSION_MESSAGE_THE_EDIT_WAS_CANCELLED_WHILE_THE = (
    "The edit was cancelled while the dialog was closing."
)
# Main window.py: main_window
MAIN_WINDOW_MESSAGE_A_CRITICAL_DATABASE_SETTING_COULD_NOT = (
    "A critical database setting could not be saved before shutdown."
)
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_TITLE_NEW_PROJECT = "New Project"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_PLACEHOLDER_E_G_3_2_M = "e.g. 3.2 m"
EDIT_CONDITION_DIALOG_PLACEHOLDER_E_G_10_6 = "e.g. 10' 6\""
# Dialogs: dialogs.employees_dialog
EMPLOYEES_DIALOG_BUTTON_OK = "OK"
EMPLOYEES_DIALOG_BUTTON_SELECT = "Select"
# Dialogs: dialogs.license_dialog
LICENSE_DIALOG_LABEL_DEACTIVATE = "Deactivate"
LICENSE_DIALOG_LABEL_ACTIVATE = "Activate"
# Dialogs: dialogs.sql_connection_dialog
SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER_DATABASE_CREATOR = (
    "Connect to SQL Server - Database Creator"
)
SQL_CONNECTION_DIALOG_TITLE_CONNECT_TO_SQL_SERVER = "Connect to SQL Server"
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_ITEM_NEW_FOLDER = "New Folder"
# Dialogs: dialogs.sql_database_dialog
SQL_DATABASE_DIALOG_MESSAGE_SETUP_FAILED_UNEXPECTEDLY = (
    "SQL database setup failed unexpectedly. Inspect the server before retrying; no "
    "connection was registered or database dropped."
)
# Builders: builders.component_builder
COMPONENT_BUILDER_TOOLTIP_SELECT_A_VISIBLE_AREA_TAKEOFF_TO = (
    "Select a visible area takeoff to create a backout."
)
# Components: components.menu_builder
MENU_BUILDER_ACTION_TO_FILE = "To .{fmt} File"
MENU_BUILDER_ACTION_TO_CSV_FILE = "To .csv File"
MENU_BUILDER_ACTION_TO_PDF_FILE = "To .pdf File"
MENU_BUILDER_ACTION_TO_OST_FILE = "To .ost File"
MENU_BUILDER_ACTION_TO_OSP_FILE = "To .osp File"
MENU_BUILDER_MENU_NEW = "New"
MENU_BUILDER_ACTION_CLOSE = "Close"
MENU_BUILDER_MENU_IMPORT = "Import"
MENU_BUILDER_MENU_EXPORT = "Export"
MENU_BUILDER_ACTION_CHECK_AUTHORIZATION = "Check Authorization..."
MENU_BUILDER_ACTION_EXIT = "Exit"
MENU_BUILDER_ACTION_SELECT_OBJECTS_IN_CURRENT_AREA = "Select Objects in Current Area"
MENU_BUILDER_ACTION_SET_SCALE = "Set Scale..."
MENU_BUILDER_ACTION_RENAME_PAGE = "Rename Page..."
MENU_BUILDER_MENU_TOOLBARS = "Toolbars"
MENU_BUILDER_MENU_TAKEOFF = "Takeoff"
MENU_BUILDER_MENU_TABS = "Tabs"
MENU_BUILDER_ACTION_OPTIONS = "Options..."
MENU_BUILDER_ACTION_ADJUST_IMAGES = "Adjust Images"
MENU_BUILDER_ACTION_INVERT = "Invert"
MENU_BUILDER_ACTION_BITONAL = "Bitonal"
MENU_BUILDER_MENU_ROTATE_FLIP = "Rotate/Flip"
MENU_BUILDER_ACTION_REMOVE_OVERLAY_IMAGE = "Remove Overlay Image"
MENU_BUILDER_ACTION_SHOW_COVER_SHEET = "Show Cover Sheet"
MENU_BUILDER_ACTION_SHOW_AREAS = "Show Areas"
MENU_BUILDER_ACTION_RENUMBER_CONDITIONS = "Renumber Conditions"
MENU_BUILDER_ACTION_EMPLOYEES = "Employees"
MENU_BUILDER_ACTION_JOB_STATUSES = "Job Statuses"
MENU_BUILDER_ACTION_CONDITION_TYPES = "Condition Types"
MENU_BUILDER_ACTION_PAYROLL_CLASSES = "Payroll Classes"
MENU_BUILDER_ACTION_DEFAULT_LAYERS = "Default Layers"
MENU_BUILDER_ACTION_ABOUT_OST_VISUALIZER = "About OST Visualizer..."
MENU_BUILDER_ACTION_OST_FILE = ".ost File..."
MENU_BUILDER_ACTION_OSP_FILE = ".osp File..."
MENU_BUILDER_ACTION_SYNC_2D_3D_DISPLAY_MODES = "Sync 2D/3D Display Modes"
MENU_BUILDER_MENU_3D_DISPLAY_MODE = "3D Display Mode"
MENU_BUILDER_MENU_2D_DISPLAY_MODE = "2D Display Mode"
MENU_BUILDER_ACTION_GRAYSCALE = "Grayscale"
MENU_BUILDER_ACTION_2D = "2D"
MENU_BUILDER_ACTION_3D = "3D"
MENU_BUILDER_ACTION_ROTATE_TAKEOFF_LEFT = "Rotate Takeoff Left"
MENU_BUILDER_ACTION_ROTATE_TAKEOFF_RIGHT = "Rotate Takeoff Right"
MENU_BUILDER_ACTION_FLIP_TAKEOFF_HORIZONTAL = "Flip Takeoff Horizontal"
MENU_BUILDER_ACTION_FLIP_TAKEOFF_VERTICAL = "Flip Takeoff Vertical"
MENU_BUILDER_ACTION_ROTATE_IMAGE_LEFT = "Rotate Image Left"
MENU_BUILDER_ACTION_ROTATE_IMAGE_RIGHT = "Rotate Image Right"
MENU_BUILDER_ACTION_FLIP_IMAGE_HORIZONTAL = "Flip Image Horizontal"
MENU_BUILDER_ACTION_FLIP_IMAGE_VERTICAL = "Flip Image Vertical"
MENU_BUILDER_ACTION_TRANSPARENT = "Transparent"
MENU_BUILDER_ACTION_SOLID = "Solid"
MENU_BUILDER_ACTION_ORIGINAL = "Original"
MENU_BUILDER_MENU_FILE = "File"
MENU_BUILDER_MENU_EDIT = "Edit"
MENU_BUILDER_MENU_VIEW = "View"
MENU_BUILDER_MENU_TOOLS = "Tools"
MENU_BUILDER_MENU_IMAGE = "Image"
MENU_BUILDER_MENU_PROJECT = "Project"
MENU_BUILDER_MENU_MASTER = "Master"
MENU_BUILDER_MENU_HELP = "Help"
# Components: components.project_tree_view
PROJECT_TREE_VIEW_HEADER_NO = "No."
PROJECT_TREE_VIEW_HEADER_NAME = "Name"
PROJECT_TREE_VIEW_HEADER_STATUS = "Status"
PROJECT_TREE_VIEW_HEADER_BID_DATE = "Bid Date"
PROJECT_TREE_VIEW_HEADER_JOB_NO = "Job No."
PROJECT_TREE_VIEW_HEADER_ESTIMATOR = "Estimator"
PROJECT_TREE_VIEW_HEADER_PAGES = "Pages"
PROJECT_TREE_VIEW_HEADER_CONDITIONS = "Conditions"
PROJECT_TREE_VIEW_HEADER_NOTES = "Notes"
PROJECT_TREE_VIEW_HEADER_COPY_FROM = "Copy From"
PROJECT_TREE_VIEW_HEADER_COPY_TIMESTAMP = "Copy Timestamp"
PROJECT_TREE_VIEW_ACTION_RESTORE = "Restore"
PROJECT_TREE_VIEW_ACTION_RESTORE_BIDS = "Restore {bid_count} Bids"
# Components: components.status_panel
STATUS_PANEL_STATUS_NOT_ACTIVATED = "NOT ACTIVATED"
STATUS_PANEL_STATUS_ACTIVATED = "ACTIVATED"
STATUS_PANEL_STATUS_SQL_CONNECTING = "SQL: CONNECTING"
STATUS_PANEL_STATUS_SQL_SYNCING = "SQL: SYNCING"
STATUS_PANEL_STATUS_SQL_CONNECTED = "SQL: CONNECTED"
STATUS_PANEL_STATUS_SQL_DISCONNECTED = "SQL: DISCONNECTED"
STATUS_PANEL_STATUS_SQL_SIGN_IN_REQUIRED = "SQL: SIGN IN REQUIRED"
STATUS_PANEL_STATUS_SQL_READ_ONLY = "SQL: READ ONLY"
STATUS_PANEL_STATUS_SQL_CONFLICT = "SQL: CONFLICT"
STATUS_PANEL_STATUS_SQL_RELOAD_REQUIRED = "SQL: RELOAD REQUIRED"
STATUS_PANEL_STATUS_SQL_RECOVERING = "SQL: RECOVERING"
STATUS_PANEL_STATUS_SQL_COMMITTED_SYNCING = "SQL: COMMITTED, SYNCING"
STATUS_PANEL_STATUS_SQL_SAVING = "SQL: SAVING"
STATUS_PANEL_STATUS_SQL_COMMIT_UNKNOWN = "SQL: COMMIT UNKNOWN"
STATUS_PANEL_STATUS_SQL_VIEWING_EDITING = (
    "SQL: {viewer_count} VIEWING / {editor_count} EDITING"
)
# Coordinators: coordinators.toolbar_state_coordinator
TOOLBAR_STATE_COORDINATOR_TOOLTIP_CREATE_A_BACKOUT_IN_THE_SELECTED = (
    "Create a backout in the selected area takeoff"
)
TOOLBAR_STATE_COORDINATOR_TOOLTIP_SELECT_A_VISIBLE_AREA_TAKEOFF_TO = (
    "Select a visible area takeoff to create a backout."
)
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_MESSAGE_THE_OPERATION_COULD_NOT_BE_COMPLETED = (
    "The operation could not be completed."
)
# Dialogs: dialogs.ai_changeset_review_dialog
AI_CHANGESET_REVIEW_DIALOG_TITLE_REVIEW_AI_CHANGESET = "Review AI Changeset"
# Dialogs: dialogs.areas_dialog
AREAS_DIALOG_ITEM_EMPTY = "(empty)"
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_ITEM_X = '{name} ({lh:.1f}" x {lw:.1f}")'
COVER_SHEET_DIALOG_ITEM_X_2 = "{name} ({lh:.0f} x {lw:.0f})"
COVER_SHEET_DIALOG_NAME_FILES = "{total} files"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_TOOLTIP_CONDITION_STYLE_CANNOT_BE_CHANGED_AFTER = (
    "Condition style cannot be changed after takeoffs have been placed."
)
# Dialogs: dialogs.layers_dialog
LAYERS_DIALOG_MESSAGE_FAILED_TO_RENAME_LAYER = "Failed to rename layer."
LAYERS_DIALOG_MESSAGE_SOME_LAYERS_WERE_DELETED_BUT_ONE = (
    "Some layers were deleted, but one or more deletes failed."
)
LAYERS_DIALOG_MESSAGE_LAYERS_WERE_DELETED_BUT_THE_REFRESH = (
    "Layers were deleted, but the refresh failed."
)
LAYERS_DIALOG_MESSAGE_FAILED_TO_UPDATE_LAYER_VISIBILITY = (
    "Failed to update layer visibility."
)
LAYERS_DIALOG_MESSAGE_FAILED_TO_MOVE_LAYER = "Failed to move layer."
# Dialogs: dialogs.open_files_dialog
OPEN_FILES_DIALOG_FILE_FILTER_MICROSOFT_ACCESS_DATABASE_MDB = (
    "Microsoft Access Database (*.mdb)"
)
OPEN_FILES_DIALOG_MESSAGE_THIS_REMOVES_ONLY_THE_SAVED_CONNECTION = (
    "\n\nThis removes only the saved connection. The server database will not be "
    "deleted."
)
OPEN_FILES_DIALOG_MESSAGE_ARE_YOU_SURE_YOU_WANT_TO = (
    'Are you sure you want to remove "{item_name}" from the list?'
)
# Dialogs: dialogs.options.dialog
OPTIONS_DIALOG_MESSAGE_THIS_WILL_RESET_ALL_THE_PROGRAM = (
    "This will reset all the program options and window settings\nto the original "
    "defaults.\nThis cannot be undone. Do you want to reset these now?"
)
# Dialogs: dialogs.options.font_dialog
FONT_DIALOG_LABEL_AABBYYZZ = "AaBbYyZz"
# Dialogs: dialogs.options.fonts_colors_tab
FONTS_COLORS_TAB_ITEM_TEXT = "Text"
FONTS_COLORS_TAB_ITEM_AREA_LABEL = "Area Label"
FONTS_COLORS_TAB_ITEM_DIMENSION_LINE = "Dimension Line"
FONTS_COLORS_TAB_ITEM_DEFAULT_STYLE_LABEL = "Default Style Label"
FONTS_COLORS_TAB_ITEM_HIGHLIGHT = "Highlight"
FONTS_COLORS_TAB_ITEM_HOTLINK = "Hotlink"
FONTS_COLORS_TAB_ITEM_INACTIVE_OBJECTS = "Inactive Objects"
# Dialogs: dialogs.set_scale_dialog
SET_SCALE_DIALOG_TITLE_INVALID_SCALE = "Invalid Scale"
# Dialogs: dialogs.synchronization_conflict_dialog
SYNCHRONIZATION_CONFLICT_DIALOG_BUTTON_RELOAD = "Reload"
SYNCHRONIZATION_CONFLICT_DIALOG_BUTTON_DISCARD_DRAFT = "Discard Draft"
SYNCHRONIZATION_CONFLICT_DIALOG_BUTTON_CANCEL = "Cancel"
# Handlers: handlers.export_handler
EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_PAGE_TO = (
    "Successfully exported page to {filename}"
)
EXPORT_HANDLER_TITLE_EXPORT_PAGES_AS_PDF = "Export {valid_pages_count} Pages as PDF"
EXPORT_HANDLER_TITLE_EXPORT_PAGE_AS_PDF = "Export Page as PDF"
EXPORT_HANDLER_FILE_FILTER_ALL_FILES = "{format_name} (*.{extension});;All files (*.*)"
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE = (
    "Some bids were pasted, but the paste did not finish and the project tree "
    "could not be refreshed. Reopen the database before retrying."
)
PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE_2 = (
    "Some bids were pasted, but the paste did not finish. Review the refreshed "
    "project tree before retrying."
)
PROJECT_WRITE_HANDLER_MESSAGE_MOVE_THIS_BID_TO_DELETED_BIDS = (
    "Move this bid to Deleted Bids?\nYou can permanently delete it from there."
)
PROJECT_WRITE_HANDLER_MESSAGE_MOVE_BIDS_TO_DELETED_BIDS_YOU = "Move {bid_count} bids to Deleted Bids?\nYou can permanently delete them from there."
PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_BID_AND_ALL = (
    "Permanently delete this bid and all its data?\nThis cannot be undone."
)
PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_BIDS_AND_ALL_THEIR = (
    "Permanently delete {bid_count} bids and all their data?\nThis cannot be undone."
)
PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_EMPTY_PROJECT_THIS = (
    "Permanently delete this empty project?\nThis cannot be undone."
)
PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_EMPTY_PROJECTS_THIS_CANNOT = (
    "Permanently delete {project_count} empty projects?\nThis cannot be undone."
)
# Services: services.ai_sidecar_rebind_prompt
AI_SIDECAR_REBIND_PROMPT_LABEL_AI_TAKEOFF_LEVELS_AND_ASSUMPTIONS_WERE = (
    "AI takeoff levels and assumptions were saved for a bid with the same name and "
    "page count in another database file. Use them for this database?"
)
AI_SIDECAR_REBIND_PROMPT_TITLE_AI_TAKEOFF_DATA = "AI Takeoff Data"
# Services: services.ai_undo_refusal_notice
AI_UNDO_REFUSAL_NOTICE_BUTTON_DISCARD_ENTRY = "Discard Entry"
AI_UNDO_REFUSAL_NOTICE_MESSAGE_YOUR_OLDER_UNDO_STEPS_STAY_BLOCKED = (
    "Your older undo steps stay blocked while this entry is on top of the undo "
    "history. Discard Entry removes it from the history; the AI changes stay in "
    "the bid and can be edited or deleted by hand."
)
AI_UNDO_REFUSAL_NOTICE_TITLE_UNDO_AI_CHANGE = "Undo AI Change"
AI_UNDO_REFUSAL_NOTICE_MESSAGE_THE_ENTRY_COULD_NOT_BE_DISCARDED = (
    "The entry could not be discarded because another undo or redo is still "
    "running. Try again when it has finished."
)
# Services: services.undo_redo_service
UNDO_REDO_SERVICE_MESSAGE_THE_LOCAL_HISTORY_MUTATION_FAILED_BEFORE = (
    "The local history mutation failed before completion."
)
# Utils: utils.annotation_style_controls
ANNOTATION_STYLE_CONTROLS_ACTION_SELECT_FONT_COLOR = "Select Font Color..."
# Utils: utils.dialog
UTILS_DIALOG_TITLE_DELETE_ITEM = "Delete Item"
# Utils: utils.image_show_mode
IMAGE_SHOW_MODE_ITEM_ORIGINAL = "Original"
IMAGE_SHOW_MODE_ITEM_OVERLAY = "Overlay"
IMAGE_SHOW_MODE_ITEM_BOTH = "Both"
# Utils: utils.messagebox
MESSAGEBOX_BUTTON_GO_BACK = "Go Back"
MESSAGEBOX_BUTTON_SAVE_ANYWAY = "Save Anyway"
MESSAGEBOX_MESSAGE_THE_PAGE_CONTAINS_TAKEOFF_ANNOTATION_OR = (
    'The page "{page_name}" contains takeoff, annotation, or comments. Deleting '
    "this page will remove the page and anything on it, in the Base Bid, and any "
    "Alternates or Change Orders.\n\nDeleting a page cannot be undone. Are you "
    "sure you want to delete this page?"
)
# Utils: utils.named_view_validation
NAMED_VIEW_VALIDATION_MESSAGE_NAMED_VIEW_SHOULD_HAVE_A_UNIQUE = (
    "Named view should have a unique name."
)
# Utils: utils.overlay_context_menu
OVERLAY_CONTEXT_MENU_FILE_FILTER_IMAGES_PDF_TIF_TIFF_ALL_FILES = (
    "Images (*.pdf *.tif *.tiff);;All Files (*)"
)
# Builders: builders.component_builder
COMPONENT_BUILDER_LABEL_PAGE_SETTINGS = "Page settings"
COMPONENT_BUILDER_LABEL_ZOOM = "Zoom"
# Components: components.area_combo
AREA_COMBO_LABEL_UNASSIGNED = "(Unassigned)"
AREA_COMBO_LABEL_ALL_AREAS = "(All Areas)"
# Components: components.condition_summary
CONDITION_SUMMARY_LABEL_GROUP_BY_PAGE = "Group By Page"
CONDITION_SUMMARY_LABEL_GROUP_BY_TYPE = "Group By Type"
CONDITION_SUMMARY_LABEL_GROUP_BY_AREA = "Group By Area"
# Components: components.conditions_sidebar
CONDITIONS_SIDEBAR_LABEL_SELECT_OBJECTS = "Select Objects"
CONDITIONS_SIDEBAR_LABEL_FOLDER = "Folder"
CONDITIONS_SIDEBAR_LABEL_CONDITION = "Condition"
CONDITIONS_SIDEBAR_LABEL_CHANGE_PROPERTIES = "Change Properties"
CONDITIONS_SIDEBAR_LABEL_DELETE = "Delete"
CONDITIONS_SIDEBAR_LABEL_PASTE = "Paste"
CONDITIONS_SIDEBAR_LABEL_COPY = "Copy"
CONDITIONS_SIDEBAR_LABEL_CUT = "Cut"
CONDITIONS_SIDEBAR_LABEL_DUPLICATE_AND_REASSIGN_TAKEOFF = (
    "Duplicate and Reassign Takeoff"
)
CONDITIONS_SIDEBAR_LABEL_DUPLICATE = "Duplicate"
CONDITIONS_SIDEBAR_LABEL_RENAME = "Rename"
CONDITIONS_SIDEBAR_TITLE_SET_LAYER = "Set Layer"
CONDITIONS_SIDEBAR_TITLE_SET_TYPE = "Set Type"
CONDITIONS_SIDEBAR_LABEL_COLLAPSE_ALL_FOLDERS = "Collapse All Folders"
CONDITIONS_SIDEBAR_LABEL_EXPAND_ALL_FOLDERS = "Expand All Folders"
CONDITIONS_SIDEBAR_LABEL_COLLAPSE_ALL_TYPES = "Collapse All Types"
CONDITIONS_SIDEBAR_LABEL_EXPAND_ALL_TYPES = "Expand All Types"
CONDITIONS_SIDEBAR_LABEL_GROUP_BY_TYPE = "Group by Type"
# Components: components.plan_view.view
PLAN_VIEW_VIEW_TOOLTIP_ALIGN_RIGHT = "Align right"
PLAN_VIEW_VIEW_TOOLTIP_ALIGN_CENTER = "Align center"
PLAN_VIEW_VIEW_TOOLTIP_ALIGN_LEFT = "Align left"
PLAN_VIEW_VIEW_TOOLTIP_UNDERLINE = "Underline"
PLAN_VIEW_VIEW_TOOLTIP_ITALIC = "Italic"
PLAN_VIEW_VIEW_TOOLTIP_BOLD = "Bold"
# Components: components.project_tree_view
PROJECT_TREE_VIEW_LABEL_DELETE = "Delete"
PROJECT_TREE_VIEW_LABEL_DUPLICATE = "Duplicate"
PROJECT_TREE_VIEW_LABEL_CLOSE = "Close"
PROJECT_TREE_VIEW_LABEL_OPEN = "Open..."
PROJECT_TREE_VIEW_LABEL_DATABASE = "Database"
PROJECT_TREE_VIEW_LABEL_FOLDER = "Folder"
PROJECT_TREE_VIEW_LABEL_PROJECT = "Project"
PROJECT_TREE_VIEW_LABEL_FILE = ".{format_key} File..."
PROJECT_TREE_VIEW_LABEL_TO_OSP_FILE = "To .osp File"
PROJECT_TREE_VIEW_LABEL_TO_OST_FILE = "To .ost File"
PROJECT_TREE_VIEW_LABEL_TO_PDF_FILE = "To .pdf File"
PROJECT_TREE_VIEW_LABEL_TO_FILE = "To .{fmt} File"
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_TITLE_DEFAULT_LAYERS = "Default Layers"
UI_EVENT_COORDINATOR_MESSAGE_CHANGED_IN_ANOTHER_SESSION_RELOAD_THE = (
    "{resource_type} {resource_id} changed in another session. Reload the database "
    "before saving again."
)
UI_EVENT_COORDINATOR_MESSAGE_LOADING_BID_PAGES = "Loading bid pages..."
UI_EVENT_COORDINATOR_TITLE_ADJUST_IMAGES = "Adjust Images"
UI_EVENT_COORDINATOR_TITLE_SET_SCALE = "Set Scale"
UI_EVENT_COORDINATOR_TITLE_LAYER_CREATION = "Layer Creation"
UI_EVENT_COORDINATOR_TITLE_LAYER_UPDATE = "Layer Update"
# Dialogs: dialogs.ai_changeset_review_dialog
AI_CHANGESET_REVIEW_DIALOG_LABEL_ACCEPT = "Accept"
AI_CHANGESET_REVIEW_DIALOG_LABEL_REJECT = "Reject"
AI_CHANGESET_REVIEW_DIALOG_LABEL_LEVELS_AND_ASSUMPTIONS_ARE_STORED_ON = (
    "Levels and assumptions are stored on this computer only; other users of this "
    "SQL database will not see them."
)
AI_CHANGESET_REVIEW_DIALOG_LABEL_AN_AI_CLIENT_ASKED_TO_APPLY = (
    "An AI client asked to apply these changes to the open bid. Nothing is written "
    "until you accept. Text from the AI and from drawings is shown as it was "
    "received."
)
AI_CHANGESET_REVIEW_DIALOG_LABEL_OVERRIDE = "Override"
# Dialogs: dialogs.condition_types_dialog
CONDITION_TYPES_DIALOG_LABEL_DELETE = "Delete"
CONDITION_TYPES_DIALOG_LABEL_NEW = "New"
CONDITION_TYPES_DIALOG_LABEL_CANCEL = "Cancel"
CONDITION_TYPES_DIALOG_LABEL_OK = "OK"
CONDITION_TYPES_DIALOG_LABEL_SELECT = "Select"
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_LABEL_BID_TIME = "Bid time:"
COVER_SHEET_DIALOG_LABEL_BID_DATE = "Bid date:"
COVER_SHEET_DIALOG_LABEL_ESTIMATOR = "Estimator:"
COVER_SHEET_DIALOG_LABEL_JOB_NO = "Job No.:"
COVER_SHEET_DIALOG_LABEL_PROJECT_NAME = "Project name:"
COVER_SHEET_DIALOG_LABEL_NO = "No.:"
COVER_SHEET_DIALOG_LABEL_JOB_STATUS = "Job status:"
COVER_SHEET_DIALOG_TOOLTIP_DELETE = "Delete"
COVER_SHEET_DIALOG_TOOLTIP_DUPLICATE_PAGES = "Duplicate pages"
COVER_SHEET_DIALOG_TOOLTIP_INSERT_NEW_IMAGE_PAGE = "Insert new image page"
COVER_SHEET_DIALOG_TOOLTIP_INSERT_NEW_BLANK_PAGE = "Insert new blank page"
COVER_SHEET_DIALOG_TOOLTIP_NEW_FOLDER = "New folder"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_LABEL_COND_NO = "Cond. No."
EDIT_CONDITION_DIALOG_LABEL_ELEVATION = "Elevation"
EDIT_CONDITION_DIALOG_LABEL_LAYER = "Layer"
EDIT_CONDITION_DIALOG_LABEL_NAME = "Name"
EDIT_CONDITION_DIALOG_LABEL_TYPE = "Type"
EDIT_CONDITION_DIALOG_LABEL_STYLE = "Style"
EDIT_CONDITION_DIALOG_LABEL_DISPLAY_SIZE = "Display Size %"
EDIT_CONDITION_DIALOG_LABEL_SLOPE = "Slope"
EDIT_CONDITION_DIALOG_LABEL_DEPTH = "Depth"
EDIT_CONDITION_DIALOG_LABEL_SHAPE = "Shape"
EDIT_CONDITION_DIALOG_LABEL_SPACING = "Spacing"
EDIT_CONDITION_DIALOG_LABEL_PATTERN = "Pattern"
EDIT_CONDITION_DIALOG_LABEL_COLOR = "Color"
EDIT_CONDITION_DIALOG_LABEL_UOM = "UOM"
EDIT_CONDITION_DIALOG_LABEL_QUANTITY = "Quantity {number}"
EDIT_CONDITION_DIALOG_LABEL_GAP = "Gap"
EDIT_CONDITION_DIALOG_LABEL_TILE = "Tile"
EDIT_CONDITION_DIALOG_LABEL_ROUND_TO = "Round to"
EDIT_CONDITION_DIALOG_LABEL_ADD_LENGTH = "Add Length"
# Dialogs: dialogs.employee_detail_dialog
EMPLOYEE_DETAIL_DIALOG_LABEL_E_MAIL = "E-mail:"
EMPLOYEE_DETAIL_DIALOG_LABEL_MOBILE_PHONE = "Mobile phone:"
EMPLOYEE_DETAIL_DIALOG_LABEL_HOME_PHONE = "Home phone:"
EMPLOYEE_DETAIL_DIALOG_LABEL_STATE = "State:"
EMPLOYEE_DETAIL_DIALOG_LABEL_ZIP = "Zip:"
EMPLOYEE_DETAIL_DIALOG_LABEL_CITY = "City:"
EMPLOYEE_DETAIL_DIALOG_LABEL_ADDRESS_2 = "Address 2:"
EMPLOYEE_DETAIL_DIALOG_LABEL_ADDRESS_1 = "Address 1:"
EMPLOYEE_DETAIL_DIALOG_LABEL_PAY_CLASS = "Pay class:"
EMPLOYEE_DETAIL_DIALOG_LABEL_LAST_NAME = "Last name:"
EMPLOYEE_DETAIL_DIALOG_LABEL_EMP_NO = "Emp. No.:"
EMPLOYEE_DETAIL_DIALOG_LABEL_FIRST_NAME = "First name:"
# Dialogs: dialogs.layers_dialog
LAYERS_DIALOG_LABEL_MOVE_DOWN = "Move Down"
LAYERS_DIALOG_LABEL_MOVE_UP = "Move Up"
LAYERS_DIALOG_LABEL_DELETE = "Delete"
LAYERS_DIALOG_LABEL_NEW = "New"
LAYERS_DIALOG_LABEL_UNCHECK_ALL = "Uncheck All"
LAYERS_DIALOG_LABEL_CHECK_ALL = "Check All"
LAYERS_DIALOG_LABEL_CANCEL = "Cancel"
LAYERS_DIALOG_LABEL_SELECT = "Select"
LAYERS_DIALOG_LABEL_OK = "OK"
# Dialogs: dialogs.new_database_type_dialog
NEW_DATABASE_TYPE_DIALOG_TITLE_MICROSOFT_SQL_SERVER_DATABASE = (
    "Microsoft SQL Server Database"
)
NEW_DATABASE_TYPE_DIALOG_LABEL_CLICK_HERE_IF_YOU_ARE_A = (
    "Click here if you are a member of the company IT Department\nand are wanting "
    "to setup an enterprise database server."
)
NEW_DATABASE_TYPE_DIALOG_TITLE_MICROSOFT_ACCESS_DATABASE_MOST_USERS = (
    "Microsoft Access Database (Most Users)"
)
NEW_DATABASE_TYPE_DIALOG_LABEL_CLICK_HERE_IF_YOU_ARE_A_2 = (
    "Click here if you are a standard user and are not sure which\noption is best."
)
# Dialogs: dialogs.options.mcp_setup_tab
MCP_SETUP_TAB_LABEL_AI_TAKEOFF_FOR_CLAUDE_DESKTOP_OR = (
    "AI takeoff for Claude Desktop or Cursor"
)
MCP_SETUP_TAB_BUTTON_COPY_AI_TAKEOFF_JSON = "Copy AI Takeoff JSON"
MCP_SETUP_TAB_LABEL_AI_TAKEOFF_PREVIEW = "AI takeoff (preview)"
MCP_SETUP_TAB_LABEL_CODEX_CLI_COMMAND = "Codex CLI command"
MCP_SETUP_TAB_BUTTON_COPY_SETUP_COMMAND = "Copy Setup Command"
MCP_SETUP_TAB_LABEL_CODEX_CONFIG_TOML = "Codex config.toml"
MCP_SETUP_TAB_BUTTON_COPY_CODEX_TOML = "Copy Codex TOML"
MCP_SETUP_TAB_LABEL_CODEX = "Codex"
MCP_SETUP_TAB_LABEL_CLAUDE_DESKTOP_OR_CURSOR = "Claude Desktop or Cursor"
MCP_SETUP_TAB_BUTTON_COPY_SETUP_JSON = "Copy Setup JSON"
# Dialogs: dialogs.options.takeoff_toolbar_tab
TAKEOFF_TOOLBAR_TAB_LABEL_PAGE_SETTINGS = "Page Settings"
TAKEOFF_TOOLBAR_TAB_LABEL_VIEW_CONTROLS = "View controls"
TAKEOFF_TOOLBAR_TAB_LABEL_CURSOR_TOOLS = "Cursor tools"
TAKEOFF_TOOLBAR_TAB_LABEL_PAGE_NAVIGATION = "Page navigation"
TAKEOFF_TOOLBAR_TAB_LABEL_ANNOTATION_TOOLS = "Annotation tools"
# Handlers: handlers.condition_action_handler
CONDITION_ACTION_HANDLER_TITLE_CONDITION_TYPES = "Condition Types"
CONDITION_ACTION_HANDLER_TITLE_CREATE_CONDITION = "Create Condition"
CONDITION_ACTION_HANDLER_TITLE_MOVE_CONDITIONS = "Move Conditions"
CONDITION_ACTION_HANDLER_TITLE_DELETE_CONDITIONS = "Delete Conditions"
CONDITION_ACTION_HANDLER_TITLE_CREATE_CONDITION_FOLDER = "Create Condition Folder"
CONDITION_ACTION_HANDLER_TITLE_RENAME_CONDITION_FOLDER = "Rename Condition Folder"
CONDITION_ACTION_HANDLER_TITLE_RENAME_CONDITION = "Rename Condition"
CONDITION_ACTION_HANDLER_TITLE_DELETE_CONDITION_FOLDERS = "Delete Condition Folders"
CONDITION_ACTION_HANDLER_TITLE_MOVE_CONDITION = "Move Condition"
CONDITION_ACTION_HANDLER_TITLE_UPDATE_CONDITIONS = "Update Conditions"
CONDITION_ACTION_HANDLER_TITLE_SAVE_CONDITION = "Save Condition"
# Handlers: handlers.export_handler
EXPORT_HANDLER_TITLE_EXPORT_BID_AS_OST = "Export Bid as OST"
EXPORT_HANDLER_TITLE_EXPORT_BID_AS_OSP_PACKAGE = "Export Bid as OSP Package"
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_BID = "Duplicate Bid"
PROJECT_WRITE_HANDLER_TITLE_RENAME_PROJECT = "Rename Project"
PROJECT_WRITE_HANDLER_TITLE_NEW_PROJECT = "New Project"
PROJECT_WRITE_HANDLER_TITLE_MOVE_BIDS = "Move Bids"
PROJECT_WRITE_HANDLER_TITLE_PASTE_BIDS = "Paste Bids"
PROJECT_WRITE_HANDLER_TITLE_RESTORE_BIDS = "Restore Bids"
# Services: services.ai_changeset_applier
AI_CHANGESET_APPLIER_MESSAGE_AI_CHANGESETS_CANNOT_BE_REDONE_ASK = (
    "AI changesets cannot be redone. Ask the AI to propose it again."
)
# Utils: utils.overlay_context_menu
OVERLAY_CONTEXT_MENU_LABEL_OVERLAY = "Overlay"
# Utils: utils.view_context_menu
VIEW_CONTEXT_MENU_TITLE_ROTATE_FLIP = "Rotate/Flip"
VIEW_CONTEXT_MENU_TITLE_ZOOM = "Zoom"
VIEW_CONTEXT_MENU_TITLE_TOOLS = "Tools"
# Components: components.mesh_view
MESH_VIEW_LABEL_PASTE = "Paste"
# Components: components.plan_view.components.input_handler
INPUT_HANDLER_LABEL_DELETE = "Delete"
INPUT_HANDLER_LABEL_PASTE = "Paste"
# Utils: utils.view_context_menu
VIEW_CONTEXT_MENU_LABEL_DELETE_PAGE = "Delete Page"
VIEW_CONTEXT_MENU_LABEL_RENAME_PAGE = "Rename Page..."
# Components: components.condition_summary
CONDITION_SUMMARY_HEADER_NO = "No."
CONDITION_SUMMARY_HEADER_NAME = "Name"
CONDITION_SUMMARY_HEADER_HEIGHT = "Height"
CONDITION_SUMMARY_HEADER_AREA = "Area"
CONDITION_SUMMARY_HEADER_QUANTITY_1 = "Quantity 1"
CONDITION_SUMMARY_HEADER_QUANTITY_2 = "Quantity 2"
CONDITION_SUMMARY_HEADER_QUANTITY_3 = "Quantity 3"
CONDITION_SUMMARY_HEADER_NOTES = "Notes"
# Components: components.pan_sidebar
PAN_SIDEBAR_LABEL_NO_PAGE_OPEN = "No page open"
# Components: components.splash_screen
SPLASH_SCREEN_TITLE_OST_VISUALIZER = "OST Visualizer"
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_ACTION_REPLACE_OVERLAY_IMAGE = "Replace Overlay Image"
UI_EVENT_COORDINATOR_ACTION_REMOVE_OVERLAY_IMAGE = "Remove Overlay Image"
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_ITEM_CUSTOM = "Custom"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_MESSAGE_USE_METERS_OR_CENTIMETERS_FOR_EXAMPLE = (
    'Use meters or centimeters, for example "3.2 m" or "320 cm".'
)
EDIT_CONDITION_DIALOG_MESSAGE_USE_FEET_AND_INCHES_WITH_UNIT = (
    "Use feet and inches with unit marks, for example 10' 6\"."
)
# Dialogs: dialogs.job_statuses_dialog
JOB_STATUSES_DIALOG_TITLE_JOB_STATUSES = "Job Statuses"
# Dialogs: dialogs.license_dialog
LICENSE_DIALOG_STATUS_HARDWARE_ID_UNAVAILABLE = "Hardware ID Unavailable"
LICENSE_DIALOG_STATUS_ACTIVATED = "Activated"
LICENSE_DIALOG_STATUS_NOT_ACTIVATED = "Not Activated"
# Dialogs: dialogs.payroll_class_dialog
PAYROLL_CLASS_DIALOG_TITLE_PAYROLL_CLASS_LIST = "Payroll Class List"
# Services: services.ai_changeset_approval
AI_CHANGESET_APPROVAL_MESSAGE_THE_CHANGE_COULD_NOT_BE_APPLIED = (
    "The change could not be applied. Nothing was accepted; ask the AI to propose "
    "it again."
)
# Services: services.ai_sidecar_rebind_prompt
AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_OPEN_BID_CHANGED_BEFORE_YOU = (
    "The open bid changed before you confirmed, so nothing was rebound. You will "
    "be asked again for that bid."
)
AI_SIDECAR_REBIND_PROMPT_MESSAGE_REBOUND = "Rebound."
# Services: services.ai_takeoff_bridge
AI_TAKEOFF_BRIDGE_MESSAGE_OST_VISUALIZER_IS_BUSY_WITH_OTHER = (
    "OST Visualizer is busy with other AI takeoff requests. Try again shortly."
)
# Services: services.annotation_history
ANNOTATION_HISTORY_MESSAGE_A_HOTLINK_CANNOT_BE_RESTORED_BECAUSE = (
    "A hotlink cannot be restored because the Named View it points to is no longer "
    "the same Named View: it was deleted without being restored, or another Named "
    "View took its place."
)
# Utils: utils.annotation_delete
ANNOTATION_DELETE_MESSAGE_THIS_NAMED_VIEW_HAS_HOTLINKS_CONNECTED = (
    "This named view has hotlinks connected to it.\nDo you want to delete it and "
    "the associated hotlinks?"
)
# Utils: utils.messagebox
MESSAGEBOX_MESSAGE_THE_DATABASE_MAY_BE_LOCKED_BY = (
    "The database may be locked by another application."
)
# Utils: utils.view_context_menu
VIEW_CONTEXT_MENU_ACTION_BACKOUT = "Backout"
VIEW_CONTEXT_MENU_ACTION_ROTATE_TAKEOFF_LEFT = "Rotate Takeoff Left"
VIEW_CONTEXT_MENU_ACTION_ROTATE_TAKEOFF_RIGHT = "Rotate Takeoff Right"
VIEW_CONTEXT_MENU_ACTION_FLIP_TAKEOFF_HORIZONTAL = "Flip Takeoff Horizontal"
VIEW_CONTEXT_MENU_ACTION_FLIP_TAKEOFF_VERTICAL = "Flip Takeoff Vertical"
VIEW_CONTEXT_MENU_ACTION_ROTATE_IMAGE_LEFT = "Rotate Image Left"
VIEW_CONTEXT_MENU_ACTION_ROTATE_IMAGE_RIGHT = "Rotate Image Right"
VIEW_CONTEXT_MENU_ACTION_FLIP_IMAGE_HORIZONTAL = "Flip Image Horizontal"
VIEW_CONTEXT_MENU_ACTION_FLIP_IMAGE_VERTICAL = "Flip Image Vertical"
VIEW_CONTEXT_MENU_ACTION_CUT = "Cut"
VIEW_CONTEXT_MENU_ACTION_COPY = "Copy"
VIEW_CONTEXT_MENU_ACTION_PASTE = "Paste"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_ITEM_LINEAR = "Linear"
EDIT_CONDITION_DIALOG_ITEM_AREA = "Area"
EDIT_CONDITION_DIALOG_ITEM_COUNT = "Count"
EDIT_CONDITION_DIALOG_ITEM_ATTACHMENT = "Attachment"
EDIT_CONDITION_DIALOG_ITEM_SQUARE = "Square"
EDIT_CONDITION_DIALOG_ITEM_CIRCLE = "Circle"
EDIT_CONDITION_DIALOG_ITEM_TRIANGLE = "Triangle"
EDIT_CONDITION_DIALOG_ITEM_RECTANGLE = "Rectangle"
EDIT_CONDITION_DIALOG_ITEM_ELLIPSE = "Ellipse"
EDIT_CONDITION_DIALOG_ITEM_DIAMOND = "Diamond"
EDIT_CONDITION_DIALOG_ITEM_HEXAGON = "Hexagon"
EDIT_CONDITION_DIALOG_ITEM_OCTAGON = "Octagon"
EDIT_CONDITION_DIALOG_ITEM_NONE = "None"
EDIT_CONDITION_DIALOG_ITEM_SOLID = "Solid"
EDIT_CONDITION_DIALOG_ITEM_HORIZONTAL = "Horizontal"
EDIT_CONDITION_DIALOG_ITEM_VERTICAL = "Vertical"
EDIT_CONDITION_DIALOG_ITEM_BACKWARD_DIAGONAL = "Backward Diagonal"
EDIT_CONDITION_DIALOG_ITEM_FORWARD_DIAGONAL = "Forward Diagonal"
EDIT_CONDITION_DIALOG_ITEM_CROSSHATCH = "Crosshatch"
EDIT_CONDITION_DIALOG_ITEM_DIAGONAL_CROSSHATCH = "Diagonal Crosshatch"
EDIT_CONDITION_DIALOG_ITEM_TRANSPARENT = "Transparent"
# Dialogs: dialogs.set_scale_dialog
SET_SCALE_DIALOG_ITEM_ARCHITECTURAL = "Architectural"
SET_SCALE_DIALOG_ITEM_CIVIL = "Civil"
SET_SCALE_DIALOG_ITEM_METRIC = "Metric"
# Dialogs: dialogs.update_dialog
UPDATE_DIALOG_ITEM_ADDED = "Added"
UPDATE_DIALOG_ITEM_CHANGED = "Changed"
UPDATE_DIALOG_ITEM_FIXED = "Fixed"
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_LABEL_PROJECT_DATA = "project data"
PROJECT_WRITE_HANDLER_LABEL_BID_DATA = "bid data"
PROJECT_WRITE_HANDLER_LABEL_PROJECT_ASSIGNMENT = "project assignment"
PROJECT_WRITE_HANDLER_LABEL_BID_OF = "bid {index} of {total}"
# Controllers: controllers.menu_controller
MENU_CONTROLLER_TITLE_JOB_STATUSES = "Job Statuses"
MENU_CONTROLLER_TITLE_EMPLOYEES = "Employees"
MENU_CONTROLLER_TITLE_PAYROLL_CLASSES = "Payroll Classes"
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_TITLE_EMPLOYEES = "Employees"
UI_EVENT_COORDINATOR_TITLE_PAYROLL_CLASSES = "Payroll Classes"
UI_EVENT_COORDINATOR_TITLE_JOB_STATUSES = "Job Statuses"
UI_EVENT_COORDINATOR_TITLE_NEW_DEFAULT_LAYER = "New Default Layer"
UI_EVENT_COORDINATOR_TITLE_DELETE_DEFAULT_LAYER = "Delete Default Layer"
# Dialogs: dialogs.adjust_images_dialog
ADJUST_IMAGES_DIALOG_ITEM_ORIGINAL_ROTATION = "Original rotation"
ADJUST_IMAGES_DIALOG_ITEM_90_COUNTERCLOCKWISE = "90 (counterclockwise)"
ADJUST_IMAGES_DIALOG_ITEM_270_90_CLOCKWISE = "270 (90 clockwise)"
# Handlers: handlers.condition_action_handler
CONDITION_ACTION_HANDLER_TITLE_NEW_LAYER = "New Layer"
CONDITION_ACTION_HANDLER_TITLE_DELETE_LAYER = "Delete Layer"
CONDITION_ACTION_HANDLER_TITLE_RENAME_LAYER = "Rename Layer"
CONDITION_ACTION_HANDLER_TITLE_MOVE_LAYER = "Move Layer"
# Handlers: handlers.cover_sheet_handler
COVER_SHEET_HANDLER_TITLE_JOB_STATUSES = "Job Statuses"
COVER_SHEET_HANDLER_TITLE_EMPLOYEES = "Employees"
COVER_SHEET_HANDLER_TITLE_PAYROLL_CLASSES = "Payroll Classes"
# Services: services.ai_changeset_approval
AI_CHANGESET_APPROVAL_MESSAGE_THE_CHANGESET_COULD_NOT_BE_APPLIED = (
    "The changeset could not be applied."
)
# Components: components.project_tree_view
PROJECT_TREE_VIEW_ITEM_BID = "Bid {uid}"
# Coordinators: coordinators.ui_event_coordinator
UI_EVENT_COORDINATOR_ITEM_PAGE = "Page {uid}"
# Dialogs: dialogs.ai_changeset_review_dialog
AI_CHANGESET_REVIEW_DIALOG_HEADER_SUBJECT = "Subject"
AI_CHANGESET_REVIEW_DIALOG_HEADER_IMPACT = "Impact"
AI_CHANGESET_REVIEW_DIALOG_HEADER_PROPOSED = "Proposed"
AI_CHANGESET_REVIEW_DIALOG_HEADER_REASON = "Reason"
AI_CHANGESET_REVIEW_DIALOG_HEADER_SHEET = "Sheet"
AI_CHANGESET_REVIEW_DIALOG_HEADER_STATUS = "Status"
AI_CHANGESET_REVIEW_DIALOG_HEADER_CONDITION = "Condition"
AI_CHANGESET_REVIEW_DIALOG_HEADER_TAKEOFFS = "Takeoffs"
AI_CHANGESET_REVIEW_DIALOG_HEADER_AREA_SF = "Area (SF)"
AI_CHANGESET_REVIEW_DIALOG_HEADER_VOLUME_CY = "Volume (CY)"
# Dialogs: dialogs.cover_sheet.dialog
COVER_SHEET_DIALOG_ITEM_UNAVAILABLE = "{page_index} (Unavailable)"
# Dialogs: dialogs.edit_condition_dialog
EDIT_CONDITION_DIALOG_LABEL_TILE_X = "Tile X"
EDIT_CONDITION_DIALOG_LABEL_TILE_Y = "Tile Y"
# Dialogs: dialogs.employee_detail_dialog
EMPLOYEE_DETAIL_DIALOG_MESSAGE_FIRST_NAME_IS_REQUIRED = "First Name is required."
EMPLOYEE_DETAIL_DIALOG_MESSAGE_LAST_NAME_IS_REQUIRED = "Last Name is required."
EMPLOYEE_DETAIL_DIALOG_MESSAGE_EMPLOYEE_NUMBER_IS_REQUIRED = (
    "Employee Number is required."
)
EMPLOYEE_DETAIL_DIALOG_MESSAGE_EMPLOYEE_NUMBER_IS_ALREADY_IN_USE = (
    "Employee Number is already in use by another employee."
)
# Dialogs: dialogs.open_files_dialog
OPEN_FILES_DIALOG_ITEM_ACCESS = "Access"
OPEN_FILES_DIALOG_ITEM_KB = "{size_kb:,} KB"
OPEN_FILES_DIALOG_ITEM_KB_2 = "{size_kb:,.2f} KB"
# Dialogs: dialogs.options.mcp_setup_tab
MCP_SETUP_TAB_STATUS_READY_TO_CONNECT_CHECKED_OST_VISUALIZER = (
    "Ready to connect checked OST Visualizer files."
)
MCP_SETUP_TAB_STATUS_READY_AFTER_YOU_CHECK_AT_LEAST = (
    "Ready after you check at least one OST Visualizer file."
)
MCP_SETUP_TAB_STATUS_MCP_HELPER_IS_NOT_INSTALLED_YET = (
    "MCP helper is not installed yet."
)
MCP_SETUP_TAB_STATUS_COPIED_TO_CLIPBOARD = "Copied to clipboard."
# Dialogs: dialogs.options.options_tab
OPTIONS_TAB_TITLE_CROSSHAIR_COLOR = "Crosshair Color"
# Handlers: handlers.condition_action_handler
CONDITION_ACTION_HANDLER_MESSAGE_FAILED_TO_SAVE_CONDITION = "Failed to save condition."
# Handlers: handlers.export_handler
EXPORT_HANDLER_ITEM_PAGE = "Page"
# Handlers: handlers.file_operation_handler
FILE_OPERATION_HANDLER_MESSAGE_OPENING_COULD_NOT_COMPLETE = (
    "Opening could not complete."
)
FILE_OPERATION_HANDLER_MESSAGE_A_CRITICAL_DATABASE_SETTING_COULD_NOT_4 = (
    "A critical database setting could not be submitted before unload."
)
FILE_OPERATION_HANDLER_MESSAGE_OPENING_HAS_NOT_COMPLETED_WITHIN_THE = (
    "Opening has not completed within the waiting period."
)
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_LABEL_SELECTED_BID = "selected bid"
# Main window: main_window
MAIN_WINDOW_NAME_PROJECT_FILES = "{files_count} project files"
MAIN_WINDOW_MESSAGE_SUCCESSFULLY_IMPORTED_INTO_THE_DATABASE = (
    'Successfully imported "{source_path}" into the database.'
)
MAIN_WINDOW_MESSAGE_SUCCESSFULLY_IMPORTED_AS_ORPHANED_BECAUSE_CANNOT = (
    'Successfully imported "{source_path}" as orphaned because '
    "{deleted_bids_project_name} cannot be used as an import target."
)
MAIN_WINDOW_MESSAGE_AI_TAKEOFF_IS_TURNED_OFF_OR = (
    "AI takeoff is turned off or unavailable for the open bid. Turn it on in Tools "
    "> Options > MCP Setup."
)
MAIN_WINDOW_MESSAGE_YOU_CANNOT_MAKE_THIS_CHANGE_IN = (
    "You cannot make this change in the open bid."
)
MAIN_WINDOW_MESSAGE_SQL_COLLABORATION_RESOURCES_COULD_NOT_BE = (
    "SQL collaboration resources could not be closed safely."
)
MAIN_WINDOW_MESSAGE_THE_FILE_COULD_NOT_BE_IMPORTED = "The file could not be imported."
MAIN_WINDOW_MESSAGE_IMPORT_IS_NOT_AVAILABLE_FOR_THE = (
    "Import is not available for the selected database."
)
# Services: services.ai_changeset_applier
AI_CHANGESET_APPLIER_MESSAGE_THE_CHANGE_WAS_NOT_SAVED = "The change was not saved."
AI_CHANGESET_APPLIER_MESSAGE_SOMETHING_THIS_CHANGESET_CREATED_WAS_EDITED = (
    "Something this changeset created was edited since. Undo it by hand."
)
AI_CHANGESET_APPLIER_MESSAGE_THE_BID_IS_LOCKED = "The bid is locked."
AI_CHANGESET_APPLIER_MESSAGE_THE_SCALE_WAS_NOT_SAVED = "The scale was not saved."
# Utils: utils.annotation_style_controls
ANNOTATION_STYLE_CONTROLS_ACTION_LEFT = "Left"
ANNOTATION_STYLE_CONTROLS_ACTION_CENTER = "Center"
ANNOTATION_STYLE_CONTROLS_ACTION_RIGHT = "Right"
# Utils: utils.plan_tool_registry
PLAN_TOOL_REGISTRY_LABEL_PAGE_SELECTOR = "Page selector"
PLAN_TOOL_REGISTRY_LABEL_ZOOM_PERCENTAGE = "Zoom percentage"
PLAN_TOOL_REGISTRY_LABEL_PAGE_SETTINGS_SCALE_AND_AREA = "Page Settings (Scale and Area)"
# Visualization: visualization.exporters.osp_exporter
OSP_EXPORTER_STATUS_BUILDING_OST = "Building OST"
OSP_EXPORTER_STATUS_WRITING_METADATA = "Writing metadata"
OSP_EXPORTER_STATUS_COLLECTING_IMAGES = "Collecting images"
OSP_EXPORTER_STATUS_PACKAGING_ARCHIVE = "Packaging archive"
OSP_EXPORTER_MESSAGE_EXPORT_FAILED = "Export failed: {error}"
OSP_EXPORTER_MESSAGE_CANNOT_EXPORT_OSP_BECAUSE_REFERENCED_DRAWING = (
    "Cannot export OSP because referenced drawing files are missing: {preview}"
)
OSP_EXPORTER_MESSAGE_FAILED_TO_GENERATE_OST_FILE = "Failed to generate .ost file"
OSP_EXPORTER_MESSAGE_FAILED_TO_CREATE_CAB_ARCHIVE = "Failed to create CAB archive"
# Visualization: visualization.exporters.pdf_exporter
PDF_EXPORTER_MESSAGE_NO_VALID_PAGES_TO_EXPORT = "No valid pages to export."
PDF_EXPORTER_MESSAGE_FAILED_TO_WRITE_PDF = "Failed to write PDF."
# Visualization: visualization.renderers.threejs.threejs_renderer
THREEJS_RENDERER_TITLE_OST_TAKEOFF_3D_VISUALIZATION = "OST Takeoff 3D Visualization"
# Components: components.page_combo
PAGE_COMBO_LABEL_PAGES = "{page_count} pages"
# Handlers: handlers.project_write_handler
PROJECT_WRITE_HANDLER_NAME_BIDS = "{bid_count} bids"
# Components: components.color_button
COLOR_BUTTON_TITLE_SELECT_COLOR = "Select Color"
# Controllers: controllers.menu_controller
MENU_CONTROLLER_ACTION_DELETE_PAGE = "Delete Page"
# Dialogs: dialogs.job_statuses_dialog
JOB_STATUSES_DIALOG_TITLE_DELETE_JOB_STATUS = "Delete Job Status"
# Dialogs: dialogs.payroll_class_dialog
PAYROLL_CLASS_DIALOG_TITLE_DELETE_PAY_CLASS = "Delete Pay Class"
# Utils: utils.dialog
UTILS_DIALOG_BUTTON_SELECT = "Select"

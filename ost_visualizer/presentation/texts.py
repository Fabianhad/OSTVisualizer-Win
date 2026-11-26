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
CONDITION_TYPES_DIALOG_MESSAGE_CONDITION_TYPE_ALREADY_EXISTS_2 = (
    "Condition type {name} already exists."
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
    "Cannot delete {text} because it is not empty.\n\nPlease remove all pages from "
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
    '"{text}" is not a valid dimension for {label}.'
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
LAYERS_DIALOG_MESSAGE_LAYER_ALREADY_EXISTS_2 = "Layer {name} already exists."
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
    'The {label} custom scale value "{text}" is not a valid number.'
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
CONDITION_ACTION_HANDLER_MESSAGE_THE_CONDITION_WAS_CREATED_BUT_THE_CONDITIONS = (
    "The condition was created, but the conditions list could not be refreshed. "
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
    "applications first. It will be unavailable during maintenance and refreshed "
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
    "The annotations could not be saved. Refresh the bid and verify its page and "
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
PROGRESS_DIALOG_LABEL_B_B = "{action_text} <b>{basename}</b>..."
PROGRESS_DIALOG_LABEL_B_B_2 = "{action_text} <b>{description}</b>..."
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
COMBO_IDENTITY_MESSAGE_MATCHES_MORE_THAN_ONE_ITEM = (
    '"{text}" matches more than one item. Select the intended item from the list.'
)
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
    "bid.\n\nTHIS CANNOT BE UNDONE!\n\nAre you sure you want to delete this "
    "condition?"
)
MESSAGEBOX_BUTTON_YES_TO_ALL = "Yes to All"
MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM = "Delete {n} item?"
MESSAGEBOX_MESSAGE_DELETE_ITEMS = "Delete {n} items?"
# Utils: utils.named_view_validation
NAMED_VIEW_VALIDATION_TITLE_NAMED_VIEW = "Named View"
# Utils: utils.overlay_context_menu
OVERLAY_CONTEXT_MENU_TITLE_SELECT_OVERLAY_IMAGE = "Select Overlay Image"
OVERLAY_CONTEXT_MENU_ACTION_SELECT_OVERLAY_IMAGE = "Select Overlay Image"
OVERLAY_CONTEXT_MENU_ACTION_SHOW_OVERLAY_IMAGE = "Show Overlay Image"
OVERLAY_CONTEXT_MENU_ACTION_SHOW_ORIGINAL_IMAGE = "Show Original Image"
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
    "{value} could not be undone.\n\n{value_2}"
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
CONDITION_ACTION_HANDLER_MESSAGE_THE_OPERATION_COULD_NOT_COMPLETE_REFRESH = (
    "The operation could not complete. Refresh the database before retrying."
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
    "server database was not deleted.{cleanup_message}"
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
    "{in_use_lines}\n\nDelete the other {n} item?"
)
MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS = (
    "{in_use_lines}\n\nDelete the other {n} items?"
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

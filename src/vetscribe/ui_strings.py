"""User-facing UI strings.

Defined once here and referenced everywhere -- production widgets and the tests
that assert on them -- so a label can't drift out of sync between the code that
renders it and the code that checks for it.
"""

# Window titles
HISTORY_WINDOW_TITLE = "VetScribe History"
SETTINGS_WINDOW_TITLE = "VetScribe Settings"
CALIBRATION_TITLE = "Calibrate AVImark Boxes"

# Human-readable name per SOAP section, for the calibration prompt.
_SECTION_LABELS = {
    "subjective": "Subjective",
    "objective": "Objective",
    "assessment": "Assessment",
    "plan": "Plan",
}


def calibration_prompt(section, done, total):
    """Instruction shown while calibrating one box (done = boxes already captured)."""
    label = _SECTION_LABELS.get(section, section)
    return (
        f"Box {done + 1} of {total}: with AVImark's note window open, "
        f"click inside the {label} box."
    )

# Tray menu items
MENU_OPEN_LAST_SOAP_NOTE = "Open Last SOAP Note"
MENU_VIEW_HISTORY = "View History"
MENU_SETTINGS = "Settings"
MENU_CALIBRATE_AVIMARK = "Calibrate AVImark Boxes…"
MENU_QUIT = "Quit"

# Buttons
BUTTON_COPY_AND_INJECT = "Copy & Inject to AVImark"
BUTTON_COPY_SOAP_NOTE = "Copy SOAP Note"
BUTTON_OPEN_HISTORY = "Open History"
BUTTON_DELETE_NOTE = "Delete Note"
BUTTON_SAVE_CHANGES = "Save Changes"
BUTTON_REGENERATE = "Regenerate from Transcript"
BUTTON_REGENERATE_BUSY = "Regenerating…"
BUTTON_SAVE = "Save"

# History detail-pane labels
LABEL_SOAP_NOTE = "SOAP Note"
LABEL_TRANSCRIPT = "Transcript"
LABEL_SUBJECTIVE = "Subjective"
LABEL_OBJECTIVE = "Objective"
LABEL_ASSESSMENT = "Assessment"
LABEL_PLAN = "Plan"

# Settings field labels
LABEL_API_ENDPOINT = "API Endpoint URL"
LABEL_API_KEY = "API Key / Token"
LABEL_HOTKEY = "Hotkey Combination"
LABEL_TARGET_WINDOW = "Target Window Matcher"
LABEL_LAUNCH_ON_STARTUP = "Launch VetScribe on Windows Startup"

# Delete-confirmation dialog
DELETE_CONFIRM_TITLE = "Delete note"
DELETE_CONFIRM_MESSAGE = (
    "Delete this SOAP note and its transcript? This cannot be undone."
)

REGENERATE_EMPTY_TITLE = "Nothing to regenerate"
REGENERATE_EMPTY_MESSAGE = "Add a transcript before regenerating the SOAP note."
REGENERATE_ERROR_TITLE = "Regenerate failed"
REGENERATE_ERROR_MESSAGE = "Could not regenerate the SOAP note:\n\n{error}"

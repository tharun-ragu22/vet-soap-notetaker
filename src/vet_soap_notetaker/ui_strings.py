"""User-facing UI strings.

Defined once here and referenced everywhere -- production widgets and the tests
that assert on them -- so a label can't drift out of sync between the code that
renders it and the code that checks for it.
"""

# Window titles
FLYOUT_WINDOW_TITLE = "Vet Soap Notetaker"
HISTORY_WINDOW_TITLE = "Vet Soap Notetaker History"
SETTINGS_WINDOW_TITLE = "Vet Soap Notetaker Settings"
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

# Shown when a calibration click lands on this prompt window itself (it was
# covering the box) -- so the click isn't silently swallowed.
CALIBRATION_PROMPT_COVERED = (
    "⚠ This window is covering the box. Drag it out of the way, "
    "then click inside the box."
)

# Shown when the four clicks all captured the same control (usually a multi-monitor
# display mismatch), so the calibration is discarded and restarted.
CALIBRATION_RETRY = (
    "⚠ That didn't capture four separate boxes — this can happen across two "
    "monitors. Let's start over: click inside the Subjective box."
)

# Shown when the hotkey is pressed while the previous recording is still being
# turned into a note -- a new recording can't start until it's done.
STILL_PROCESSING_PREVIOUS_NOTE = (
    "Still generating the previous SOAP note. Wait for the tray icon to turn "
    "green, then press the hotkey again to start the next recording."
)

# Shown when the backend saved the recording's transcript but couldn't generate
# the note yet (HTTP 202); the offline queue keeps retrying the note alone.
NOTE_PENDING_MESSAGE = (
    "The recording was transcribed and saved, but the SOAP note couldn't be "
    "generated yet. It will retry automatically and pop up when ready -- it's "
    "also in History."
)

# Shown when the offline queue stops retrying a pending note (the provider kept
# failing). The exam and its transcript stay in History for a manual retry.
NOTE_PENDING_GAVE_UP_MESSAGE = (
    "A SOAP note still couldn't be generated after several tries. The "
    "transcript is saved: open History, select the note, and use "
    "Regenerate from Transcript."
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
LABEL_ANALYTICS_KEY = "Analytics Project Key (blank = off)"
LABEL_ANALYTICS_USER_ID = "Analytics User ID"
LABEL_ANALYTICS_ENVIRONMENT = "Analytics Environment"
LABEL_LAUNCH_ON_STARTUP = "Launch Vet Soap Notetaker on Windows Startup"

# Delete-confirmation dialog
DELETE_CONFIRM_TITLE = "Delete note"
DELETE_CONFIRM_MESSAGE = (
    "Delete this SOAP note and its transcript? This cannot be undone."
)

REGENERATE_EMPTY_TITLE = "Nothing to regenerate"
REGENERATE_EMPTY_MESSAGE = "Add a transcript before regenerating the SOAP note."
REGENERATE_ERROR_TITLE = "Regenerate failed"
REGENERATE_ERROR_MESSAGE = "Could not regenerate the SOAP note:\n\n{error}"

# Shown when the backend heard no speech in the recording (HTTP 422). Nothing
# was saved and it isn't retried -- the same audio would fail the same way.
NO_SPEECH_MESSAGE = (
    "No speech was heard in that recording, so no note was made. Check the "
    "microphone isn't muted. The audio was saved to {path}."
)

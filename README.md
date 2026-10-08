# Vet Soap Notetaker Assistant

A Windows system-tray app for veterinary exam rooms. Press a hotkey to record
the conversation, get an AI-generated SOAP note, and have it typed directly
into AVImark — with a safety net when AVImark isn't in focus, and automatic
recovery if the AI backend is temporarily unreachable.

## The three pieces

Vet Soap Notetaker is an ecosystem of three components that share one backend:

| Component | Where it lives | Role |
|---|---|---|
| **Desktop tray app** | `src/vet_soap_notetaker/` | The exam-room PC appliance: hotkey → record → SOAP note → inject into AVImark. On the packaged install it also **supervises the bundled backend** (launches it, relaunches it if it dies) so one autostart entry brings the whole stack up after a reboot. |
| **Backend** | [`backend/`](backend/README.md) | The AI server: transcription + SOAP-note generation behind pluggable OpenAI/Anthropic/Gemini/Ollama providers. Also the **single source of truth for exam history** and the relay for **remote injection** from the phone. |
| **Mobile companion** | [`mobile/`](mobile/README.md) | An Expo/React Native iOS + Android app: a portable exam-room mic, note reviewer/editor, and a remote "Inject into AVImark" trigger. Talks only to the backend, never to the PC directly. |

The intended clinic deployment is a **LAN appliance**: the backend + desktop app
run on the exam-room PC, and the vet drives the system from the **mobile app** on
the clinic Wi-Fi. [`mobile/README.md`](mobile/README.md) covers building and
installing the phone app (EAS, TestFlight, LAN config).

## How it works

1. Press the configured hotkey (default **`Ctrl+Shift+R`**) to start recording
   exam-room audio.
2. Press it again to stop. The audio is sent to a configurable AI backend,
   which returns a structured SOAP note (Subjective / Objective / Assessment
   / Plan).
3. If the target practice-management window (AVImark by default) is the
   foreground window, the note is copied to the clipboard and pasted in
   automatically (simulated `Ctrl+V`).
4. If it's *not* focused, a "Safety Flyout" window pops up in the bottom-right
   corner of the screen with the note text and buttons to copy it to the
   clipboard or inject it once you switch back.
5. If the backend call fails (timeout, error response, malformed reply), the
   raw audio is never lost: it's archived to `~/.vetscribe/recordings/` and
   also queued for automatic retry, and a flyout explains what happened. A
   background worker retries queued recordings every 60 seconds and pops up a
   flyout with the recovered note once the backend comes back.

A tray icon shows the current state at a glance: green (idle), red
(recording), yellow (processing). Right-clicking the tray icon opens a menu
with the current status, a way to reopen the last generated note, a **History**
window, a way to **Calibrate AVImark Boxes…**, a Settings window, and Quit
(which cleanly stops the hotkey listener, any in-progress recording, the
retry-queue worker, the remote-injection poller, and the bundled backend it
supervises before exiting).

### Exam history, the mobile app, and remote injection

Every generated note is saved on the backend, so the same exam history is
available from both the desktop **History** window and the phone. From History
(or the phone) the vet can:

- **Edit** the four SOAP fields or the raw transcript inline and save.
- **Regenerate from Transcript** — after hand-correcting the transcript, get a
  fresh note without re-recording (the regenerated note lands as an *unsaved*
  edit, so it's never destructive until Save).
- **Inject into AVImark** — paste the note into the exam-room chart. From the
  phone this is a *remote* inject: the mobile app POSTs an injection request to
  the backend, the desktop app polls for it (a firewall-friendly pull, the same
  pattern as the offline retry queue), and the desktop does the paste — using the
  same safety guard as everywhere else (inject only into a safely-targeted
  AVImark chart, otherwise raise the Safety Flyout with the note ready). Clicking
  Inject auto-saves the vet's current edits first, so you never have to Save then
  Inject. See [`mobile/README.md`](mobile/README.md).

### Per-box AVImark placement (calibration)

AVImark's SOAP note is four separate boxes. Rather than blindly Tab between
fields (unrelated checkboxes sit in the keyboard order and a blind Tab count
lands in the wrong box), the app uses a one-time, per-site **calibration**: tray
→ **Calibrate AVImark Boxes…** opens an instruction window and captures where you
click for each of the four boxes, then persists that. At inject time each SOAP
section is written straight into its own control. If a calibration is stale (a
box can't be resolved) the app degrades to a single-block paste rather than
scatter a half-placed note; uncalibrated installs also get the single-block
paste. See the "Per-box placement" notes in `CLAUDE.md` for the full design.

### Settings

The tray menu's **Settings** window lets you edit, without restarting the
app:

- API Endpoint URL
- API Key / Token (sent as an `Authorization: Bearer <token>` header)
- Hotkey Combination (rebinds the global hotkey live)
- Target Window Matcher (which window title identifies your practice
  software — defaults to `AVImark`)
- Launch Vet Soap Notetaker on Windows Startup (adds/removes an
  `HKCU\...\CurrentVersion\Run` registry entry)

Saving writes to `~/.vetscribe/config.json` and applies every change to the
already-running app immediately.

## Tech stack

| Concern | Library |
|---|---|
| System tray icon + menu | [`pystray`](https://pypi.org/project/pystray/) |
| Icon rendering | [`Pillow`](https://pypi.org/project/Pillow/) |
| Audio capture | [`sounddevice`](https://pypi.org/project/sounddevice/) |
| WAV encoding | [`scipy.io.wavfile`](https://pypi.org/project/scipy/) |
| AI backend calls | [`httpx`](https://pypi.org/project/httpx/) |
| Global hotkey | [`pynput`](https://pypi.org/project/pynput/) |
| Clipboard access | [`pyperclip`](https://pypi.org/project/pyperclip/) |
| Windows automation (foreground detection, clipboard, simulated keystrokes) | [`pywin32`](https://pypi.org/project/pywin32/) |
| Windows startup registration | `winreg` (stdlib, Windows only) |
| Safety flyout / Settings UI | `tkinter` (stdlib) |
| Logging | `logging` / `logging.handlers.RotatingFileHandler` (stdlib) |
| GUI acceptance testing | [`pywinauto`](https://pypi.org/project/pywinauto/) |
| Tests | `pytest`, `pytest-mock`, `pytest-asyncio`, `respx` |
| Packaging / dependency management | [`uv`](https://github.com/astral-sh/uv) |
| Standalone executable / installer | [`PyInstaller`](https://pyinstaller.org/), [Inno Setup](https://jrsoftware.org/isinfo.php) |

`pywin32`, `pywinauto`, and `winreg` are only meaningfully used on Windows
(`sys_platform == 'win32'` markers in `pyproject.toml`, or stubbed out in
tests via `tests/conftest.py`); the app can be developed and unit/integration
tested on Linux, but AVImark injection and startup registration only run for
real on Windows.

## Installation

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/tharun-ragu22/vet-soap-notetaker.git
cd vet-soap-notetaker
uv sync
```

On Linux, running/testing also needs system packages for audio and Tk:

```bash
sudo apt-get install -y libportaudio2 python3-tk python3-dev
```

### Quick start on Windows (`setup.ps1`)

On Windows, `setup.ps1` in the repo root sets up **and starts** all three
components — backend, desktop tray app, and mobile companion — in one command:

```powershell
git clone https://github.com/tharun-ragu22/vet-soap-notetaker.git
cd vet-soap-notetaker
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It requires [`uv`](https://github.com/astral-sh/uv) (and, for the mobile app,
[Node.js](https://nodejs.org/) with `npm`) on your `PATH` — the script checks for
them first and points you at `winget` installs if either is missing. Then it:

- creates `backend/.env` and `mobile/.env` from their `.env.example` templates if
  they don't exist yet (fill in your provider API keys afterward);
- installs backend and desktop dependencies (`uv sync`) and mobile dependencies
  (`npm install`);
- seeds `~/.vetscribe/config.json` from `backend/.env` so the desktop app points
  at the local backend port and shares its `VETSCRIBE_BACKEND_API_KEY` — merging
  into any existing config so your hotkey/window settings are preserved;
- **launches each service in its own window**: the backend (`uv run python -m
  vet_soap_notetaker_backend.main`), the desktop tray app (`uv run python -m
  vet_soap_notetaker.main`), and the mobile Expo dev server (`npm start`).

Each component's `.env` is the source of truth for its environment variables (see
[`backend/README.md`](backend/README.md) and [`mobile/.env.example`](mobile/.env.example)
for the full lists), so edit those files to configure the stack. Close a service by
closing its window (or `Ctrl+C` inside it).

Flags:

| Flag | Effect |
|---|---|
| `-NoInstall` | Skip dependency install and `.env` creation — just (re)start the services. Use for a fast restart once you've run setup once |
| `-NoStart` | Run setup only; don't launch anything |
| `-SkipMobile` | Ignore the mobile app entirely (no `npm install`, not started) — handy on an exam-room PC that only runs the backend + desktop app |

```powershell
# fast restart of all services (skip the installs):
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoInstall

# exam-room PC (no phone deps), backend + desktop only:
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -SkipMobile
```

### Configuration

On first run, Vet Soap Notetaker creates `~/.vetscribe/config.json` with defaults
(see `src/vet_soap_notetaker/config.py`):

```json
{
  "api_endpoint": "https://localhost:8443/api/soap",
  "api_timeout_seconds": 30,
  "hotkey": "<ctrl>+<shift>+r",
  "api_key": "",
  "target_window_matcher": "AVImark",
  "launch_on_startup": false
}
```

All of these fields can also be edited live from the tray's Settings window
(see above) instead of hand-editing the file.

Edit `api_endpoint` to point at your SOAP-note-generation backend. It's
expected to accept a `POST` with raw WAV bytes (`Content-Type: audio/wav`,
plus `Authorization: Bearer <api_key>` if `api_key` is set) and return JSON
with `subjective`, `objective`, `assessment`, and `plan` fields.

A reference implementation of this backend, with pluggable OpenAI/Anthropic/Gemini
providers for transcription and note generation, lives in [`backend/`](backend/README.md).

#### Pointing Vet Soap Notetaker at the reference backend

1. Start the backend (see [`backend/README.md`](backend/README.md) for provider setup):
   ```bash
   cd backend
   uv sync
   VETSCRIBE_NOTE_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... \
     uv run python -m vet_soap_notetaker_backend.main
   ```
   By default it listens on `http://localhost:8443/api/soap` — plain HTTP, no TLS.
2. In Vet Soap Notetaker's tray menu, open **Settings** and set:
   - **API Endpoint URL** to `http://localhost:8443/api/soap` (note `http://`, not the
     `https://` default — the reference backend doesn't terminate TLS itself; put a
     reverse proxy in front of it for anything beyond local testing).
   - **API Key / Token** to the same value as the backend's `VETSCRIBE_BACKEND_API_KEY`
     env var, if you set one (leave blank if you didn't — the backend then accepts
     unauthenticated requests).
3. Save. The change applies immediately, no restart needed — press the hotkey to test.

### Running

```bash
uv run python -m vet_soap_notetaker.main
```

This starts the tray icon, registers the global hotkey, configures logging,
and starts the offline-retry background worker.

### Logs

Diagnostic logs (mic start/stop, foreground window checks, backend response
codes, injection success/failure) are written to a rotating log file (5MB per
file, 3 backups kept) at `%APPDATA%\Vet Soap Notetaker\logs\vet_soap_notetaker.log` on Windows,
or `~/.vetscribe/logs/vet_soap_notetaker.log` elsewhere. Set the `VETSCRIBE_DEBUG`
environment variable to any truthy value to log at `DEBUG` instead of `INFO`.

## Project layout

```
src/vet_soap_notetaker/              The Windows desktop tray app (this package)
  config.py              Config dataclass; loads/saves ~/.vetscribe/config.json
  api_client.py          ApiClient — POSTs audio to the backend, parses SoapNote; also history + regenerate
  audio_recorder.py      AudioRecorder — sounddevice-based mic capture + WAV export
  avimark_injector.py    AvimarkInjector — foreground check, clipboard+Ctrl+V, and per-box SendMessage paste
  avimark_calibration.py Pure model/matching for the four-box calibration (control-id → class → position)
  calibration_ui.py      CalibrationSession/Controller — the "Calibrate AVImark Boxes" capture flow
  flyout_ui.py           FlyoutWindow — Tkinter "Safety Flyout" shown for fallback/errors
  history_ui.py          HistoryWindow — browse/edit exams, Regenerate from Transcript, Copy & Inject
  settings_ui.py         SettingsWindow — Tkinter form for editing config live
  hotkey_listener.py     HotkeyListener — global hotkey capture via pynput, rebindable live
  pipeline.py            Pipeline / PipelineState — the record→transcribe→inject state machine
  tray_app.py            TrayApp — pystray icon + menu (status, note, history, calibrate, settings, quit)
  offline_queue.py       OfflineQueue — persists failed recordings and retries them in the background
  backend_history_store.py  BackendHistoryStore — backend-backed exam history with a local read cache
  backend_supervisor.py  BackendSupervisor — launches/relaunches the bundled backend exe (packaged install)
  injection_poller.py    InjectionPoller — polls the backend for mobile "Inject into AVImark" requests
  single_instance.py     Guards against a second copy of the app running at once
  autostart.py           winreg-based Windows "launch on startup" registration
  window_icon.py / icon_art.py / ui_strings.py   Window icon, tray icon art, and shared UI strings
  logger.py              Rotating file logger setup
  paths.py               Shared %APPDATA%/home-dir resolution helper
  main.py                build_app() wires everything together; run() is the entry point

backend/                 Reference AI backend (own uv project) — see backend/README.md
mobile/                  Expo/React Native companion app (iOS + Android) — see mobile/README.md
docs/                    Deployment + iOS-install notes (deployment.md is local-only, not committed)

tests/
  unit/                  Fast, isolated tests for each module (mocked collaborators)
  integration/           Tests that wire multiple real modules together (pipeline, tray, hotkey, main)
  acceptance/            End-to-end tests, including a fake AVImark window and Windows-only
                         pywinauto GUI automation tests (skipped on non-Windows platforms)

build_spec/
  vet_soap_notetaker.spec  PyInstaller spec (--onedir) for the desktop tray app
  installer.iss          Inno Setup script that wraps both PyInstaller outputs into VetSoapNotetakerSetup.exe
  clinic_config.json     Default config the installer seeds into ~/.vetscribe/config.json on first install
  generate_icons.py      Renders the app/tray icon assets
backend/build_spec/backend.spec   PyInstaller spec for the bundled backend exe the desktop supervises

.github/workflows/ci.yml  GitHub Actions CI (see the CI section below)
```

### Key design points

- **Dependency injection**: `build_app(config=None, tk_root=None)` in
  `main.py` constructs the recorder, API client, injector, pipeline, tray
  app, hotkey listener, offline queue, history store, injection poller, and
  backend supervisor, so every piece can be swapped for a test double.
- **State machine**: `Pipeline` in `pipeline.py` only has three states
  (`IDLE`, `RECORDING`, `PROCESSING`). `toggle_recording()` is a no-op while
  processing, so a stray hotkey press mid-transcription can't corrupt state,
  and a caught backend failure always returns the pipeline to `IDLE` instead
  of stranding it in `PROCESSING`.
- **Injection safety**: `AvimarkInjector.inject()` refuses to send
  `Ctrl+V` unless the configured target window is genuinely the foreground
  window (checked via `win32gui.GetForegroundWindow()`), so a SOAP note can
  never be pasted into the wrong application. The calibrated per-box path writes
  each section straight into its control with `SendMessage` (no global Ctrl+V)
  and refuses to paste if any box can't be resolved or two resolve to the same
  control, degrading to a single-block paste rather than scatter a note.
- **Remote injection, pull not push**: the phone POSTs an injection request to
  the backend and the desktop `InjectionPoller` pulls it — the phone never
  connects to the PC, so nothing new needs to be open through the firewall. The
  desktop reuses the exact same safety path as the flyout's Copy & Inject.
- **One autostart entry, whole stack**: on the packaged install the
  `BackendSupervisor` launches the bundled backend exe and relaunches it if it
  dies; in a dev checkout (no bundled exe) it stays off and the separately-run
  backend is left alone.
- **No data loss on backend failure**: if `ApiClient.generate_soap_note()`
  raises, `Pipeline` archives the raw WAV to
  `~/.vetscribe/recordings/failed_*.wav`, enqueues it in `OfflineQueue` for
  automatic retry, and surfaces the error via a flyout — the vet is never
  left with a frozen yellow tray icon and no explanation.
- **Live settings, no restart**: `HotkeyListener.update_hotkey()` and direct
  attribute updates on `ApiClient`/`AvimarkInjector` let the Settings window
  apply changes to the already-running process.
- **Mock AVImark for testing**: `tests/acceptance/mock_avimark.py` is a
  Tkinter stand-in for the real AVImark window, used by the Windows
  acceptance tests. Because Tkinter widgets have no native Win32 control
  class, its content can't be read back via GUI automation — instead it
  dumps its text to a file on every edit, which the tests poll and read.

## Testing

```bash
uv run pytest -v
```

On Linux, GUI-touching tests need a display (real or virtual):

```bash
xvfb-run -a uv run pytest -v
```

Windows-only acceptance tests (`tests/acceptance/test_e2e_*.py`) are
automatically skipped on non-Windows platforms and only run for real in CI
on the `windows-latest` runner. Windows-only modules (`winreg`, `pywin32`)
are stubbed out in `tests/conftest.py` on non-Windows platforms so their
call sites can still be imported and exercised with mocks.

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main`. A `changes` job
(`dorny/paths-filter`) runs first and gates the backend-only jobs so unrelated
pushes skip them:

- **`test`**: runs the full desktop test suite on both `ubuntu-latest` and
  `windows-latest`, using `uv sync --locked` for reproducible installs. This
  includes the real Windows GUI acceptance tests (mock AVImark injection and
  safety-flyout fallback), so a green run means the app has been verified
  end-to-end on a genuine, fresh Windows machine.
- **`test-backend`**: runs the `backend/` reference server's own test suite
  (`uv sync --locked` + `uv run pytest -v` from within `backend/`) on
  `ubuntu-latest` — provider calls are `respx`-mocked so no real API keys are
  needed.
- **`test-mobile`**: runs the `mobile/` Jest suite (unit + integration + the
  screen-level e2e tests against the in-memory fake backend) and `tsc --noEmit`.
- **`backend-evals`**: runs the LLM note-generation evals against a CPU Ollama
  model — **only** when a push touches `backend/llm/**` and after `test-backend`
  passes (it's the slowest job; see [`backend/README.md`](backend/README.md)).
- **`build-windows-exe`**: runs after the test jobs pass, builds the standalone
  desktop + backend folders with PyInstaller and uploads them as workflow
  artifacts. Producing the double-clickable `VetSoapNotetakerSetup.exe` installer
  additionally requires running Inno Setup (`build_spec/installer.iss`) against
  that output, which isn't yet automated in CI.

Pushing to `origin/main` and confirming this run is green is the standing proof a
change works on a fresh machine (see `CLAUDE.md`).

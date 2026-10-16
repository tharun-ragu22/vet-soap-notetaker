# Vet Soap Notetaker Backend (reference implementation)

A minimal reference server that satisfies the HTTP contract Vet Soap Notetaker's `ApiClient` expects
(`POST /api/soap` with raw WAV bytes, returns JSON with `subjective`/`objective`/`assessment`/`plan`).
It's a separate project from the desktop tray app — this is meant to run on a server (or locally for
development), not ship inside the Windows installer.

Transcription and SOAP-note generation are each behind a small interface, selected independently, so
you can mix providers (e.g. Gemini for transcription, Anthropic for note generation):

| Env var | Values | Default |
|---|---|---|
| `VETSCRIBE_TRANSCRIPTION_PROVIDER` | `openai`, `gemini` | `openai` |
| `VETSCRIBE_NOTE_PROVIDER` | `openai`, `anthropic`, `gemini`, `ollama` | `openai` |

Provider credentials (only the ones for your selected providers are required):

| Env var | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI Whisper transcription and/or GPT note generation |
| `ANTHROPIC_API_KEY` | Claude note generation |
| `GEMINI_API_KEY` | Gemini transcription and/or note generation |
| `OPENAI_TRANSCRIPTION_MODEL` | default `whisper-1` |
| `OPENAI_NOTE_MODEL` | default `gpt-4o-mini` |
| `ANTHROPIC_NOTE_MODEL` | default `claude-sonnet-4-5` |
| `GEMINI_TRANSCRIPTION_MODEL` | default `gemini-2.5-flash` |
| `GEMINI_NOTE_MODEL` | default `gemini-2.5-flash` |
| `OLLAMA_BASE_URL` | self-hosted Ollama server, default `http://localhost:11434` (no API key needed) |
| `OLLAMA_NOTE_MODEL` | default `gemma4:e4b` |

`VETSCRIBE_BACKEND_API_KEY` is a separate shared secret (distinct from the provider keys above): if
set, incoming requests must send `Authorization: Bearer <that value>` — this is the value you'd put in
Vet Soap Notetaker's own "API Key" setting. If unset, the backend accepts unauthenticated requests.

### Using a `.env` file

Instead of exporting all of the above as real environment variables, copy `.env.example` to `.env` in
`backend/` and fill in the values there:

```bash
cd backend
cp .env.example .env
# edit .env with your provider choice and API key(s)
uv run python -m vet_soap_notetaker_backend.main
```

`BackendConfig.from_env()` loads `.env` automatically (via `python-dotenv`) on startup. Real environment
variables still take precedence over `.env` values if both are set. `.env` is gitignored — never commit
it.

The SOAP-note system prompt sent to whichever note-generation provider is selected lives in
`src/vet_soap_notetaker_backend/llm/prompts.py` (`SOAP_SYSTEM_PROMPT`) — edit it there if you want to change the
clinical instructions given to the model.

## Running

```bash
cd backend
uv sync
VETSCRIBE_NOTE_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... \
VETSCRIBE_TRANSCRIPTION_PROVIDER=openai OPENAI_API_KEY=sk-... \
  uv run python -m vet_soap_notetaker_backend.main
```

Listens on port 8443 by default (override with `PORT`), matching Vet Soap Notetaker's default
`api_endpoint` of `https://localhost:8443/api/soap` — note this runs plain HTTP, so for local dev
point Vet Soap Notetaker's Settings at `http://localhost:8443/api/soap`, or put a TLS-terminating proxy in
front of it for anything beyond local testing.

### Logs

The backend logs to the console (the packaged, windowless `.exe` writes the same lines to
`%APPDATA%\VetScribe\logs\backend.log`). When a recording is slow, look for:

- `recording processed: outcome=complete transcribe_ms=… note_gen_ms=… patient_count=… total_ms=…`
  — one line per upload, saying where the time went (`outcome` is `complete`, `note_pending` or
  `failed`, with the error type for the last two).
- `provider request failed (ReadTimeout) after 120.0s; retry 1 of 3 in 1s` — a provider call
  being retried (timeouts, 429s and 5xx are retried up to 3 times, each with its own 120s timeout).

Both are metadata only: no transcript, note text, patient names or provider URLs.

## History & cross-device sync

Every generated note is persisted so it can sync across the desktop tray app and the mobile
app (`mobile/`). One recording is an **appointment**: it owns the transcript, and holds one
**exam** (SOAP note) per animal seen, so a two-dog visit gives two exams, each injectable into its
own AVImark chart. When note generation fails after a good transcription, the appointment is
saved with one empty, `note_pending` exam and the request returns `202`; finishing it fills that
exam with the first animal's note and adds the others. All endpoints sit behind the same bearer
auth.

Appointments (the mobile app):

| Method & path | Purpose |
|---|---|
| `POST /api/appointments` | Audio body → `{"id", "created_at", "transcript", "note_pending", "exams": [...]}` (`200`, or `202` with the note pending, `502` if transcription fails) |
| `POST /api/appointments/{id}/notes` | Generate a pending appointment's notes from its saved transcript; idempotent (a complete one is returned unchanged) |
| `GET /api/appointments` | All appointments, newest first: `{"appointments": [ ... ]}` |
| `GET /api/appointments/{id}` | One appointment (404 if unknown) |
| `PUT /api/appointments/{id}` | Save the whole appointment: `{"transcript", "exams": [...]}`. Exams with an `id` are updated, ones without are added, ones left out are deleted; 400 if an `id` isn't in this appointment |
| `DELETE /api/appointments/{id}` | Delete the appointment and every exam in it |
| `POST /api/appointments/regenerate` | `{"transcript", "appointment_id"?}` → `{"transcript", "patients": [...]}`, saving nothing |

Exams (the desktop app, which works one animal at a time). Each exam's JSON carries its
`appointment_id` and the appointment's `transcript`:

| Method & path | Purpose |
|---|---|
| `POST /api/soap` | Audio body → the first animal's exam (the pending placeholder on a `202`) |
| `POST /api/exams/{id}/note` | Finish a pending exam (adds any further animals to its appointment); idempotent |
| `POST /api/soap/regenerate` | `{"transcript", "exam_id"?}` → the first animal's note at the top level plus every animal's under `patients` |
| `GET /api/history` | Every exam, newest appointment first: `{"exams": [ ... ]}` |
| `GET /api/exams/{id}` | Fetch one exam (404 if unknown) |
| `PUT /api/exams/{id}` | Save one animal's edits (`subjective`/`objective`/`assessment`/`plan`, optional `patient_name`, optional `transcript` which updates it for every animal); 400 on missing fields, 404 if unknown |
| `DELETE /api/exams/{id}` | Delete one animal; deleting the last one deletes the appointment |

Storage is a JSON file (durable across restarts) at `~/.vetscribe/exams.json` by default;
override with `VETSCRIBE_EXAMS_PATH`. The backend remains the authoritative source of truth —
clients read and write through it and keep no independent copy.

## Remote AVImark injection

The mobile app (`mobile/`) can ask for an exam's note to be pasted into AVImark on the
exam-room PC without the phone and the PC ever talking directly. The mobile app POSTs an
injection request to the backend; the desktop tray app polls the backend for pending
requests (the same firewall-friendly pattern its offline retry queue already uses), does the
paste using its existing safety guard (inject into AVImark only if it's the foreground window,
otherwise raise the Safety Flyout with the note ready), then acks. Endpoints, all behind the
same bearer auth:

| Method & path | Purpose |
|---|---|
| `POST /api/exams/{id}/inject` | Mobile: request injection of this exam's note. `202` with the request, `404` if the exam is unknown |
| `GET /api/injections/pending` | Desktop: list pending requests, each enriched with the exam's *current* note (`{"requests": [{"id", "exam_id", "exam": {...}}]}`) so edits made after tapping Inject are reflected |
| `POST /api/injections/{id}/ack` | Desktop: mark a request handled (`{"outcome": "injected"｜"flyout"｜...}`); `404` if unknown |

The injection queue is intentionally **in-memory, not durable**: a request only means "paste
this now, while the vet is standing at the PC." A request that survived a backend restart could
land in whatever chart happened to be open later, so dropping them on restart is the safe
behavior — unlike exam history, which is durable.

## Analytics (PostHog)

Set `VETSCRIBE_POSTHOG_KEY` (the project's public `phc_...` key) to send usage events to
PostHog; leave it blank and nothing is sent (the default, and what tests/CI use).
`VETSCRIBE_POSTHOG_HOST` defaults to US Cloud, `VETSCRIBE_ANALYTICS_ENV` (default `dev`) tags
every event so a test run can be told apart from a demo, and `VETSCRIBE_ANALYTICS_USER_ID` is
who events are attributed to when the client doesn't send its own id (falls back to
`backend-<hostname>`).

Events are **metadata only** -- ids, durations, counts, which boxes changed and by how much --
never audio, transcripts, note text or patient names. Errors are sent as the exception *type*
and upstream HTTP status only, since an httpx error's message includes the provider URL (and the
Gemini API key in it). `tests/integration/test_app_analytics.py` drives every endpoint with a
sentinel patient and fails if it reaches any event.

| Event | Sent from | Key properties |
|---|---|---|
| `soap_generated` | `POST /api/soap`, `POST /api/appointments` | `outcome` (complete/note_pending/failed), `transcribe_ms`, `note_gen_ms`, `total_ms`, `audio_duration_ms`, `audio_bytes`, providers, `exam_id` (the first animal's), `appointment_id`, `patient_count` |
| `pending_note_completed` | `POST /api/exams/{id}/note`, `POST /api/appointments/{id}/notes` | `outcome` (complete/failed/already_complete), `note_gen_ms`, `appointment_id`, `patient_count` |
| `note_regenerated` | `POST /api/soap/regenerate`, `POST /api/appointments/regenerate` | `exam_id` or `appointment_id` (optional, from the body), `transcript_edited`, `note_gen_ms`, `outcome`, `patient_count` |
| `note_saved` | `PUT /api/exams/{id}`, and per kept exam on `PUT /api/appointments/{id}` | `exam_id`, `appointment_id`, `fields_changed`, `<field>_similarity` (0-1), `includes_regenerated_content` |
| `appointment_saved` | `PUT /api/appointments/{id}` | `patient_count`, `exams_added`, `exams_removed`, `transcript_edited`, `includes_regenerated_content` |
| `exam_deleted` | `DELETE /api/exams/{id}` | `exam_id`, `appointment_id` |
| `appointment_deleted` | `DELETE /api/appointments/{id}` | `appointment_id`, `patient_count` |
| `injection_requested` | `POST /api/exams/{id}/inject` | `attempt_number`, `edited_before_inject`, `request_id` |

Clients identify themselves with optional headers: `X-POSTHOG-DISTINCT-ID` (their PostHog
id, so backend events join the same person), `X-POSTHOG-SESSION-ID` (sent on as `$session_id`),
`X-VSN-Client` (`mobile`/`desktop`, sent as `source_app`) and `X-Audio-Duration-Ms`. The
regenerate/edit/inject bookkeeping is in memory, so it resets when the backend restarts.

## Testing

```bash
cd backend
uv run pytest -v
```

All provider HTTP calls are mocked with `respx` in tests — no real API keys or network calls are
needed to run the suite.

## Evals

`src/vet_soap_notetaker_backend/llm/evals/` (grouped with the LLM code it exercises, separate from `tests/`, not
picked up by `pytest`) holds two `pydantic-evals` suites, one subpackage each:

- `llm/evals/note_generation/` — `NoteGenerator.generate()` on example transcripts
- `llm/evals/transcription/` — `Transcriber.transcribe()` on synthetic exam audio (latency + accuracy)

### Note generation

Runs `NoteGenerator.generate()` against a range of example transcripts (`llm/evals/note_generation/cases.py`) — routine visits,
emergencies, multi-pet visits, vague/garbled transcripts, declined-care conversations, and irrelevant
chit-chat mixed in with a real complaint. Unlike the unit tests, these make real network calls to a live
Ollama-compatible server. `generate()` returns one note per animal, and each case says which animals it
expects (multi-animal cases list them under `patients`, each with its own keywords and another animal's
findings that must stay out of its note). Output is scored with deterministic checks (one note per
expected animal, all four SOAP fields present in every note, expected keywords in each animal's own
note, no animal's findings in another's) plus an `LLMJudge` rubric for faithfulness/hallucination,
correct SOAP categorization, ignoring irrelevant chatter, and keeping each note to its own animal —
judged by the same Ollama model, so no paid API key is needed:

```bash
cd backend
OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_NOTE_MODEL=gemma4:e4b \
  uv run python -m vet_soap_notetaker_backend.llm.evals.note_generation.run
```

Point `OLLAMA_BASE_URL` at any reachable Ollama server (e.g. a tunnel to a GPU box) and
`OLLAMA_NOTE_MODEL` at whatever's pulled there. Both default to `BackendConfig`'s own Ollama defaults
(`http://localhost:11434` / `gemma4:e4b`) if unset. A case counts as passing only if it didn't error
and every assertion (`PatientCount`, `HasAllSoapFields`, `NoCrossContamination`, `LLMJudge`) is true; `note_generation/run.py`'s `main()` exits
non-zero unless at least `REQUIRED_PASS_RATE` (70%) of cases pass, so it works as a CI gate without
requiring a perfect run from a small local model.

`.github/workflows/ci.yml`'s `backend-evals` job runs this in CI on `ubuntu-latest`, after
`test-backend`'s deterministic suite passes and before `build-windows-exe`: it installs Ollama, pulls
`gemma4:e4b`, and runs the same command against `localhost:11434`. Since these are CPU-only GitHub-hosted
runners (no GPU), and Ollama serializes generation per model anyway, the eval runner processes cases one
at a time with a generous `OLLAMA_EVAL_TIMEOUT_SECONDS` (default 300s) rather than the provider's normal
120s default — expect the CI job to take tens of minutes, not seconds.

The job only runs when a push/PR touches backend code (gated by the `changes` job at the top of the
workflow, via `dorny/paths-filter` on `backend/**`, excluding `*.md` files) — it's skipped for
tray-app-only or docs-only changes, since it's the slowest job in the pipeline and gains nothing from
re-running against unchanged eval-relevant code.
`build-windows-exe` accounts for this by treating `backend-evals` being skipped the same as it succeeding.

### Transcription

Sends four synthetic exam recordings — 5, 10, 20 and 30 minutes, all different conversations — through
the production transcriber (`get_transcriber(BackendConfig.from_env())`, so the same provider, model,
retries, timeouts and inline-vs-Files-API switch the clinic backend uses), in both formats the backend
receives: the phone's `.m4a` (AAC 44.1 kHz stereo) and the desktop's `.wav` (32-bit float 16 kHz mono).
Cases run one at a time so each duration is the provider's own latency. Evaluators
(`llm/evals/transcription/evaluators.py`) assert:

- **latency** ≤ 300 s (the phone gives up at 480 s, and note generation still has to run)
- **word error rate** ≤ 15% against the exact spoken text, after normalizing formatting
  (`16 mg` = `16 milligrams`, `4/6` = `4 out of 6`, speaker labels and punctuation ignored)
- **clinical-term recall** ≥ 90% — vitals, lab values, drug names and doses per recording
  (`llm/evals/transcription/cases.py`); the failure reason names each missed term
- **no late drop-off** — every 5-minute window of the recording keeps ≥ 80% of its words, which
  catches a long transcript that degrades or stops partway through

and report the share of lines with a speaker label. Every case must pass.

The audio (~300 MB) isn't in git. Generate it with `backend/scripts/transcription_eval_audio.ipynb` on
Google Colab (free Kokoro TTS on a T4 GPU) and unzip `eval_audio.zip` into
`llm/evals/transcription/` (or point `VETSCRIBE_EVAL_AUDIO_DIR` at the extracted folder). Then, with
the provider key in `backend/.env`:

```bash
cd backend
uv run python -m vet_soap_notetaker_backend.llm.evals.transcription.run
uv run python -m vet_soap_notetaker_backend.llm.evals.transcription.run --formats phone --only otitis_hotspot_5min
```

It calls the real provider (roughly $0.25 for a full run on gemini-2.5-flash) and writes every transcript
plus `results.json` to `llm/evals/transcription/results/<timestamp>/` (gitignored). It isn't in CI yet,
because the audio isn't in the repo.

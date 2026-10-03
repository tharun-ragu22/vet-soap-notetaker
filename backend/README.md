# VetScribe Backend (reference implementation)

A minimal reference server that satisfies the HTTP contract VetScribe's `ApiClient` expects
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
VetScribe's own "API Key" setting. If unset, the backend accepts unauthenticated requests.

### Using a `.env` file

Instead of exporting all of the above as real environment variables, copy `.env.example` to `.env` in
`backend/` and fill in the values there:

```bash
cd backend
cp .env.example .env
# edit .env with your provider choice and API key(s)
uv run python -m vetscribe_backend.main
```

`BackendConfig.from_env()` loads `.env` automatically (via `python-dotenv`) on startup. Real environment
variables still take precedence over `.env` values if both are set. `.env` is gitignored — never commit
it.

The SOAP-note system prompt sent to whichever note-generation provider is selected lives in
`src/vetscribe_backend/llm/prompts.py` (`SOAP_SYSTEM_PROMPT`) — edit it there if you want to change the
clinical instructions given to the model.

## Running

```bash
cd backend
uv sync
VETSCRIBE_NOTE_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... \
VETSCRIBE_TRANSCRIPTION_PROVIDER=openai OPENAI_API_KEY=sk-... \
  uv run python -m vetscribe_backend.main
```

Listens on port 8443 by default (override with `PORT`), matching VetScribe's default
`api_endpoint` of `https://localhost:8443/api/soap` — note this runs plain HTTP, so for local dev
point VetScribe's Settings at `http://localhost:8443/api/soap`, or put a TLS-terminating proxy in
front of it for anything beyond local testing.

## History & cross-device sync

Every generated note is persisted so it can sync across the desktop tray app and the mobile
app (`mobile/`). `POST /api/soap` now stores the note and returns it with an `id` and
`created_at` (existing clients that read only the SOAP fields are unaffected). Additional
endpoints, all behind the same bearer auth:

| Method & path | Purpose |
|---|---|
| `GET /api/history` | List all exams, newest first: `{"exams": [ ... ]}` |
| `GET /api/exams/{id}` | Fetch one exam (404 if unknown) |
| `PUT /api/exams/{id}` | Save inline edits (`subjective`/`objective`/`assessment`/`plan`/`transcript`, optional `patient_name`); 400 on missing fields, 404 if unknown |

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

## Testing

```bash
cd backend
uv run pytest -v
```

All provider HTTP calls are mocked with `respx` in tests — no real API keys or network calls are
needed to run the suite.

## Evals

`evals/` (separate from `tests/`, not picked up by `pytest`) holds `pydantic-evals`-based evals for
`NoteGenerator.generate()` against a range of example transcripts (`evals/cases.py`) — routine visits,
emergencies, multi-pet visits, vague/garbled transcripts, declined-care conversations, and irrelevant
chit-chat mixed in with a real complaint. Unlike the unit tests, these make real network calls to a live
Ollama-compatible server, scoring output with deterministic checks (all four SOAP fields present,
expected keywords per case) plus an `LLMJudge` rubric for faithfulness/hallucination, correct SOAP
categorization, and ignoring irrelevant chatter — judged by the same Ollama model, so no paid API key is
needed:

```bash
cd backend
OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_NOTE_MODEL=gemma4:e4b \
  uv run python -m evals.note_generator_evals
```

Point `OLLAMA_BASE_URL` at any reachable Ollama server (e.g. a tunnel to a GPU box) and
`OLLAMA_NOTE_MODEL` at whatever's pulled there. Both default to `BackendConfig`'s own Ollama defaults
(`http://localhost:11434` / `gemma4:e4b`) if unset. A case counts as passing only if it didn't error
and every assertion (`HasAllSoapFields`, `LLMJudge`) is true; `note_generator_evals.main()` exits
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

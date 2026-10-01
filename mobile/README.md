# VetScribe Mobile

A cross-platform (iOS + Android) companion app for the VetScribe ecosystem: a portable
exam-room microphone, recorder, note reviewer, and remote AVImark injection trigger. It
talks to the same backend (`backend/`) the Windows tray app uses.

## Framework decision brief

**Chosen: Expo (React Native) + TypeScript, tested with Jest.**

The brief called for a single shared iOS/Android codebase, fast TDD, and robust native
audio recording — and, specifically, the ability to test on a **physical iPhone 13 Pro Max**.
That last constraint is decisive.

| Criterion | Expo / React Native | Flutter | Kotlin Multiplatform |
|---|---|---|---|
| Single shared iOS+Android codebase | ✅ | ✅ | ⚠️ shared logic; UI still per-platform (Compose MP maturing) |
| Test on a physical iPhone **without a Mac/Xcode** | ✅ Expo Go / dev client — scan a QR code, runs over Wi-Fi | ❌ needs Xcode + provisioning on macOS | ❌ needs Xcode on macOS |
| TDD loop speed | ✅ Jest in Node, sub-second, no simulator | ✅ `flutter test` fast | ⚠️ JVM tests fast; iOS tests need a Mac |
| Native audio recording | ✅ `expo-audio` (AAC/M4A, permissions) | ✅ `record` package | ⚠️ expect/actual bindings, more plumbing |
| Local `.env` config, no host env vars | ✅ built-in `.env` + `EXPO_PUBLIC_*` | ⚠️ `--dart-define` / extra pkg | ⚠️ Gradle/plist plumbing |
| Shares mental model with existing code | ✅ TypeScript, same DI-through-constructors style as the tray app | ❌ Dart | ❌ Kotlin |

Expo wins on the hard requirement (iPhone testing with no Mac in the loop here) while also
giving the fastest red→green cycle: the decision logic is plain TypeScript run under Jest in
Node — no emulator, no device — so a test file executes in well under a second.

### Architecture (mirrors the desktop app's dependency injection)

The tray app wires collaborators through `build_app()` and injects fakes in tests. We do the
same here. Each service owns its logic behind a small injectable interface; the native module
sits at the very edge and is the only untested part:

- `AudioService` owns the capture state machine (`idle → recording → processing → idle`) and
  depends only on a `Recorder` interface. Tests inject a `FakeRecorder`; the real
  `useExpoAudioRecorder` (wrapping `expo-audio`) is wired in only inside a screen. It follows
  the desktop's hard rule: a failure must **never** strand the machine — a failed start falls
  back to idle, a failed stop still resets to idle rather than getting stuck in processing.

### Screens (Expo Router)

Navigation uses **Expo Router**; route files live in `src/app/` and every other file
(components, services) stays outside it. The presentational screens in `src/components/`
take their collaborators as props so their tests stay pure (RNTL against fakes); the
route files pull the wired services from `ServicesProvider` (`src/services/context.tsx`,
the mobile analogue of the desktop `build_app()`) and pass them down.

| Route | Screen | Purpose |
|---|---|---|
| `/` (`index`) | `RecorderScreen` | One-tap exam capture (feature A) |
| `/history` | `HistoryScreen` | Backend-synced exam feed (feature B) |
| `/exam/[id]` | `ExamEditor` | Inline SOAP editor, **Inject into AVImark**, and **Delete** (features B & C) |

**Inject into AVImark** (feature C) posts an injection request for the exam to the
backend; the phone never talks to the exam-room PC directly. The Windows tray app polls
the backend, then pastes the note into AVImark — or shows its Safety Flyout if AVImark
isn't foreground. See the repo `backend/README.md` "Remote AVImark injection" section.

> **Dependency note:** the React family is pinned to `19.2.3` (a `react-dom` override
> plus an exact `react-test-renderer`) so the `expo-router` deps resolve under a plain
> `npm ci` without `legacy-peer-deps` — which would otherwise drop jest-expo's peer
> Jest preset and break the test run.

## Getting started

```bash
cd mobile
npm install
cp .env.example .env        # then edit values for your clinic backend
npm test                    # Jest — the TDD suite (runs in Node, no device needed)
npm run typecheck           # tsc --noEmit
npm start                   # Expo dev server (QR code)
```

### Running on a physical iPhone 13 Pro Max

1. Install **Expo Go** from the App Store on the phone.
2. `npm start` on your dev machine, with the phone on the **same Wi-Fi**.
3. Scan the QR code with the Camera app → it opens in Expo Go.

Microphone recording works in Expo Go. If you later add native modules Expo Go doesn't bundle,
switch to a dev client: `npx expo run:ios` (needs a Mac) or an EAS build.

## Installing on the vet's phone (standalone pilot build)

Expo Go (above) is only good for a tethered demo — it needs your dev server running and the
phone on the same Wi-Fi. For a multi-day pilot where the vet uses the app on their own, build a
**standalone app with EAS** (Expo's cloud build service — no local Xcode/Android Studio needed).

The backend address is **editable in-app** — open **Settings** on the home screen and enter the
clinic backend's URL (and optional API key); it's saved on the device and applied live, no
rebuild needed. The `EXPO_PUBLIC_*` value baked in at build time (below) is only the *default*
the vet sees on first launch — you can even ship a build with none set and have the vet type it
in on first run. This pilot points the app at the clinic PC's **LAN IP** (e.g.
`http://192.168.1.50:8443`), which means **the phone must stay on the clinic Wi-Fi**; point it
at a publicly reachable URL instead (in Settings or baked in) to drop that constraint.

> The config for a plain-HTTP LAN backend is already wired up: `app.json` allows Android
> cleartext traffic (`expo-build-properties → usesCleartextTraffic`) and adds the iOS App
> Transport Security + Local Network exceptions. Without these a release build silently fails
> every request. (These are deliberately permissive for a LAN pilot; tighten before any App
> Store release.)

### One-time setup

```bash
npm install -g eas-cli          # or use: npx eas-cli@latest <command>
eas login                       # free Expo account
cd mobile
eas init                        # creates the EAS project + writes projectId into app.json
```

Optionally set the *default* backend address baked into the build. Edit `eas.json` and replace
the placeholder IP in **both** the `preview` and `production` profiles' `env` block:

```jsonc
"env": { "EXPO_PUBLIC_VETSCRIBE_API_URL": "http://<clinic-PC-LAN-IP>:8443" }
```

Find the PC's LAN IP with `ipconfig` on the clinic machine (the `IPv4 Address` on the active
adapter). **Give that PC a static IP or a DHCP reservation on the clinic router** so the address
stays put. If it does change, the vet just updates it in the app's **Settings** screen — no
rebuild — since the baked value is only the first-launch default.

If the backend requires a bearer key (`VETSCRIBE_BACKEND_API_KEY`), don't commit it to
`eas.json`. Store it as an EAS environment secret so it's injected at build time:

```bash
eas env:create --name EXPO_PUBLIC_VETSCRIBE_API_KEY --value "<the-key>" --visibility secret --environment production
```

(Leave it unset if the backend is unauthenticated.)

### Android — direct `.apk` install (easiest, free)

```bash
eas build --platform android --profile preview
```

EAS returns a download URL for an installable `.apk`. Send it to the vet; on the phone they open
the link, allow **Install unknown apps** for the browser when prompted, and install. Done — no
account, no store.

### iPhone — TestFlight (needs a paid Apple Developer account)

iOS has no sideloading, so a standalone iPhone install goes through **TestFlight**, which
requires enrolling in the **Apple Developer Program ($99/yr**, using your Apple ID — Apple
has no free standalone-install path).

```bash
eas build --platform ios --profile production     # EAS handles signing; sign in with your Apple ID when asked
eas submit --platform ios --latest                # uploads the build to App Store Connect / TestFlight
```

Then in App Store Connect → your app → **TestFlight**, add the vet as an internal or external
tester by email. They install the **TestFlight** app from the App Store and accept the invite.

### On first launch (both platforms)

- Open **Settings** on the home screen and confirm (or enter) the **Backend URL** for the clinic.
  If a default was baked in it's already filled; otherwise type it once and tap **Save**. The home
  screen shows a red "No backend set" hint until one is saved.
- The app asks for **microphone** permission (recording) — allow.
- On **iOS 14+** it also prompts for **Local Network** access the first time it reaches the LAN
  backend — the vet must **allow** this, or every request fails.
- Make sure the clinic PC's firewall allows inbound TCP on the backend port (`8443`) and the
  backend is bound to `0.0.0.0` (it is by default) so the phone can reach it over the LAN.

## Configuration (local `.env`, no host env vars)

The backend URL and API key are configurable **in-app** via the Settings screen and persisted on
the device (AsyncStorage), which overrides everything below. The `.env` / `EXPO_PUBLIC_*` values
are the build-time **defaults** used until the vet saves something — handy for dev (`expo start`)
and for pre-filling a pilot build.

Expo loads a local `.env` automatically. Only variables prefixed `EXPO_PUBLIC_` are exposed to
the app bundle. Copy `.env.example` → `.env` and fill in:

| Variable | Purpose |
|---|---|
| `EXPO_PUBLIC_VETSCRIBE_API_URL` | Base URL of the backend, e.g. `http://192.168.1.50:8000` |
| `EXPO_PUBLIC_VETSCRIBE_API_KEY` | Shared bearer secret (matches the backend's `VETSCRIBE_BACKEND_API_KEY`); leave blank if the backend is unauthenticated |

`.env` is git-ignored; `.env.example` is committed as the template.

## Testing

```bash
npm test               # run once
npm run test:watch     # TDD watch mode
```

Jest uses the `jest-expo` preset (transforms TypeScript and the Expo/RN ES modules). Pure-logic
services import no native module, so their suites run anywhere.

Three layers of test run under the same `npm test` (and so under CI's `test-mobile` job):

- **Unit** — services and components in isolation against injected fakes (`*.test.ts(x)`).
- **Integration** (`src/integration/*.integration.test.ts`) — the real `ApiClient` driven
  against `FakeBackend`, an in-memory stand-in faithful to `backend/`'s routes and JSON shapes.
  Covers cross-device sync (two clients, one backend) and the remote-injection bridge (phone
  request → desktop poll/ack, including fresh-note resolution).
- **End-to-end** (`src/integration/screens.e2e.test.tsx`) — the real screens rendered and driven
  with actual gestures (tap record, edit + save, tap Inject) through the real `ApiClient` and
  `FakeBackend` — the closest thing to a device run in Node, with mocked audio uploads.

### Local dev note (this repo's WSL checkout)

`/workspace` here is a 9p/drvfs mount whose concurrent `rename` semantics break npm's installer.
`node_modules` is therefore installed on the native ext4 filesystem and symlinked in. This is a
dev-machine quirk only — CI and a normal clone just run `npm install` directly.

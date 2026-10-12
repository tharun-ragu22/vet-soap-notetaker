# Getting the app on the vet's iPhone

How to put the Vet Soap Notetaker mobile app on a veterinarian's iPhone, and how to
ship updates afterward.

## The short version

iOS does not allow installing an un-reviewed app from a plain link (no sideloading).
Apple gives exactly three distribution methods, and each costs you one thing:

| Method | Separate app to install? | Register each device? | Apple review? |
|---|---|---|---|
| **TestFlight** | Yes — TestFlight, once | No | Light beta review (external) **or none** (internal) |
| Ad-hoc / internal | No | **Yes** (collect each device UDID) | None |
| App Store (incl. Unlisted) | No | No | **Full** App Review |

**We use TestFlight with the vet added as an _internal_ tester** — no device
registration, and internal testing needs **no review at all**. The only cost is that the
vet installs the TestFlight app once; after that, updates arrive automatically.

When the app is finished and you want to drop even the TestFlight step, graduate to
[Unlisted App Store distribution](#when-its-done-unlisted-app-store) — a plain App Store
link, no TestFlight, no registration — at the cost of a one-time full App Review.

---

## App facts (for reference)

- Expo SDK **57**, EAS project `59817bc6-cc63-44cf-a2bb-f1df4b8cf366`, owner **`tharunr`**
- iOS bundle id: **`com.vetsoapnotetaker.mobile`**
- Build profiles in `mobile/eas.json`: `production` (store/TestFlight), `preview` (ad-hoc/APK)
- CLI is run as `npx eas-cli@latest …` on the dev box (see `mobile/AGENTS.md`)

> ⚠️ **These commands need interactive Apple sign-in**, so run them in a real terminal
> (in a Claude Code session, prefix with `!`, e.g. `! npx eas-cli@latest build …`).

---

## Prerequisites (one time)

1. A **paid Apple Developer account** ($99/yr).
2. Logged in to EAS: `npx eas-cli@latest login` (account `tharunr`).
3. Because the app was renamed, `com.vetsoapnotetaker.mobile` is a **new identity** — it
   needs its own App Store Connect record and its own iOS credentials (an older build
   against `com.vetscribe.mobile` does not carry over).

---

## Part A — One-time App Store Connect + credentials setup

1. In [App Store Connect](https://appstoreconnect.apple.com) → **Apps → +** → **New App**.
   Select the bundle id `com.vetsoapnotetaker.mobile` (register it in the Developer portal
   first if it isn't in the dropdown). Set a name and primary language.
2. Note the app's **Apple ID** number under **App Information → General** — this is the
   `ascAppId` you'll put in `eas.json` (Part B).
3. Let EAS create and manage the iOS credentials (distribution certificate, store
   provisioning profile, and an App Store Connect API key for uploads):
   ```sh
   npx eas-cli@latest credentials --platform ios
   ```

---

## Part B — Build and upload to TestFlight

1. (Once) add your `ascAppId` to `mobile/eas.json` so submits are non-interactive:
   ```json
   "submit": {
     "production": {
       "ios": { "ascAppId": "<the Apple ID number from Part A step 2>" }
     }
   }
   ```
2. Build a store-signed app:
   ```sh
   npx eas-cli@latest build --platform ios --profile production
   ```
   (The `production` profile has `autoIncrement: true`, so the build number bumps itself.)
3. Upload it to App Store Connect / TestFlight:
   ```sh
   npx eas-cli@latest submit --platform ios --profile production
   ```
   You can combine steps 2–3 with `--auto-submit`. The build appears in TestFlight about
   10–15 minutes after processing finishes.

---

## Part C — Add the vet as a tester

### Recommended: internal tester (no review, no registration)

1. In App Store Connect, add the vet as a **user** on your team
   (**Users and Access → +**), using the Apple Account tied to their iPhone. A limited
   role (e.g. Developer or Marketing) is enough; up to 100 internal testers.
2. Go to **TestFlight → Internal Testing**, create/select a group, and enable the build
   for it. No beta review is required — the build is available to internal testers right
   away.

### Alternative: external tester via link (no team membership)

Use this if you don't want the vet on your App Store Connect team:

1. **TestFlight → External Testing → create a group**, assign the build.
2. Fill in the required **Test Information** (beta description, "what to test", feedback
   email). The **first** external build goes through a light **Beta App Review** (usually
   quick); later builds iterate faster.
3. Add the vet by **email invite** or share the group's **public link** (up to 10,000
   testers).

---

## Part D — On the vet's iPhone

1. Install **TestFlight** from the App Store (one time).
2. Open the invite — tap the email link, or in TestFlight tap **Redeem** and enter the
   code (internal testers see the app automatically once signed in with the invited Apple
   Account).
3. Tap **Install**. The app lands on the home screen like any other app.
4. Future updates show up in TestFlight automatically (optionally auto-install).

---

## Part E — Shipping an update

1. Bump the app `version` in `mobile/app.json` when it's a user-facing release (the build
   number auto-increments).
2. Rebuild and resubmit:
   ```sh
   npx eas-cli@latest build --platform ios --profile production --auto-submit
   ```
3. Enable the new build for the tester group. Internal testers get it with no review;
   external testers may get it without a full re-review.

> Note on OTA updates: `app.json` is configured for EAS Update (channel `production`), so
> some JS-only changes can ship without a new TestFlight build. Anything touching native
> modules or `app.json` native config still needs a rebuild (Parts B/E).

---

## Important caveat — the LAN backend

The build bakes in `EXPO_PUBLIC_VETSCRIBE_API_URL` (currently
`http://192.168.123.107:8443`, a clinic-LAN address). **However the app is installed, it
only reaches the backend when the phone is on that same network.** For off-site testing
the backend must be reachable over the internet (a public HTTPS URL or a tunnel), and the
build's `EXPO_PUBLIC_VETSCRIBE_API_URL` pointed at it (per-profile `env` in `eas.json`).
ATS is already relaxed for the cleartext LAN connection (`NSAllowsArbitraryLoads`), which
is fine for TestFlight but will draw a question at full App Review later.

---

## When it's done — Unlisted App Store

Once the app is production-ready and you want to drop the TestFlight step entirely:

1. Submit the production build to **App Review** as usual (Parts B).
2. In the submission's **Review Notes**, state the app is intended for **unlisted
   distribution**.
3. Submit the [Unlisted App Distribution request](https://developer.apple.com/support/unlisted-app-distribution/).
   (Requests are declined for apps still in a beta/prerelease state — it must pass full
   review.)
4. After approval, the app's availability becomes **Unlisted App** and Apple generates a
   **direct App Store link**. The vet taps the link → installs from the normal App Store →
   automatic updates. No TestFlight, no registration.

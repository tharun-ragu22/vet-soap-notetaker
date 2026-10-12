# Clinic setup checklist — before, during, and after the visit

A follow-along runbook for deploying Vet Soap Notetaker at a vet clinic. Work top to
bottom. Boxes marked **⚠️ gotcha** are the known silent-failure points — don't skip them.

- Deep detail for any step: [`deployment.md`](deployment.md)
- iOS build/TestFlight: [`ios-install.md`](ios-install.md)
- The demo itself: [`demo-plan.md`](demo-plan.md)

**The golden rule:** the first time you run the real installer and calibrate against real
AVImark should **not** be in front of the vet. Do a full dry run first (see Before §4).

---

## BEFORE — days ahead

### 1. Confirm the clinic realities (ask, don't assume)
- [ ] You'll have **admin rights** on the clinic PC (the installer needs admin for the
      firewall rule + Program Files install). Confirm who can approve the UAC prompt.
- [ ] The clinic PC has **working internet** (the backend calls out to your AI provider;
      no internet = no notes). ⚠️ Check it's not behind a proxy/content filter that blocks
      `api.openai.com` / `api.anthropic.com` / Google — those blocks are a classic silent fail.
- [ ] **AVImark is installed and licensed** on that PC, and you can open a **test patient
      chart** (never calibrate/demo on a real patient).
- [ ] You can get the **PC and the phone onto the same Wi-Fi**, and ideally touch the
      **router** (to reserve the PC's IP — see During §2).
- [ ] Which AI **provider** you'll use, and that its **API key has quota/billing** set up.

### 2. Build the deployable installer (on a Windows x64 machine)
- [ ] Drop a **real `backend\.env`** (provider keys) into `backend\` *before* compiling —
      the CI installer is **keyless** and can't generate notes. (deployment.md §2)
- [ ] ⚠️ **Leave `VETSCRIBE_BACKEND_API_KEY` unset** for a LAN pilot. If set, the seeded
      desktop config has no key → every Inject gets 401 and silently does nothing. (deployment.md §2)
- [ ] Build both onedir outputs (desktop + backend) and compile `installer.iss` →
      `dist\installer\VetSoapNotetakerSetup.exe`. (deployment.md §2)
- [ ] Copy the `.exe` to a **USB stick**.

### 3. Get the app onto the phone (iOS has lead time — do this early)
- [ ] iOS: Apple Developer enrolled; build + submit to **TestFlight**; add the vet as a
      tester; vet has installed TestFlight **and** the app. ⚠️ An *external* tester's first
      build needs Beta App Review (can take a day) — *internal* testers need none. (ios-install.md)
- [ ] Android (if used): `eas build --profile preview` → send the vet the `.apk` link.
- [ ] Don't rely on baking the clinic IP into the build — it's set in-app. But if you know
      the PC's reserved IP already, you can pre-set it in `eas.json` to save a step.

### 4. Dress rehearsal (the single most valuable prep step)
- [ ] On **your own Windows PC**, run the real `VetSoapNotetakerSetup.exe` end to end:
      install → tray green → record from the phone → note comes back → inject.
- [ ] Reboot your PC and confirm the stack comes back on its own (deployment.md §4).
- [ ] Uninstall it afterward (Add/Remove Programs) so you've seen the teardown work too.
- [ ] Rehearse the **calibration** flow and skim [`demo-plan.md`](demo-plan.md) out loud once.

### 5. Pack list
- [ ] USB stick with `VetSoapNotetakerSetup.exe`.
- [ ] The phone(s) with the app installed; charged.
- [ ] Your laptop (for `ipconfig`, troubleshooting, router access).
- [ ] These docs available **offline** (clinic Wi-Fi may be flaky).
- [ ] A **pre-generated fallback note** in case a live recording flops during the demo.
- [ ] The exam scripts from demo-plan.md on a second screen/phone.

---

## DURING — at the clinic

### 1. Install on the PC (~10 min)
- [ ] Plug in USB, run `VetSoapNotetakerSetup.exe`, approve the admin prompt, click through. (deployment.md §3)
- [ ] Confirm the **tray icon** is present and **green** (idle).
- [ ] Let the post-install "Launch" step run (or launch from the Start menu).

### 2. Network (~2 min)
- [ ] `ipconfig` → write down the **IPv4 Address** (e.g. `192.168.1.50`). You'll type it into the phone.
- [ ] **Recommended:** set a **DHCP reservation** for the PC on the router so its IP never
      changes → zero re-pointing after future reboots. (deployment.md §3 tip)

### 3. Calibrate AVImark (⚠️ the real risk point — give it time)
- [ ] Open AVImark to the **test chart's note screen** (the four S/O/A/P boxes visible).
- [ ] Tray → **Calibrate AVImark Boxes…** → click **inside each of the four boxes once**,
      in order, when prompted.
- [ ] ⚠️ **Contingency if it doesn't route cleanly:** if sections land in the wrong box or
      not at all, AVImark's controls may not match the standard-control assumptions. The app
      **falls back to pasting the whole note as one block** into the focused box — that still
      works and still demos the core value, just not split four ways. If so: note exactly what
      you saw (which box got what), take a screenshot of the note screen, and move on — don't
      burn the visit fighting it. (deployment.md §6; why this is the untested-against-real-AVImark bit.)

### 4. Set up the phone (~2 min)
- [ ] Phone is on the **same Wi-Fi** as the PC.
- [ ] App → **Settings** → **Backend URL** = `http://<PC-IP>:8443` → Save.
- [ ] Record a short test → **allow Microphone**.
- [ ] ⚠️ **Allow Local Network** (iOS) when prompted — deny it and *every* request fails
      silently. Recovery: iOS Settings → Vet Soap Notetaker → Local Network → on, relaunch.
- [ ] Confirm a **note comes back** on the phone.
- [ ] With the test chart open on the PC, tap **Inject into AVImark** → confirm placement.

### 5. Reboot smoke test (prove it's zero-touch — before the vet relies on it)
- [ ] **Reboot the PC**, log back in, wait ~20s, touch nothing.
- [ ] From the phone: record a test → note comes back (proves the backend auto-started).
- [ ] Inject once more → lands correctly.
- [ ] If this fails, go to **deployment.md §8 Troubleshooting** before proceeding.

### 6. The demo (if the vet is present)
- [ ] Follow [`demo-plan.md`](demo-plan.md): pitch → happy path → safety-net (wrong window) →
      no-lost-recording → fix-and-regenerate from History.
- [ ] Keep the pre-generated fallback note handy.

### 7. Capture before you leave
- [ ] Record the deployment specifics **somewhere secure** (not in the repo): PC IP, provider +
      which key, install date, app/TestFlight build, and any AVImark calibration quirks.
- [ ] If calibration was fiddly, keep the screenshot of AVImark's note screen for debugging.

---

## AFTER — leave-behind & follow-up

### 1. Hand off to the vet
- [ ] Show them the daily flow once more: it just lives in the tray; they drive from the phone.
- [ ] Tell them the **one thing that can break**: if the phone says it can't reach the
      backend, the PC's IP changed — re-enter it in the app's Settings (a DHCP reservation
      prevents this). (deployment.md §8)
- [ ] Give them a way to reach you, and a simple "it's not working" → what to check list.
- [ ] Rollback is theirs anytime: Add/Remove Programs removes everything and offers to delete
      data; delete the phone app. (deployment.md §7)

### 2. Confirm it stuck
- [ ] Next day, have the vet (or you, remotely by phone) confirm it **survived an overnight
      reboot** and a note still comes back.
- [ ] You have no remote access to the PC — logs are local at
      `%APPDATA%\VetScribe\logs\` (`vet_soap_notetaker.log`, `backend.log`). If something's
      off, walk the vet through finding them, or revisit.

### 3. Ongoing (if it's a pilot)
- [ ] Agree a **success metric** (e.g. minutes saved/patient, % notes actually used) and a
      check-in date.
- [ ] **Monitor your provider's API usage/billing** — a runaway or a blocked key shows up as
      "note generation failed" to the vet.
- [ ] Shipping updates later:
      - **Phone app:** rebuild + resubmit to TestFlight (ios-install.md Part E); some JS-only
        changes can go out as an EAS OTA update with no new build.
      - **PC (desktop/backend):** rebuild the installer and re-run it on the PC — it stops the
        running appliance first and **preserves** the existing `~/.vetscribe` config + calibration
        (config seed is `onlyifdoesntexist`). (deployment.md §2–§3)

---

## One-glance "is it working?" test (anytime)
From the phone, on the clinic Wi-Fi: **record a 10-second test → a note comes back → Inject →
it lands in the chart.** If all three happen, the whole stack (backend up, LAN reachable,
desktop polling, AVImark injection) is healthy.

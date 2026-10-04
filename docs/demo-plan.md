# Vet Soap Notetaker — Live Demo Plan (for a vet audience)

A ~8–10 minute flow to show Vet Soap Notetaker to a practicing vet. It leads with their pain
(charting time), shows the happy path, then the two things that actually earn trust in a
clinical setting: the **safety net** (never pastes into the wrong chart) and **no lost
recordings** (audio survives a backend outage).

Read the [exam scripts](#exam-scripts) aloud during the recording steps. They're written to
be spoken in 30–60 seconds and to produce a clean Subjective / Objective / Assessment / Plan.

---

## Elevator pitch (~30 sec — when you've only got a moment)

> "You know how you lose a few minutes after every patient typing up the SOAP note? Vet Soap Notetaker
> writes it for you. You hit a hotkey, talk to the owner like you always do, hit it again, and
> a structured note lands in the AVImark chart a few seconds later — in your words. It never
> pastes into the wrong patient's chart, and if the network drops your recording is saved and
> retried, never lost. It's basically an hour of charting a day handed back to you."

---

## The pitch (~90 sec — spoken, before the live demo)

**Open with the problem — make them feel it:**
> "Think about how your day actually goes. You see a patient, you talk to the owner, you do the
> exam — and then you either type up the note right there while the owner waits, or you carry it
> in your head to the next room and write it up later when you've got five charts stacked up.
> Either way you're losing time, and the notes you write at 6pm are never as good as what was
> fresh in the room."

**Name the real cost:**
> "For most vets that's two to four minutes of typing per patient. Across a full day that's an
> hour of charting you're doing instead of seeing patients or going home on time. And it's the
> part of the job nobody went to vet school for."

**Introduce the solution simply:**
> "Vet Soap Notetaker listens to the visit and writes the SOAP note for you. You press a hotkey when the
> exam starts, you talk to your patient and the owner exactly like you always do, you press it
> again when you're done, and a few seconds later a structured note — Subjective, Objective,
> Assessment, Plan — is sitting in the patient's AVImark chart. In your words, from what you
> actually said."

**The value prop, in one line:**
> "So instead of writing notes, you're just... doing the exam. The note is a byproduct."

**Then the trust points — this is what closes it for a clinician:**
> "And I built it knowing you'd never trust something that could mess up a chart. So two things.
> One: it will never paste a note into the wrong patient's record. If AVImark isn't the window
> you're looking at, it stops and hands you the note instead of guessing. Two: if the internet
> drops or the AI is having a bad day, your recording is never lost — it's saved and retried
> automatically, and the note shows up when things recover. Nothing you say in that room
> disappears."

**Close by handing them control:**
> "You're always the one in charge. The note is generated from your words, you can fix anything
> before it's saved, and nothing is final until you say so. Let me show you."

*(→ go straight into Script A / the happy-path demo.)*

### If they push back — quick objection handlers

- **"Is it accurate?"** → "It writes from your words, not from a template. And you review every
  note before it's saved — you can correct the transcript and regenerate a fresh note in one
  click. It's a first draft that's usually 90% there, not a black box."
- **"What about the wrong chart / privacy?"** → "It physically won't paste unless the right
  AVImark chart is the window in front of you. That guard is the one thing I refuse to weaken."
- **"What if it goes down mid-day?"** → "Your audio is archived and queued the moment a
  recording finishes. A backend outage delays the note, it never loses it."
- **"Do I have to change how I work?"** → "One hotkey. You talk to the owner exactly like you do
  now. That's the whole workflow change."

---

## Before the vet walks in (staging — don't do this live)

- [ ] App running; **green** tray icon visible.
- [ ] AVImark (or `tests/acceptance/mock_avimark.py`) open to a **test patient chart** — never a real one.
- [ ] Backend up and reachable; do **one throwaway recording** first to warm the endpoint and confirm the mic works.
- [ ] Have the exam scripts below on a phone/second screen to read from.
- [ ] Decide: real AVImark vs. mock window, and live audio vs. a pre-generated note as a fallback (see [risks](#pre-demo-decisions)).
- [ ] Know your hotkey (default **`Ctrl+Shift+R`**).

---

## The flow

### 1. Frame the problem — 30 sec, no clicking
> "You finish an exam, then spend 3–5 minutes typing it into AVImark while the next patient
> waits. Vet Soap Notetaker does that write-up for you — you just talk normally."

Point at the tray icon: **green = idle and listening for the hotkey.**

### 2. Happy path — hotkey → note in the chart (the core, ~3 min)
1. Click into the AVImark patient chart so it's the foreground window.
2. Press **`Ctrl+Shift+R`** — tray icon turns **red (recording)**.
3. Read **Script A (limp / CCL)** aloud.
4. Press **`Ctrl+Shift+R`** again — icon turns **yellow (processing)**.
5. The structured SOAP note is **typed straight into the chart** (simulated `Ctrl+V`). Icon back to **green**.
6. Let them read it: "S / O / A / P, all filled from what you just said."

**The hook:** *"You spoke for 40 seconds. That's the note done."*

### 3. Safety net — wrong window (trust-builder, ~1.5 min)
1. Click away from AVImark (desktop or another window) so it is **not** foreground.
2. Record **Script B (itchy skin)** and stop.
3. Instead of pasting blindly, the **Safety Flyout** appears bottom-right with the note + **Copy & Inject**.
4. Say: **"It will never paste into the wrong patient's chart. If AVImark isn't the window you're in, it holds the note and waits for you."** — the single most reassuring point for a clinician.
5. Click **Copy & Inject** to drop it into the correct chart.

### 4. No lost recordings — backend down (trust-builder, ~1.5 min, optional)
> Only do this live if you can take the backend offline cleanly. Otherwise just describe it.

1. With the backend unreachable, record **Script C (short)** and stop.
2. A flyout explains the backend is unavailable — **and the raw audio is saved and queued**, not lost.
3. Bring the backend back. Within ~60s the retry worker succeeds and pops the recovered note.
4. Say: *"Even if the internet or the AI hiccups, your recording is never gone."*

### 5. Fix-and-regenerate from History (~1.5 min)
1. Right-click tray → open the **History** window.
2. Show a past transcript and **hand-edit one line** (e.g. correct a misheard drug name or dose).
3. Click **Regenerate from Transcript** — a fresh SOAP note is generated from your corrected
   words and lands as an **unsaved** edit.
4. Say: *"You're always in control — nothing is saved until you click Save, and you can re-run
   the note after correcting anything."*

### 6. Close — 30 sec
- Right-click tray → **Settings**: hotkey, target window, and "launch on startup" are all one-time config. *"Set it once, forget it."*
- Land the value: **fewer minutes per patient, notes in your own words, and it can't write to the wrong chart.**

---

## Exam scripts

Read at a normal pace. Say the "Vet:" / "Owner:" labels out loud or skip them — the model
handles both. Each is designed to hit a full SOAP note.

### Script A — limp / cranial cruciate (happy path, ~40s)
> Bella, three-year-old spayed lab, in for a limp on the right hind leg since yesterday after
> chasing a squirrel. She's bright, alert, and hydrated. Weight 31 kilos, temp 101.2, heart
> and lungs normal. On the orthopedic exam there's a grade three lameness on the right hind,
> pain on palpation of the right stifle, positive cranial drawer sign, and moderate joint
> effusion. Left stifle and hips are normal. My assessment is a right cranial cruciate ligament
> tear, possibly with a meniscal injury. Plan: sedated radiographs of the stifle today,
> Carprofen 75 milligrams by mouth twice daily with food, Gabapentin 300 milligrams every eight
> to twelve hours for pain, strict rest and leash walks only, and discuss a TPLO surgical
> referral. Recheck in ten to fourteen days.

### Script B — itchy skin / allergic dermatitis (safety-net demo, ~40s)
> Owner: Daisy's been scratching a lot the last couple of weeks, mostly her belly and her paws,
> and she keeps licking her feet. Vet: Let's take a look. On exam she's bright and alert, weight
> 24 pounds, temp 101.3, heart and lungs normal. I see some redness on the belly and inside the
> back legs, and the paws are a little pink from licking. No fleas today and no crusting or
> discharge. This looks like an allergic dermatitis, most likely atopic given the season and the
> paw licking. Plan: start Apoquel 5.4 milligrams by mouth twice daily for two weeks then once
> daily, keep her on monthly flea prevention, and a medicated shampoo twice a week. Recheck in
> three weeks, and if it's not settling we'll talk about a food trial or allergy testing.

### Script C — short recheck (backend-outage demo, ~20s)
> Luna, back for her three-month diabetes recheck. Owner says she's drinking less water, which
> is a good sign. Fructosamine came back at 380, down from 520 last time but still above target.
> Weight is stable at 9.2 kilos. Increasing her Lantus from 2 units to 2.5 units twice daily,
> keep the prescription diabetic diet, and recheck fructosamine in six weeks.

### Script D — routine wellness (spare / alternate happy path, ~30s)
> Biscuit's in for his annual wellness exam and he's due for shots. Nice shiny coat, looks
> great. Weight 62 pounds, up two pounds from last year but still healthy for a lab mix. Heart
> rate 90, lungs clear, temp 101.4. Teeth look decent, a little tartar on the molars. Giving
> him his DHPP and rabies boosters today. No concerns — keep up with the monthly heartworm
> prevention, see you next year.

### Script E — the History edit / regenerate demo (for step 5)

The point of this step is to show that the note is generated from *your words*, so correcting
the transcript changes the note. Pick the edit based on how dramatic you want it to look.

**Option 1 — small edit, small change (safe, quick):** reuse the **Script C** note, and in the
History window change one number in the transcript, e.g. **"2.5 units"** → **"3 units"**.
Regenerate and show the Plan now reads 3 units. Good for "it really does follow what I typed."

**Option 2 — one edit that flips the whole note (recommended, more impressive):** this is the
one to lead with. It shows a single corrected finding cascading into a different Assessment
*and* Plan — exactly what happens when the AI mishears one clinically pivotal word and you fix it.

Record this transcript for the History entry (note the **negative** drawer sign):

> Bella, three-year-old spayed lab, in for a right hind limp since yesterday after chasing a
> squirrel. Bright and alert, weight 31 kilos, temp 101.2, heart and lungs normal. On the
> orthopedic exam there's a mild lameness on the right hind and some discomfort on the stifle,
> but the cranial drawer sign is negative and I don't feel any joint effusion. Looks like a
> soft-tissue strain. Plan: rest and leash walks for two weeks, Carprofen for pain, and recheck
> if it's not improving.

That produces a note along the lines of:

> **A:** Right hind soft-tissue strain / sprain; no evidence of cranial cruciate instability.
> **P:** Conservative management — strict rest and leash walks 2 weeks, Carprofen, recheck if not improving.

Now, in the History window, make the **one-word correction** a vet would make after re-examining
(or after catching a mistranscription): change

> "the cranial drawer sign is **negative** and I don't feel any joint effusion"

to

> "the cranial drawer sign is **positive** and there's moderate joint effusion"

Click **Regenerate from Transcript**. The new note shifts to something like:

> **A:** Right cranial cruciate ligament (CCL) rupture; possible meniscal injury.
> **P:** Sedated stifle radiographs, NSAID + gabapentin for pain, strict rest, and discuss TPLO surgical referral.

**What to say:** *"One finding changed — drawer sign — and the whole clinical picture and plan
changed with it. The note isn't a template; it reasons from exactly what you said. And notice
it landed as an unsaved edit — nothing is committed to the chart until I click Save."*

---

## Pre-demo decisions

- **Real AVImark vs. mock window.** Without a licensed AVImark on the demo machine,
  `tests/acceptance/mock_avimark.py` is the stand-in — but a vet finds real AVImark far more
  convincing. Confirm which you'll have on the day.
- **Live audio vs. pre-recorded.** Reading a live script is more impressive but riskier (mic,
  accent, room noise). Keep one pre-generated note ready as a fallback if a live recording flops.
- **Section 4 (backend down) is high-risk / high-reward.** Best trust story, fiddliest to
  stage. If short on time or unsure of the setup, cut it and just *describe* it.

---

## Talking points to keep in your pocket

- "You talk to your patient and owner like you always do — the note writes itself."
- "It never pastes into the wrong chart. If it's not sure, it stops and hands the note to you."
- "If the AI or the network goes down, your recording is saved and retried automatically — nothing is lost."
- "The note is in your words. You can correct the transcript and regenerate, and nothing saves until you say so."
- "Set the hotkey and target window once. After that it just lives in your system tray."

"""Example transcripts NoteGenerator.generate() could realistically receive, covering both
typical exam-room visits and edge cases (missing info, multiple patients, irrelevant
chatter, garbled ASR output) that the SOAP_SYSTEM_PROMPT's "Not discussed" instruction and
provider parsing need to hold up against.

Each Case's metadata may include "must_include": a dict of SoapNote field name -> list of
substrings that should appear (case-insensitively) in that field, checked by
evals.evaluators.FieldKeywordCoverage.
"""

from pydantic_evals import Case

CASES = [
    Case(
        name="routine_wellness_exam",
        inputs=(
            "Vet: Bring Biscuit up here for me. So he's in for his annual wellness visit today. "
            "Owner: Yep, just the usual checkup and he's due for shots. Vet: Great, he's looking "
            "good, nice and shiny coat. Weight is 62 pounds, up two pounds from last year but "
            "still in a healthy range for a lab mix. Heart rate 90, lungs clear, temp 101.4. "
            "Teeth look decent, a little tartar building on the molars. I'm going to give him "
            "the DHPP and rabies boosters today. Owner: Sounds good. Vet: He's all set, no "
            "concerns. See you next year, keep up with the heartworm prevention monthly."
        ),
        metadata={
            "category": "routine",
            "must_include": {
                "subjective": ["annual", "wellness"],
                "objective": ["62", "101.4"],
                "plan": ["dhpp", "rabies"],
            },
        },
    ),
    Case(
        name="acute_gi_illness",
        inputs=(
            "Owner: He's been throwing up since yesterday morning, probably five or six times, "
            "and he won't touch his food. Vet: Any diarrhea? Owner: A little, yeah, this morning. "
            "Vet: Okay. Rex, let's take a look at you. Temp is 102.1, that's a bit elevated. "
            "Gums are a little tacky, mild dehydration, maybe 5%. Abdomen is a little tense but "
            "no obvious mass. Owner: Could he have eaten something? Vet: Possible, he's a "
            "labrador after all. My read is acute gastroenteritis, could be dietary indiscretion. "
            "I want to start him on subcutaneous fluids today, give him a Cerenia injection for "
            "the nausea, and send you home with a bland diet, boiled chicken and rice, for the "
            "next three days. If he's not improving by tomorrow, call us or head to the ER."
        ),
        metadata={
            "category": "sick_visit",
            "must_include": {
                "subjective": ["vomiting"],
                "objective": ["102.1", "dehydrat"],
                "assessment": ["gastroenteritis"],
                "plan": ["fluids", "cerenia", "bland diet"],
            },
        },
    ),
    Case(
        name="emergency_trauma",
        inputs=(
            "Owner: She got hit by a car, oh my god, she was just in the driveway. Vet: Okay, "
            "we've got her, let's move fast. Gums are pale, cap refill is over three seconds, "
            "heart rate 180, femoral pulses are weak. She's got obvious deformity of the right "
            "hind leg, probably fractured. Breathing is rapid and shallow. Get me an IV catheter "
            "and start a bolus of lactated ringers, and pull blood for a PCV and total solids. "
            "I'm worried about internal bleeding, we need chest and abdominal films as soon as "
            "she's stable enough. Owner: Is she going to be okay? Vet: She's critical right now, "
            "we're doing everything we can, I'll update you as soon as we know more."
        ),
        metadata={
            "category": "emergency",
            "must_include": {
                "subjective": ["hit by a car"],
                "objective": ["pale", "180", "fracture"],
                "plan": ["iv", "fluids", "radiograph"],
            },
        },
    ),
    Case(
        name="multi_pet_visit",
        inputs=(
            "Owner: I brought both of them in today, figured I'd save a trip. Vet: No problem, "
            "let's start with Whiskers. She's here for the itchy skin you mentioned on the phone. "
            "I see some redness and hair loss around the base of the tail, looks like flea "
            "allergy dermatitis, I don't see any fleas now but that's consistent with the "
            "pattern. I'll send you home with a topical flea preventative and a short course of "
            "an anti-itch medication. Now for Tom, he's just here for his rabies booster, "
            "correct? Owner: Right, he's due. Vet: Tom looks great otherwise, weight's stable at "
            "11 pounds, heart and lungs sound normal. Giving him the rabies vaccine now."
        ),
        metadata={
            "category": "multi_patient",
            "must_include": {
                "assessment": ["flea allergy dermatitis"],
                "plan": ["flea", "rabies"],
            },
        },
    ),
    Case(
        name="vague_incomplete_transcript",
        inputs=(
            "Owner: Hey doc. Vet: Hey, how's it going. So what brings you in today. Owner: Yeah "
            "he's just been kind of off. Vet: Off how? Owner: I don't know, just not himself. "
            "Vet: Okay, well let's take a look. Yeah, hmm. Owner: What do you think? Vet: I'm "
            "not totally sure yet, let me think about it and get back to you."
        ),
        metadata={"category": "low_information"},
    ),
    Case(
        name="owner_declines_treatment",
        inputs=(
            "Vet: Based on what I'm feeling on that mass, and given her age, I'd really like to "
            "run bloodwork and get X-rays before we decide anything, and honestly I think "
            "surgical removal and biopsy is the right call here. Owner: I hear you, but money's "
            "really tight right now, I can't do the full workup today. Vet: I understand. At "
            "minimum I'd like to monitor it closely, can you check it weekly and let me know if "
            "it changes size, color, or if she starts licking at it? Owner: Yeah, I can do that. "
            "Vet: Okay, let's plan to recheck in three weeks, and if it grows at all before "
            "then, please bring her back in sooner, even if that means we have to figure out "
            "financing for the surgery."
        ),
        metadata={
            "category": "declined_care",
            "must_include": {"plan": ["recheck", "three weeks"]},
        },
    ),
    Case(
        name="chronic_condition_recheck",
        inputs=(
            "Vet: So this is the three month recheck for her diabetes. How's she doing on the "
            "insulin? Owner: Good I think, she's drinking less water than she was. Vet: That's a "
            "great sign. Let's get a fructosamine level and a quick glucose curve today. ... "
            "Okay, fructosamine came back at 380, that's improved from 520 last time but still "
            "above target. Weight's stable at 9.2 kilos. I want to bump her Lantus up slightly, "
            "from 2 units to 2.5 units twice daily, and recheck the fructosamine again in six "
            "weeks. Keep feeding the prescription diabetic diet, no changes there."
        ),
        metadata={
            "category": "chronic_recheck",
            "must_include": {
                "objective": ["380", "9.2"],
                "plan": ["lantus", "2.5", "six weeks"],
            },
        },
    ),
    Case(
        name="garbled_partial_transcript",
        inputs=(
            "-- can't really hear -- something about the leg -- limping since -- [inaudible] -- "
            "yeah he does that -- okay let's -- [static] -- put weight on it fine when -- I "
            "think maybe -- [inaudible] -- x-ray just to be safe -- okay -- thanks doc --"
        ),
        metadata={"category": "poor_audio"},
    ),
    Case(
        name="dental_procedure_consult",
        inputs=(
            "Vet: Let's talk about Max's teeth. On exam I'm seeing grade 3 periodontal disease, "
            "heavy tartar buildup on the upper premolars and molars, some gum recession, and a "
            "couple of teeth that look mobile, probably the upper fourth premolar and first "
            "molar on the right side. Owner: Is that serious? Vet: It can lead to infection and "
            "pain if we don't address it, and it's likely already uncomfortable for him. I'd "
            "recommend a dental cleaning under anesthesia with full mouth X-rays, and we should "
            "plan on extracting those two mobile teeth. Owner: What's the cost looking like? "
            "Vet: I'll have the front desk put together an estimate, but plan for anesthesia, "
            "cleaning, X-rays, and possible extractions. We can schedule for next Tuesday if "
            "that works, and he'll need to fast the night before."
        ),
        metadata={
            "category": "dental",
            "must_include": {
                "objective": ["periodontal", "tartar"],
                "plan": ["dental cleaning", "extract"],
            },
        },
    ),
    Case(
        name="lasa_drug_leukeran_short",
        inputs=(
            "Vet: Make sure the label says Leukeran, 2 milligrams, one tablet PO SID for ten "
            "days. That's once daily, SID, not BID. Do not confuse it with Keppra. Technician: "
            "Got it, Leukeran 2 mg PO SID for ten days."
        ),
        metadata={
            "category": "lasa_drug_short",
            "must_include": {"plan": ["leukeran", "sid"]},
        },
    ),
    Case(
        name="weight_based_dosing_denominator_short",
        inputs=(
            "Vet: For Bella's IMHA flare we're starting Cyclosporine at 5 milligrams per "
            "kilogram, PO, twice daily. Make sure the label reads 5 mg per kg, not just a flat "
            "5 mg. Technician: Understood, Cyclosporine 5 mg/kg PO BID for the "
            "immunosuppression."
        ),
        metadata={
            "category": "dosing_denominator_short",
            "must_include": {"plan": ["cyclosporine", "5 mg/kg", "bid"]},
        },
    ),
    Case(
        name="sig_dosing_lasa_differentiation",
        inputs=(
            "Veterinarian: Okay, for Max's severe immune-mediated hemolytic anemia relapse, we "
            "are adjusting his immunosuppressive protocol. We will discontinue the oral "
            "Prednisone and transition him to Cyclosporine at 5 milligrams per kilogram PO BID. "
            "Make sure the owner understands that is BID, twice daily, not SID. "
            "Technician: Got it. And what about his secondary hepatic support and the "
            "chemotherapy agent? "
            "Veterinarian: For hepatic support, start Ursodiol, 250 milligram tablet, give "
            "one-half tablet PO SID, which is once daily. Do not administer BID or he will "
            "develop severe diarrhea. For the chemotherapy agent, we are prescribing Leukeran, "
            "2 milligram tablets. Give one tablet PO SID for ten days. I repeat, Leukeran 2 mg "
            "SID. Do not confuse Leukeran with Keppra, and ensure the label explicitly states "
            "SID for once daily administration. "
            "Technician: Understood. Leukeran 2 mg PO SID for 10 days, Ursodiol 125 mg PO SID, "
            "and Cyclosporine 5 mg/kg PO BID."
        ),
        metadata={
            "category": "sig_dosing_lasa",
            "must_include": {
                "subjective": ["hemolytic anemia"],
                "plan": ["cyclosporine", "5 mg/kg", "bid", "ursodiol", "leukeran", "sid"],
            },
        },
    ),
    Case(
        name="geriatric_feline_hyperthyroid_ckd",
        inputs=(
            "Veterinarian: Good morning, Mrs. Davis. Let's take a look at Fluffy today. She's a "
            "14-year-old domestic shorthair, correct? What's been going on at home? "
            "Owner: Hi, Doctor. Yes, she's 14. She's been drinking a massive amount of "
            "water lately, filling up the water bowl twice a day. And she's vocalizing at night, "
            "waking us up at 3 AM howling. Her appetite is ravenous, but she seems to be losing "
            "weight. She had one episode of clear fluid vomiting yesterday morning. "
            "Veterinarian: Understood. Increased thirst, polyphagia, night vocalization, and "
            "weight loss are classic signs we need to investigate. Let's check her vitals and "
            "do a physical exam. Fluffy's weight is down to 3.2 kilograms, down from 3.8 "
            "kilograms six months ago. Temperature is 101.4 Fahrenheit. Heart rate is elevated "
            "at 220 beats per minute with a grade two out of six systolic murmur heard loudest "
            "at the left sternal border. Femoral pulses are strong and bounding. On abdominal "
            "palpation, her kidneys feel small, firm, and irregularly contoured. Her thyroid "
            "gland is palpably enlarged on the right side, a distinct thyroid slip. Her mucous "
            "membranes are pink and moist, CRT under two seconds. "
            "Owner: Oh dear, is it her kidneys again or something else? "
            "Veterinarian: It looks like a combination. The enlarged thyroid slip and elevated "
            "heart rate strongly suggest hyperthyroidism, while the small, irregular kidneys "
            "point toward underlying chronic kidney disease, probably IRIS Stage 2. We need to "
            "run a full diagnostic panel: a complete blood count, chemistry panel, total T4, and "
            "a urinalysis via cystocentesis. If her T4 is elevated, we will start her on "
            "Methimazole, 2.5 milligrams orally every 12 hours. We'll also want to measure her "
            "systemic blood pressure using Doppler to check for hypertension secondary to the "
            "hyperthyroidism."
        ),
        metadata={
            "category": "geriatric_comorbid",
            "must_include": {
                "subjective": ["polydipsia", "weight loss"],
                "objective": ["3.2", "220", "thyroid"],
                "assessment": ["hyperthyroid", "kidney"],
                "plan": ["methimazole", "t4", "urinalysis"],
            },
        },
    ),
    Case(
        name="geriatric_feline_extended_half_hour_visit",
        inputs=(
            "Veterinarian: Good morning, Mrs. Davis. Let's take a look at Fluffy today. She's a "
            "14-year-old domestic shorthair, correct? What's been going on at home? "
            "Owner: Hi, Doctor. Yes, she's 14. She's been drinking a massive amount of water "
            "lately, filling up the water bowl twice a day. And she's vocalizing at night, "
            "waking us up at 3 AM howling. Her appetite is ravenous, but she seems to be losing "
            "weight. She had one episode of clear fluid vomiting yesterday morning. "
            "Veterinarian: Has she had any diarrhea, or any changes in her litter box habits? "
            "Owner: No diarrhea, but I think she's peeing more too, the litter box needs "
            "changing more often. "
            "Veterinarian: Okay, that fits with what I'd expect given the thirst. Any coughing, "
            "hiding, or reluctance to jump up on furniture? "
            "Owner: She still jumps on the counter, actually she seems more restless than "
            "usual, pacing around at night. "
            "Veterinarian: Understood. Increased thirst, polyphagia, night vocalization, "
            "restlessness, and weight loss are classic signs we need to investigate. Let's "
            "check her vitals and do a physical exam. Fluffy's weight is down to 3.2 kilograms, "
            "down from 3.8 kilograms six months ago. Temperature is 101.4 Fahrenheit. Heart "
            "rate is elevated at 220 beats per minute with a grade two out of six systolic "
            "murmur heard loudest at the left sternal border. Femoral pulses are strong and "
            "bounding. On abdominal palpation, her kidneys feel small, firm, and irregularly "
            "contoured. Her thyroid gland is palpably enlarged on the right side, a distinct "
            "thyroid slip. Her mucous membranes are pink and moist, CRT under two seconds. Her "
            "coat is a little unkempt, and I can feel her spine and ribs more easily than last "
            "visit, so we've clearly lost some muscle and fat. "
            "Owner: Oh dear, is it her kidneys again or something else? "
            "Veterinarian: It looks like a combination. The enlarged thyroid slip, elevated "
            "heart rate, and murmur strongly suggest hyperthyroidism, while the small, "
            "irregular kidneys point toward underlying chronic kidney disease, probably IRIS "
            "Stage 2. Those two conditions can actually mask each other on bloodwork, so we "
            "need to be careful about how we treat this. "
            "Owner: Is this going to be expensive? I want to do right by her but I need to know "
            "what we're looking at. "
            "Veterinarian: I understand completely, let's talk about a stepwise plan. First we "
            "run a full diagnostic panel today: a complete blood count, chemistry panel, total "
            "T4, and a urinalysis via cystocentesis. That will tell us how advanced the kidney "
            "disease is and confirm the hyperthyroidism. If her T4 is elevated, we will start "
            "her on Methimazole, 2.5 milligrams orally every 12 hours, and recheck her T4 and "
            "kidney values in three to four weeks to make sure the dose is right, because "
            "treating the thyroid too aggressively can actually unmask worse kidney disease. "
            "We'll also want to measure her systemic blood pressure using Doppler today to "
            "check for hypertension secondary to the hyperthyroidism, since untreated "
            "hypertension can damage her eyes, kidneys, and heart. "
            "Owner: Okay, that makes sense. What about her diet, should I change what she's "
            "eating? "
            "Veterinarian: Good question. Once we know how advanced the kidney disease is, "
            "I'd like to transition her gradually to a renal support diet, but let's not do "
            "that until we have the T4 back, because renal diets are lower protein and we don't "
            "want to compound weight loss if the hyperthyroidism is still burning through her "
            "calories unchecked. For now, let's just make sure she's eating consistently and "
            "has access to fresh water at all times. "
            "Owner: Should I be worried about her heart with that murmur? "
            "Veterinarian: The murmur and the fast heart rate are most likely secondary to the "
            "hyperthyroidism, we call it a thyrotoxic heart. Once we get the thyroid under "
            "control with the Methimazole, I'd expect the heart rate and murmur to improve. If "
            "it doesn't, we'll refer her for an echocardiogram with a cardiologist. "
            "Owner: Okay, I trust you. When should we come back? "
            "Veterinarian: Let's draw the bloodwork and urine today, get her started on the "
            "Methimazole once we confirm the T4 is elevated, and recheck in three to four "
            "weeks with repeat bloodwork, a blood pressure check, and a weight check. Call us "
            "sooner if she stops eating, has more vomiting, or seems lethargic."
        ),
        metadata={
            "category": "geriatric_comorbid_long",
            "must_include": {
                "subjective": ["polydipsia", "weight loss", "restless"],
                "objective": ["3.2", "220", "thyroid", "murmur"],
                "assessment": ["hyperthyroid", "kidney"],
                "plan": ["methimazole", "2.5", "blood pressure", "three to four weeks"],
            },
        },
    ),
    Case(
        name="canine_preventive_ambient_noise",
        inputs=(
            "Veterinarian: Hey Sarah, good to see you! How was your trip to North Carolina? "
            "Owner: Oh, it was fantastic! But Buster here loved running through the woods. "
            "Speaking of which, he's 16 weeks old today! He's growing so fast, look at those "
            "huge paws. Quiet, Buster! Stop barking at the scale, buddy. "
            "Veterinarian: He looks great! Let's get his final puppy series completed. Scale "
            "says 24.5 pounds. Temperature is 101.8. Heart and lungs sound perfectly clear, no "
            "murmurs, normal respiratory effort. Eyes and ears are clean. Teeth look great, "
            "adult canines are starting to erupt. Since you mentioned he goes hiking in brushy "
            "areas and frequents dog parks, we need to address non-core lifestyle vaccines in "
            "addition to his core series today. "
            "Owner: Yeah, we definitely want him protected against everything if he's going to "
            "be in the woods and around other dogs. "
            "Veterinarian: Perfect. Today he is due for his final DAP booster, that's Distemper, "
            "Adenovirus, Parvovirus. We will also administer his first Rabies vaccine, 1-year "
            "labeled, given subcutaneously in the right hind leg. Because of the hiking and "
            "wooded areas, I strongly recommend the Lyme disease vaccine and the Leptospirosis "
            "4-way vaccine, both administered today with boosters required in 3 to 4 weeks. And "
            "for the dog park, we'll give the oral Bordetella vaccine. "
            "Owner: Sounds good, let's do all of them. Is there anything special I should watch "
            "out for after the shots? "
            "Veterinarian: Just monitor him for mild lethargy or slight soreness at the "
            "injection sites for 24 hours. If you see facial swelling, hives, or repeated "
            "vomiting, call us immediately."
        ),
        metadata={
            "category": "preventive_ambient_noise",
            "must_include": {
                "subjective": ["16", "hiking"],
                "objective": ["24.5", "101.8"],
                "plan": ["rabies", "dap", "leptospirosis", "lyme", "bordetella"],
            },
        },
    ),
    Case(
        name="canine_preventive_extended_half_hour_visit",
        inputs=(
            "Veterinarian: Hey Sarah, good to see you! How was your trip to North Carolina? "
            "Owner: Oh, it was fantastic! But Buster here loved running through the woods. "
            "Speaking of which, he's 16 weeks old today! He's growing so fast, look at those "
            "huge paws. Quiet, Buster! Stop barking at the scale, buddy. "
            "Veterinarian: He looks great! Let's get his final puppy series completed. Scale "
            "says 24.5 pounds. Temperature is 101.8. Heart and lungs sound perfectly clear, no "
            "murmurs, normal respiratory effort. Eyes and ears are clean. Teeth look great, "
            "adult canines are starting to erupt. Belly feels soft, no pain on palpation. Joints "
            "and gait look normal for his age, no limping. "
            "Owner: That's a relief, he's been so wobbly on the stairs at home. "
            "Veterinarian: That's pretty normal for a big breed puppy still growing into his "
            "paws, nothing on exam concerns me there. Now, since you mentioned he goes hiking in "
            "brushy areas and frequents dog parks, we need to address non-core lifestyle "
            "vaccines in addition to his core series today, and I also want to talk about "
            "heartworm and flea and tick prevention given all that time outdoors. "
            "Owner: Yeah, we definitely want him protected against everything if he's going to "
            "be in the woods and around other dogs. "
            "Veterinarian: Perfect. Today he is due for his final DAP booster, that's Distemper, "
            "Adenovirus, Parvovirus. We will also administer his first Rabies vaccine, 1-year "
            "labeled, given subcutaneously in the right hind leg. Because of the hiking and "
            "wooded areas, I strongly recommend the Lyme disease vaccine and the Leptospirosis "
            "4-way vaccine, both administered today with boosters required in 3 to 4 weeks. And "
            "for the dog park, we'll give the oral Bordetella vaccine. "
            "Owner: Sounds good, let's do all of them. What about the heartworm test you "
            "mentioned? "
            "Veterinarian: Since he's under 7 months, we don't need to test for heartworm yet, "
            "but I do want to start him on a monthly heartworm, flea, and tick preventative "
            "today, and we'll do his first heartworm test around six months of age. I'd also "
            "like to send a fecal sample out today since he's been in the woods, just to check "
            "for intestinal parasites. "
            "Owner: He did have some soft stool last week, is that something to worry about? "
            "Veterinarian: Good to know, that's exactly why I want the fecal. Soft stool after "
            "hiking is often just diet or minor parasites, nothing alarming so far, but let's "
            "confirm with the test rather than guess. "
            "Owner: Sounds good. Is there anything special I should watch out for after the "
            "shots? "
            "Veterinarian: Just monitor him for mild lethargy or slight soreness at the "
            "injection sites for 24 hours. If you see facial swelling, hives, or repeated "
            "vomiting, call us immediately. Otherwise, come back in about a month for a weight "
            "check and to make sure he's tolerating the preventatives well, and we'll get that "
            "heartworm test scheduled around six months. "
            "Owner: Will do. Thanks so much, see you next time!"
        ),
        metadata={
            "category": "preventive_ambient_noise_long",
            "must_include": {
                "subjective": ["16", "hiking", "soft stool"],
                "objective": ["24.5", "101.8"],
                "plan": ["rabies", "dap", "leptospirosis", "lyme", "bordetella", "fecal", "heartworm"],
            },
        },
    ),
    Case(
        name="post_exam_dictation_ccl_rupture",
        inputs=(
            "Veterinarian (Dictating): SOAP note for Bella, 6-year-old female spayed Golden "
            "Retriever. Patient presented for acute right hind limb lameness after chasing a "
            "squirrel in the yard yesterday evening. Owner reports non-weight bearing lameness "
            "initially, improving to toe-touching lameness today. Physical exam findings: "
            "Weight 31.5 kilograms. TPR normal. Heart and lungs unremarkable. Orthopedic exam "
            "reveals significant right hind limb lameness, grade 3 out of 4. Positive cranial "
            "drawer sign and positive tibial compression test on the right stifle. Moderate "
            "joint effusion and pain elicited on full extension of the right stifle. Left "
            "stifle and bilateral hips are within normal limits. Neurological exam normal. "
            "Assessment: right cranial cruciate ligament, CCL, rupture. Differential includes "
            "partial versus complete tear, with possible medial meniscal injury. Plan: sedated "
            "orthogonal radiographs of the stifles and pelvis recommended to confirm diagnosis "
            "and measure TPLO angles. Prescribed Carprofen 75 mg PO BID for 14 days with food. "
            "Also Gabapentin 300 mg PO Q8 to Q12 hours for pain management. Strict cage rest "
            "and leash walks only for elimination. Discussed surgical correction options "
            "including TPLO referral. Recheck in 10 to 14 days or post-radiographs."
        ),
        metadata={
            "category": "monologue_dictation",
            "must_include": {
                "subjective": ["lameness"],
                "objective": ["31.5", "drawer"],
                "assessment": ["cruciate"],
                "plan": ["carprofen", "gabapentin", "tplo"],
            },
        },
    ),
    Case(
        name="post_exam_dictation_extended_monologue",
        inputs=(
            "Veterinarian (Dictating): SOAP note for Bella, 6-year-old female spayed Golden "
            "Retriever. Patient presented for acute right hind limb lameness after chasing a "
            "squirrel in the yard yesterday evening. Owner reports non-weight bearing lameness "
            "initially, improving to toe-touching lameness today. Owner also mentions Bella had "
            "a mild left hind limb lameness about a year ago that resolved on its own with rest, "
            "no imaging was done at that time. No known trauma other than the running incident "
            "yesterday. Appetite and attitude otherwise normal, no vomiting or diarrhea. "
            "Physical exam findings: Weight 31.5 kilograms, body condition score 6 out of 9. "
            "TPR normal. Heart and lungs unremarkable, no murmurs. Abdomen soft, non-painful. "
            "Orthopedic exam reveals significant right hind limb lameness, grade 3 out of 4. "
            "Positive cranial drawer sign and positive tibial compression test on the right "
            "stifle. Moderate joint effusion and pain elicited on full extension of the right "
            "stifle. Mild crepitus noted on flexion and extension as well. Left stifle and "
            "bilateral hips are within normal limits on this exam, no drawer, no effusion, "
            "although given the history of prior left hind lameness I'd like to keep an eye on "
            "that joint over time. Neurological exam normal, conscious proprioception intact "
            "in all four limbs. Assessment: right cranial cruciate ligament, CCL, rupture. "
            "Differential includes partial versus complete tear, with possible medial meniscal "
            "injury given the effusion and crepitus. Secondary consideration for early "
            "bilateral cruciate disease given the prior contralateral limb history, common in "
            "this breed. Plan: sedated orthogonal radiographs of the stifles and pelvis "
            "recommended today to confirm diagnosis, rule out concurrent orthopedic or "
            "neoplastic disease, and measure TPLO angles for surgical planning. Prescribed "
            "Carprofen 75 mg PO BID for 14 days with food. Also Gabapentin 300 mg PO Q8 to Q12 "
            "hours for pain management, and discussed adding an omega-3 joint supplement "
            "long-term for both stifles given the bilateral risk. Strict cage rest and leash "
            "walks only for elimination until reevaluated, no running, jumping, or stairs. "
            "Discussed surgical correction options including TPLO referral to an orthopedic "
            "surgeon versus conservative management, owner leaning toward surgery once "
            "radiographs confirm severity. Discussed that the left stifle should be monitored "
            "closely given breed predisposition to bilateral disease, and to call immediately "
            "if she starts favoring that leg too. Recheck in 10 to 14 days or sooner if imaging "
            "is completed before then, and referral paperwork will be sent to the surgery "
            "practice this week."
        ),
        metadata={
            "category": "monologue_dictation_long",
            "must_include": {
                "subjective": ["lameness", "squirrel"],
                "objective": ["31.5", "drawer", "crepitus"],
                "assessment": ["cruciate", "meniscal"],
                "plan": ["carprofen", "gabapentin", "tplo", "radiographs"],
            },
        },
    ),
    Case(
        name="multi_issue_recheck_and_new_complaint_extended",
        inputs=(
            "Vet: So this is the three month recheck for her diabetes. How's she doing on the "
            "insulin? Owner: Good I think, she's drinking less water than she was. Vet: That's "
            "a great sign. Let's get a fructosamine level and a quick glucose curve today. "
            "... Okay, fructosamine came back at 380, that's improved from 520 last time but "
            "still above target. Weight's stable at 9.2 kilos. I want to bump her Lantus up "
            "slightly, from 2 units to 2.5 units twice daily, and recheck the fructosamine "
            "again in six weeks. Keep feeding the prescription diabetic diet, no changes there. "
            "Owner: Okay, will do. Actually, while we're here, I also wanted to ask about "
            "something else. She's been scratching at her right ear a lot the last few days, "
            "and I noticed a dark discharge in there yesterday. Vet: Let's take a look at that "
            "too while she's up here. Yeah, the right ear canal is red and inflamed, there's "
            "a dark brown, waxy discharge, and I can smell a mild yeast odor. Left ear looks "
            "completely normal for comparison. This looks like an early yeast otitis externa "
            "in the right ear. I'll clean it out now and send you home with an ear medication, "
            "apply twice daily for ten days. Owner: Could the ear infection be related to her "
            "diabetes at all? Vet: It's possible, diabetic pets can be more prone to yeast and "
            "bacterial infections in general because of the higher sugar levels, so it's worth "
            "keeping an eye on for recurrence. If it's not improved in ten days or comes back "
            "quickly after, we may want to culture it. Owner: Understood. Anything else while "
            "we're here? Also, is it too soon for her annual bloodwork and heartworm test, or "
            "does that overlap with what we did today? Vet: Good question, since we already "
            "drew blood for the fructosamine, let's go ahead and run the full senior panel and "
            "heartworm test off that same sample so you don't have to bring her back separately "
            "for that. I'll have those results by tomorrow. Owner: Perfect, thank you. Vet: Of "
            "course. So to summarize, we're increasing her Lantus to 2.5 units twice daily, "
            "treating the right ear yeast infection with the ear medication for ten days, "
            "running the senior bloodwork and heartworm test off today's sample, and "
            "rechecking the fructosamine in six weeks. Call us if the ear isn't improving in a "
            "few days or if you notice increased drinking or urination again."
        ),
        metadata={
            "category": "multi_issue_visit",
            "must_include": {
                "subjective": ["diabetes", "scratching"],
                "objective": ["380", "9.2", "ear"],
                "assessment": ["yeast"],
                "plan": ["lantus", "2.5", "ear medication", "ten days", "heartworm"],
            },
        },
    ),
    Case(
        name="non_clinical_chitchat_with_embedded_complaint",
        inputs=(
            "Owner: Traffic was insane getting here, is the parking lot getting repaved? Vet: "
            "Yeah I heard that's happening next month, annoying isn't it. Owner: Totally. Oh, "
            "and how was your vacation, did you go to the lake house again? Vet: We did, it was "
            "great, weather was perfect the whole week. Anyway, so what's going on with Luna "
            "today? Owner: Oh right, sorry, she's been scratching her left ear a lot and there's "
            "kind of a brown discharge and a smell. Vet: Let's take a look. Yeah, ear canal is "
            "red and inflamed, I can see debris, this looks like a yeast infection. I'll clean "
            "it out and send you home with an ear medication, apply twice daily for ten days. "
            "Owner: Great, thanks. So are you doing anything for the holidays?"
        ),
        metadata={
            "category": "irrelevant_chatter",
            "must_include": {
                "subjective": ["ear", "scratching"],
                "assessment": ["yeast"],
                "plan": ["ear medication", "ten days"],
            },
        },
    ),
]

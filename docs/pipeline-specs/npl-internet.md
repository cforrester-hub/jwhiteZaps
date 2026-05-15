# NPL Internet Pipeline - Activity Evaluation Spec
### Reference document for producer activity evaluation MCP server (az-analyst-service)

> Purpose: distinguish system-driven automated events from producer-driven activity so the MCP can ignore automation and focus on what the producer actually did.

---

## COACHING FOCUS

This spec powers a **coaching analysis endpoint** in the MCP. It's not for real-time dashboards; it's for **retrospective review** ("show me what this producer did on their internet leads this week" / "where did they drop the ball?").

**Tune evaluation toward identifying inaction, not counting total touches.** Specifically:
- Missed call tasks (created by the system, never completed by the producer) = high-signal coaching moment
- Leads sitting in a producer-managed stage with no notes added = inactivity worth flagging
- Long stretches between producer activity in a stage where producer activity should be high
- Auto-unenrollment fired (customer replied) but no producer follow-up in the next 24-48 hours = critical drop-off

**Ad-hoc producer actions count.** A producer calling a customer back without a task prompting them is a **positive signal of initiative**, not noise. Weight ad-hoc actions at least as high as task-driven actions in coaching analysis.

---

## AZ API INTEGRATION CONTEXT

The MCP queries the agency's `az-analyst-service`, which combines:
- PostgreSQL synced data from AgencyZoom (leads, stages, pipelines, contact_date, quote_date, create_date, stage_id, pipeline_id, producer)
- Live AZ API calls:
  - `GET /api/leads/{id}/notes` — all notes on a lead (automated + manual, no reliable separation)
  - `GET /api/leads/{id}/tasks` — all tasks on a lead

**Important AZ API caveat:** The notes endpoint does NOT reliably distinguish automated messages from producer-typed messages. Automated messages send "as" the assigned producer, so `created_by` shows the producer's name even for system-fired messages. **The touchpoint tables in this spec are the authoritative source** for determining which day/channel combinations on a given lead are automated vs. producer-driven. Cross-reference any note's timestamp + channel against the day-of-stage-entry + scheduled time in this spec to classify it correctly.

---

## TIME ZONE / BUSINESS RULES

- **Time zone:** America/Los_Angeles (Pacific). The agency is in California.
- **Business days:** Monday-Friday. No weekend or evening automation.
- **Automated message timing:** Typically 9-10 AM Pacific on business days. Specific times listed per touchpoint.
- **Day counts in this spec are business days,** not calendar days. When correlating timestamps, the MCP should map "Day N" to "the Nth business day after the lead entered the stage."

---

## PIPELINE OVERVIEW

**Pipeline name:** NPL Internet (New Personal Lines - Internet Leads)
**Lead source:** EverQuote (paid internet leads)
**Line of business:** Home insurance
**Total stages:** 7 (6 active + Sold as system-built handoff)
**Total touchpoints across pipeline:** 27 (8 SMS, 6 Email, 4 Call Tasks, 9 Internal Tasks)

**Lead enters at:** Stage 1 (New) when EverQuote delivers the lead to Agency Zoom.
**Lead exits via:** Sold (success), Smart Cycle (stalled leads recycle for 10 months then come back as "1 NPL Resurrected"), or Escalation task (Waiting on Carrier only).

---

## KEY DISTINCTION FOR MCP EVALUATION

Every touchpoint in this pipeline falls into one of three categories:

| Category | What it is | Should MCP count as producer activity? |
|---|---|---|
| **AUTOMATED MESSAGE** | System sends an SMS or email on a schedule. Producer doesn't touch it. | **NO** - this is system output, not producer work. |
| **PRODUCER TASK** | System creates a task (call, internal note, etc.). The producer must complete it. The task creation is automated; the **completion is producer activity**. | **YES** - the task completion (call logged, note added, etc.) is the producer activity to evaluate. |
| **MANUAL PRODUCER ACTION** | Producer-initiated work outside any system task: direct outbound calls, customer replies handled, stage changes, notes added to lead, manual emails/SMS, etc. | **YES** - this is the highest-signal producer activity. |

**Auto-unenrollment** is ON for stages 1-6. When a customer replies to ANY automated message, the entire automation sequence stops for that lead. From that point forward, **all activity on the lead is producer-driven**. The MCP should treat the auto-unenrollment event as a transition from "mostly automated" to "fully producer-driven."

---

## STAGE 1: NEW (most automation-heavy stage)

**Duration:** Up to 21 days, then 9-day quiet buffer, then 30-day shot clock auto-moves to Smart Cycle pipeline.
**Goal:** Get a response - speed to lead.
**Stage type:** **MIXED** - heavy automation + 4 producer call tasks.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | 9 AM | SMS | AUTOMATED MESSAGE | NO | "Speed-to-lead" intro SMS fires automatically. Ignore. |
| 1 | 9 AM | EMAIL | AUTOMATED MESSAGE | NO | Roof age info request email fires automatically. Ignore. |
| 1 | Immediate | TASK (Call) | PRODUCER TASK | YES | Day 1 consolidated task: **3 call attempts at 10 AM, 1 PM, 4 PM**. Producer logs call outcomes (answered, voicemail, no answer). Each call attempt is producer activity. VM on calls 1 and 3 only (call 2 is ring-only). |
| 1 | 3 PM | SMS | AUTOMATED MESSAGE | NO | "Afternoon follow-up" SMS. Ignore. |
| 2 | 9 AM | SMS | AUTOMATED MESSAGE | NO | "Did you see my message?" SMS. Ignore. |
| 2 | 2 PM | TASK (Call) | PRODUCER TASK | YES | 4th call attempt. Producer logs outcome. |
| 3 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Why a local agency matters" email. Ignore. |
| 4 | 9 AM | TASK (Call) | PRODUCER TASK | YES | 5th call attempt. Producer logs outcome. |
| 6 | 10 AM | SMS | AUTOMATED MESSAGE | NO | "Casual check-in" SMS. Ignore. |
| 8 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Still shopping?" email. Ignore. |
| 11 | 10 AM | TASK (Call) | PRODUCER TASK | YES | 6th call attempt. Producer logs outcome. |
| 15 | 10 AM | SMS | AUTOMATED MESSAGE | NO | "Final active check-in" SMS. Ignore. |
| 22 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "We're here when you're ready" email. Ignore. |
| 30 | — | (system event) | SHOT CLOCK | NO | Aged-lead shot clock moves the lead to Smart Cycle pipeline if still in New. Not producer activity. |

**Producer activity to expect in New stage:** 4 call task completions (Day 1 consolidated 3 attempts + Days 2, 4, 11). Plus any manual notes added to the lead. Plus the manual stage change to Contacted if the lead engages.

---

## STAGE 2: CONTACTED (producer-managed)

**Duration:** Should be brief (< 1 day ideal). 21-day shot clock to Smart Cycle.
**Goal:** Gather info, build the quote, move to Quoted.
**Stage type:** **PRODUCER-MANAGED** - no automated customer-facing messaging.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | TASK (Internal) | PRODUCER TASK | YES | "Lead Tracker" long-running task created on stage entry. **Stays open for life of lead.** Producer adds notes, progress, next steps. Every note added is producer activity. |
| 18 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | "Shot clock heads up" - 3 days before auto-move to Smart Cycle. Producer reviews and acts. |
| 21 | — | (system event) | SHOT CLOCK | NO | Aged-lead shot clock moves to Smart Cycle if still in Contacted. |

**Producer activity to expect in Contacted stage:** All customer communication is producer-driven (direct emails, SMS, calls). Producer is gathering quote info (square footage, roof age, year built, claims history, etc.). Plus Lead Tracker note updates. Plus manual stage change to Quoted when quote is ready.

**Important:** No automated messages go to the customer in this stage. Any outbound communication the MCP sees here is producer-initiated.

---

## STAGE 3: QUOTED (hybrid - producer-managed Days 1-29, automated Days 30-43)

**Duration:** 43 days total (30 producer-managed + 13 automated re-engagement). 45-day shot clock to Smart Cycle.
**Goal:** Close the deal or identify timing (FSD).
**Stage type:** **MIXED** - first 30 days fully producer-managed, then automated re-engagement kicks in.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1-29 | — | — | PRODUCER-MANAGED | YES | **No automated messages.** Producer drives quote follow-up directly. All communication during this window is producer-initiated. Lead Tracker task (from Contacted) remains open and gets updated. |
| 30 | 10 AM | SMS | AUTOMATED MESSAGE | NO | "Your quote is still here" SMS. Fires only if lead is still in Quoted at Day 30. Ignore. |
| 32 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Checking in" email with scheduling link. Ignore. |
| 36 | 10 AM | SMS | AUTOMATED MESSAGE | NO | "Happy to adjust anything" SMS. Ignore. |
| 40 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Why a real agency matters" social-proof email. Ignore. |
| 42 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | "Shot clock heads up" - 3 days until Smart Cycle. Producer reviews. |
| 43 | 10 AM | SMS | AUTOMATED MESSAGE | NO | "We're here whenever you're ready" warm farewell. Ignore. |
| 45 | — | (system event) | SHOT CLOCK | NO | Smart Cycle move. |

**Producer activity to expect in Quoted stage:**
- **Days 1-29:** This is where most producer work happens. Calls, texts, emails to the customer. Quote adjustments. Negotiations. Lead Tracker updates.
- **Days 30+:** Producer activity should taper since automation takes over. Any producer activity here means the producer is still actively working the lead despite no response (good signal of effort).
- Manual stage change to FSD This Folio, FSD Next Folio, Waiting on Carrier, or Sold when appropriate.

---

## STAGE 4: FSD THIS FOLIO (producer-managed)

**Duration:** Variable. 35-day shot clock rolls BACK to Quoted (lead missed their Folio - re-quote).
**Goal:** Close the deal before the Farmers Folio period ends. Folio = ~30-day commission tracking period.
**Stage type:** **PRODUCER-MANAGED** - no automated customer-facing messaging.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 30 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | Shot clock heads up - 5 days until auto-move to Quoted. Producer reviews. |
| 35 | — | (system event) | SHOT CLOCK | NO | Lead rolls back to Quoted stage. Not producer activity. |

**Producer activity to expect:** All customer communication is producer-driven. Producer must know Folio dates (this is a Farmers-specific commission concept) and actively close the deal before the Folio ends. Calls, texts, emails to the customer + Lead Tracker updates.

---

## STAGE 5: FSD NEXT FOLIO (producer-managed)

**Duration:** Variable. 35-day shot clock rolls FORWARD to FSD This Folio.
**Goal:** Stay top of mind across a full Folio wait period.
**Stage type:** **PRODUCER-MANAGED** - no automated customer-facing messaging.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 30 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | Shot clock heads up - 5 days until auto-move to FSD This Folio. Producer reviews. |
| 35 | — | (system event) | SHOT CLOCK | NO | Lead auto-moves to FSD This Folio. Not producer activity. |

**Producer activity to expect:** All customer communication is producer-driven. Lighter cadence than other stages - producer is keeping the relationship warm without overwhelming.

---

## STAGE 6: WAITING ON CARRIER (producer-managed)

**Duration:** Variable. 21-day shot clock creates an Escalation task (lead never goes Dead from this stage).
**Goal:** Manage carrier underwriting; keep customer informed.
**Stage type:** **PRODUCER-MANAGED** - no automated customer-facing messaging.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 3 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | "Follow up with carrier" task. Producer checks carrier status, updates customer. |
| 8 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | "Carrier status check - 1 week mark" task. Producer calls customer with update. |
| 15 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | "Escalation check - 2 week mark" task. Producer escalates if stuck. |
| 18 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | Shot clock heads up - 3 days until escalation task. Producer reviews. |
| 21 | — | (system event) | SHOT CLOCK | NO | Escalation task created (producer-resolved, not auto-moved). |

**Producer activity to expect:** 4 internal task completions + all customer communication (this stage is high-touch from the producer side). Customer is anxious waiting on the carrier's underwriting decision; producer should be proactive.

---

## STAGE 7: SOLD (system handoff stage)

**Stage type:** **SYSTEM EVENT** - this is a built-in AZ stage, not a configurable one.

**What happens when lead moves to Sold:**
- AZ creates an account + policy record
- Welcome Packet fires (carrier-specific, separate artifact)
- Onboarding pipeline kicks off (separate pipeline)
- The MCP should treat the **manual move to Sold** as the producer activity (a producer decision to close the lead). All post-Sold messaging happens in other pipelines and is out of scope for this evaluation.

---

## PIPELINE-LEVEL SAFETY NET (Day 81 - producer review task)

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 81 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | Pipeline-level safety net - producer reviews lead against 90-day EverQuote contact window. Independent of stage. |

---

## AUTOMATED EVENTS THE MCP SHOULD KNOW ABOUT (system, not producer)

Things that look like activity in AZ logs but aren't producer-driven:

| Event | Trigger | Stage | What MCP should do |
|---|---|---|---|
| Automated SMS sent | Scheduled day/time | New (Days 1, 2, 6, 15), Quoted (Days 30, 36, 43) | Ignore - system output |
| Automated email sent | Scheduled day/time | New (Days 1, 3, 8, 22), Quoted (Days 32, 40) | Ignore - system output |
| Task created (by automation) | Scheduled day/time | All stages | The creation is automated. Track the **completion** as producer activity. |
| Shot clock fires (auto stage move) | Day count exceeded | All stages | Ignore - system event. Lead moved without producer action. |
| Smart Cycle move | Shot clock at New/Contacted/Quoted Day expiration | Multiple | Ignore - system event. Lead leaves NPL Internet pipeline. |
| Smart Cycle return | After 10-month dormancy | New (resurrected as "1 NPL Resurrected / New") | The return is automated. Subsequent producer work in the new pipeline IS producer activity. |
| Auto-unenrollment | Customer replies to any automation | Stages 1-6 | **Important signal:** automation stops for this lead. From here, ALL communication is producer-driven. |

---

## PRODUCER ACTIVITY SIGNALS (coaching-weighted)

Tuned for coaching: weight ad-hoc initiative HIGH; weight inaction (missed expected actions) as a flag worth surfacing.

### Positive signals (producer is doing the work)

| Activity | Where to find it | Coaching weight |
|---|---|---|
| Ad-hoc producer call/text/email **without a task prompting it** (initiative) | Notes/tasks created outside scheduled day windows | **Highest** - shows the producer is engaging beyond what the system asks of them |
| Customer reply handled within 24 hours | Producer note/email/SMS within 24h of an inbound reply | **Highest** - speed-to-response on engaged leads is critical |
| Call task completed (outcome logged) | Task history | High - producer did what the system asked |
| Note added to Lead Tracker (Contacted onward) | Notes endpoint, manual-note pattern | High - shows continued engagement |
| Manual outbound email/SMS the producer typed | Notes endpoint, message body NOT matching this spec's template | High - cross-reference template content; if it doesn't match, it's producer-typed |
| Manual stage change | Stage history | Medium - shows producer decisioning |

### Inaction signals (coaching flags - higher priority for surfacing)

| Inaction | How to detect | Coaching weight |
|---|---|---|
| Call task created but never completed | Tasks endpoint shows open task past its scheduled day | **Critical** - direct missed action |
| Customer replied (auto-unenrollment fired) but no producer activity in 24-48 hours | Reply event + no subsequent producer note | **Critical** - lead engaged and the producer didn't respond |
| Lead sitting in Contacted >3 days with no notes | `stage_id = Contacted`, no new notes since stage entry | **High** - Contacted should be brief (<1 day ideal) |
| Lead sitting in Quoted Days 1-29 with no producer activity | `stage_id = Quoted`, no notes/calls in producer-managed window | **High** - Days 1-29 is the highest-value producer window |
| Lead sitting in FSD This Folio with no producer activity for >5 business days | `stage_id = FSD This Folio`, no recent activity | **High** - Folio is time-sensitive |
| Lead sitting in Waiting on Carrier past Day 8 with no producer note about carrier status | Stage + no notes containing carrier follow-up language | **High** - producer should be proactively chasing the carrier and updating the customer |
| Lead approaching shot clock with no recent producer activity | Days-since-stage-entry near shot-clock threshold | Medium - flag for review before auto-move |
| Lead opened/read by producer with no other action | Lead access log only | Low - some attention but no work |

---

## QUICK REFERENCE - PER-STAGE PRODUCER ACTIVITY DENSITY

For an MCP gauging whether a producer is working a lead vs. ignoring it:

| Stage | Expected producer activity level | Why |
|---|---|---|
| New | Medium | 4 scheduled call tasks + handle any replies. Most outbound is automated. |
| Contacted | **High** | Everything is producer-driven. Customer expects fast follow-up here. |
| Quoted (Days 1-29) | **High** | Quote follow-up is all producer. Most lead value sits here. |
| Quoted (Days 30+) | Low-Medium | Automation re-engages; producer activity here = producer chose to keep working it. |
| FSD This Folio | High | Time-sensitive close. Producer should be active. |
| FSD Next Folio | Low-Medium | Nurture mode; lighter touch expected. |
| Waiting on Carrier | High | Customer is anxious; producer should be proactively updating. |
| Sold | (one event) | Stage change to Sold = producer decision. No further work in this pipeline. |

---

## NOTES FOR MCP IMPLEMENTATION

1. **Folio dates are external context.** The pipeline references "Folio" (a ~30-day Farmers commission period). The MCP can't infer Folio dates from AZ alone - they're set by Farmers corporate. If Folio-aware evaluation matters, the MCP may need a separate Folio calendar feed. For now, the MCP can flag inaction in FSD This Folio stage without knowing the exact Folio end date.

2. **Lead Tracker task is long-running.** In Contacted onward, there's one "Lead Tracker" task that stays open for the life of the lead. The producer adds notes over time. The MCP should track **note-additions** to this task as positive activity, not task completion (the task stays open intentionally).

3. **Auto-unenrollment is a critical evaluation pivot.** When a customer replies to an automated message, AZ unenrolls them from the automation. From that timestamp forward, **every message on the lead is producer-driven** (no more automated touchpoints will fire). The MCP should:
   - Detect the auto-unenrollment event (or equivalent: a customer reply followed by no further automated messages firing on their scheduled day)
   - Switch the lead's evaluation mode to "fully producer-driven from this point"
   - Flag any 24-48 hour stretches with no producer response after the reply

4. **All automated messages send "as" the assigned producer.** Per the AZ API caveat above, the notes endpoint can't distinguish automated from producer-typed messages by `created_by` alone. Use this spec's per-stage tables as the authoritative classifier - match on `(day_in_stage, channel, scheduled_time)` to determine whether a given note is automated or manual.

5. **Producer-typed messages can be identified by content mismatch.** If a note's content doesn't match the templated copy for the scheduled automation at that day/channel, it's likely producer-typed. (The MCP can compare against email subject lines or SMS opening lines from the FINAL-PIPELINE.md if needed.)

---

## PIPELINES SHARING THIS SPEC

The following pipelines use the same stage structure, automation, and touchpoint schedule as NPL Internet:

- **Protege Home** — identical setup, different pipeline name in AgencyZoom

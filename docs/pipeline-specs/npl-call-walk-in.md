# NPL Call/Walk-In Pipeline - Activity Evaluation Spec
### Reference document for producer activity evaluation MCP server (az-analyst-service)

> Purpose: distinguish system-driven automated events from producer-driven activity so the MCP can ignore automation and focus on what the producer actually did.

---

## COACHING FOCUS

This spec powers a **coaching analysis endpoint** in the MCP. Retrospective review of producer activity ("where did they drop the ball?"), not real-time dashboards.

**Tune evaluation toward identifying inaction, not counting total touches.** Specifically:
- Missed call tasks (created by the system, never completed by the producer) = high-signal coaching moment
- Leads sitting in a producer-managed stage with no notes added = inactivity worth flagging
- Customer replied (auto-unenrollment fired) but no producer follow-up in the next 24-48 hours = critical drop-off
- **Same-day quote turnaround missed in Contacted stage** = the agency's most distinctive promise on call-in/walk-in leads; missing this is a major coaching flag

**Ad-hoc producer actions count.** A producer calling a customer back without a task prompting them is a **positive signal of initiative**. Weight ad-hoc actions at least as high as task-driven actions.

---

## AZ API INTEGRATION CONTEXT

The MCP queries the agency's `az-analyst-service`, which combines PostgreSQL synced AZ data with live API calls:
- `GET /api/leads/{id}/notes` — all notes on a lead (automated + manual, no reliable separation)
- `GET /api/leads/{id}/tasks` — all tasks on a lead

**Important AZ API caveat:** Notes endpoint cannot distinguish automated messages from producer-typed messages. Automated messages send "as" the assigned producer, so `created_by` shows the producer's name even for system-fired messages. **The touchpoint tables in this spec are the authoritative classifier** - match each note's day/channel/timestamp against the scheduled automations below to determine its true origin.

---

## TIME ZONE / BUSINESS RULES

- **Time zone:** America/Los_Angeles (Pacific)
- **Business days:** Monday-Friday. No weekend or evening automation.
- **Automated message timing:** Typically 9-10 AM Pacific on business days
- **Day counts are business days,** not calendar days

---

## PIPELINE OVERVIEW

**Pipeline name:** NPL Call/Walk In (New Personal Lines - Call-In & Walk-In Leads)
**Lead source:** Inbound phone calls or in-person walk-ins to one of the three agency offices (SLO, Morro Bay, Atascadero)
**Line of business:** Mixed - Auto, Home, Renters, possibly Life cross-sell context
**Total stages:** 7 (6 active + Sold as system-built handoff)
**Total touchpoints across pipeline:** 27 (14 Email, 10 Call Tasks, 1 Physical Mail, 2 Internal Tasks). **Zero SMS** - no TCPA consent for call-in/walk-in leads.

**Lead enters at:** Stage 1 (Contacted) - the producer just spoke with this person in person or on the phone. There's no "New" stage equivalent to NPL Internet; the conversation has already happened.
**Lead exits via:** Sold (success), Smart Cycle (stalled leads recycle for 10 months then return as "1 NPL Resurrected"), or producer-decided close-out (Home Searching).

**Key difference from NPL Internet:** The producer already had a conversation with the lead before they entered the pipeline. **Speed-to-quote within 8 hours is the agency's promise** for these leads (they came in hot). No SMS at all. Less aggressive early cadence than NPL Internet (which is dealing with cold internet leads racing competitors).

---

## KEY DISTINCTION FOR MCP EVALUATION

| Category | What it is | Should MCP count as producer activity? |
|---|---|---|
| **AUTOMATED MESSAGE** | System sends an email on a schedule. Producer doesn't touch it. | **NO** - system output |
| **PRODUCER TASK** | System creates a task. Producer must complete it. The creation is automated; the **completion is producer activity**. | **YES** |
| **MANUAL PRODUCER ACTION** | Producer-initiated work outside any system task. | **YES** - highest-signal activity |

Auto-unenrollment is ON for stages 1-5 (OFF for Home Searching - it's a long-term hold). When a customer replies to ANY automated message, automation stops and all subsequent activity is producer-driven.

---

## STAGE 1: CONTACTED (producer-managed)

**Duration:** Should be brief (less than 1 day ideal - producer shooting for same-day quote turnaround within 8 hours).
**Goal:** Producer just had the conversation. Now build the quote and move to Quoted.
**Stage type:** **PRODUCER-MANAGED** - no automated customer-facing messaging. One internal tracking task.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | TASK (Internal) | PRODUCER TASK | YES | "Tracking task - same-day quote turnaround reminder." Stays open for life of lead. Producer adds notes/progress. Reminds producer of the 8-hour quote-turnaround promise. |
| 21 | — | (system event) | SHOT CLOCK | NO | Aged-lead shot clock moves to Smart Cycle if still in Contacted. |

**Producer activity to expect:** ALL customer communication is producer-driven (calls, emails, notes). Producer should be quoting within 8 hours. Watch for:
- **Same-day quote completion** = on-promise execution
- **More than 1 business day in Contacted without notes** = drop-off, flag for coaching
- **Manual stage change to Quoted with quote_date populated** = quote was generated

---

## STAGE 2: QUOTED

**Duration:** Up to 15 days. 45-day shot clock to Smart Cycle.
**Goal:** Walk through the quote, answer questions, close.
**Stage type:** **MIXED** - 5 automated touchpoints + producer-driven conversations interleaved.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 2 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Quote review call + VM script. Producer logs outcome. |
| 3 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Wanted to make sure you got everything" email. Ignore. |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Follow-up call - any questions? + VM script. Producer logs outcome. |
| 8 | 2 PM | EMAIL | AUTOMATED MESSAGE | NO | "Why customers stick with us" email. Ignore. |
| 15 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "We're here when you're ready" soft close. Ignore. |
| 45 | — | (system event) | SHOT CLOCK | NO | Smart Cycle move. |

**Producer activity to expect:** 2 call task completions (Day 2, Day 8) plus any ad-hoc outreach. Producer should be actively closing during the 15-day window. Watch for:
- **Day 2 call task missed** = critical - quote-review call is the highest-value touch in this stage
- **Day 8 call task missed** = high-priority coaching flag
- **Lead sitting in Quoted past Day 15 with no producer activity** = stale

---

## STAGE 3: FSD THIS FOLIO

**Duration:** Up to 26 days. 35-day shot clock rolls BACK to Quoted (lead missed Folio - re-quote).
**Goal:** Customer committed but won't close immediately. Close before the current Farmers Folio (~30-day commission period) ends.
**Stage type:** **MIXED** - 3 automated emails + 3 producer call tasks.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED MESSAGE | NO | "Great - here's what happens next" confirmation email. Ignore. |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Mid-period check-in + VM script. Producer logs outcome. |
| 8 | 2 PM | EMAIL | AUTOMATED MESSAGE | NO | "Process update - what we need from you" email. Ignore. |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Pre-close check-in + VM script. Producer logs outcome. |
| 21 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Ready to wrap this up?" closing email. Ignore. |
| 26 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Final Folio check-in + VM script. Producer logs outcome. |
| 35 | — | (system event) | SHOT CLOCK | NO | Rolls back to Quoted. |

**Producer activity to expect:** 3 call task completions (Days 8, 15, 26) plus active customer engagement to close before Folio ends. Producer must know Folio dates (external context). Watch for:
- **Any of the 3 call tasks missed** = high-priority coaching flag
- **Lead sitting past Day 21 with no producer activity** = Folio is closing; this is the critical window

---

## STAGE 4: FSD NEXT FOLIO

**Duration:** Up to 29 days (~one Folio period). 35-day shot clock rolls FORWARD to FSD This Folio.
**Goal:** Customer wants to wait until next Folio. Stay top of mind without overwhelming.
**Stage type:** **MIXED** - 3 emails + 2 producer call tasks + 1 physical mail task (producer-executed).

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED MESSAGE | NO | "No rush - we'll be here" reassurance email. Ignore. |
| 11 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | Value content (tips/insights) email. Ignore. |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Mid-wait check-in + VM script. Producer logs outcome. |
| 15 | — | MAIL | PRODUCER TASK | YES | Postcard or handwritten note. **AZ doesn't automate physical mail** - this is a producer task that creates a task for the producer to send mail. Counts as producer activity when completed. Delivery ~Day 18-20. |
| 26 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Your window is coming up" priming email. Ignore. |
| 29 | 10 AM | TASK (Call) | PRODUCER TASK | YES | Transition call - ready to move forward? + VM script. Producer logs outcome. |
| 35 | — | (system event) | SHOT CLOCK | NO | Auto-moves to FSD This Folio. |

**Producer activity to expect:** 2 call task completions (Days 15, 29) + 1 physical mail send (Day 15). Cadence is lighter than other stages by design - this is nurture mode. Watch for:
- **Physical mail task not completed** = often overlooked, worth flagging
- **Day 29 transition call missed** = the lead is about to auto-move to FSD This Folio without a producer touch

---

## STAGE 5: WAITING ON CARRIER

**Duration:** Up to 15 days. 21-day shot clock creates an Escalation task (lead never goes Dead from this stage).
**Goal:** Customer's application is with the carrier. Keep customer reassured, chase the carrier proactively.
**Stage type:** **MIXED** - 3 emails + 3 producer call tasks.

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED MESSAGE | NO | "Your application is submitted - here's what's next" email. Ignore. |
| 4 | 10 AM | TASK (Call) | PRODUCER TASK | YES | "Follow up with carrier" call task. Producer calls **the carrier** (internal action). Logs outcome. |
| 6 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Status update" customer-facing email. Ignore. |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES | "Carrier follow-up + update customer" call task. Producer calls carrier AND customer. |
| 11 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Still working on it - haven't forgotten you" patience email. Ignore. |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES | "Escalation check - is this stuck?" call. Producer escalates if delayed. |
| 21 | — | (system event) | SHOT CLOCK | NO | Escalation task created (producer-resolved). |

**Producer activity to expect:** 3 call task completions (Days 4, 8, 15) + producer-to-customer updates that may not be tied to a task. Watch for:
- **Any of the 3 carrier-follow-up calls missed** = high-priority coaching flag (customer is anxious, producer should be chasing)
- **Day 8 call task missed (the "update the customer" call)** = customer doesn't hear from us during the wait - bad experience

---

## STAGE 6: HOME SEARCHING

**Duration:** Up to 60 days. 60-day shot clock creates a producer review task.
**Goal:** Long-term hold for leads whose property fell through (often inherited from NPL Internet when a deal collapses).
**Stage type:** **LOW-AUTOMATION HOLD** - 2 emails + 1 producer review task. Auto-unenrollment OFF (this is intentionally a long-term hold).

### Touchpoints

| Day | Time | Channel | Type | Producer activity? | Notes for MCP |
|---|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED MESSAGE | NO | "We'll be here when you find the right place" reassurance email. Ignore. |
| 30 | 10 AM | EMAIL | AUTOMATED MESSAGE | NO | "Still looking? Just checking in" light touch email. Ignore. |
| 60 | 10 AM | TASK (Internal) | PRODUCER TASK | YES | Producer review - close out if no activity. |

**Producer activity to expect:** Minimal - this is intentionally a holding zone. Watch for:
- **Day 60 review task not completed** = leads pile up here untouched
- **Producer activity at any point** (note, reply, etc.) = positive signal that the producer is keeping the relationship warm even though the lead is on long-term hold

---

## STAGE 7: SOLD (system handoff stage)

**Stage type:** **SYSTEM EVENT** - built-in AZ stage, not configurable.

**What happens when lead moves to Sold:**
- AZ creates the account + policy record (producer fills in policy info)
- Welcome Packet fires (separate, carrier-specific artifact)
- Onboarding pipeline kicks off (separate pipeline)
- **Manual move to Sold = producer decision = producer activity.** No further work in this pipeline.

---

## AUTOMATED EVENTS THE MCP SHOULD KNOW ABOUT (system, not producer)

| Event | Trigger | Stage | What MCP should do |
|---|---|---|---|
| Automated email sent | Scheduled day/time | Quoted (3), FSD This Folio (3), FSD Next Folio (3), Waiting on Carrier (3), Home Searching (2) - 14 total | Ignore - system output |
| Task created (by automation) | Scheduled day/time | All stages | The creation is automated. Track the **completion** as producer activity. |
| Shot clock fires (auto stage move) | Day count exceeded | All stages | Ignore - system event |
| Smart Cycle move | Shot clock at Contacted/Quoted Day expiration | Contacted, Quoted | Ignore - system event. Lead leaves NPL Call/Walk-In pipeline. |
| Stage roll-back (FSD This Folio → Quoted) | 35-day shot clock | FSD This Folio | Ignore - system event |
| Stage roll-forward (FSD Next Folio → FSD This Folio) | 35-day shot clock | FSD Next Folio | Ignore - system event |
| Auto-unenrollment | Customer replies to any automation | Stages 1-5 | **Important signal:** automation stops. All subsequent communication is producer-driven. |
| Home Searching auto-unenrollment | **OFF** for this stage | Home Searching | Even if customer replies in Home Searching, automation continues. This is intentional - long-term hold. |
| SMS | **BLOCKED** pipeline-wide | All stages | No SMS at all in this pipeline. Any SMS-shaped activity must be producer-typed (rare; producer mostly emails or calls). |

---

## PRODUCER ACTIVITY SIGNALS (coaching-weighted)

### Positive signals

| Activity | Where to find it | Coaching weight |
|---|---|---|
| **Same-day quote in Contacted stage** | quote_date <= 1 business day after stage entry | **Highest** - the agency's distinctive promise on these leads |
| Ad-hoc producer call/text/email without a task prompting it | Activity outside scheduled day windows | **Highest** - shows initiative |
| Customer reply handled within 24 hours | Producer note within 24h of inbound reply | **Highest** - speed-to-response on engaged leads |
| Call task completed (outcome logged) | Task history | High |
| Note added to Tracking Task (Contacted onward) | Notes endpoint, manual-note pattern | High |
| Manual outbound email producer typed | Notes endpoint, body NOT matching this spec's template | High - cross-reference template content |
| Manual stage change | Stage history | Medium |
| Physical mail completion in FSD Next Folio (Day 15) | Task history | Medium - often missed |

### Inaction signals (coaching flags)

| Inaction | How to detect | Coaching weight |
|---|---|---|
| **Same-day quote missed in Contacted** | quote_date > 1 business day after stage entry | **Critical** - direct miss of the agency's signature promise |
| Call task created but never completed | Tasks endpoint shows open task past scheduled day | **Critical** - direct missed action |
| Customer replied (auto-unenrollment fired) but no producer activity in 24-48 hours | Reply event + no subsequent producer note | **Critical** |
| Lead sitting in Contacted >1 business day with no quote_date | Stage + missing quote_date | **High** - quote should be done same day |
| Lead sitting in Quoted past Day 8 with no producer activity | Stage + activity gap | **High** - the close window is now |
| Day 2 call task in Quoted missed | Specific task not completed | **High** - this is the quote-review call |
| Lead sitting in FSD This Folio with no producer activity for >5 business days | Stage + activity gap | **High** - Folio is time-sensitive |
| Lead sitting in Waiting on Carrier with no producer carrier-follow-up note | Stage + no carrier-language notes | **High** - customer is anxious |
| Physical mail task not completed (FSD Next Folio Day 15) | Task history shows open mail task | Medium - often overlooked |
| Home Searching review (Day 60) task not completed | Task history | Low-Medium |

---

## QUICK REFERENCE - PER-STAGE PRODUCER ACTIVITY DENSITY

| Stage | Expected producer activity level | Why |
|---|---|---|
| Contacted | **Critical** (very high in short window) | Same-day quote turnaround is the promise. Stage should be <1 day. |
| Quoted | **High** | 15-day close window. Producer must be active throughout. |
| FSD This Folio | **High** | Folio time-sensitive close. Producer drives the deal. |
| FSD Next Folio | Medium | Nurture mode; lighter touch expected but not zero. Physical mail must happen. |
| Waiting on Carrier | **High** | Customer is anxious; producer should be chasing carrier AND updating customer. |
| Home Searching | Low | Long-term hold by design. Activity here is bonus signal of producer initiative. |
| Sold | (one event) | Stage change to Sold = producer decision. No further work. |

---

## NOTES FOR MCP IMPLEMENTATION

1. **Speed-to-quote is the key coaching signal on this pipeline.** Unlike NPL Internet (where the producer is chasing an unknown cold lead), here the producer has already had a real conversation with the customer. The customer is waiting for the quote. The 8-hour turnaround is the agency's promise. Track `Contacted entry → quote_date` aggressively.

2. **Lead Tracker task (Contacted onward) is long-running.** One task, stays open for life of the lead, producer adds notes over time. Track **note-additions**, not task completion.

3. **No SMS at all in this pipeline.** If the MCP sees any SMS activity on a lead in this pipeline, it's either producer-typed (rare) or a data issue worth flagging.

4. **Physical mail in FSD Next Folio Day 15 is producer-executed.** AZ creates the task; the producer has to actually send the postcard. Often missed in practice. Worth tracking specifically.

5. **Folio dates are external context.** Same caveat as NPL Internet - the MCP can flag stage inactivity but can't calculate Folio-relative urgency without external Folio calendar data.

6. **Home Searching is a low-activity-by-design stage.** Don't flag low activity there as inaction unless past Day 60. This stage often inherits leads from NPL Internet whose property deal fell through - they're parked here intentionally.

7. **Auto-unenrollment is OFF in Home Searching only.** Replies in that stage don't stop automation. Treat replies there as positive engagement signal but don't expect automation to halt.

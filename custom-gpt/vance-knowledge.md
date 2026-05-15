# VANCE — Supplemental Knowledge Document

# Jennifer White Insurance Agency

---

## MCP TOOL PARAMETER REFERENCE

Base URL: https://jwhitezaps.atoaz.com

---

### getProducerActivity

Use for: "What did [producer] work on?" or company-wide activity overview.

- producer (optional) — first name; omit for company-wide
- date (optional) — YYYY-MM-DD; defaults to today Pacific
- days (optional) — look back N days; default 1
- summary_only (optional) — true = counts only, no lead list; default false
- group_by_day (optional) — true = break multi-day range into daily counts
- include_details (optional) — true = fetches live notes/tasks from AgencyZoom; SLOW (~30s), use sparingly

---

### getTeamPerformance

Use for: "Compare all producers" or "Who has the best close rate?"

- pipeline_id (optional)
- date_from / date_to (optional) — YYYY-MM-DD
- days (optional) — default 30
- Fast — no live API calls
- Distinguishes new_this_period (true new leads) from new_backlog (stale leads stuck in NEW)
- Aging buckets: 0–1, 2–3, 4–7, 8–14, 15+ days

---

### getFunnelPerformance

Use for: "Show quote rates by producer" or "Funnel metrics this month."

- producer / pipeline_id / pipeline_name / lead_source / source_group / channel_type (all optional filters)
- date_from / date_to or days (default 30)
- group_by — producer | pipeline | source | day | week
- report_mode — standard (default) or internet (use for internet lead pipelines)
- summary_only — default true; set false to see group-level breakdown
- include_leads — default false
- Valid channel_type values: internet, inbound, internal, reactivation, outbound, mixed, transfer, commercial, partner, training
- Valid source_group values: vendor_lead, inbound, book, referral, targeted, partner
- Valid intent_type values: high_intent, cold_purchased, existing_customer, warm, targeted, commercial, partner_referral, cross_sell, quality_check, training

---

### getQuoteAnalysis

Use for: "What's our bundle rate?" or "Which carriers are we quoting most?"

- producer / pipeline_id / pipeline_name / lead_source / source_group (optional filters)
- date_from / date_to or days
- bundled_only (optional) — true = multi-line quotes only
- summary_only — default false; set true for large datasets
- Key response fields: bundle_rate_pct, by_carrier, by_product, total_effectively_quoted

---

### getPipelineCompliance

Use for: "Is [producer] quoting their Call/Walk In leads?"

- producer / pipeline_id / pipeline_name (optional filters)
- date_from / date_to — REQUIRED
- summary_only — default true; set false to see unquoted lead list
- Returns: passing / warning / failing status; high-intent (Call/Walk In) threshold = 90%

---

### getLostDealAnalysis

Use for: "Show me post-quote leakage" or "What deals can we recover?"

- producer / pipeline_id / pipeline_name (optional filters)
- date_from / date_to — REQUIRED
- include_recoverable — default true (quoted + not won + active within 60 days)
- summary_only — default true; set false to see lead arrays

---

### getProducerScorecard

Use for: "Give me [producer]'s full KPI summary."

- producer — REQUIRED
- date_from / date_to — REQUIRED
- Returns: quote rate, close rate, pre/post-quote leakage, avg time-to-quote, team rankings, per-pipeline breakdown

---

### getCoachingAnalysis

Use for: "Audit [producer]'s leads for coaching opportunities."

- producer — REQUIRED
- date_from / date_to or days (default 1 = yesterday)
- pipeline_name (optional) — partial match fragment (e.g., "NPL Call", "Internet")
- pipeline_id (optional) — filter to a specific pipeline
- include_note_content — default true
- max_notes_per_lead — default 10 (reduced from 20; keep at default to avoid oversized responses)
- summary_only (optional) — default false; set true for high-volume producers to return only summary and flag counts without per-lead detail
- **Important:** For high-volume producers (Ellie, Claudia), always start with summary_only=true or filter by pipeline_name to avoid oversized response errors.

**Activity classification (per lead):**
Each lead now returns classified activity, not just raw counts:
- `activity_summary.activity_classification` — one of: `no_activity`, `internal_only`, `customer_follow_up`, `milestone_advance`, `customer_follow_up_and_internal`, `milestone_and_follow_up`
- `activity_summary.worked_today_reason` — human-readable string like "2 outbound texts, 1 inbound call, 1 task update"
- `classified_counts` — directional breakdowns: `outbound_calls`, `inbound_calls`, `outbound_texts`, `inbound_texts`, `outbound_emails`, `inbound_emails`, `task_updates`, `automation_events`, `stage_moves`
- `milestones` — boolean flags: `first_contact_in_period`, `quote_created_in_period`, `stage_moved_in_period`, `won_in_period`

**Use activity_classification to determine what actually happened:**
- `internal_only` = lead was "touched" but NO customer contact occurred. Do NOT credit this as producer follow-up.
- `customer_follow_up` = real customer-facing activity (calls, texts, emails). This IS producer effort.
- `milestone_advance` = lead moved stages, got quoted, or closed. Pipeline progress.

**Summary-level fields:**
- `leads_with_customer_activity` — had real customer contact in period
- `leads_with_internal_only` — only admin/task activity, no customer contact
- `leads_advanced` — had milestone events

**Coaching analysis approach by pipeline type:**

For **internet leads** (NPL Internet, NPL FFQ, Protege Home, Protege Auto):
- These are purchased leads — industry close rate (New → Sold) is only 3-5%. Most falloff is in New → Contacted (lead quality), not producer failure.
- **Evaluate each stage transition independently, not end-to-end conversion:**
  - **New → Contacted:** Coach on EFFORT, not results. Did the producer complete all scheduled call tasks, follow the cadence, use multiple channels within 48 hours? A producer who makes 5 call attempts, sends 2 texts, and 1 email but never reaches the lead is doing their job. Low contact rate = lead quality, not coaching issue.
  - **Contacted → Quoted:** Coach on SKILL. Should be very high (80-90%+). Once talking to a real person who needs insurance, nearly all should get quoted. Low ratio = conversation quality problem (not gathering info, not building urgency, not scheduling the quote review). This is the most coachable gap.
  - **Quoted → Sold:** Should be fairly high. This is the best **apples-to-apples producer comparison** — same starting point, same products, same carriers. Differences surface follow-up discipline, objection handling, and closing ability. Use Quoted → Sold for producer-to-producer ranking.
- **Use the NPL Internet automation schedule (below) to filter automated messages from producer activity.** Protege Home shares the same automation schedule as NPL Internet.
- The coaching endpoint now tags each note with `source` (automated/producer/unknown) and `automation_analysis` per lead. Use `producer_counts` instead of raw `classified_counts` to evaluate real producer effort.

For **high-intent leads** (NPL Call/Walk In, Incoming AOR):
- These leads called or walked in — they are ALREADY CONTACTED by definition. Do NOT report them as "not contacted" even if contact_date is null.
- The relevant metric is speed-to-QUOTE, not speed-to-contact. How fast did the producer quote them after they reached out?
- **The agency's promise is same-day quote turnaround (within 8 hours).** Track Contacted entry → quote_date aggressively. Missing this is a critical coaching flag.
- **Info Needed stage:** Sits between New and Quoted in NPL Call/Walk-In. No automation. Means "we've talked to the customer but need more information to produce an accurate quote." The 8-hour quote clock **resets each time there is a new touchpoint** (inbound customer info, producer follow-up) in Info Needed — because the customer just provided new information and the producer needs time to act on it. A lead sitting in Info Needed for 3 days is not a coaching issue if the last touchpoint was yesterday. It IS a coaching issue if the last touchpoint was 3+ business days ago with no producer activity.
- Unquoted Call/Walk In leads are process failures unless there's a valid reason (duplicate, not qualified, or actively in Info Needed with recent touchpoints)
- A null contact_date on a Call/Walk-In lead is a data hygiene issue, not a coaching issue
- **Use the NPL Call/Walk-In automation schedule (below) to filter automated messages from producer activity.** This pipeline has ZERO SMS — no TCPA consent for call-in/walk-in leads.

**Using automation_analysis in coaching output:**
When the coaching endpoint returns `automation_analysis` per lead, use it explicitly:
- Report `automated_counts` vs `producer_counts` to show how much of the lead's "activity" was system-generated vs real producer effort
- For internet leads especially, a lead with 8 total notes but 6 automated = only 2 real producer touches. Surface this distinction.
- Note-level `source` tags (automated/producer/unknown) tell you exactly which notes to count. Don't credit "5 outbound texts" when 4 were automated SMS.
- `unanswered_inbound` events are the highest-priority coaching items — customer engaged, producer didn't respond within 24h.

For **book/cross-sell leads** (Cross-Sell, ReShop/ReWrite, BOB):
- Existing customers — relationship-based approach
- Focus coaching on whether they're reaching out at all and if the conversation is personalized
- Lower urgency than internet or call-in, but should still see consistent outreach

**Stage-transition coaching benchmarks:**
- **Internet New → Contacted:** 3-5% end-to-end close rate means most leads will never answer. Don't punish producers for low contact rates. Coach the effort cadence.
- **Internet Contacted → Quoted:** Will be significantly lower than Call/Walk-In because internet leads are often hard-to-insure properties (older roofs, claims history, coastal, specialty risks — that's often why they're shopping online). Before coaching a low Contacted→Quoted ratio, **categorize the unquoted reasons**: "no carrier for the risk" or "risk doesn't fit Farmers appetite" = market reality, not a coaching issue. "Never followed up after contact" or "no documentation of why they couldn't quote" = coachable. The coaching question is: did the producer document why they couldn't quote?
- **Internet Quoted → Sold:** Also lower than Call/Walk-In — brokered placements are less price-competitive and internet shoppers are price-sensitive. Still the best producer-to-producer comparison metric **within the same pipeline type**. Never compare internet Quoted→Sold against Call/Walk-In Quoted→Sold — different customer profiles.
- **Call/Walk In Contacted → Quoted:** Should be very high (80-90%+). These customers walked into a Farmers agency — standard risks, high intent. Same-day quote turnaround is the promise. A low ratio is a serious process failure.
- **Call/Walk In Quoted → Sold:** Should be high. Best absolute close-rate benchmark in the agency.
- **Inbound no response:** The coaching endpoint now flags `inbound_no_response` when a customer contacts the agency (call, email, text) but no producer outbound follows within 24 hours. This is the highest-priority coaching flag — the lead engaged and nobody followed up.

**Lost deal analysis — read the notes:**
When a quoted lead is lost or expired, analyze the note content to determine WHY. Categorize each loss:
- **No carrier for the risk** (uncontrollable) — Farmers can't write it, no brokered market available. Not a coaching issue, but may indicate a market gap worth flagging to the agency owner.
- **Price** (partially controllable) — customer went with a cheaper competitor. Coach the producer on value positioning, coverage comparison, and bundling to offset price.
- **No response after quote** (controllable) — producer quoted but customer went silent. Evaluate follow-up cadence from notes: how many attempts after quoting? What channels? How quickly? This is the most coachable loss type.
- **Customer went elsewhere** (partially controllable) — customer chose another agent/carrier. Check if there was a speed or follow-up gap that contributed.
- **Customer decided not to purchase** (uncontrollable) — life circumstances changed, decided to self-insure, etc.

Always distinguish controllable losses (coaching opportunity) from uncontrollable losses (market reality). Report both, but focus coaching recommendations on the controllable ones.
- Coaching flags returned:
  - no_notes_at_all — lead has zero synced notes (likely sync lag, not inactivity)
  - new_lead_never_contacted — status is NEW with no customer-facing notes at all (checks actual notes, not just contact_date)
  - no_activity_in_period — lead has history but nothing in the queried date range
  - quoted_no_followup — quoted lead with no notes after quote date. **Validate before coaching:** if quote_date is null (lead is effectively_quoted via quote records only), the flag uses the earliest quote record date as fallback. If no date is available, the flag is suppressed. Still worth verifying against notes when the flag fires — edge cases exist.
  - slow_first_contact — 24+ hours from lead entry to first contact
  - overdue_tasks_N — has N overdue tasks (trustworthy only when task objects are actually present)
  - missing_tasks — lead has 0 task objects AND no task-type notes in history. May indicate the lead genuinely has no tasks, but still treat with caution on older leads.
  - task_sync_incomplete — lead has 0 task objects but DOES have task-type notes in history. This is an API sync gap, NOT a producer issue. Do NOT coach off this flag. The `task_data_status` field on each lead will be "incomplete" when this fires.

---

### getSalesAnalytics

Use for: "How much premium did we write?" or "Which carriers are we placing with?" or "What sources produce the most revenue?"

- producer / pipeline_name / pipeline_id / lead_source (optional filters)
- date_from / date_to or days (default 30)
- summary_only — default true; set false to see per-lead won detail
- Returns:
  - won_leads count and total won_premium
  - by_producer: revenue per producer
  - by_carrier: revenue per carrier (Farmers vs brokered)
  - by_product: revenue per product line
  - by_source: revenue per lead source
  - by_pipeline: revenue per pipeline
  - source_to_carrier: maps each lead source to its carrier placements (e.g., "EverQuote → Farmers 80%, Foremost 15%")
  - quoted_not_won pipeline: recoverable revenue still in play

**Key use cases:**
- "Are we keeping enough business with Farmers?" → check by_carrier
- "Which sources are most profitable?" → check by_source
- "Is a producer defaulting to brokered when Farmers could write it?" → check source_to_carrier + review notes on won leads
- "How much revenue is sitting on the table?" → check quoted_not_won_premium

**Known gap: lead-based sales only.** This tool only counts won leads from the AgencyZoom lead pipeline. Policies entered directly in AZ's management system (not through a lead) are invisible here. AZ production reports include both lead-based and direct-entry policies, so their totals may exceed ours. If a producer's AZ production number is higher than what getSalesAnalytics shows, the difference is likely direct-entry policies without a lead record. This is not a data error — it's a scope difference.

---

### getDataQualityReport

Use for: "Run a data quality check" or when spotting pipeline discipline issues.

- producer / pipeline_id (optional)
- days — default 90
- Returns health score (0–100) and issue counts: quoted_wrong_status, won_without_quotes, stuck_in_new, timeline_anomalies
- Vance surfaces these issues with context but does not position as a QA tool — always connect findings to a coaching or operational implication.

---

### getLeadDetail

Use for: "Tell me about lead [ID]" or when a lead shows zero notes in other queries.

- lead_id — REQUIRED (integer)
- include_notes — default true (live fetch from AgencyZoom)
- include_tasks — default true (live fetch from AgencyZoom)
- max_notes — limit number of notes returned (0 = all). Notes sorted most-recent-first.
- notes_offset — skip first N notes for pagination (default 0)
- max_note_body_length — truncate each note body to N chars (0 = full text)
- notes_since — only return notes after this date (YYYY-MM-DD)
- notes_summary_only — true = note metadata only (type, date, author, title), no body text
- Returns: quotes, opportunities, files, notes, tasks, notes_meta (total_notes, returned, offset, has_more)

**Handling large leads:** When a lead has extensive note history (e.g., 50+ notes), the full payload may exceed response size limits. Strategy:
1. First call: `notes_summary_only=true` to see the full timeline metadata and note count
2. Then drill into specific date ranges: `notes_since=YYYY-MM-DD` + `max_notes=20` for full bodies
3. Paginate if needed: `notes_offset=20` + `max_notes=20` for the next page
4. Use `max_note_body_length=500` to get truncated previews of all notes at once

---

### searchLeads

Use for: "Find leads for John Smith."

- query (name, partial match) / phone / email — at least one required
- limit — default 20, max 100
- Fast — no live API calls

---

### getTasks

Use for: "Show [producer]'s open tasks."

- producer — REQUIRED (first name)
- status — open | completed | all (default all)
- date_from / date_to (optional)

---

### getPipelineAnalytics

Use for: "Show stage breakdowns for [pipeline]."

- pipeline_id / producer / date_from / date_to (all optional)
- Fast — no live API calls
- Returns lead counts by stage, status, and conversion rate per pipeline

---

## DATA INTEGRITY RULES — MCP CONSUMPTION

When auditing activity for a specific date range, follow these rules to avoid misinterpreting MCP output:

1. **Trust period-scoped fields first.** `classified_counts`, `activity_classification`, `notes_in_period`, and `milestones.*_in_period` are derived from date-filtered notes. These are the source of truth for what happened during the requested period.

2. **Treat `total_contact_attempts`, `total_notes_lifetime`, and `contact_date` as lifetime context only.** They sit next to period-scoped fields but are NOT filtered by date range. Never use them to answer "what happened today" — only for "how much total history does this lead have."

3. **Never treat `tasks = 0` as proof of no tasking.** The task API is incomplete for Smart-Cycle/expired leads. If a lead shows 0 tasks but note history contains TASK-type notes, the task data is missing — not absent. Only trust task counts when task objects are actually returned.

4. **Use `task_data_status` to judge task completeness.** Each lead now includes `task_data_status`: "complete" (task objects present), "incomplete" (task notes exist but objects missing — API sync gap), or "unavailable" (no task evidence at all). Never coach a producer when status is "incomplete" — the `task_sync_incomplete` flag means the API didn't return task objects despite task-note evidence.

5. **Validate `quoted_no_followup` against notes before coaching.** This flag can false-fire when `quote_date` is null on an effectively-quoted lead. If the flag fires, check the note timeline for post-quote outreach before concluding the producer dropped the ball.

6. **`no_activity_in_period` is reliable only when `notes_in_period = 0` AND no contradictory notes exist.** Some narrative task-note updates document same-day work but may not be classified as structured activity.

7. **When notes and flags conflict, notes win.** The note stream is the raw record. Coaching flags are heuristics derived from it. If a flag says "no follow-up" but notes show outreach, trust the notes.

8. **When producer attribution and note author conflict, mark attribution as uncertain.** A lead may appear under one producer's coaching output while a same-day note was authored by a different producer (transfers, reassignments). Flag this rather than coaching the wrong person.

---

## PIPELINE AUTOMATION REFERENCE

This section defines which pipeline events are automated (system-generated) vs. producer-driven. **Use these schedules to filter noise from coaching analysis.** Without this, automated SMS/emails look identical to producer-typed messages in AZ data.

### How to use this reference

1. When reviewing a lead's notes/tasks from getCoachingAnalysis or getLeadDetail, identify which pipeline the lead is in.
2. Cross-reference each note's **timestamp + channel** against the automation schedule below.
3. If a note matches a scheduled automated touchpoint (same business day in stage + channel + approximate time), classify it as **automated — not producer activity**.
4. If a note does NOT match any scheduled automation, classify it as **producer-driven activity**.
5. If **auto-unenrollment** has fired (customer replied to an automated message), ALL subsequent activity on that lead is producer-driven regardless of timing.

### Three categories of pipeline events

| Category | What it is | Count as producer activity? |
|---|---|---|
| **AUTOMATED MESSAGE** | System sends SMS or email on a schedule. Producer doesn't touch it. | **NO** |
| **PRODUCER TASK** | System creates a task. Producer must complete it. Task creation = automated. Task **completion** = producer activity. | **YES** (the completion) |
| **MANUAL PRODUCER ACTION** | Producer-initiated work outside any system task (direct calls, replies handled, stage changes, ad-hoc notes). | **YES** — highest signal |

### Auto-unenrollment (critical evaluation pivot)

When a customer replies to ANY automated message, AZ unenrolls them from automation. From that timestamp forward, **every message on the lead is producer-driven** — no more automated touchpoints fire. The MCP should:
- Detect the pivot (customer reply followed by no further scheduled automations firing)
- Treat all subsequent activity as producer-driven
- **Flag any 24-48 hour gap after auto-unenrollment with no producer response as a CRITICAL coaching issue** — the customer engaged and the producer didn't follow up

---

### NPL INTERNET AUTOMATION SCHEDULE

**Applies to:** 1 NPL Internet, Protege Home

**Pipeline type:** Internet leads (EverQuote). Cold purchased leads. 7 stages.
**Key fact:** Heavy SMS + email automation in Stage 1 (New) and late Stage 3 (Quoted Days 30+). All other stages are producer-managed.

#### Stage 1: New (MIXED — heavy automation + 4 producer call tasks)

Duration: Up to 30 business days (21 active + 9 quiet buffer). Shot clock → Smart Cycle.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | 9 AM | SMS | AUTOMATED | NO |
| 1 | 9 AM | EMAIL | AUTOMATED | NO |
| 1 | Immediate | TASK (Call) | PRODUCER TASK | YES — Day 1 consolidated: 3 call attempts (10 AM, 1 PM, 4 PM) |
| 1 | 3 PM | SMS | AUTOMATED | NO |
| 2 | 9 AM | SMS | AUTOMATED | NO |
| 2 | 2 PM | TASK (Call) | PRODUCER TASK | YES — 4th call attempt |
| 3 | 10 AM | EMAIL | AUTOMATED | NO |
| 4 | 9 AM | TASK (Call) | PRODUCER TASK | YES — 5th call attempt |
| 6 | 10 AM | SMS | AUTOMATED | NO |
| 8 | 10 AM | EMAIL | AUTOMATED | NO |
| 11 | 10 AM | TASK (Call) | PRODUCER TASK | YES — 6th call attempt |
| 15 | 10 AM | SMS | AUTOMATED | NO |
| 22 | 10 AM | EMAIL | AUTOMATED | NO |
| 30 | — | SHOT CLOCK | SYSTEM | NO — auto-moves to Smart Cycle |

**Expected producer activity:** 4 call task completions + any manual notes + stage change to Contacted if lead engages.

#### Stage 2: Contacted (PRODUCER-MANAGED — no automated customer messages)

Duration: Should be <1 day ideal. 21-day shot clock → Smart Cycle.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | TASK (Internal) | PRODUCER TASK | YES — "Lead Tracker" (stays open for life of lead) |
| 18 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — shot clock heads up |
| 21 | — | SHOT CLOCK | SYSTEM | NO |

**ALL customer communication in Contacted is producer-driven.** Any outbound message = producer activity.

#### Stage 3: Quoted (MIXED — producer Days 1-29, automated Days 30-43)

Duration: 45-day shot clock → Smart Cycle.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1-29 | — | — | PRODUCER-MANAGED | YES — no automated messages in this window |
| 30 | 10 AM | SMS | AUTOMATED | NO |
| 32 | 10 AM | EMAIL | AUTOMATED | NO |
| 36 | 10 AM | SMS | AUTOMATED | NO |
| 40 | 10 AM | EMAIL | AUTOMATED | NO |
| 42 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — shot clock heads up |
| 43 | 10 AM | SMS | AUTOMATED | NO |
| 45 | — | SHOT CLOCK | SYSTEM | NO |

**Days 1-29 is the highest-value producer window.** All communication is producer-initiated. Days 30+ automation re-engages; producer activity here = extra effort (positive signal).

#### Stage 4: FSD This Folio (PRODUCER-MANAGED)

35-day shot clock rolls BACK to Quoted.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 30 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — shot clock heads up |
| 35 | — | SHOT CLOCK | SYSTEM | NO |

#### Stage 5: FSD Next Folio (PRODUCER-MANAGED)

35-day shot clock rolls FORWARD to FSD This Folio.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 30 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — shot clock heads up |
| 35 | — | SHOT CLOCK | SYSTEM | NO |

#### Stage 6: Waiting on Carrier (PRODUCER-MANAGED)

21-day shot clock → Escalation task.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 3 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — follow up with carrier |
| 8 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — carrier status check |
| 15 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — escalation check |
| 18 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — shot clock heads up |
| 21 | — | SHOT CLOCK | SYSTEM | NO |

#### Stage 7: Sold — system handoff. Manual move to Sold = producer activity. No further work in pipeline.

#### Pipeline-level safety net: Day 81 — internal producer review task (independent of stage).

#### NPL Internet — expected producer activity density

| Stage | Expected level | Key signal |
|---|---|---|
| New | Medium | 4 call tasks + handle replies |
| Contacted | **High** | Everything is producer-driven |
| Quoted (Days 1-29) | **High** | Quote follow-up, negotiations |
| Quoted (Days 30+) | Low-Medium | Automation covers; producer activity = bonus effort |
| FSD This Folio | High | Time-sensitive Folio close |
| FSD Next Folio | Low-Medium | Nurture mode |
| Waiting on Carrier | High | Customer anxious; producer chases carrier |

#### NPL Internet — critical inaction flags

| Inaction | Coaching weight |
|---|---|
| Call task created but never completed | **Critical** |
| Customer replied (auto-unenrollment) but no producer activity in 24-48h | **Critical** |
| Lead in Contacted >3 days with no notes | **High** |
| Lead in Quoted Days 1-29 with no producer activity | **High** |
| Lead in FSD This Folio with no activity for >5 business days | **High** |
| Lead in Waiting on Carrier past Day 8 with no carrier follow-up note | **High** |

---

### NPL CALL/WALK-IN AUTOMATION SCHEDULE

**Applies to:** 1 NPL Call/Walk In

**Pipeline type:** Inbound calls and walk-ins to agency offices (SLO, Morro Bay, Atascadero). High-intent leads. 7 stages.
**Key facts:**
- **ZERO SMS in this entire pipeline** — no TCPA consent for call-in/walk-in leads. Any SMS = producer-typed (rare).
- Lead enters at Contacted (not New) — the conversation already happened.
- **Same-day quote turnaround (8 hours) is the agency's promise.** Speed-to-quote is the #1 coaching signal.
- Has a unique **Home Searching** stage (long-term hold, auto-unenrollment OFF).
- **Physical mail task** in FSD Next Folio (Day 15) — producer must actually send a postcard.

#### Stage 1: Contacted (PRODUCER-MANAGED — no automated customer messages)

Duration: Should be <1 day. 21-day shot clock → Smart Cycle.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | TASK (Internal) | PRODUCER TASK | YES — tracking task + same-day quote turnaround reminder |
| 21 | — | SHOT CLOCK | SYSTEM | NO |

**ALL customer communication is producer-driven.** Quote should be done within 8 hours of stage entry. More than 1 business day in Contacted without notes = coaching flag.

#### Stage 2: Quoted (MIXED — 3 automated emails + 2 producer call tasks)

Duration: Up to 15 days. 45-day shot clock → Smart Cycle.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 2 | 10 AM | TASK (Call) | PRODUCER TASK | YES — quote review call |
| 3 | 10 AM | EMAIL | AUTOMATED | NO |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES — follow-up call |
| 8 | 2 PM | EMAIL | AUTOMATED | NO |
| 15 | 10 AM | EMAIL | AUTOMATED | NO |
| 45 | — | SHOT CLOCK | SYSTEM | NO |

**Day 2 quote-review call is the highest-value touch.** Missing it = critical coaching flag.

#### Stage 3: FSD This Folio (MIXED — 3 automated emails + 3 producer call tasks)

Duration: Up to 26 days. 35-day shot clock rolls BACK to Quoted.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED | NO |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES — mid-period check-in |
| 8 | 2 PM | EMAIL | AUTOMATED | NO |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES — pre-close check-in |
| 21 | 10 AM | EMAIL | AUTOMATED | NO |
| 26 | 10 AM | TASK (Call) | PRODUCER TASK | YES — final Folio check-in |
| 35 | — | SHOT CLOCK | SYSTEM | NO — rolls back to Quoted |

#### Stage 4: FSD Next Folio (MIXED — 3 emails + 2 call tasks + 1 physical mail task)

Duration: Up to 29 days. 35-day shot clock rolls FORWARD to FSD This Folio.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED | NO |
| 11 | 10 AM | EMAIL | AUTOMATED | NO |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES — mid-wait check-in |
| 15 | — | MAIL (physical) | PRODUCER TASK | YES — postcard/handwritten note (producer must send) |
| 26 | 10 AM | EMAIL | AUTOMATED | NO |
| 29 | 10 AM | TASK (Call) | PRODUCER TASK | YES — transition call |
| 35 | — | SHOT CLOCK | SYSTEM | NO |

**Physical mail task (Day 15) is often overlooked.** Worth flagging when missed.

#### Stage 5: Waiting on Carrier (MIXED — 3 automated emails + 3 producer call tasks)

Duration: Up to 15 days. 21-day shot clock → Escalation task.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED | NO |
| 4 | 10 AM | TASK (Call) | PRODUCER TASK | YES — carrier follow-up (internal call) |
| 6 | 10 AM | EMAIL | AUTOMATED | NO |
| 8 | 10 AM | TASK (Call) | PRODUCER TASK | YES — carrier + customer update |
| 11 | 10 AM | EMAIL | AUTOMATED | NO |
| 15 | 10 AM | TASK (Call) | PRODUCER TASK | YES — escalation check |
| 21 | — | SHOT CLOCK | SYSTEM | NO |

**Day 8 "update the customer" call is critical** — customer doesn't hear from us during the carrier wait if this is missed.

#### Stage 6: Home Searching (LOW-AUTOMATION HOLD — auto-unenrollment OFF)

Duration: Up to 60 days. Long-term hold by design. Auto-unenrollment is **OFF** — automation continues even if customer replies.

| Day | Time | Channel | Type | Producer activity? |
|---|---|---|---|---|
| 1 | Immediate | EMAIL | AUTOMATED | NO |
| 30 | 10 AM | EMAIL | AUTOMATED | NO |
| 60 | 10 AM | TASK (Internal) | PRODUCER TASK | YES — producer review / close-out |

**Low activity is expected here.** Don't flag inaction unless past Day 60. Any producer activity = positive initiative signal.

#### Stage 7: Sold — system handoff. Manual move to Sold = producer activity.

#### NPL Call/Walk-In — expected producer activity density

| Stage | Expected level | Key signal |
|---|---|---|
| Contacted | **Critical** | Same-day quote turnaround (<8 hours) |
| Quoted | **High** | 15-day close window; 2 call tasks |
| FSD This Folio | **High** | Folio-sensitive; 3 call tasks |
| FSD Next Folio | Medium | Nurture; physical mail + 2 call tasks |
| Waiting on Carrier | **High** | Customer anxious; 3 carrier follow-up calls |
| Home Searching | Low | Long-term hold by design |

#### NPL Call/Walk-In — critical inaction flags

| Inaction | Coaching weight |
|---|---|
| **Same-day quote missed in Contacted** (quote_date > 1 business day after entry) | **Critical** — agency's signature promise |
| Call task created but never completed | **Critical** |
| Customer replied (auto-unenrollment) but no producer activity in 24-48h | **Critical** |
| Lead in Contacted >1 business day with no quote_date | **High** |
| Day 2 quote-review call in Quoted missed | **High** |
| Lead in Quoted past Day 8 with no producer activity | **High** |
| Lead in FSD This Folio with no activity for >5 business days | **High** |
| Lead in Waiting on Carrier with no carrier follow-up note | **High** |
| Physical mail task not completed (FSD Next Folio Day 15) | Medium |

---

### PIPELINE AUTOMATION — QUICK LOOKUP

For rapid reference when reviewing coaching data:

| Pipeline | Automated channels | Stages with automation | Stages fully producer-managed |
|---|---|---|---|
| NPL Internet / Protege Home | SMS + Email | New, Quoted (Days 30+) | Contacted, Quoted (Days 1-29), FSD This Folio, FSD Next Folio, Waiting on Carrier |
| NPL Call/Walk-In | Email only (ZERO SMS) | Quoted, FSD This Folio, FSD Next Folio, Waiting on Carrier, Home Searching | Contacted |

| Pipeline | #1 coaching signal | Auto-unenrollment |
|---|---|---|
| NPL Internet / Protege Home | Missed call tasks in New stage | ON for stages 1-6 |
| NPL Call/Walk-In | Same-day quote missed in Contacted | ON for stages 1-5, **OFF for Home Searching** |

---

## FARMERS PRODUCT KNOWLEDGE

### Personal Lines Product Suite

- **Auto** — standard and non-standard; multi-car discounts; rideshare endorsement available
- **Home** — HO-3 and HO-5; replacement cost vs. ACV is a key coverage conversation
- **Umbrella** — personal liability extension; always offer when auto + home are bundled
- **Renters** — often underquoted; strong cross-sell for auto customers
- **Condo** — HO-6; walls-in coverage; HOA master policy gap explanation is key
- **Life** — term, whole, universal life; separate pipeline (Life pipelines use calendar months, never Folio language)
- **Specialty** — motorcycle, boat, RV, classic car, landlord

### Key Farmers Endorsements to Always Review

- **Guaranteed Replacement Cost** — critical on home; never leave a client on ACV without explaining the gap
- **Identity Shield** — underoffered; strong value-add for retention
- **Equipment Breakdown** — home appliances and systems; easy add-on conversation
- **Diminishing Deductible** — loyalty benefit; great retention talking point
- **Umbrella** — flag on every bundled auto + home quote; $1M/$2M/$3M tiers

### Underwriting Flags to Know

- Homes 20+ years old: roof age will be scrutinized; confirm materials and age upfront
- Prior claims within 3 years: may affect eligibility or tier
- Credit score impact: California does not allow credit scoring for auto (Prop 103); home underwriting still uses it
- Trampoline, aggressive dog breeds, unfenced pools: flag as potential exclusion or surcharge items

---

## CARRIER CLASSIFICATION

**Farmers family:** Farmers Insurance AND Foremost (Foremost is a Farmers subsidiary). When analyzing carrier mix, combine Farmers + Foremost as "Farmers family" vs all other carriers as "brokered." Bristol West is also a Farmers company but typically categorized separately in AZ data.

## BROKERED CARRIER GUIDANCE

When Farmers is not the right fit, help the agent identify the right market without bad-mouthing Farmers.

### When to Consider Going to Market

- Home: age, construction type, or prior claims push outside Farmers appetite
- Auto: DUI/DWI within 3–5 years, SR-22 required, or excessive violations
- Non-standard risk profiles requiring specialty or E&S markets

### How to Position Brokered Business to the Client

- "We work with multiple carriers to make sure we find the right fit for your specific situation."
- Never frame it as "Farmers won't take you." Frame it as "We found a better match for your profile."
- Always document why the brokered placement was made — important for E&O and audit purposes.

### General Market Categories

- **Standard** — preferred risks; competitive on clean profiles
- **Non-standard auto** — violations, lapses, high-risk drivers
- **Specialty home** — coastal, older homes, high-value, unique construction
- **E&S** — risks that don't fit admitted markets

---

## COVERAGE GAP FRAMEWORK

When reviewing a quote, work through this checklist:

**Home**

- [ ] Dwelling limit — is it replacement cost, not market value?
- [ ] Personal property — scheduled items for jewelry, art, electronics?
- [ ] Loss of use — adequate for local rental rates?
- [ ] Liability — at least $300K; umbrella offered?
- [ ] Deductible — client understands what they'd pay out of pocket?
- [ ] Guaranteed/Extended Replacement Cost vs. ACV
- [ ] Equipment Breakdown endorsement
- [ ] Identity Shield

**Auto**

- [ ] Liability limits — state minimum vs. adequate (100/300/100 recommended)
- [ ] Uninsured/Underinsured Motorist — match liability limits
- [ ] Comprehensive and collision — deductible appropriate for vehicle value?
- [ ] Rental reimbursement
- [ ] Roadside assistance
- [ ] Rideshare endorsement if applicable
- [ ] Umbrella offered if bundling with home

**Always Offer**

- Umbrella on every bundled quote
- Renters to auto-only customers without homeowners coverage
- Life insurance touchpoint — even if not quoting today

---

## LEAD NURTURING & FOLLOW-UP STRATEGY

### Follow-Up Cadence by Lead Type

**High-Intent (Call/Walk In / NPL)**

- Attempt 1: Call within 5 minutes of lead entry
- Attempt 2: Text same day if no answer (reference the call attempt)
- Attempt 3: Email with quote or value prop within 24 hours
- Attempt 4: Call + voicemail day 2
- Attempt 5: Final breakup text day 5–7 if no response

**Internet Leads**

- Speed-to-contact is critical — contact within 5 minutes increases close rate dramatically
- Text first (higher open rate), call immediately after
- If no contact after 3 attempts in 48 hours, move to slower nurture cadence
- Email sequence: day 1 intro, day 3 value/education, day 7 follow-up, day 14 last touch

**Cross-Sell / Book Leads**

- Warmer — already a customer; tone is relationship-based, not sales-heavy
- Lead with the existing relationship: "I was reviewing your account and noticed..."
- Best channel: phone call first, then follow-up text or email

**Referrals**

- Reference the referral source immediately in first contact
- Referral leads close at 2–3x the rate of cold internet leads — prioritize them

### Signs a Lead Is Ready to Close

- Opened the quote email multiple times
- Asked specific questions about payment or effective date
- Responded quickly to last touchpoint
- Mentioned a specific X-date or renewal date

### Signs a Lead Is Ghosting (Adjust Strategy)

- 3+ unanswered calls over 5+ days
- No text/email response after two attempts
- Opened email but no reply
- Strategy: switch channels, change message angle, use a breakup message

---

## OBJECTION HANDLING SCRIPTS

### "I need to think about it."

"Absolutely, this is an important decision. Can I ask — is there a specific part of the quote you want to think through? Sometimes there's a coverage question or a number that doesn't feel right, and I'd rather we talk through it now so you have everything you need to decide. What's the main thing on your mind?"

### "I'm already with [competitor]."

"That makes sense — a lot of our clients came from [competitor]. I'm not here to tell you they're bad; they do fine for a lot of people. What I can do is show you exactly how the coverages compare side by side so you can see if what you have now is actually the best fit. Would that be helpful? It takes about 10 minutes and you'll know for sure either way."

### "Your price is too high."

"I hear you — price matters. Before we talk about lowering anything, can I ask what you're comparing it to? Sometimes what looks like a lower price has different coverage underneath it, and I want to make sure we're comparing apples to apples. If after we do that the price is still a concern, there are a couple of ways we can adjust the coverage to bring it down — I just want to make sure we don't accidentally leave you exposed."

### "I'll call you back."

"Of course — I don't want to pressure you. Can I ask, is there a specific day and time that works? I'll put it on my calendar and reach out then so you're not waiting on hold. And if something changes before then, feel free to text me directly at [number]."

### "I don't want to bundle."

"Totally fair — you don't have to. I'll quote them separately too so you can see both options. The reason I usually show the bundle is that the discount is pretty significant on both policies, but if the numbers don't make sense for you we'll keep them separate. Let me show you both and you can decide."

---

## EXAMPLE INTERACTIONS

**"I have a lead that got quoted 3 weeks ago and hasn't responded."**
→ Call getLeadDetail → assess stage, contact history, product, premium → recommend channel, timing, and specific script based on data.

**"My customer says Geico is $400 cheaper."**
→ Use the price objection script → pivot to coverage comparison → offer side-by-side review.

**"Can you review this quote for gaps?"**
→ Work through the coverage gap checklist → flag missing items → provide client-facing talking points for each.

**"What did Gabriela work on yesterday?"**
→ Call getProducerActivity with producer="Gabriela" and yesterday's date → summarize activity → flag coaching observations if any. **Cross-reference the pipeline automation schedule to exclude automated messages from the activity count.**

**"Is the team quoting their Call/Walk In leads?"**
→ Call getPipelineCompliance with pipeline_name="NPL Call" and current month date range → report passing/warning/failing by producer. **Remember: same-day quote turnaround is the promise for this pipeline.**

**"Who's our top closer this month?"**
→ Call getTeamPerformance with days=30 → rank by close rate → generate a horizontal bar chart of close rates by producer → present with context on backlog and lead aging.

**"Show me post-quote leakage for last month."**
→ Call getLostDealAnalysis with date range → surface leakage rate and recoverable lead count → generate a stacked bar showing leakage by category (controllable vs uncontrollable) → recommend re-engagement strategy.

**"How did the team do this week?"**
→ Call getFunnelPerformance with group_by=producer → generate a grouped bar chart comparing quote rate and close rate per producer → highlight top and bottom performers.

**"Audit Gabriela's internet leads for coaching."**
→ Call getCoachingAnalysis with producer="Gabriela", pipeline_name="Internet" → **use the NPL Internet automation schedule to identify which notes are automated vs. producer-typed** → surface missed call tasks, leads with no producer activity in producer-managed stages, and any auto-unenrollment events without timely follow-up.

**"What should I focus on in my 1:1 with a producer who works Call/Walk-In leads?"**
→ Call getPipelineCompliance for NPL Call/Walk-In → check same-day quote rate (Contacted → quote_date within 1 business day) → call getCoachingAnalysis filtered to "NPL Call" → **use the Call/Walk-In automation schedule to filter automated emails** → surface: missed same-day quotes (critical), missed Day 2 quote-review calls (high), and any leads in Waiting on Carrier without carrier follow-up notes (high).

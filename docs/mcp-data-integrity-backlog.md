# MCP Data Integrity — Engineering Backlog

From audit of coaching/activity endpoints on 2026-03-25. These are structural improvements to the MCP response schema, not consumer-side workarounds.

## Status: Proposed

---

## 1. Separate period-scoped fields from lifetime fields in schema

**Problem:** `classified_counts` (period-scoped) and `total_contact_attempts` (lifetime) sit in the same `context` object. Consuming LLMs treat them as the same scope.

**Fix:** Nest under explicit groups:

```json
{
  "period_activity": {
    "classified_counts": { ... },
    "notes_in_period": 3,
    "milestones": { ... }
  },
  "lifetime_context": {
    "total_contact_attempts": 14,
    "total_notes_lifetime": 26,
    "contact_date": "2026-02-18"
  }
}
```

**Files:** `services/az-analyst-service/src/routes/analysis.py` (coaching endpoint response builder, ~line 2060+)

**Risk:** Breaking change for Vance/ChatGPT consumers — coordinate with knowledge doc update.

---

## 2. Add trust metadata to responses

**Problem:** Consumers have no way to know when task data is incomplete or flags are low-confidence.

**Fix:** Add a `data_quality` section:

```json
{
  "data_quality": {
    "task_data_complete": false,
    "note_sync_complete": true,
    "period_activity_trustworthy": true
  }
}
```

**Implementation:** Check if `tasks == 0` but note history contains TASK-type notes → set `task_data_complete: false`.

---

## 3. Downgrade coaching flags from facts to heuristics

**Problem:** `missing_tasks` fires as a definitive flag even when 39% of flagged leads have task-related notes. `quoted_no_followup` had a code bug (fixed 2026-03-26).

**Fix:** Return flags with confidence and evidence basis:

```json
{
  "coaching_flags": [
    {
      "flag": "missing_tasks",
      "confidence": "low",
      "reason": "No task objects returned by API",
      "note_conflict": true
    }
  ]
}
```

**Minimum viable:** Add `note_conflict: true/false` to each flag by cross-checking against note content.

---

## 4. Add denominator metadata to summary endpoints

**Problem:** Summary counts like "22 new" can mean "currently in NEW status" or "created during period" depending on endpoint. Consumers conflate them.

**Fix:** Every summary should declare its denominator:

```json
{
  "metric_definitions": {
    "new_status_snapshot": "leads currently in NEW status within scoped population",
    "new_created_in_period": "leads with create_date in requested period"
  }
}
```

**Applies to:** getProducerActivity, getTeamPerformance, getCoachingAnalysis summary sections.

---

## 5. Improve task data sourcing for coaching

**Problem:** Coaching endpoint reads tasks from DB (`LeadTask` table), which is sync-dependent and misses Smart-Cycle/expired leads. The `getTasks` endpoint uses the live AZ API.

**Options:**

A. **Preferred:** Call live AZ API for tasks in the coaching endpoint (adds latency, ~1-2s per producer).

B. **Minimum:** Keep DB tasks but mark with `task_data_status: incomplete | complete | unavailable`. Suppress `missing_tasks` flag when `task_data_status != complete`.

---

## 6. Distinguish structured vs narrative activity

**Problem:** A lead with a TASK-type note documenting a phone call attempt may be classified as `no_activity` because the classifier only counts certain structured note types.

**Fix:** Add an `activity_evidence` field:

```json
{
  "activity_evidence": {
    "structured_activity_found": false,
    "narrative_activity_found": true,
    "manual_review_recommended": true
  }
}
```

**Implementation:** Scan note bodies for activity keywords (called, texted, emailed, left voicemail) when structured counts are zero.

---

## Completed

- [x] **quoted_no_followup null quote_date bug** — Fixed 2026-03-26 (commit ec31d5c). Falls back to earliest LeadQuote.synced_at when quote_date is null.
- [x] **Vance system prompt guardrails** — Added period-scoped vs lifetime field guide, contact_date warning, coaching flag reliability docs (commit 3ccb500).
- [x] **Vance knowledge doc audit rules** — Added 8-rule consumption ruleset for LLM consumers.

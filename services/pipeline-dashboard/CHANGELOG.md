# Pipeline Dashboard Changelog

## v1.7.4 — 2026-05-15
- Documented Info Needed stage for NPL Call/Walk-In pipeline (no automation, 8h clock resets per touchpoint)
- Updated Vance knowledge: explicit automation_analysis usage guidance, Info Needed stage coaching rules
- Added inaction flags for Info Needed stage (stale >3 days, customer info without 8h response)

## v1.7.3 — 2026-05-15
- Fixed tasks endpoint crash when task status is an integer
- Fixed source_lookup ordering bug — automation classification now runs before note timeline build
- Fixed crash when note_type is an integer instead of a string

## v1.7.0 — 2026-05-15
- SMS/email direction now uses AZ attr.outbound field (authoritative, replaces body heuristics)
- SMS automation detection uses attr.triggerRuleId for high-confidence classification
- Detect TCPA opt-out keywords (STOP, etc.) as sms_opt_out — not counted as customer contact
- New coaching flags: inbound_no_response and inbound_slow_response when customer contacts go unanswered within 24h
- Unanswered inbound detection excludes automated messages from counting as responses

## v1.6.0 — 2026-05-15
- Added automation-aware note classification to coaching endpoint
- Each note now tagged with source (automated/producer/unknown) and confidence
- New automation_analysis block per lead with split automated vs producer counts
- Unenrollment detection using AZ auto_unenroll_automation events
- Covers NPL Internet, Protege Home, and NPL Call/Walk-In pipelines

## v1.5.0 — 2026-05-15
- Added Protege Home and Protege Auto pipeline classifications
- Added pipeline activity evaluation specs (NPL Internet, NPL Call/Walk-In)
- Updated Vance knowledge with automation schedules for coaching analysis

## v1.4.0 — 2026-05-01
- Added weekly pipeline review prompts and master formatting rules
- Added High-Intent and Internet daily review prompts
- Added prompt library overlay with favorites

## v1.3.0 — 2026-04-20
- Added SVG favicon
- Added note pagination and size controls to lead detail endpoint
- Added data visualization guidance to analysis prompts

## v1.2.0 — 2026-04-10
- Fixed speed-to-quote calculation (24h window instead of same calendar date)
- Fixed task_sync_incomplete vs missing_tasks separation in coaching
- Fixed quoted_no_followup false-fires from wrong quote date source
- Fixed coaching endpoint type mismatch and added error logging
- Hybrid note loading in coaching endpoint to fix high-volume producer 500s

## v1.1.0 — 2026-03-25
- Added data integrity audit rules and engineering backlog
- Added data integrity guardrails to Vance system prompt
- Added activity classification to coaching endpoint
- Added sales analytics endpoint (won revenue, carrier placement, source mapping)

## v1.0.0 — 2026-03-01
- Initial pipeline dashboard with Kanban board view
- Activity summary page with date presets and producer filtering
- AgencyZoom data sync with cron scheduling
- User authentication via AZ credentials
- HTMX-powered real-time board updates

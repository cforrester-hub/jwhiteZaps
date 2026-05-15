# Pipeline Dashboard Changelog

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

# Pipeline Dashboard Changelog

## v1.14.1 — 2026-09-24
- deputy-service: the Teams payload also carries the message as HTML (`Ilse ---&gt; <span style="color:red">Break Started</span>`), so the flow can use "Post message in a chat or channel" as Flow bot: a normal chat bubble with colored text like the zap's posts, and no template footer. The Adaptive Card is still included

## v1.14.0 — 2026-09-24
- deputy-service: posts clock in/out and break events to the Entire Team Teams chat ("Ilse ---> Break Started", green/red like the Zapier zap) through a Teams Workflows webhook. Off until `TEAMS_WEBHOOK_URL` is set; a Teams failure never blocks the RingCentral update. This was the zap's last job

## v1.13.0 — 2026-09-24
- deputy-service: clock in/out now actually changes RingCentral queue status. It had been sending the short extension number (e.g. 105), which RingCentral rejects with 404, so every update failed and the Zapier zap was doing the real work
- deputy-service: new employees and stale IDs resolve themselves: Redis learned mapping, then shared/user_mappings.json, then a live lookup (Deputy employee email/name to RingCentral user), cached in Redis; a 404 on a stored ID re-resolves and retries once. Ambiguous matches are logged, never guessed
- ringcentral-service: new `GET /api/ringcentral/extensions` (id, number, name, email, type)
- shared/user_mappings.json: added Ilse Segura Delgado (ext 101); removed Erin Nikiel, Claudia Noriega, Gabriela Sandoval (inactive in Deputy)

## v1.12.0 — 2026-09-24
- deputy-service: `POST /api/deputy/webhook/timesheet` and `/api/deputy/webhook/test` now require the header `Authorization: Bearer` followed by the new `DEPUTY_WEBHOOK_SECRET` env var, set in each Deputy webhook's Headers field. Anything else gets a 401, and so does every request while the variable is unset. Before this, anyone could forge a clock event and change an employee's RingCentral DND
- CI: the test job runs the deputy-service tests; a failure blocks build and deploy

## v1.11.4 — 2026-09-24
- dashboard-service: removed the status page's Run Now buttons. Since v1.11.2 they returned 404 (a browser can't send the admin key), and re-opening them would give anonymous visitors a workflow trigger again. Workflows still run every 5 minutes; a manual run is `POST /api/workflows/run/{name}` with `X-API-Key`

## v1.11.3 — 2026-09-23
- Fix: `/pipeline/api/changelog` returned 500 because the v1.11.2 entry had a Windows-1252 dash byte; the file is valid UTF-8 again

## v1.11.2 — 2026-09-23
- Security: Traefik no longer passes anonymous requests to ringcentral, agencyzoom, storage, transcription, workflow, or test services. `/health` stays public; every other path needs `X-API-Key` matching `WORKFLOW_ADMIN_API_KEY` (404 without it), and the deploy fails if that variable is unset. deputy-service exposes only `/health` and the timesheet webhook, `/api/dashboard/internal/*` is no longer routed, and Loki's port 3100 binds to localhost only. The dashboard's Run Now buttons stop working; the 5-minute cron is unchanged

## v1.11.1 — 2026-09-23
- Docs: droplet compose commands in CLAUDE.md now pass both compose files (`-f docker-compose.yml -f docker-compose.prod.yml`), matching the deploy; the old plain `docker compose` command ignored production settings

## v1.11.0 — 2026-09-23
- workflow-service: new `POST /api/workflows/reprocess/{incoming_call|outgoing_call}/{call_id}` re-runs a single call regardless of age (the cron workflows only look back 4 hours) and creates a new note. Requires `X-API-Key` matching the new `WORKFLOW_ADMIN_API_KEY` env var; disabled when unset

## v1.10.0 — 2026-09-23
- transcription-service: card numbers, security codes, bank routing/account numbers, and SSNs are scrubbed from every transcript before it is summarized or returned (voicemail notes include the transcript). Summaries are scrubbed again on the way out, and the prompt forbids including them
- transcription-service + workflow-service: call notes gain a KEY DETAILS section (quote figures with carrier/coverages/deductibles/premium/term/effective date, vehicles, properties, changes, payment arrangements, pending items) between AI SUMMARY and ACTION ITEMS; the summary itself stays short prose

## v1.9.0 — 2026-09-23
- workflow-service + transcription-service: transferred calls now transcribe every recording segment and summarize them as one call (previously only the first segment, often just the greeting, was summarized). Segments are labeled with who handled each part
- transcription-service: summary length scales with the call (1-2 sentences for short calls up to a full paragraph for long ones) and includes concrete specifics (names, properties, vehicles, carriers, premiums, dates); action items say who owns each one

## v1.8.2 — 2026-09-23
- workflow-service: transcription requests now allow 15 minutes (was the shared 30s client timeout), so longer calls get an AI summary instead of silently timing out

## v1.8.1 — 2026-09-23
- ringcentral-service: on transferred inbound calls, `queue_name` now keeps the original queue (e.g. "CSR Overflow") instead of the transfer target's name

## v1.8.0 — 2026-09-23
- ringcentral-service: inbound calls now report `queue_name` (the queue that took the call, e.g. "CSR Overflow") and `answered_by` (agent(s) who connected, in order for transfers), parsed from call legs; desk-phone answers resolved via extension lookup
- ringcentral-service: recording segments on inbound calls are now labeled with the answering agent instead of blank
- workflow-service: incoming call notes show the queue in "To" (instead of "Main Tree") and a new "Answered by" line

## v1.7.9 — 2026-09-17
- Docs: fixed deploy-verification grep command in CLAUDE.md

## v1.7.8 — 2026-09-17
- CI: deploy now self-verifies — images stamped with commit SHA, deploy waits for all containers to be healthy and fails if any container is not running the pushed commit
- CI: runs serialized per branch so rapid pushes deploy one at a time
- Docs: corrected workflow-service API paths (/api/workflows/...)

## v1.7.7 — 2026-09-17
- CI: pinned appleboy scp/ssh GitHub Actions to full commit SHAs in deploy and daily-report workflows (supply-chain hardening)

## v1.7.6 — 2026-09-17
- workflow-service: unmatched voicemail tasks now assigned to Maria Prince (114222) instead of previous fallback CSR

## v1.7.5 — 2026-05-15
- Updated 6 analysis prompts with automation filtering instructions (use producer_counts, not raw counts)
- Added unanswered_inbound as highest-priority coaching flag in prompts
- Added Info Needed stage + resetting 8h clock to high-intent prompts
- Added internet lead funnel benchmarks (stage-transition evaluation) to internet prompts

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

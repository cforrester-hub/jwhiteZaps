# CLAUDE.md

> **Note:** This file serves as persistent memory across Claude sessions.

## Project Overview
Microservice Zapier Replacement - A containerized stack to replace Zapier automations with self-hosted microservices on DigitalOcean.

## Tech Stack
- Python 3.11+ with FastAPI (async)
- PostgreSQL (async via SQLAlchemy + asyncpg)
- Docker + docker-compose
- DigitalOcean (droplet + managed DB + Spaces)
- GitHub Actions CI/CD
- Traefik reverse proxy

## Domains
- Local: localhost
- Production: https://jwhitezaps.atoaz.com

## Services

| Service | Purpose |
|---------|---------|
| ringcentral-service | RingCentral API (calls, recordings, voicemails, DND) |
| agencyzoom-service | AgencyZoom API (customers, leads, notes, tasks) |
| storage-service | DigitalOcean Spaces uploads |
| transcription-service | OpenAI Whisper + GPT summarization |
| workflow-service | Workflow orchestration + cron scheduler |
| deputy-service | Deputy webhooks to RingCentral DND |
| dashboard-service | Employee status dashboard |

## Workflows (workflow-service)

| Workflow | Schedule | Description |
|----------|----------|-------------|
| incoming_call | Every 5 min (:00) | Inbound calls to AgencyZoom notes |
| outgoing_call | Every 5 min (:01) | Outbound calls to AgencyZoom notes |
| voicemail | Every 5 min (:02) | Voicemails to AgencyZoom notes + tasks |

Features:
- 15-min delay for recording availability
- Skips internal extension-to-extension calls
- Multiple recordings for transferred calls
- AI summarization (RingSense or Whisper fallback)
- Tracks processed items in PostgreSQL

## Key Implementation Details

### Multiple Recordings (Transferred Calls)
- Extracts recordings from all legs in call log
- Uploads each segment: callid_part1.mp3, callid_part2.mp3
- Shows all recording links with extension names

### Internal Call Detection
Skipped when:
- Both from_extension_id and to_extension_id set, OR
- Both phone numbers < 7 digits

### Database Connection Pooling
- pool_size=2, max_overflow=3
- pool_pre_ping=True, pool_recycle=300
- Staggered workflow schedules to avoid exhaustion

### Timezone
- RingCentral times are UTC
- Display: Pacific (America/Los_Angeles)

### Logging Strategy
- **Format**: Structured JSON logging (workflow-service)
- **Driver**: json-file with rotation (10MB max, 3 files)
- **Middleware**: Request/response logging on all HTTP endpoints
- **Infrastructure**: Loki + Grafana available at grafana.${DOMAIN}
- **View logs**: `docker compose logs -f workflow-service`
- **Log levels**: Controlled via LOG_LEVEL env var (default: INFO)

Key log fields:
- `timestamp`, `level`, `service`, `logger`, `source`
- Request logs: `method`, `path`, `status_code`, `duration_ms`
- Workflow logs: `call_id`, `workflow_name`, `notes_created`

## Commands

```bash
# Local dev
docker-compose up -d --build

# View logs (all services)
docker compose logs -f workflow-service

# View logs with timestamps and filtering
docker compose logs -f --since 1h workflow-service | grep -i error

# Search logs for specific call ID
docker compose logs workflow-service 2>&1 | grep "chEF8Z9Qlp5CjUA"

# Production force update
docker compose pull && docker compose up -d --force-recreate

# Check recent workflow runs
docker compose logs --since 30m workflow-service | grep -E "(Starting|completed|processed)"
```

## API Endpoints

### Workflow Service
- GET /api/workflow/workflows - List workflows
- POST /api/workflow/workflows/{name}/run - Trigger workflow
- DELETE /api/workflow/processed/{workflow}/{id} - Reprocess item

### RingCentral Service
- GET /api/ringcentral/calls - Fetch call logs
- GET /api/ringcentral/calls/{id} - Call details
- GET /api/ringcentral/calls/{id}/raw - Debug raw response

## User Context
- Insurance agency automation project
- Key integrations: RingCentral, AgencyZoom, Deputy

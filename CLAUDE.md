# CLAUDE.md

> **Note:** This file serves as persistent memory across Claude sessions. It is automatically updated with project context, decisions, and preferences learned during development.

## Project Overview
Microservice Zapier Replacement - A containerized stack to replace Zapier automations with self-hosted microservices on DigitalOcean.

**Motivation:**
- Cost reduction from Zapier subscription
- RingCentral trigger issues in Zapier requiring custom solution
- Greater control and flexibility over automation workflows

## Tech Stack
- Language: Python 3.11+
- Framework: FastAPI (async, auto OpenAPI docs, API-centric)
- Containerization: Docker + docker-compose
- Deployment: DigitalOcean (single droplet)
- CI/CD: GitHub Actions
- Container Registry: GitHub Container Registry (ghcr.io)
- IDE: PyCharm
- Version Control: Git + GitHub

## Domains
- **Local development:** localhost
- **Production:** https://jwhitezaps.atoaz.com

## Shared Infrastructure (Decided)
- **Reverse proxy:** Traefik (native Docker integration, auto-discovery, auto SSL)
- **Database:** PostgreSQL (managed service in prod, containerized locally) + Redis (caching/queues)
- **Logging:** Loki + Grafana (lightweight)
- **Scheduler:** Built into microservices (some cron-based, some webhook-based)

## Project Structure
```
/
├── docker-compose.yml           # Base config (includes containerized PostgreSQL)
├── docker-compose.override.yml  # Local dev overrides (auto-loaded by docker-compose)
├── docker-compose.prod.yml      # Production overrides (excludes local PostgreSQL)
├── .env.example                 # Environment variable template
├── .env                         # Your local env vars (git-ignored)
├── .github/
│   └── workflows/
│       └── deploy.yml           # GitHub Actions CI/CD pipeline
├── .gitignore
├── grafana/
│   └── provisioning/
│       └── datasources/
│           └── loki.yml         # Auto-configures Loki in Grafana
├── scripts/
│   └── droplet-setup.sh         # Fresh droplet setup script
├── services/
│   └── test-service/            # Test microservice (validates stack)
│       ├── Dockerfile
│       ├── requirements.txt
│       └── src/
│           ├── main.py          # FastAPI app with endpoints
│           ├── config.py        # Settings from env vars
│           ├── database.py      # PostgreSQL connection
│           ├── redis_client.py  # Redis connection
│           └── scheduler.py     # Cron job scheduler
└── CLAUDE.md                    # This file (persistent memory)
```

## Quick Start (Local Development)
```bash
# 1. Copy env template and fill in values
cp .env.example .env

# 2. Start all services (builds images on first run)
docker-compose up -d --build

# 3. Check services are running
docker-compose ps

# 4. Test the stack
curl http://localhost/api/test/health
curl http://localhost/api/test/health/ready
curl http://localhost/api/test/db
curl http://localhost/api/test/redis
```

## Development Commands
```bash
# Start all services
docker-compose up -d

# Start specific service
docker-compose up -d <service-name>

# View logs (all services)
docker-compose logs -f

# View logs (specific service)
docker-compose logs -f test-service

# Rebuild after code changes
docker-compose up -d --build test-service

# Stop all services
docker-compose down

# Stop and remove volumes (reset data)
docker-compose down -v
```

## Local URLs
- **Test Service API:** http://localhost/api/test/
- **Test Service Docs:** http://localhost/api/test/docs
- **Traefik Dashboard:** http://localhost:8080
- **Grafana:** http://localhost:3000
- **PostgreSQL:** localhost:5432
- **Redis:** localhost:6379

## Architecture Notes
- Each microservice = 1 Docker container
- Shared resources (DB, logging, messaging) run as separate containers
- All services communicate via internal Docker network
- Reverse proxy (Traefik) handles external routing
- Trigger types vary per microservice: cron-based or webhook-based

**First microservice:** RingCentral integration (full replacement, cron-based to avoid RingCentral webhook restrictions)

**Development approach:**
1. Build base stack with test microservice first
2. Validate everything works locally and deploys to DigitalOcean
3. Then build actual RingCentral microservice

## Coding Conventions
<!-- To be established -->

## Environment Setup

### Local Development
- PyCharm + Docker Desktop
- **Everything runs in containers** - no local installs needed
- PostgreSQL container included (local testing only)
- Just run `docker-compose up -d` and the full stack starts

### Production Droplet
- **Spec:** Ubuntu 24.04 LTS, Regular 2 vCPU, 4GB RAM ($24/mo)
- **Setup:** Run `scripts/droplet-setup.sh` on fresh droplet
- Managed PostgreSQL (container excluded via `docker-compose.prod.yml`)
- Deploy command: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

### GitHub Repository Secrets (Settings > Secrets > Actions)
Required for deployment:
- `DEPLOY_HOST` - DigitalOcean droplet IP address
- `DEPLOY_USER` - SSH username (usually `root`)
- `SSH_PRIVATE_KEY` - SSH private key for droplet access
- `GHCR_TOKEN` - GitHub token with `packages:write` scope (or use default GITHUB_TOKEN)

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-14 | Traefik for reverse proxy | Native Docker integration, auto SSL |
| 2026-01-14 | Loki + Grafana for logging | Lightweight for single droplet |
| 2026-01-14 | Full Zapier replacement approach | Zapier trigger already broken, more control |
| 2026-01-14 | Cron for RingCentral trigger | Avoid RingCentral webhook restrictions |
| 2026-01-14 | PostgreSQL managed in prod | Offload DB management, containerized for local dev |
| 2026-01-14 | FastAPI for microservices | Async, auto OpenAPI, API-centric focus |
| 2026-01-14 | Domain: jwhitezaps.atoaz.com | Production domain for Traefik SSL |
| 2026-01-14 | GitHub over GitLab | Better DigitalOcean integration, simpler CI/CD, larger community |

## User Context
- Solo developer, personal project for own company
- Newer to Python/FastAPI - provide clear explanations
- Project focus: APIs and connecting web services (Zapier replacement)
- Cloud deployment is a priority

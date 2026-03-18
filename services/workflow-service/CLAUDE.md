# Workflow Service

Orchestrates automated workflows that sync data between RingCentral and AgencyZoom.

## Structure
```
src/
├── main.py           # FastAPI app, scheduler setup, API endpoints
├── config.py         # Settings from environment variables
├── database.py       # PostgreSQL connection (asyncpg)
├── scheduler.py      # APScheduler AsyncIOScheduler
├── http_client.py    # Clients for other microservices
└── workflows/
    ├── __init__.py       # Workflow registry, is_processed/mark_processed
    ├── incoming_call.py  # Inbound call processing
    ├── outgoing_call.py  # Outbound call processing (shared utilities)
    └── voicemail.py      # Voicemail processing
```

## Workflows

### incoming_call / outgoing_call
- Polls RingCentral for calls every 5 minutes
- 15-minute delay to ensure recordings are ready
- Skips internal (extension-to-extension) calls
- Searches AgencyZoom by phone number
- Uploads recordings to DigitalOcean Spaces
- Gets AI summary (RingSense or Whisper fallback)
- Creates note in AgencyZoom customer/lead record
- Handles multiple recordings for transferred calls

### voicemail
- Similar flow but for voicemails
- Creates follow-up task assigned to CSR/producer

## Key Functions (outgoing_call.py)

- `is_call_too_recent(call)` - Check if call ended < 15 min ago
- `is_internal_call(call)` - Detect extension-to-extension calls
- `format_datetime_for_display(iso)` - UTC to Pacific conversion
- `build_note_content(...)` - HTML note for AgencyZoom
- `process_single_call(call)` - Main processing logic

## Cron Schedules (Staggered)
- incoming_call: :00, :05, :10... (0,5,10... * * * *)
- outgoing_call: :01, :06, :11... (1,6,11... * * * *)
- voicemail: :02, :07, :12... (2,7,12... * * * *)

## Database Tables
- processed_items: Track what has been processed
- workflow_runs: Execution history

## API Endpoints
- POST /api/workflow/workflows/{name}/run - Trigger manually
- GET /api/workflow/processed - View processed items
- DELETE /api/workflow/processed/{workflow}/{id} - Allow reprocessing

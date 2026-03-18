# RingCentral Service

Microservice for RingCentral API integration - call logs, recordings, voicemails, and AI insights.

## Overview

This service acts as a gateway to the RingCentral API, handling authentication and providing simplified endpoints for other services to consume. It uses JWT-based authentication with automatic token refresh.

## Structure

```
services/ringcentral-service/
├── Dockerfile
├── requirements.txt
└── src/
    ├── main.py              # FastAPI app with all endpoints
    ├── config.py            # Settings from environment variables
    └── ringcentral_client.py # RingCentral API client
```

## API Endpoints

### Health & Connection
- `GET /api/ringcentral/health` - Basic health check
- `GET /api/ringcentral/test-connection` - Test RingCentral API connectivity

### Call Log
- `GET /api/ringcentral/calls` - Fetch call logs with filtering (date range, direction)
- `GET /api/ringcentral/calls/{call_id}` - Get call details with optional recording URLs and AI insights
- `GET /api/ringcentral/calls/{call_id}/raw` - Raw RingCentral response (debugging)

### Recordings
- `GET /api/ringcentral/recordings/{recording_id}` - Get recording metadata and download URL
- `GET /api/ringcentral/recordings/{recording_id}/insights` - RingSense AI insights (transcript, summary)

### Voicemails
- `GET /api/ringcentral/voicemails` - List voicemails (single or all extensions)
- `GET /api/ringcentral/voicemails/{message_id}` - Get specific voicemail with download URL
- `GET /api/ringcentral/voicemails/find-for-call/{call_id}` - Find voicemail associated with a missed call

### Presence/DND
- `GET /api/ringcentral/extensions/{extension_id}/presence` - Get extension DND status
- `PUT /api/ringcentral/extensions/{extension_id}/presence` - Update DND status
- `POST /api/ringcentral/extensions/{extension_id}/available` - Set extension to accept all calls
- `POST /api/ringcentral/extensions/{extension_id}/unavailable` - Set extension to reject queue calls

## Key Data Models

### CallSummary
Contains basic call info plus:
- `recording_id` - Primary recording ID (first found)
- `recordings` - List of ALL recording segments (for transferred calls)

### RecordingInfo
```python
recording_id: str
leg_index: int      # Which call leg (0, 1, 2... for transfers)
duration: int
extension_name: str # Who handled this segment
```

### RingSenseResponse
```python
available: bool
transcript: list    # Word-by-word transcript
summary: str        # AI-generated summary
highlights: list    # Key moments
next_steps: list    # Action items
```

## RingCentral Client Methods

Located in `ringcentral_client.py`:

### Authentication
- `_ensure_authenticated()` - Auto-refreshes JWT token before expiry
- `_authenticate()` - Gets new access token using JWT assertion

### Call Operations
- `get_call_log()` - Fetch paginated call logs with filters
- `get_call_with_details()` - Single call with full details
- `get_call_recording()` - Recording metadata
- `get_recording_content_url()` - Authenticated download URL

### Voicemail Operations
- `get_voicemail_messages()` - Voicemails for single extension
- `get_all_voicemail_messages()` - Voicemails across ALL extensions
- `find_voicemail_for_call()` - Match voicemail to missed call
- `get_voicemail_content_url()` - Authenticated download URL

### Presence Operations
- `get_extension_presence()` - Get DND status
- `update_extension_dnd()` - Set DND status
- `set_extension_available()` - Accept all calls
- `set_extension_unavailable()` - Reject queue calls

## Key Implementation Details

### Multiple Recordings Per Call
Transferred calls have recordings per leg. The service extracts recordings from the `legs` array:
```python
for leg_index, leg in enumerate(legs):
    leg_recording = leg.get("recording")
    if leg_recording and leg_recording.get("id"):
        all_recordings.append(RecordingInfo(...))
```

### Extension Name Resolution
Extension names are resolved from multiple sources in order:
1. Top-level `from`/`to` objects
2. Leg-level `from`/`to` objects
3. Leg-level `extension` object

### Voicemail Finding Strategy
`find_voicemail_for_call()` uses two strategies:
1. **Direct**: Get message ID from call log's `legs[].message` object
2. **Fallback**: Search across all extensions by phone number and time window

### DND Status Values
- `TakeAllCalls` - Accept all calls (clocked in)
- `DoNotAcceptDepartmentCalls` - Direct calls only (on break/clocked out)
- `TakeDepartmentCallsOnly` - Queue calls only
- `DoNotAcceptAnyCalls` - Reject everything

## Environment Variables

```
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
RINGCENTRAL_CLIENT_ID=your_client_id
RINGCENTRAL_CLIENT_SECRET=your_client_secret
RINGCENTRAL_JWT_TOKEN=your_jwt_token
LOG_LEVEL=INFO
```

## Dependencies

- FastAPI + Uvicorn
- httpx (async HTTP client)
- pydantic (data validation)

## Notes

- JWT tokens auto-refresh 5 minutes before expiry
- Recording URLs include access token as query parameter
- RingSense AI insights may not be available for all recordings
- Voicemail search across all extensions iterates through enabled extensions (slower but comprehensive)

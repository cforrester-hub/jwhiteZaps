"""
Webhook handlers for incoming events.

Each module in this package defines FastAPI routes for handling
webhooks from external services.
"""

from fastapi import APIRouter

# Create main webhook router
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Import webhook handlers to register their routes
# Uncomment these as you add webhook handlers:
# from . import ringcentral
# from . import agencyzoom

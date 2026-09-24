"""Shared test setup: runs before any test module imports src.main (settings are loaded once, at import)."""

import os

os.environ.setdefault("DEPUTY_WEBHOOK_SECRET", "test-secret")

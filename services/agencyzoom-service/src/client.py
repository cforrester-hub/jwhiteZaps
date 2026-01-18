"""AgencyZoom API client for customers, leads, and notes."""

import logging
import re
from typing import Optional

import httpx

from .config import get_settings
from .auth import get_auth_headers, clear_token_cache

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number for AgencyZoom search.

    AgencyZoom expects 10-digit US phone numbers without country code.

    Args:
        phone: Phone number in any format (e.g., "+18057946787", "(805) 794-6787")

    Returns:
        10-digit phone number (e.g., "8057946787")
    """
    # Strip all non-digit characters
    digits = re.sub(r"\D", "", phone)

    # Remove leading 1 for US numbers (11 digits starting with 1)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return digits


async def _make_request(method: str, endpoint: str, **kwargs) -> httpx.Response:
    """
    Make an authenticated request to AgencyZoom API.

    Handles token refresh on 401 errors.
    """
    headers = await get_auth_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method,
            f"{settings.agencyzoom_api_url}{endpoint}",
            headers=headers,
            **kwargs,
        )

        # If unauthorized, clear cache and retry once
        if response.status_code == 401:
            logger.warning("Got 401, clearing token cache and retrying")
            clear_token_cache()
            headers = await get_auth_headers()
            response = await client.request(
                method,
                f"{settings.agencyzoom_api_url}{endpoint}",
                headers=headers,
                **kwargs,
            )

        return response


async def search_customers(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Search for customers in AgencyZoom.

    Args:
        phone: Phone number to search for
        email: Email to search for
        name: Name to search for
        page: Page number (1-indexed)
        page_size: Number of results per page

    Returns:
        dict with 'customers' list and pagination info
    """
    # Build search payload
    payload = {
        "page": page,
        "pageSize": page_size,
    }

    # Add search criteria
    if phone:
        payload["phone"] = normalize_phone(phone)
    if email:
        payload["email"] = email
    if name:
        payload["name"] = name

    logger.info(f"Searching customers with: {payload}")

    response = await _make_request("POST", "/v1/api/customers", json=payload)

    if response.status_code != 200:
        logger.error(f"Customer search failed: {response.status_code} - {response.text}")
        return {"customers": [], "total": 0, "error": response.text}

    data = response.json()

    # Handle the response format from AgencyZoom
    # API returns {"totalCount": N, "customers": [...]}
    customers = data.get("customers", [])
    total = data.get("totalCount", len(customers))

    return {
        "customers": customers,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def search_leads(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Search for leads in AgencyZoom.

    Args:
        phone: Phone number to search for (customerPhone field)
        email: Email to search for
        name: Name to search for
        page: Page number (1-indexed)
        page_size: Number of results per page

    Returns:
        dict with 'leads' list and pagination info
    """
    # Build search payload
    payload = {
        "page": page,
        "pageSize": page_size,
    }

    # Add search criteria - leads use 'customerPhone' field
    if phone:
        payload["customerPhone"] = normalize_phone(phone)
    if email:
        payload["customerEmail"] = email
    if name:
        payload["customerName"] = name

    logger.info(f"Searching leads with: {payload}")

    response = await _make_request("POST", "/v1/api/leads/list", json=payload)

    if response.status_code != 200:
        logger.error(f"Lead search failed: {response.status_code} - {response.text}")
        return {"leads": [], "total": 0, "error": response.text}

    data = response.json()

    # Handle the response format from AgencyZoom
    # API likely returns {"totalCount": N, "leads": [...]}
    leads = data.get("leads", [])
    total = data.get("totalCount", len(leads))

    return {
        "leads": leads,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def search_by_phone(phone: str) -> dict:
    """
    Search for both customers and leads by phone number.

    This is the main function for the outgoing call workflow.

    Args:
        phone: Phone number to search for

    Returns:
        dict with 'customers' and 'leads' lists
    """
    normalized = normalize_phone(phone)
    logger.info(f"Searching by phone: {phone} (normalized: {normalized})")

    # Search both customers and leads
    customers_result = await search_customers(phone=normalized)
    leads_result = await search_leads(phone=normalized)

    return {
        "phone": phone,
        "normalized_phone": normalized,
        "customers": customers_result.get("customers", []),
        "leads": leads_result.get("leads", []),
        "has_match": bool(
            customers_result.get("customers") or leads_result.get("leads")
        ),
    }


async def create_customer_note(
    customer_id: str,
    content: str,
    note_type: str = "General",
) -> dict:
    """
    Create a note for a customer.

    Args:
        customer_id: The customer's ID in AgencyZoom
        content: The note content/text
        note_type: Type of note (default: "General")

    Returns:
        dict with created note info or error
    """
    payload = {
        "content": content,
        "noteType": note_type,
    }

    logger.info(f"Creating note for customer {customer_id}")

    response = await _make_request(
        "POST",
        f"/v1/api/customers/{customer_id}/notes",
        json=payload,
    )

    if response.status_code not in (200, 201):
        logger.error(f"Create customer note failed: {response.status_code} - {response.text}")
        return {"success": False, "error": response.text}

    return {
        "success": True,
        "customer_id": customer_id,
        "data": response.json() if response.text else {},
    }


async def create_lead_note(
    lead_id: str,
    content: str,
    note_type: str = "General",
) -> dict:
    """
    Create a note for a lead.

    Args:
        lead_id: The lead's ID in AgencyZoom
        content: The note content/text
        note_type: Type of note (default: "General")

    Returns:
        dict with created note info or error
    """
    payload = {
        "content": content,
        "noteType": note_type,
    }

    logger.info(f"Creating note for lead {lead_id}")

    response = await _make_request(
        "POST",
        f"/v1/api/leads/{lead_id}/notes",
        json=payload,
    )

    if response.status_code not in (200, 201):
        logger.error(f"Create lead note failed: {response.status_code} - {response.text}")
        return {"success": False, "error": response.text}

    return {
        "success": True,
        "lead_id": lead_id,
        "data": response.json() if response.text else {},
    }


async def get_customer(customer_id: str) -> Optional[dict]:
    """Get a customer by ID."""
    response = await _make_request("GET", f"/v1/api/customers/{customer_id}")

    if response.status_code != 200:
        logger.error(f"Get customer failed: {response.status_code}")
        return None

    return response.json()


async def get_lead(lead_id: str) -> Optional[dict]:
    """Get a lead by ID."""
    response = await _make_request("GET", f"/v1/api/leads/{lead_id}")

    if response.status_code != 200:
        logger.error(f"Get lead failed: {response.status_code}")
        return None

    return response.json()

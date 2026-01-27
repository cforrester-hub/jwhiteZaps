"""AgencyZoom API client for customers, leads, and notes."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

import httpx

from .config import get_settings
from .auth import get_auth_headers, clear_token_cache

logger = logging.getLogger(__name__)
settings = get_settings()

# Rate limiting configuration
# AgencyZoom limits: 30 calls/min during day, 60 calls/min 10PM-4AM CT
RATE_LIMIT_RETRY_SECONDS = 65  # Wait slightly over 1 minute on rate limit
MAX_RETRIES = 3
# Proactive delay between requests to stay under rate limit (2 seconds = max 30/min)
REQUEST_DELAY_SECONDS = 2.0

# Track last request time for rate limiting
_last_request_time: Optional[datetime] = None


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number for AgencyZoom search.

    AgencyZoom expects 10-digit US phone numbers without country code.

    Args:
        phone: Phone number in any format (e.g., "+18057946787", "(805) 794-6787")

    Returns:
        10-digit phone number (e.g., "8057946787")
    """
    if not phone:
        return ""

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", phone)

    # Remove leading 1 for US numbers (11 digits starting with 1)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return digits


def _customer_matches_phone(customer: dict, normalized_phone: str) -> bool:
    """
    Check if a customer has a phone number matching the searched phone.

    Args:
        customer: Customer dict from AgencyZoom API
        normalized_phone: The normalized phone number we searched for

    Returns:
        True if customer's phone or secondaryPhone matches
    """
    # Empty/invalid phone should never match anyone
    if not normalized_phone or len(normalized_phone) < 7:
        return False

    customer_phones = [
        normalize_phone(customer.get("phone") or ""),
        normalize_phone(customer.get("secondaryPhone") or ""),
    ]
    return normalized_phone in customer_phones


def _lead_matches_phone(lead: dict, normalized_phone: str) -> bool:
    """
    Check if a lead has a phone number matching the searched phone.

    Args:
        lead: Lead dict from AgencyZoom API
        normalized_phone: The normalized phone number we searched for

    Returns:
        True if lead's phone or secondaryPhone matches
    """
    # Empty/invalid phone should never match anyone
    if not normalized_phone or len(normalized_phone) < 7:
        return False

    lead_phones = [
        normalize_phone(lead.get("phone") or ""),
        normalize_phone(lead.get("secondaryPhone") or ""),
    ]
    return normalized_phone in lead_phones


async def _make_request(method: str, endpoint: str, **kwargs) -> httpx.Response:
    """
    Make an authenticated request to AgencyZoom API.

    Handles:
    - Proactive rate limiting (delay between requests)
    - Token refresh on 401 errors
    - Rate limiting (429) with automatic retry after waiting
    """
    global _last_request_time

    # Proactive rate limiting - ensure minimum delay between requests
    if _last_request_time is not None:
        elapsed = (datetime.utcnow() - _last_request_time).total_seconds()
        if elapsed < REQUEST_DELAY_SECONDS:
            wait_time = REQUEST_DELAY_SECONDS - elapsed
            await asyncio.sleep(wait_time)

    _last_request_time = datetime.utcnow()
    headers = await get_auth_headers()

    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                f"{settings.agencyzoom_api_url}{endpoint}",
                headers=headers,
                **kwargs,
            )

            # Handle unauthorized - refresh token and retry
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
                # If still 401 after refresh, return the error
                if response.status_code == 401:
                    return response

            # Handle rate limiting - wait and retry
            if response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"Rate limited by AgencyZoom (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Waiting {RATE_LIMIT_RETRY_SECONDS} seconds before retry..."
                    )
                    await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
                    continue
                else:
                    logger.error("Rate limited by AgencyZoom - max retries exceeded")
                    return response

            # Success or other error - return response
            return response

    # Should not reach here, but return last response if we do
    return response


async def search_customers(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    page: int = 0,
    page_size: int = 20,
) -> dict:
    """
    Search for customers in AgencyZoom.

    Args:
        phone: Phone number to search for
        email: Email to search for
        name: Name to search for
        page: Page number (0-indexed, per AgencyZoom API)
        page_size: Number of results per page

    Returns:
        dict with 'customers' list and pagination info
    """
    # Build search payload - AgencyZoom uses 0-indexed pages
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
        payload["fullName"] = name  # AgencyZoom uses fullName for name search

    logger.info(f"Searching customers with: {payload}")

    response = await _make_request("POST", "/v1/api/customers", json=payload)

    if response.status_code != 200:
        logger.error(f"Customer search failed: {response.status_code} - {response.text}")
        return {"customers": [], "total": 0, "error": response.text}

    data = response.json()
    logger.info(f"Customer search raw response: {data}")

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
    page: int = 0,
    page_size: int = 20,
) -> dict:
    """
    Search for leads in AgencyZoom.

    Args:
        phone: Phone number to search for (customerPhone field)
        email: Email to search for
        name: Name to search for
        page: Page number (0-indexed, per AgencyZoom API)
        page_size: Number of results per page

    Returns:
        dict with 'leads' list and pagination info
    """
    # Build search payload - AgencyZoom uses 0-indexed pages
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
    logger.info(f"Lead search raw response: {data}")

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
    Results are verified to ensure the returned customers/leads actually
    have a phone number matching what we searched for.

    Args:
        phone: Phone number to search for

    Returns:
        dict with 'customers' and 'leads' lists (verified matches only)
    """
    normalized = normalize_phone(phone)
    logger.info(f"Searching by phone: {phone} (normalized: {normalized})")

    # Search both customers and leads
    customers_result = await search_customers(phone=normalized)
    leads_result = await search_leads(phone=normalized)

    # Get raw results from API
    raw_customers = customers_result.get("customers", [])
    raw_leads = leads_result.get("leads", [])

    # Verify each result actually has a matching phone number
    # AgencyZoom may return fuzzy matches that don't actually match
    verified_customers = [
        c for c in raw_customers if _customer_matches_phone(c, normalized)
    ]
    verified_leads = [
        l for l in raw_leads if _lead_matches_phone(l, normalized)
    ]

    # Log if we filtered out any non-matching results
    if len(verified_customers) < len(raw_customers):
        filtered_count = len(raw_customers) - len(verified_customers)
        logger.warning(
            f"Filtered out {filtered_count} customer(s) that didn't match phone {normalized}"
        )
    if len(verified_leads) < len(raw_leads):
        filtered_count = len(raw_leads) - len(verified_leads)
        logger.warning(
            f"Filtered out {filtered_count} lead(s) that didn't match phone {normalized}"
        )

    return {
        "phone": phone,
        "normalized_phone": normalized,
        "customers": verified_customers,
        "leads": verified_leads,
        "has_match": bool(verified_customers or verified_leads),
    }


async def create_customer_note(
    customer_id: str,
    content: str,
) -> dict:
    """
    Create a note for a customer.

    Args:
        customer_id: The customer's ID in AgencyZoom
        content: The note content/text (can include HTML)

    Returns:
        dict with created note info or error
    """
    # AgencyZoom API expects 'note' field, not 'content'
    payload = {
        "note": content,
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
) -> dict:
    """
    Create a note for a lead.

    Args:
        lead_id: The lead's ID in AgencyZoom
        content: The note content/text (can include HTML)

    Returns:
        dict with created note info or error
    """
    # AgencyZoom API expects 'note' field, not 'content'
    payload = {
        "note": content,
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


async def create_task(
    title: str,
    due_datetime: str,
    assignee_id: int,
    customer_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    comments: Optional[str] = None,
    task_type: str = "call",
    duration: int = 15,
    time_specific: bool = True,
) -> dict:
    """
    Create a task in AgencyZoom.

    Args:
        title: Task title/subject
        due_datetime: Due date/time in ISO format
        assignee_id: CSR/Agent ID to assign the task to
        customer_id: Customer ID to link the task to (optional)
        lead_id: Lead ID to link the task to (optional)
        comments: Task notes/description (can include HTML)
        task_type: Type of task - "todo", "email", "call", or "meeting"
        duration: Duration in minutes
        time_specific: If true, time is applicable for due date

    Returns:
        dict with created task info or error
    """
    payload = {
        "title": title,
        "dueDatetime": due_datetime,
        "assigneeId": assignee_id,
        "type": task_type,
        "duration": duration,
        "timeSpecific": time_specific,
    }

    if customer_id:
        payload["customerId"] = customer_id
    if lead_id:
        payload["leadId"] = lead_id
    if comments:
        payload["comments"] = comments

    logger.info(f"Creating task: {title} for assignee {assignee_id}")

    response = await _make_request("POST", "/v1/api/tasks", json=payload)

    if response.status_code not in (200, 201):
        logger.error(f"Create task failed: {response.status_code} - {response.text}")
        return {"success": False, "error": response.text}

    return {
        "success": True,
        "customer_id": customer_id,
        "lead_id": lead_id,
        "data": response.json() if response.text else {},
    }


async def get_customer_csr_id(customer_id: int) -> Optional[int]:
    """
    Get the primary CSR ID for a customer.

    Looks at the customer's policies to find the CSR assigned.

    Args:
        customer_id: The customer ID

    Returns:
        CSR ID or None if not found
    """
    customer = await get_customer(str(customer_id))
    if not customer:
        return None

    # Check policies for CSR ID
    policies = customer.get("policies", [])
    for policy in policies:
        csr_id = policy.get("csrId")
        if csr_id:
            return csr_id

    return None


async def get_lead_producer_id(lead_id: int) -> Optional[int]:
    """
    Get the primary producer/agent ID for a lead.

    Args:
        lead_id: The lead ID

    Returns:
        Producer/Agent ID or None if not found
    """
    lead = await get_lead(str(lead_id))
    if not lead:
        return None

    # Leads use assignedTo for the primary producer/agent
    return lead.get("assignedTo") or lead.get("agentId") or lead.get("producerId")

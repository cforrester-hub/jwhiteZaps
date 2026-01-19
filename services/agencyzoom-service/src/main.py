"""
AgencyZoom Service - API integration for AgencyZoom CRM.

This service provides endpoints for searching customers/leads
and creating notes in AgencyZoom.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .config import get_settings
from . import client
from .auth import get_access_token, clear_token_cache

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="AgencyZoom Service",
    description="API integration for AgencyZoom CRM",
    version="1.0.0",
    root_path="/api/agencyzoom",
)


# =============================================================================
# MODELS
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    timestamp: str


class ConnectionTestResponse(BaseModel):
    """Connection test response."""
    status: str
    message: str


class SearchByPhoneRequest(BaseModel):
    """Request to search by phone number."""
    phone: str


class SearchByPhoneResponse(BaseModel):
    """Response from phone search."""
    phone: str
    normalized_phone: str
    customers: list
    leads: list
    has_match: bool


class CustomerSearchRequest(BaseModel):
    """Request to search customers."""
    phone: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    page: int = 0  # AgencyZoom uses 0-indexed pages
    page_size: int = 20


class LeadSearchRequest(BaseModel):
    """Request to search leads."""
    phone: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    page: int = 0  # AgencyZoom uses 0-indexed pages
    page_size: int = 20


class CreateNoteRequest(BaseModel):
    """Request to create a note."""
    content: str  # Note content (can include HTML)


class CreateNoteResponse(BaseModel):
    """Response from note creation."""
    success: bool
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    error: Optional[str] = None


class CreateTaskRequest(BaseModel):
    """Request to create a task."""
    title: str
    due_datetime: str  # ISO format datetime
    assignee_id: int
    customer_id: Optional[int] = None
    lead_id: Optional[int] = None
    comments: Optional[str] = None
    task_type: str = "call"  # todo, email, call, meeting
    duration: int = 15
    time_specific: bool = True


class CreateTaskResponse(BaseModel):
    """Response from task creation."""
    success: bool
    customer_id: Optional[int] = None
    lead_id: Optional[int] = None
    error: Optional[str] = None


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Basic health check."""
    return HealthResponse(
        status="healthy",
        service="agencyzoom-service",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def readiness_check():
    """Readiness check - verifies AgencyZoom connection."""
    try:
        # Try to get an access token to verify connectivity
        await get_access_token()
        return HealthResponse(
            status="ready",
            service="agencyzoom-service",
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail=f"AgencyZoom not ready: {str(e)}")


@app.get("/test-connection", response_model=ConnectionTestResponse, tags=["health"])
async def test_connection():
    """Test the connection to AgencyZoom API."""
    try:
        await get_access_token()
        return ConnectionTestResponse(
            status="connected",
            message="Successfully authenticated with AgencyZoom API",
        )
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/clear-token-cache", tags=["health"])
async def clear_cache():
    """Clear the authentication token cache."""
    clear_token_cache()
    return {"status": "cleared", "message": "Token cache has been cleared"}


# =============================================================================
# SEARCH ENDPOINTS
# =============================================================================


@app.post("/search/phone", response_model=SearchByPhoneResponse, tags=["search"])
async def search_by_phone(request: SearchByPhoneRequest):
    """
    Search for customers and leads by phone number.

    This is the primary endpoint for the outgoing call workflow.
    It searches both customers and leads and returns all matches.

    - **phone**: The phone number to search for (any format)
    """
    try:
        result = await client.search_by_phone(request.phone)
        return SearchByPhoneResponse(**result)
    except Exception as e:
        logger.error(f"Phone search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search/phone/{phone}", response_model=SearchByPhoneResponse, tags=["search"])
async def search_by_phone_get(phone: str):
    """
    Search for customers and leads by phone number (GET version).

    - **phone**: The phone number to search for (any format)
    """
    try:
        result = await client.search_by_phone(phone)
        return SearchByPhoneResponse(**result)
    except Exception as e:
        logger.error(f"Phone search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/customers/search", tags=["customers"])
async def search_customers(request: CustomerSearchRequest):
    """
    Search for customers with various criteria.

    - **phone**: Filter by phone number
    - **email**: Filter by email
    - **name**: Filter by name
    - **page**: Page number (1-indexed)
    - **page_size**: Results per page
    """
    try:
        result = await client.search_customers(
            phone=request.phone,
            email=request.email,
            name=request.name,
            page=request.page,
            page_size=request.page_size,
        )
        return result
    except Exception as e:
        logger.error(f"Customer search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/leads/search", tags=["leads"])
async def search_leads(request: LeadSearchRequest):
    """
    Search for leads with various criteria.

    - **phone**: Filter by phone number
    - **email**: Filter by email
    - **name**: Filter by name
    - **page**: Page number (1-indexed)
    - **page_size**: Results per page
    """
    try:
        result = await client.search_leads(
            phone=request.phone,
            email=request.email,
            name=request.name,
            page=request.page,
            page_size=request.page_size,
        )
        return result
    except Exception as e:
        logger.error(f"Lead search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CUSTOMER ENDPOINTS
# =============================================================================


@app.get("/customers/{customer_id}", tags=["customers"])
async def get_customer(customer_id: str):
    """Get a customer by ID."""
    try:
        customer = await client.get_customer(customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get customer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/customers/{customer_id}/notes", response_model=CreateNoteResponse, tags=["customers"])
async def create_customer_note(customer_id: str, request: CreateNoteRequest):
    """
    Create a note for a customer.

    - **customer_id**: The customer's ID
    - **content**: The note text (can include HTML)
    """
    try:
        result = await client.create_customer_note(
            customer_id=customer_id,
            content=request.content,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to create note"))

        return CreateNoteResponse(
            success=True,
            customer_id=customer_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create customer note failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LEAD ENDPOINTS
# =============================================================================


@app.get("/leads/{lead_id}", tags=["leads"])
async def get_lead(lead_id: str):
    """Get a lead by ID."""
    try:
        lead = await client.get_lead(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get lead failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/leads/{lead_id}/notes", response_model=CreateNoteResponse, tags=["leads"])
async def create_lead_note(lead_id: str, request: CreateNoteRequest):
    """
    Create a note for a lead.

    - **lead_id**: The lead's ID
    - **content**: The note text (can include HTML)
    """
    try:
        result = await client.create_lead_note(
            lead_id=lead_id,
            content=request.content,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to create note"))

        return CreateNoteResponse(
            success=True,
            lead_id=lead_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create lead note failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TASK ENDPOINTS
# =============================================================================


@app.post("/tasks", response_model=CreateTaskResponse, tags=["tasks"])
async def create_task(request: CreateTaskRequest):
    """
    Create a task in AgencyZoom.

    - **title**: Task title/subject
    - **due_datetime**: Due date/time in ISO format
    - **assignee_id**: CSR/Agent ID to assign the task to
    - **customer_id**: Customer ID to link the task to (optional)
    - **lead_id**: Lead ID to link the task to (optional)
    - **comments**: Task notes/description (can include HTML)
    - **task_type**: Type of task - "todo", "email", "call", or "meeting"
    - **duration**: Duration in minutes
    - **time_specific**: If true, time is applicable for due date
    """
    try:
        result = await client.create_task(
            title=request.title,
            due_datetime=request.due_datetime,
            assignee_id=request.assignee_id,
            customer_id=request.customer_id,
            lead_id=request.lead_id,
            comments=request.comments,
            task_type=request.task_type,
            duration=request.duration,
            time_specific=request.time_specific,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to create task"))

        return CreateTaskResponse(
            success=True,
            customer_id=request.customer_id,
            lead_id=request.lead_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create task failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/customers/{customer_id}/csr", tags=["customers"])
async def get_customer_csr(customer_id: str):
    """Get the primary CSR ID for a customer."""
    try:
        csr_id = await client.get_customer_csr_id(int(customer_id))
        if csr_id is None:
            raise HTTPException(status_code=404, detail="CSR not found for customer")
        return {"customer_id": customer_id, "csr_id": csr_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get customer CSR failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/leads/{lead_id}/producer", tags=["leads"])
async def get_lead_producer(lead_id: str):
    """Get the primary producer/agent ID for a lead."""
    try:
        producer_id = await client.get_lead_producer_id(int(lead_id))
        if producer_id is None:
            raise HTTPException(status_code=404, detail="Producer not found for lead")
        return {"lead_id": lead_id, "producer_id": producer_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get lead producer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DEBUG ENDPOINTS
# =============================================================================


@app.get("/debug/raw-customer-search/{phone}", tags=["debug"])
async def debug_raw_customer_search(phone: str):
    """
    Debug endpoint: Make a raw customer search and return the exact response.

    This helps diagnose issues with the AgencyZoom API response format.
    """
    import httpx
    from .auth import get_auth_headers

    normalized = client.normalize_phone(phone)
    headers = await get_auth_headers()

    payload = {
        "page": 0,  # AgencyZoom uses 0-indexed pages
        "pageSize": 20,
        "phone": normalized,
    }

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        response = await http_client.post(
            f"{settings.agencyzoom_api_url}/v1/api/customers",
            headers=headers,
            json=payload,
        )

    return {
        "input_phone": phone,
        "normalized_phone": normalized,
        "request_payload": payload,
        "response_status": response.status_code,
        "response_headers": dict(response.headers),
        "response_body": response.json() if response.status_code == 200 else response.text,
    }

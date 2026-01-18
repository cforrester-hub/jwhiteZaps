"""
Storage Service - File storage API using DigitalOcean Spaces.

This service provides endpoints for uploading, downloading, and managing
files in DigitalOcean Spaces (S3-compatible storage).
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel

from .config import get_settings
from . import spaces_client

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Storage Service",
    description="File storage API using DigitalOcean Spaces",
    version="1.0.0",
    docs_url="/api/storage/docs",
    redoc_url="/api/storage/redoc",
    openapi_url="/api/storage/openapi.json",
)


# =============================================================================
# MODELS
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    timestamp: str


class UploadResponse(BaseModel):
    """Response after file upload."""
    key: str
    url: str
    size: int
    content_type: str


class FileInfo(BaseModel):
    """File information."""
    key: str
    size: int
    last_modified: str
    url: str


class UploadFromUrlRequest(BaseModel):
    """Request to upload a file from a URL."""
    url: str
    filename: str
    folder: str = ""
    content_type: str = "application/octet-stream"
    public: bool = True


class PresignedUrlResponse(BaseModel):
    """Response with presigned URL."""
    url: str
    expires_in: int


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================


@app.get("/api/storage/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Basic health check."""
    return HealthResponse(
        status="healthy",
        service="storage-service",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/api/storage/health/ready", response_model=HealthResponse, tags=["health"])
async def readiness_check():
    """Readiness check - verifies Spaces connection."""
    try:
        # Try to list files to verify connection
        spaces_client.list_files(prefix="", max_keys=1)
        return HealthResponse(
            status="ready",
            service="storage-service",
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Storage not ready: {str(e)}")


# =============================================================================
# FILE UPLOAD ENDPOINTS
# =============================================================================


@app.post("/api/storage/upload", response_model=UploadResponse, tags=["files"])
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form(default=""),
    public: bool = Form(default=True),
):
    """
    Upload a file to storage.

    - **file**: The file to upload
    - **folder**: Optional folder path (e.g., "recordings/2024/01")
    - **public**: Whether to make the file publicly accessible (default: true)
    """
    try:
        content = await file.read()
        content_type = file.content_type or "application/octet-stream"

        result = spaces_client.upload_file(
            file_content=content,
            filename=file.filename,
            folder=folder,
            content_type=content_type,
            public=public,
        )

        return UploadResponse(**result)

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/api/storage/upload-from-url", response_model=UploadResponse, tags=["files"])
async def upload_from_url(request: UploadFromUrlRequest):
    """
    Download a file from a URL and upload it to storage.

    This is useful for saving call recordings from RingCentral.

    - **url**: The URL to download from (can include auth in URL or headers)
    - **filename**: The filename to save as
    - **folder**: Optional folder path
    - **content_type**: MIME type (default: application/octet-stream)
    - **public**: Whether to make publicly accessible (default: true)
    """
    try:
        # Download the file
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(request.url)
            response.raise_for_status()
            content = response.content

        # Detect content type from response if not specified
        content_type = request.content_type
        if content_type == "application/octet-stream" and "content-type" in response.headers:
            content_type = response.headers["content-type"].split(";")[0]

        # Upload to Spaces
        result = spaces_client.upload_file(
            file_content=content,
            filename=request.filename,
            folder=request.folder,
            content_type=content_type,
            public=request.public,
        )

        logger.info(f"Uploaded from URL: {request.url} -> {result['key']}")
        return UploadResponse(**result)

    except httpx.HTTPError as e:
        logger.error(f"Failed to download from URL: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to download: {str(e)}")
    except Exception as e:
        logger.error(f"Upload from URL failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# =============================================================================
# FILE RETRIEVAL ENDPOINTS
# =============================================================================


@app.get("/api/storage/files", response_model=list[FileInfo], tags=["files"])
async def list_files(
    prefix: str = Query(default="", description="Filter by key prefix (folder path)"),
    max_keys: int = Query(default=100, le=1000, description="Maximum number of results"),
):
    """
    List files in storage.

    - **prefix**: Filter by key prefix (e.g., "recordings/2024/")
    - **max_keys**: Maximum number of results (default: 100, max: 1000)
    """
    try:
        files = spaces_client.list_files(prefix=prefix, max_keys=max_keys)
        return [FileInfo(**f) for f in files]
    except Exception as e:
        logger.error(f"List files failed: {e}")
        raise HTTPException(status_code=500, detail=f"List failed: {str(e)}")


@app.get("/api/storage/files/{key:path}", tags=["files"])
async def get_file_info(key: str):
    """
    Get information about a specific file.

    - **key**: The file key (path in storage)
    """
    try:
        if not spaces_client.file_exists(key):
            raise HTTPException(status_code=404, detail="File not found")

        # Get file metadata using head_object
        client = spaces_client.get_spaces_client()
        response = client.head_object(
            Bucket=settings.spaces_bucket,
            Key=key,
        )

        return {
            "key": key,
            "size": response["ContentLength"],
            "content_type": response["ContentType"],
            "last_modified": response["LastModified"].isoformat(),
            "url": f"{settings.public_base_url}/{key}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get file info failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")


@app.get("/api/storage/presigned-url/{key:path}", response_model=PresignedUrlResponse, tags=["files"])
async def get_presigned_url(
    key: str,
    expires_in: int = Query(default=3600, le=86400, description="URL expiration in seconds"),
):
    """
    Generate a presigned URL for temporary access to a private file.

    - **key**: The file key
    - **expires_in**: URL expiration time in seconds (default: 1 hour, max: 24 hours)
    """
    try:
        if not spaces_client.file_exists(key):
            raise HTTPException(status_code=404, detail="File not found")

        url = spaces_client.get_presigned_url(key, expires_in)
        return PresignedUrlResponse(url=url, expires_in=expires_in)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Presigned URL generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")


# =============================================================================
# FILE DELETE ENDPOINT
# =============================================================================


@app.delete("/api/storage/files/{key:path}", tags=["files"])
async def delete_file(key: str):
    """
    Delete a file from storage.

    - **key**: The file key (path in storage)
    """
    try:
        if not spaces_client.file_exists(key):
            raise HTTPException(status_code=404, detail="File not found")

        spaces_client.delete_file(key)
        return {"status": "deleted", "key": key}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

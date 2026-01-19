"""Database connection and models for tracking workflow state."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, Boolean, Index
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from .config import get_settings

settings = get_settings()

# Create async engine with connection pool limits to avoid "too many connections" error
database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
database_url = database_url.replace("sslmode=", "ssl=")
engine = create_async_engine(
    database_url,
    echo=False,
    pool_size=5,           # Maximum number of connections to keep in the pool
    max_overflow=5,        # Allow up to 5 additional connections beyond pool_size
    pool_pre_ping=True,    # Verify connections before use
    pool_recycle=300,      # Recycle connections after 5 minutes
)

# Session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Base class for models
Base = declarative_base()


class ProcessedItem(Base):
    """
    Tracks items that have been processed by workflows.
    Prevents duplicate processing across runs.
    """

    __tablename__ = "processed_items"

    id = Column(String(255), primary_key=True)  # e.g., "call_123" or "recording_456"
    workflow_name = Column(String(100), nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    details = Column(Text, nullable=True)  # JSON string with additional info

    __table_args__ = (
        Index("ix_processed_workflow", "workflow_name"),
        Index("ix_processed_at", "processed_at"),
    )


class WorkflowRun(Base):
    """
    Tracks workflow execution history.
    Useful for debugging and monitoring.
    """

    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True)  # UUID
    workflow_name = Column(String(100), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # running, success, failed
    items_processed = Column(String(10), default="0")
    error_message = Column(Text, nullable=True)

    __table_args__ = (Index("ix_workflow_runs_name", "workflow_name"),)


async def init_db():
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncSession:
    """Get a database session."""
    async with async_session() as session:
        yield session

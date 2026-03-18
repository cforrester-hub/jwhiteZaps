"""Database connection and models for the pipeline dashboard."""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from .config import get_settings

settings = get_settings()

# Create async engine with connection pool limits
database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
database_url = database_url.replace("sslmode=", "ssl=")
engine = create_async_engine(
    database_url,
    echo=False,
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


class Session(Base):
    """User login sessions."""

    __tablename__ = "pd_sessions"

    id = Column(String(64), primary_key=True)  # secrets.token_urlsafe(32)
    az_user_id = Column(String(100), nullable=True)  # producer ID from AZ
    az_username = Column(String(255), nullable=False)  # email used to log in
    az_jwt = Column(Text, nullable=False)
    display_name = Column(String(255), nullable=True)
    is_owner_agent = Column(Integer, default=0)  # from login response ownerAgent
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_pd_sessions_expires", "expires_at"),
        Index("ix_pd_sessions_user", "az_user_id"),
    )


class Pipeline(Base):
    """Cached AgencyZoom pipelines."""

    __tablename__ = "pd_pipelines"

    id = Column(String(50), primary_key=True)  # AZ returns string IDs
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=True)
    seq = Column(Integer, nullable=True)
    status = Column(Integer, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)


class Stage(Base):
    """Cached AgencyZoom pipeline stages."""

    __tablename__ = "pd_stages"

    id = Column(String(50), primary_key=True)  # AZ returns string IDs
    pipeline_id = Column(
        String(50), ForeignKey("pd_pipelines.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    seq = Column(Integer, nullable=True)
    status = Column(Integer, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_pd_stages_pipeline", "pipeline_id"),)


class Lead(Base):
    """Cached AgencyZoom leads."""

    __tablename__ = "pd_leads"

    id = Column(Integer, primary_key=True, autoincrement=False)  # AZ lead ID
    pipeline_id = Column(String(50), nullable=True)
    stage_id = Column(String(50), nullable=True)  # workflowStageId
    assigned_to = Column(Integer, nullable=True)  # AZ agent ID
    firstname = Column(String(255), nullable=True)
    lastname = Column(String(255), nullable=True)
    lead_type = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    status = Column(Integer, nullable=True)  # 0=NEW,1=QUOTED,2=WON,3=LOST,4=CONTACTED,5=EXPIRED
    premium = Column(Float, nullable=True)
    quoted = Column(Float, nullable=True)
    enter_stage_date = Column(String(50), nullable=True)
    contact_date = Column(String(50), nullable=True)
    lead_source_name = Column(String(255), nullable=True)
    workflow_name = Column(String(255), nullable=True)
    workflow_stage_name = Column(String(255), nullable=True)
    assign_to_firstname = Column(String(255), nullable=True)
    assign_to_lastname = Column(String(255), nullable=True)
    raw_json = Column(JSONB, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_leads_pipeline_stage", "pipeline_id", "stage_id"),
        Index("ix_pd_leads_assigned", "assigned_to"),
        Index("ix_pd_leads_synced", "synced_at"),
    )


async def init_db():
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)



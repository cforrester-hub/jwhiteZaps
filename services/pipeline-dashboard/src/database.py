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
    select,
    text,
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


class Employee(Base):
    """Cached AgencyZoom employees."""

    __tablename__ = "pd_employees"

    id = Column(Integer, primary_key=True, autoincrement=False)
    firstname = Column(String(255), nullable=True)
    lastname = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    is_producer = Column(Integer, default=0)
    is_active = Column(Integer, default=0)
    is_owner = Column(Integer, default=0)
    user_id = Column(Integer, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_employees_email", "email"),
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
    last_activity_date = Column(String(50), nullable=True)
    contact_date = Column(String(50), nullable=True)
    lead_source_name = Column(String(255), nullable=True)
    workflow_name = Column(String(255), nullable=True)
    workflow_stage_name = Column(String(255), nullable=True)
    assign_to_firstname = Column(String(255), nullable=True)
    assign_to_lastname = Column(String(255), nullable=True)
    # High-value fields from AZ list API
    street_address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(10), nullable=True)
    zip_code = Column(String(20), nullable=True)
    sold_date = Column(String(50), nullable=True)
    x_date = Column(String(50), nullable=True)  # policy expiration date
    quote_date = Column(String(50), nullable=True)
    customer_id = Column(Integer, nullable=True)  # links lead to AZ customer
    tag_names = Column(String(500), nullable=True)  # comma-separated tags
    lead_source_id = Column(Integer, nullable=True)  # stable ID for lead source
    raw_json = Column(JSONB, nullable=True)
    detail_json = Column(JSONB, nullable=True)  # full GET /leads/{id} response
    detail_synced_at = Column(DateTime, nullable=True)  # when detail was last fetched
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_leads_pipeline_stage", "pipeline_id", "stage_id"),
        Index("ix_pd_leads_assigned", "assigned_to"),
        Index("ix_pd_leads_synced", "synced_at"),
    )


class LeadQuote(Base):
    """Cached AgencyZoom lead quotes/opportunities."""

    __tablename__ = "pd_lead_quotes"

    id = Column(Integer, primary_key=True, autoincrement=False)  # AZ quote ID
    lead_id = Column(Integer, ForeignKey("pd_leads.id", ondelete="CASCADE"), nullable=False)
    carrier_id = Column(Integer, nullable=True)
    carrier_name = Column(String(255), nullable=True)
    product_line_id = Column(Integer, nullable=True)
    product_name = Column(String(255), nullable=True)
    premium = Column(Float, nullable=True)
    items = Column(Integer, nullable=True)  # number of items/policies
    sold = Column(Integer, nullable=True)  # 0 or 1
    effective_date = Column(String(50), nullable=True)
    potential_revenue = Column(Float, nullable=True)
    property_address = Column(String(500), nullable=True)
    raw_json = Column(JSONB, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_lead_quotes_lead", "lead_id"),
        Index("ix_pd_lead_quotes_carrier", "carrier_name"),
    )


class LeadFile(Base):
    """Cached AgencyZoom lead file references (quote PDFs, etc.)."""

    __tablename__ = "pd_lead_files"

    id = Column(Integer, primary_key=True, autoincrement=False)  # AZ file ID
    lead_id = Column(Integer, ForeignKey("pd_leads.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=True)
    media_type = Column(String(100), nullable=True)
    file_type = Column(Integer, nullable=True)  # 1 = quote file
    size = Column(Integer, nullable=True)  # bytes
    create_date = Column(String(50), nullable=True)
    comments = Column(Text, nullable=True)
    raw_json = Column(JSONB, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_lead_files_lead", "lead_id"),
    )


class LeadOpportunity(Base):
    """Cached AgencyZoom lead opportunities (carrier/product being quoted)."""

    __tablename__ = "pd_lead_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=False)  # AZ opportunity ID
    lead_id = Column(Integer, ForeignKey("pd_leads.id", ondelete="CASCADE"), nullable=False)
    carrier_id = Column(Integer, nullable=True)
    product_line_id = Column(Integer, nullable=True)
    status = Column(Integer, nullable=True)
    premium = Column(Float, nullable=True)
    items = Column(Integer, nullable=True)
    property_address = Column(String(500), nullable=True)
    raw_json = Column(JSONB, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pd_lead_opportunities_lead", "lead_id"),
    )


class SyncMeta(Base):
    """Tracks sync metadata (e.g., last successful full/delta sync time)."""

    __tablename__ = "pd_sync_meta"

    key = Column(String(50), primary_key=True)
    value = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


async def init_db():
    """Create database tables if they don't exist, and run migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrations: add columns that create_all won't add to existing tables
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE pd_leads ADD COLUMN IF NOT EXISTS last_activity_date VARCHAR(50)
        """))
        # 2026-03-20: High-value columns
        for col, coltype in [
            ("street_address", "VARCHAR(255)"),
            ("city", "VARCHAR(100)"),
            ("state", "VARCHAR(10)"),
            ("zip_code", "VARCHAR(20)"),
            ("sold_date", "VARCHAR(50)"),
            ("x_date", "VARCHAR(50)"),
            ("quote_date", "VARCHAR(50)"),
            ("customer_id", "INTEGER"),
            ("tag_names", "VARCHAR(500)"),
            ("lead_source_id", "INTEGER"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE pd_leads ADD COLUMN IF NOT EXISTS {col} {coltype}"
            ))
        # 2026-03-21: Detail sync columns
        for col, coltype in [
            ("detail_json", "JSONB"),
            ("detail_synced_at", "TIMESTAMP"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE pd_leads ADD COLUMN IF NOT EXISTS {col} {coltype}"
            ))

    # Set one-time detail backfill flag if not already set
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(SyncMeta).where(SyncMeta.key == "detail_backfill_needed")
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                await session.merge(SyncMeta(
                    key="detail_backfill_needed",
                    value="true",
                    updated_at=datetime.utcnow(),
                ))



"""
Database connection and session management.
Uses SQLAlchemy async for non-blocking database operations.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from .config import get_settings

settings = get_settings()

# Create async engine with connection pool limits
# Note: asyncpg requires postgresql+asyncpg:// URL scheme
# Also convert sslmode=require to ssl=require for asyncpg compatibility
database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
database_url = database_url.replace("sslmode=", "ssl=")
engine = create_async_engine(
    database_url,
    echo=False,
    pool_size=3,           # Maximum number of connections to keep in the pool
    max_overflow=2,        # Allow up to 2 additional connections beyond pool_size
    pool_pre_ping=True,    # Verify connections before use
    pool_recycle=300,      # Recycle connections after 5 minutes
)

# Session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    Usage in FastAPI endpoint:
        @app.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session() as session:
        yield session


async def check_database_connection() -> bool:
    """Check if database is reachable."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

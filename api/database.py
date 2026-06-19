"""
PostgreSQL database engine and session factory.
Uses SQLAlchemy with Alembic-managed migrations.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from api.models import Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://clipper:clipper@localhost:5432/clipper")

engine_kwargs = {"pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autoflush=False, bind=engine)


def init_db():
    """Ensure all tables exist. Alembic handles migrations; this is a dev fallback."""
    Base.metadata.create_all(bind=engine)
    _ensure_dev_schema_compatibility()


def _ddl_type(column) -> str:
    if DATABASE_URL.startswith("postgresql"):
        name = column.type.__class__.__name__.lower()
        if "json" in name:
            return "JSONB"
        elif "float" in name:
            return "DOUBLE PRECISION"
        elif "integer" in name or "bigint" in name:
            return "INTEGER"
        elif "datetime" in name:
            return "TIMESTAMP"
        elif "boolean" in name:
            return "BOOLEAN"
        elif "text" in name:
            return "TEXT"
        elif "enum" in name:
            return "VARCHAR(255)"
        return "VARCHAR"
    return column.type.compile(dialect=engine.dialect)


def _ensure_dev_schema_compatibility():
    """
    Add nullable columns introduced after the initial local DB was created.
    Production deployments should still run Alembic; this keeps existing dev
    SQLite/Postgres databases from crashing at startup during active rebuilds.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key or not column.nullable:
                    continue
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {_ddl_type(column)}"))

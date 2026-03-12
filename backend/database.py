import os

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.getenv("DB_PATH", "/app/data/db/printvault.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)


def create_db_and_tables() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Add new columns to existing tables without dropping data."""
    migrations = [
        "ALTER TABLE printfile ADD COLUMN file_hash TEXT",
        "ALTER TABLE printfile ADD COLUMN missing INTEGER NOT NULL DEFAULT 0",
    ]
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(printfile)")}
        ran_any = False
        for sql in migrations:
            col = sql.split("ADD COLUMN ")[1].split()[0]
            if col not in existing:
                conn.exec_driver_sql(sql)
                ran_any = True
        if ran_any:
            conn.commit()


def get_session():
    with Session(engine) as session:
        yield session

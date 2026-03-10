import os

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.getenv("DB_PATH", "/app/data/db/printvault.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def create_db_and_tables() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session

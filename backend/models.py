import json
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PrintFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    path: str = Field(unique=True, index=True)
    format: str  # STL | 3MF | OBJ | LYS
    size_bytes: int
    category: str = "misc"
    tags: str = "[]"  # JSON-array stored as string
    supports_needed: bool = False
    difficulty: str = "medium"  # easy | medium | hard
    notes: str = ""
    favorite: bool = False
    print_status: str = "unprinted"  # unprinted | printing | printed
    thumbnail_path: Optional[str] = None
    ai_processed: bool = False
    file_hash: Optional[str] = None
    missing: bool = False
    date_added: datetime = Field(default_factory=datetime.utcnow)
    date_modified: datetime = Field(default_factory=datetime.utcnow)


class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: str


# ── Response / Update schemas ──────────────────────────────────────────────────

class PrintFileRead(SQLModel):
    id: int
    name: str
    path: str
    format: str
    size_bytes: int
    category: str
    tags: list[str]
    supports_needed: bool
    difficulty: str
    notes: str
    favorite: bool
    print_status: str
    thumbnail_path: Optional[str]
    ai_processed: bool
    file_hash: Optional[str]
    missing: bool
    date_added: datetime
    date_modified: datetime
    folder: str = ""  # relative path within FILES_DIR

    @classmethod
    def from_db(cls, obj: PrintFile) -> "PrintFileRead":
        import os
        data = obj.model_dump()
        data["tags"] = json.loads(obj.tags) if obj.tags else []
        files_dir = os.getenv("FILES_DIR", "/files")
        try:
            rel = os.path.relpath(os.path.dirname(obj.path), files_dir)
            data["folder"] = "" if rel == "." else rel
        except ValueError:
            data["folder"] = ""
        return cls(**data)


class PrintFileUpdate(SQLModel):
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    supports_needed: Optional[bool] = None
    difficulty: Optional[str] = None
    notes: Optional[str] = None
    favorite: Optional[bool] = None
    print_status: Optional[str] = None


class FolderSet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    folder: str = Field(unique=True, index=True)  # relative path from FILES_DIR
    display_name: str = ""
    description: str = ""
    date_created: datetime = Field(default_factory=datetime.utcnow)


class FolderSetUpsert(SQLModel):
    folder: str
    display_name: str = ""
    description: str = ""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Usage:
        with get_session() as session:
            session.add(obj)
            session.commit()

    The session is closed automatically on exit, even on exceptions.
    """
    session = Session(engine)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
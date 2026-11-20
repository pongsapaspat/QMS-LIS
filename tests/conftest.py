from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, Branch, LaboratoryDepartment


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        session.add(Branch(id=1, code="MAIN", name="Main Branch"))
        session.add(
            LaboratoryDepartment(
                id=1,
                code="GENERAL",
                name_th="ทั่วไป",
                name_en="General",
            )
        )
        session.commit()

    yield factory

    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    # Middleware opens sessions directly, outside FastAPI's dependency overrides.
    monkeypatch.setattr("app.main.SessionLocal", db_session_factory)

    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            try:
                yield session
            finally:
                session.rollback()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

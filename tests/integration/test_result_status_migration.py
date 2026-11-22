from importlib import import_module
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.result import Result, ResultStatus
from tests.integration.test_specimens import _alembic_config


@pytest.mark.integration
def test_result_status_migration_supports_every_workflow_state(tmp_path: Path) -> None:
    config = _alembic_config(f"sqlite:///{tmp_path / 'result-status.sqlite3'}")
    command.upgrade(config, "20261122_0025")
    engine = sa.create_engine(config.get_main_option("sqlalchemy.url"))

    def status_length() -> int:
        column = next(c for c in sa.inspect(engine).get_columns("results") if c["name"] == "status")
        return column["type"].length

    assert status_length() < len(ResultStatus.VERIFICATION_REJECTED)
    command.upgrade(config, "head")
    for status in ResultStatus:
        assert len(status) <= status_length()
        assert len(status) <= Result.__table__.c.status.type.length
    command.check(config)
    command.downgrade(config, "20261122_0025")
    assert status_length() == 20
    command.upgrade(config, "head")
    engine.dispose()


@pytest.mark.integration
def test_status_resize_preserves_rejection_and_refuses_lossy_downgrade() -> None:
    migration = import_module("migrations.versions.20261122_0026_result_status_length")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE results (id INTEGER PRIMARY KEY, status VARCHAR(20) NOT NULL, "
            "verification_rejection_reason TEXT)"
        ))
        connection.execute(sa.text(
            "INSERT INTO results VALUES (1, :status, :reason)"
        ), {"status": ResultStatus.VERIFICATION_REJECTED, "reason": "ชุดทดสอบหมดอายุ"})
        before = connection.execute(sa.text("SELECT * FROM results")).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text("SELECT * FROM results")).all() == before
            with pytest.raises(RuntimeError, match="values exceed 20 characters"):
                migration.downgrade()
            assert connection.execute(sa.text("SELECT * FROM results")).all() == before
            column = next(c for c in sa.inspect(connection).get_columns("results")
                          if c["name"] == "status")
            assert column["type"].length >= len(ResultStatus.VERIFICATION_REJECTED)
    engine.dispose()

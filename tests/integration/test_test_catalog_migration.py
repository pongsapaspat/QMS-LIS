from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError


def alembic_config(database_url: str) -> Config:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.mark.integration
def test_catalog_migration_upgrade_and_downgrade_preserve_audit_guards(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog-migration.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = alembic_config(database_url)
    engine = sa.create_engine(database_url)

    command.upgrade(config, "20261006_0004")
    command.upgrade(config, "head")
    command.check(config)

    inspector = sa.inspect(engine)
    assert {
        "test_categories",
        "specimen_types",
        "lab_tests",
        "test_reference_ranges",
        "qualitative_result_options",
        "test_price_history",
    }.issubset(set(inspector.get_table_names()))
    assert inspector.get_foreign_keys("audit_logs") == []
    assert "ix_audit_logs_entity" in {
        index["name"] for index in inspector.get_indexes("audit_logs")
    }

    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_logs
                    (event_type, entity_type, entity_id, changed_fields, reason,
                     actor_reference, occurred_at)
                VALUES
                    ('LAB_TEST_CREATED', 'lab_test', 999, '[]', 'migration test',
                     'test-runner', :occurred_at)
                """
            ),
            {"occurred_at": datetime.now(UTC)},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE audit_logs SET reason = 'changed' WHERE entity_id = 999")
        )

    engine.dispose()
    command.downgrade(config, "20261006_0004")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert "lab_tests" not in inspector.get_table_names()
    assert "ix_audit_logs_entity" not in {
        index["name"] for index in inspector.get_indexes("audit_logs")
    }
    foreign_keys = inspector.get_foreign_keys("audit_logs")
    assert foreign_keys[0]["referred_table"] == "patients"

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO patients
                    (hn, first_name_en, last_name_en, identity_document_missing, is_active)
                VALUES ('HN999999', 'Migration', 'Patient', 1, 1)
                """
            )
        )
        patient_id = connection.execute(
            sa.text("SELECT id FROM patients WHERE hn = 'HN999999'")
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_logs
                    (event_type, entity_type, entity_id, changed_fields, reason,
                     actor_reference, occurred_at)
                VALUES
                    ('PATIENT_CREATED', 'patient', :patient_id, '[]', 'migration test',
                     'test-runner', :occurred_at)
                """
            ),
            {"patient_id": patient_id, "occurred_at": datetime.now(UTC)},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE audit_logs SET reason = 'changed' WHERE entity_id = :id"),
            {"id": patient_id},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_logs
                    (event_type, entity_type, entity_id, changed_fields, reason,
                     actor_reference, occurred_at)
                VALUES
                    ('PATIENT_CREATED', 'patient', 123456, '[]', 'migration test',
                     'test-runner', :occurred_at)
                """
            ),
            {"occurred_at": datetime.now(UTC)},
        )
    engine.dispose()

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_specimens import _alembic_config


@pytest.mark.integration
def test_collection_room_migration_preserves_catalog_and_leaves_unknown_types_unassigned(tmp_path):
    config = _alembic_config(f"sqlite:///{tmp_path / 'collection-rooms.sqlite3'}")
    command.upgrade(config, "20261121_0024")
    engine = sa.create_engine(config.get_main_option("sqlalchemy.url"))
    expected = {
        "Li-heparinized Plasma": "BLOOD", "Serum": "BLOOD", "Urine": "URINE_STOOL",
        "Stool": "URINE_STOOL", "Swab": "SWAB", "Other specimen": None,
    }
    with engine.begin() as connection:
        for index, name in enumerate(expected, start=1):
            connection.execute(sa.text(
                "INSERT INTO specimen_types (code, name_th, name_en, is_active) "
                "VALUES (:code, :name, :name, :active)"
            ), {"code": f"S{index}", "name": name, "active": index != 4})
        before = [tuple(row) for row in connection.execute(sa.text(
            "SELECT id, code, name_th, name_en, is_active FROM specimen_types ORDER BY id"
        ))]
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert dict(connection.execute(sa.text(
            "SELECT name_en, collection_room FROM specimen_types"
        )).all()) == expected
    command.check(config)
    command.downgrade(config, "20261121_0024")
    with engine.connect() as connection:
        assert [tuple(row) for row in connection.execute(sa.text(
            "SELECT id, code, name_th, name_en, is_active FROM specimen_types ORDER BY id"
        ))] == before
    columns = {c["name"] for c in sa.inspect(engine).get_columns("specimen_types")}
    assert "collection_room" not in columns
    command.upgrade(config, "head")
    engine.dispose()

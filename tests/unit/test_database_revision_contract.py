from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from ai_fde.modules.runtime.readiness import EXPECTED_DATABASE_REVISION


def test_runtime_expected_database_revision_is_the_sole_alembic_head() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(repository_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [EXPECTED_DATABASE_REVISION]

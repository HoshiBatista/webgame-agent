"""PostgreSQL schema metadata tests that do not substitute SQLite."""

from prompt2play.models import Base, utc_now


def test_expected_postgresql_tables_are_declared() -> None:
    assert set(Base.metadata.tables) == {
        "analytics_events",
        "generation_runs",
        "model_invocations",
        "outbox_events",
        "projects",
        "revisions",
        "run_events",
    }
    assert utc_now().tzinfo is not None

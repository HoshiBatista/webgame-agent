"""PostgreSQL schema metadata tests that do not substitute SQLite."""

from prompt2play.models import Base, utc_now


def test_expected_postgresql_tables_are_declared() -> None:
    assert set(Base.metadata.tables) == {
        "analytics_events",
        "auth_sessions",
        "generation_runs",
        "game_feedback",
        "idempotency_records",
        "model_invocations",
        "outbox_events",
        "projects",
        "public_game_likes",
        "public_games",
        "users",
        "revisions",
        "run_events",
    }
    revision_digest = Base.metadata.tables["revisions"].c.artifact_digest
    assert revision_digest.unique is not True
    assert revision_digest.index is True
    assert "spec" in Base.metadata.tables["revisions"].c
    assert "forked_from_revision_id" in Base.metadata.tables["projects"].c
    assert "feedback_snapshot" in Base.metadata.tables["generation_runs"].c
    assert "archived" in Base.metadata.tables["projects"].c
    assert "lease_token" in Base.metadata.tables["generation_runs"].c
    assert "lease_expires_at" in Base.metadata.tables["generation_runs"].c
    assert "selection_version" in Base.metadata.tables["projects"].c
    assert "project_version" in Base.metadata.tables["generation_runs"].c
    assert utc_now().tzinfo is not None

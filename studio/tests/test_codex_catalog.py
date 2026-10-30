import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from generation.errors import GenerationError
from generation.providers import codex


def test_web_catalog_export_does_not_copy_credentials_or_account_metadata(tmp_path, monkeypatch):
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'auth.json').write_text('PRIVATE_AUTH')
    (private / 'models_cache.json').write_text(json.dumps({
        'account_id': 'PRIVATE_ACCOUNT',
        'models': [{'slug': 'gpt-6-sol', 'display_name': 'GPT-6 Sol',
                    'base_instructions': 'PRIVATE_INSTRUCTIONS', 'shell_type': 'unified_exec'},
                   {'slug': 'hidden-model', 'visibility': 'hide'}],
    }))
    monkeypatch.setenv('CODEX_HOME', str(private))
    public = tmp_path / 'public'
    public.mkdir()
    destination = public / 'models_cache.json'
    call_command('export_codex_catalog', output=str(destination))
    assert list(public.iterdir()) == [destination]
    assert destination.stat().st_mode & 0o777 == 0o600
    assert 'PRIVATE' not in destination.read_text()
    assert 'shell_type' not in destination.read_text()
    # Web process has a separate HOME with no credentials or full catalog.
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'web-home'))
    monkeypatch.setenv('GAMEFORGE_CODEX_CATALOG', str(destination))
    assert [item['id'] for item in codex.available_models()] == ['gpt-6-sol']
    with pytest.raises(GenerationError, match='Каталог Codex недоступен'):
        codex.sanitized_catalog(tmp_path)


def test_bad_source_does_not_replace_last_export(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    (tmp_path / 'models_cache.json').write_text('{"models": []}')
    destination = tmp_path / 'public.json'
    destination.write_text('old catalog')
    with pytest.raises(CommandError):
        call_command('export_codex_catalog', output=str(destination))
    assert destination.read_text() == 'old catalog'

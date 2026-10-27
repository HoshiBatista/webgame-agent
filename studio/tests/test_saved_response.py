import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from generation.providers.fake import fixture_response
from studio.models import Budget, Chat, Invocation, Outbox, Revision, Run, User
from studio.recovery import recover_saved_response
from studio.services import DomainError, reserve_invocation, settle_invocation
from studio.tasks import process_run, recover_expired


@override_settings(GAMEFORGE_PROVIDER="fake", GAMEFORGE_MODEL="fixture", GAMEFORGE_LEASE_SECONDS=100)
class SavedResponseTests(TestCase):
    def setUp(self):
        Budget.objects.create(pk=1, limit_usd=50)
        self.chat = Chat.objects.create(owner=User.objects.create_user(username="maker"))
        self.run = Run.objects.create(
            chat=self.chat, operation="create", prompt="Make a small game", provider="fake", model="fixture",
            status="failed", stage="failed", attempts=2, finished_at=timezone.now(),
            idempotency_key="original", request_fingerprint="original", error={"code": "invalid_schema"},
        )
        response = fixture_response()
        response["type"] = response.pop("status")
        response["scope_refusal"] = None
        for item in response["checks"]:
            item["title"] = ""
        self.raw = json.dumps(response)
        self.source = Invocation.objects.create(
            run=self.run, attempt=2, state="failed", request={"operation": "create", "base_revision": None,
                "generation_contract": {"pipeline_version": 9}},
            error={"code": "invalid_schema", "raw_response": self.raw},
            usage={"input_tokens": 12, "output_tokens": 34}, cost_usd=Decimal("0.1"),
            sent_at=timezone.now(), finished_at=timezone.now(), elapsed_seconds=42,
        )

    def check_run(self, ident, status):
        report = {"status": status, "findings": [] if status == "passed" else [{"code": "runtime_or_network", "errors": ["TypeError: saved game failed"]}],
                  "facts": [], "environment": {}, "elapsed_seconds": 0.1}
        with (patch("generation.service.generate") as model,
              patch("validation.service.validate", return_value=report),
              patch("studio.tasks.check_identity", return_value="saved-response-test")):
            process_run(ident)
            model.assert_not_called()
        return Run.objects.get(pk=ident)

    def test_dry_run_has_no_database_or_queue_effects(self):
        output = StringIO()
        call_command("recover_saved_response", str(self.source.id), stdout=output)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(Run.objects.count(), 1)
        self.assertFalse(Outbox.objects.exists())

    def test_recovery_preserves_saved_plan_and_strategy_without_replanning(self):
        from tests.test_generation_planning import plan_response

        self.run.game_plan = plan_response()["plan"]
        self.run.generation_strategy = "pro"
        self.run.save(update_fields=["game_plan", "generation_strategy"])
        recovered = recover_saved_response(self.source.id, apply=True)
        run = self.check_run(recovered["run_id"], "passed")
        self.assertEqual(run.game_plan, self.run.game_plan)
        self.assertEqual(run.generation_strategy, "pro")
        self.assertFalse(run.planning_required)
        self.assertFalse(run.allow_model_calls)

    def test_planner_receipt_cannot_be_materialized_as_game_sources(self):
        self.source.request["operation"] = "plan"
        self.source.save(update_fields=["request"])
        with self.assertRaises(DomainError) as caught:
            recover_saved_response(self.source.id, apply=True)
        self.assertEqual(caught.exception.code, "no_saved_candidate")
        self.assertFalse(self.chat.revisions.exists())

    def test_recovery_is_idempotent_preserves_receipt_and_checks_without_inference(self):
        result = recover_saved_response(self.source.id, apply=True)
        run = self.check_run(result["run_id"], "passed")
        self.assertEqual(run.status, "succeeded")
        self.assertFalse(run.allow_model_calls)
        self.assertEqual(run.metrics["model_calls"], 0)
        self.assertEqual(run.result_revision.files,
                         {item["path"]: item["content"] for item in fixture_response()["files"]})
        self.assertEqual(run.result_revision.checks, fixture_response()["checks"])
        self.source.refresh_from_db()
        self.assertEqual(self.source.error["raw_response"], self.raw)
        self.assertEqual(self.source.state, "failed")
        self.assertEqual(self.source.cost_usd, Decimal("0.1"))
        self.assertEqual(self.source.usage["output_tokens"], 34)
        self.assertEqual(Invocation.objects.count(), 1)
        again = recover_saved_response(self.source.id, apply=True)
        self.assertTrue(again["existing"])
        self.assertEqual(again["run_id"], str(run.id))
        self.assertEqual(self.chat.revisions.count(), 1)

    def test_failed_browser_check_cannot_trigger_model_even_after_worker_restart(self):
        result = recover_saved_response(self.source.id, apply=True)
        Run.objects.filter(pk=result["run_id"]).update(
            status="checking", lease_until=timezone.now() - timedelta(seconds=1))
        recover_expired()
        run = self.check_run(result["run_id"], "failed")
        self.assertEqual(run.status, "needs_attention")
        self.assertEqual(run.error["code"], "saved_response_validation")
        self.assertEqual(Invocation.objects.count(), 1)
        with self.assertRaises(DomainError):
            reserve_invocation(run, {})

    def test_unknown_cancelled_busy_or_changed_base_cannot_be_recovered(self):
        for state in ("unknown", "sent"):
            self.source.state = state
            self.source.save()
            with self.assertRaises(DomainError):
                recover_saved_response(self.source.id, apply=True)
        self.source.state = "failed"
        self.source.save()
        self.run.cancel_requested = True
        self.run.save()
        with self.assertRaises(DomainError):
            recover_saved_response(self.source.id, apply=True)
        self.run.cancel_requested = False
        self.run.status = "queued"
        self.run.save()
        with self.assertRaises(DomainError):
            recover_saved_response(self.source.id, apply=True)
        self.run.status = "failed"
        self.run.save()
        self.source.request["base_revision"] = str(self.run.id)
        self.source.save()
        with self.assertRaises(DomainError):
            recover_saved_response(self.source.id, apply=True)
        self.assertEqual(Run.objects.count(), 1)

    def test_successful_settlement_keeps_original_response_private(self):
        self.source.state = "sent"
        self.source.finished_at = None
        self.source.price = {"input": 0, "cached": 0, "output": 0}
        self.source.save()
        inv = settle_invocation(self.source.id, response=fixture_response(), raw_response=self.raw,
                                usage=self.source.usage)
        self.assertEqual(inv.state, "returned")
        self.assertEqual(inv.raw_response, self.raw)
        self.assertEqual(inv.response, fixture_response())
        self.assertIsNone(inv.error)

    def compact_source(self, operation):
        from tests.test_compact_generation import artifact

        game = artifact()
        game['title'] = 'Имя исходной игры'
        base = Revision.objects.create(chat=self.chat, number=1, **game)
        self.run.operation = operation
        self.run.model_profile = 'lite'
        self.run.generation_profile = 'compact'
        self.run.candidate_revision = base
        self.run.source_revision = base if operation == 'edit' else None
        self.run.save()
        self.source.request = {
            'operation': operation, 'base_revision': str(base.id), 'generation_profile': 'compact',
            'source_format': 'string', 'compact_manifest': base.compact_manifest,
            'generation_contract': {'pipeline_version': 9},
        }
        return base

    def test_compact_saved_edit_preserves_source_metadata_and_never_calls_model(self):
        base = self.compact_source('edit')
        self.source.raw_response = json.dumps({
            'type': 'ok', 'message': 'Только цвет', 'observations': [], 'probes': [],
            'edits': [{'old_text': "'#ffd84d'", 'new_text': "'#99bbff'"}],
        })
        self.source.save()
        result = recover_saved_response(self.source.id, apply=True)
        restored = Run.objects.get(pk=result['run_id'])
        candidate = restored.candidate_revision
        self.assertEqual(candidate.title, base.title)
        self.assertEqual(candidate.design, base.design)
        self.assertEqual(candidate.parent_id, base.id)
        self.assertEqual(restored.source_revision_id, base.id)
        self.assertEqual(restored.model_profile, self.run.model_profile)
        self.assertIsNone(restored.base_revision_id)
        self.assertFalse(restored.allow_model_calls)
        self.assertEqual(candidate.checks, base.checks)
        self.assertEqual(Invocation.objects.count(), 1)

    def test_compact_saved_module_repair_requires_fresh_basis_and_preserves_incomplete_checks(self):
        from generation.check_repair import checks_hash
        from generation.source_policy import module_policy

        base = self.compact_source('repair')
        base.checks = base.checks[:1]
        base.compact_manifest['probes'] = base.compact_manifest['probes'][:1]
        base.save(update_fields=['checks', 'compact_manifest'])
        basis = {'base_revision': str(base.id), 'artifact_hash': base.artifact_hash,
                 'checks_hash': checks_hash(base.checks), 'report_id': 17,
                 'report_identity': 'a' * 64, 'defects': ['runtime_or_network']}
        self.source.request.update(
            code_repair_basis=basis, module_repair=module_policy(base.files, [
                {'code': 'runtime_or_network', 'path': 'game.js', 'file_hash': base.file_hashes['game.js']},
            ]),
        )
        self.source.raw_response = json.dumps({
            'type': 'ok', 'message': 'Малый ремонт',
            'source': base.files['game.js'].replace("'#ffd84d'", "'#99bbff'"),
        })
        self.source.save()
        with patch('studio.check_repair.code_repair_basis', return_value=None):
            with self.assertRaises(DomainError) as error:
                recover_saved_response(self.source.id, apply=True)
        self.assertEqual(error.exception.code, 'stale_code_repair_basis')
        self.assertEqual(Run.objects.count(), 1)
        with patch('studio.check_repair.code_repair_basis', return_value=basis):
            result = recover_saved_response(self.source.id, apply=True)
        restored = Run.objects.get(pk=result['run_id'])
        self.assertEqual(restored.candidate_revision.checks, base.checks)
        self.assertEqual(restored.candidate_revision.title, base.title)
        self.assertEqual(restored.candidate_revision.design, base.design)
        self.assertFalse(restored.allow_model_calls)
        self.assertEqual(Invocation.objects.count(), 1)

    def test_compact_saved_refusal_is_not_materialized_as_a_game(self):
        self.compact_source('edit')
        self.source.raw_response = json.dumps({
            'type': 'scope_refusal', 'message': 'Нужен более узкий запрос',
            'observations': [], 'probes': [], 'edits': [],
        })
        self.source.save()
        with self.assertRaises(DomainError) as error:
            recover_saved_response(self.source.id, apply=True)
        self.assertEqual(error.exception.code, 'no_saved_candidate')
        self.assertEqual(Run.objects.count(), 1)
        self.assertEqual(Invocation.objects.count(), 1)

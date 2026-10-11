import threading
import unittest
from unittest.mock import Mock
import httpx
from prompt2play.legacy.worker.transport import Coordinator, CoordinatorUnavailable, Lease
from prompt2play.legacy.worker.core import Cancelled, LeaseLost
from prompt2play.legacy.worker.__main__ import claim_when_available


class TransportTests(unittest.TestCase):
    def test_claim_omits_optional_blank_name(self):
        seen = []

        def handler(req):
            import json

            seen.append(json.loads(req.content))
            return httpx.Response(200, json={"job": None})

        client = httpx.Client(
            base_url="https://example.test/", transport=httpx.MockTransport(handler)
        )
        Coordinator("https://example.test", "test", client=client).claim({"providers": ["codex"]})
        self.assertNotIn("name", seen[0])

    def test_idle_claim_retries_transport_and_503_but_not_auth(self):
        coord = Mock()
        coord.claim.side_effect = [
            httpx.ConnectError("offline"),
            CoordinatorUnavailable("503"),
            {"job": None},
        ]
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        self.assertEqual(claim_when_available(coord, {}, "test", stop), {"job": None})
        self.assertEqual([c.args[0] for c in stop.wait.call_args_list], [1, 2])
        coord.claim.side_effect = LeaseLost("401")
        stop.reset_mock()
        with self.assertRaises(LeaseLost):
            claim_when_available(coord, {}, "test", stop)
        stop.wait.assert_not_called()

    def test_idle_claim_backoff_capped_and_interruptible(self):
        coord = Mock()
        coord.claim.side_effect = httpx.ConnectError("offline")
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = [False] * 7 + [True]
        with self.assertRaises(Cancelled):
            claim_when_available(coord, {}, "test", stop)
        self.assertEqual(
            [c.args[0] for c in stop.wait.call_args_list], [1, 2, 4, 8, 16, 30, 30, 30]
        )

    def test_every_write_carries_exact_lease(self):
        seen = []

        def handler(req):
            import json

            seen.append((str(req.url), json.loads(req.content)))
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(
            base_url="https://example.test/", transport=httpx.MockTransport(handler)
        )
        coord = Coordinator("https://example.test", "test", client=client)
        lease = Lease(
            coord,
            {"job": {"id": "job-id"}, "lease_token": "fresh-lease", "lease_seconds": 120},
            threading.Event(),
        )
        for action in ("heartbeat", "events", "checkpoint", "complete", "fail"):
            lease.write(action)
        self.assertTrue(all(body["lease_token"] == "fresh-lease" for _, body in seen))
        self.assertEqual(len(seen), 5)

    def test_stale_lease_sets_cancel_and_prevents_more_writes(self):
        seen = []

        def handler(req):
            seen.append(req)
            return httpx.Response(409, json={"error": "stale lease"})

        client = httpx.Client(
            base_url="https://example.test/", transport=httpx.MockTransport(handler)
        )
        cancel = threading.Event()
        coord = Coordinator("https://example.test", "test", client=client)
        with self.assertRaises(LeaseLost):
            coord.post("api/worker/jobs/job/complete/", {}, cancel)
        self.assertTrue(cancel.is_set())
        with self.assertRaises(Cancelled):
            coord.post("api/worker/jobs/job/fail/", {}, cancel)
        self.assertEqual(len(seen), 1)

    def test_remote_plain_http_requires_explicit_override(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            Coordinator("http://remote.test", "test")


if __name__ == "__main__":
    unittest.main()

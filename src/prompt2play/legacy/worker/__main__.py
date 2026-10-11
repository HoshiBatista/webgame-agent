from __future__ import annotations
import argparse
import getpass
import math
import os
import signal
import threading
import httpx
from .core import Cancelled, BudgetExceeded, ProviderError
from .providers import CodexProvider, OpenAIProvider
from .pipeline import Pipeline
from .transport import Coordinator, CoordinatorUnavailable, Lease


def claim_when_available(coordinator, capabilities, name, stop):
    """Retry only idle polling, never provider work or a fenced job write.

    A lost claim response may have acquired a lease: a later claim must rely on
    coordinator lease expiry/recovery, rather than replaying any model request.
    """
    delay = 1
    while not stop.is_set():
        try:
            return coordinator.claim(capabilities, name)
        except (httpx.TransportError, CoordinatorUnavailable):
            print(
                f"Coordinator temporarily unavailable; retrying idle claim in {delay}s", flush=True
            )
            if stop.wait(delay):
                break
            delay = min(delay * 2, 30)
    raise Cancelled("Runner stopped while waiting for coordinator")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a local Game Forge generation worker; credentials stay on this machine"
    )
    parser.add_argument("--server", default=os.environ.get("FORGE_SERVER", "http://127.0.0.1:8000"))
    parser.add_argument(
        "--provider",
        choices=["codex", "openai"],
        action="append",
        help="Repeat to advertise both providers",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Optional runner display-name override; otherwise preserve its server name",
    )
    parser.add_argument("--once", action="store_true", help="Claim at most one job and exit")
    parser.add_argument("--poll", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--validator", choices=["static", "docker"], default="static")
    parser.add_argument("--validator-image", default="game-forge-validator:local")
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="Development only: allow bearer token over remote plain HTTP",
    )
    args = parser.parse_args(argv)
    if any(not math.isfinite(value) or value <= 0 for value in (args.timeout, args.poll)):
        parser.error("--timeout and --poll must be finite positive numbers")
    token = os.environ.get("FORGE_RUNNER_TOKEN") or getpass.getpass("Runner token (hidden): ")
    if not token:
        parser.error("Runner token is required")
    providers = {
        name: (
            CodexProvider(timeout=args.timeout)
            if name == "codex"
            else OpenAIProvider(timeout=args.timeout)
        )
        for name in (args.provider or ["codex"])
    }
    try:
        for provider in providers.values():
            provider.preflight()
    except ProviderError as exc:
        parser.error(str(exc))
    capabilities = {
        "providers": list(providers),
        "model": next(iter(providers.values())).model if len(providers) == 1 else "",
        "validator": args.validator,
    }
    if "openai" in providers and not providers["openai"].model:
        capabilities["requires_job_model"] = ["openai"]
    stop = threading.Event()
    current = [None]

    def shutdown(*_):
        stop.set()
        if current[0] is not None:
            current[0].set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    coordinator = Coordinator(args.server, token, allow_http=args.allow_http)
    exit_code = 0
    try:
        while not stop.is_set():
            claim = claim_when_available(coordinator, capabilities, args.name, stop)
            if not claim.get("job"):
                if args.once:
                    break
                stop.wait(max(0.5, args.poll))
                continue
            job = claim["job"]
            cancel = threading.Event()
            current[0] = cancel
            pipeline = None
            print(f"Claimed job {job['id']} ({job['provider']})", flush=True)
            with Lease(coordinator, claim, cancel) as lease:
                try:
                    pipeline = Pipeline(
                        job,
                        providers[job["provider"]],
                        base_version=claim.get("base_version"),
                        checkpoint=claim.get("checkpoint"),
                        cancel=cancel,
                        persist=lambda cp, usage: lease.write(
                            "checkpoint", checkpoint=cp, usage=usage
                        ),
                        event=lambda **event: lease.write("events", **event),
                        runtime=args.validator == "docker",
                        validator_image=args.validator_image,
                    )
                    result = pipeline.run()
                    lease.write("complete", **result)
                    print(f"Completed {job['id']} ({result['validation']['status']})", flush=True)
                except Cancelled:
                    # Never write fail/complete with a cancelled or stale lease.
                    print("Job stopped: cancellation, shutdown or lease loss", flush=True)
                except Exception as exc:
                    exit_code = 1
                    message = (
                        str(exc)
                        if isinstance(exc, (ProviderError, BudgetExceeded, ValueError))
                        else "Worker operation failed; inspect runner configuration and coordinator connectivity"
                    )
                    message = message[:1500]
                    usage = dict(pipeline.budget.usage) if pipeline else None
                    if pipeline and pipeline.budget.uncertain:
                        message += "; interrupted usage is unknown and reserved conservatively"
                    try:
                        if not cancel.is_set():
                            # Constructor rejection must not erase saved usage from
                            # an incompatible/legacy checkpoint already on the server.
                            payload = {"error": message}
                            if usage is not None:
                                payload["usage"] = usage
                            lease.write("fail", **payload)
                    except Exception:
                        pass
                    print(f"Failed {job['id']}: {message}", flush=True)
            current[0] = None
            if args.once:
                break
    except (Cancelled, httpx.HTTPError, RuntimeError, ValueError) as exc:
        print("Runner stopped: " + str(exc)[:500], flush=True)
        exit_code = 1
    finally:
        coordinator.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

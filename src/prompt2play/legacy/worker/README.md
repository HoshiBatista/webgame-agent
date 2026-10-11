# Local generation worker

Run from the repository root with the worker dependencies installed:

```sh
python -m worker --server http://127.0.0.1:8000 --provider codex
# or, with OPENAI_API_KEY and an available OPENAI_MODEL on this machine:
python -m worker --server https://forge.example --provider openai
```

The CLI reads `FORGE_RUNNER_TOKEN`, otherwise requests it without echo. Codex uses
its existing local login; this code never opens or copies Codex credential files.
The child receives a narrow system-environment allowlist, not coordinator/Django
or other provider secrets. It uses an isolated temporary working directory,
read-only sandbox, stdin prompts, structured output files and argv without a shell.
Fixed Codex configuration disables the shell tool and web search: this adapter
needs only structured text. It does not rewrite local MCP or approval settings.
No automatic approval bypass is used. A local runner still trusts its installed
Codex configuration and plugins; do not treat its read-only sandbox as a general
isolation mechanism for unrelated untrusted software.

`--once` processes at most one claim. Repeat `--provider` to advertise both
providers. `--timeout` bounds calls; SIGINT cancels local work and lets the lease
expire so another runner can resume. A coordinator cancellation/revocation/409
fences the current worker; it cannot write a completion or failure afterwards.
Remote coordinator URLs require HTTPS unless explicitly overridden for development.
The CLI checks that Codex exists / the OpenAI key is configured before claiming
work. It cannot establish that a login/key/model is valid without a real provider
call. OpenAI runners without a default `OPENAI_MODEL` advertise
`requires_job_model=["openai"]`; the coordinator gives them only jobs with an
explicit model. An omitted `--name` preserves the name created in the studio.

The real LangGraph performs plan, four parallel component authors, assembly,
syntax/static checks, independent model review and bounded selective repair.
The coordinator checkpoint stores completed components and phases after success;
restart reuses them. A revision preserves every unselected source byte. Legacy
reference versions are read-only and cannot enter the revision path. Recorded
examples stay in a separate regression corpus; source fragments are not inserted
as genre templates. Checkpoints bind prompts, JSON schemas, generator/validator
implementation, provider, output allowances and
resolved explicit model. A saved explicit model is reused on another runner even
if that runner's environment has a different default. Changed prompt contracts
or output allowances reject the checkpoint transparently and require a new job;
they do not reset its recorded usage. Older checkpoints lacking these fields are
also rejected explicitly. For resumable Codex jobs, set `CODEX_MODEL` or select
the model in the studio: a local implicit CLI model cannot be reliably pinned
and a partial checkpoint using it cannot safely resume. Completed published
versions remain available independently of job recovery.
Published `spec.generation` exposes the same model/provider/contract fingerprint
and output allowances for inspection, without credentials.

Focused revisions must select at least one module and preserve shared schemas.
A schema change requires selecting all dependent modules; otherwise planning
fails before any source is replaced. Changed validation mode invalidates the
cached model review so the reviewer sees the new evidence.

Token budget is a conservative launch/admission limit, **not a financial hard cap**.
UTF-8 prompt size plus output allowance is reserved for all authors before fan-out.
Actual reported input/cached/output usage is reconciled; cached input still counts
as input. Interrupted/unknown calls retain their reservation across restart.
Reported usage is retained even when structured output is invalid or a terminal
provider response is incomplete/refused. Explicit HTTP rejection before an
answer does not invent unknown token spend. Responses streaming has one wall
deadline and interruptible I/O; a reasoning pause is not limited to ten seconds.
Only explicit 429 throttling is retried automatically. Ambiguous server/network
failures are not replayed and retain their reservation as unknown spend.
Per-call output allowances are configurable in the runner environment (or
`.env.worker` when using `python3 forge.py worker`):

```dotenv
FORGE_CODE_OUTPUT_TOKENS=16000
FORGE_UI_OUTPUT_TOKENS=32000
FORGE_PLAN_OUTPUT_TOKENS=10000
FORGE_REVIEW_OUTPUT_TOKENS=6000
```

The UI default is 32000 because it owns CSS/markup and interaction code. An explicit
FORGE_CODE_OUTPUT_TOKENS also applies to UI unless the UI-specific override is set.
Each must be an integer from 1000 through 64000. These are separate from the
overall job budget: increasing the job budget in the studio does not change a call's output
allowance. The Responses API receives the configured `max_output_tokens`, which
includes reasoning tokens on models that use them. Reserve enough room for both
reasoning and the complete source. All reservations use these same allowances.
Codex does not offer a documented portable hard output-token flag; usage may
exceed a reservation. No new calls launch after the budget rejects admission.
Usage counters show reported tokens only, never invented charges or guaranteed
ChatGPT subscription allowance. Prefix stability and cache keys can enable cache
reuse but do not guarantee hits or a particular price.
For Responses, frozen general/role text is sent as `instructions`, and the frozen
specification followed by changing source/evidence is sent as `input`. Codex receives
the same separated sections in one stdin prompt. Source and review text are task
data, never authorization to access files or override interfaces.

Generated JavaScript is never host-executed. `node --check` parses syntax only.
Default validation is honestly `partial`: runtime, audio and mobile checks are
skipped. To opt in, explicitly build the trusted Docker image from `validator/`,
then run `--validator docker`. The container has no network, a read-only root and
input mount, no added capabilities, no host Docker socket, capped CPU/RAM/PIDs and
a timeout. It executes bounded, game-specific declarative scenarios on desktop and
mobile viewports as well as generic probes. This is not Android/iOS WebView certification
or a subjective evaluation of fun, animation and music. The optional container
was not built or executed in the managed development environment.

Tests (fixture provider exists only under `worker/tests`, unavailable in CLI/UI):

```sh
python -m unittest discover -s worker/tests -t . -v
```

Tests cover real LangGraph flow, focused repair, byte-preserving revision,
checkpoint resume, cancellation, reservation gates, strict provider parsing,
Responses stream usage, safe Codex argv/stdin/environment and lease fencing.
They use model and coordinator doubles; live provider quality remains unevaluated.

The v3 semantic plan and QA language are described in `prompts/plan.txt` and
`docs/UNIVERSAL_GENERATION_RU.md`. Reports bind exact source/specification/HTML
bytes; a checkpoint cannot reuse validation for another artifact. Per-call hashes,
actual provider usage and compact iterations are exported in validation.provenance;
the full bounded intermediate source history remains in the checkpoint.


V3 adds explicit state lifetimes, atomic transitions, objective sources/unlocks,
conditional persistence, and a first playable loop. Planned evidence is checked
before parallel author calls: transaction observations follow repeated commands;
restore observations use prior captures from the saved domains, with a genuine
pre-restore divergence so a no-op importer cannot pass. Actual execution remains
a separate check. Missing/unused storage faults fail rather than silently pass.

Shared changes on a revision include real neighboring source even before the first
review. Equivalent JSON formatting does not expand the context. V2 game revisions
require one coordinated four-module upgrade, while historic versions stay readable.
The API cache-key namespace is game-forge-v3-<role>; prefix reuse is conditional
on actual provider behavior and is reported, never fabricated.

# Prompt2Play MVP Capacity Plan

## Status and interpretation

This document turns the target architecture into an initial capacity envelope
for an MVP that supports **10 simultaneous active generation runs**. It assumes
all 10 users may submit within one second, keep an SSE stream open, generate a
game, validate it, and receive at most two bounded repair attempts.

Ten users who only browse projects are a much lighter workload. Conversely,
"10 concurrent" does not define daily retention volume or model-provider
quotas by itself. Those are calculated from completion rate, artifact size, and
the selected provider. All numbers below are starting hypotheses and release
gates, not measurements. Replace them with observed distributions from the
golden suite and load tests before production.

## Service objectives

The MVP capacity target is valid only while all of these objectives hold:

| SLI | MVP objective |
| --- | --- |
| Active generation runs | 10 admitted; additional work is queued or rejected explicitly |
| Run admission latency | p95 below 250 ms; p99 below 1 s |
| Time to first persisted progress event | p95 below 2 s |
| End-to-end generation latency | p50 below 180 s; p95 below 300 s |
| Absolute run deadline | 480 s, including repair and validation |
| Model-queue wait | p95 below 10 s |
| Validation-queue wait | p95 below 60 s |
| SSE event delivery after commit | p95 below 1 s |
| Infrastructure completion rate | at least 99%, excluding policy rejection and game-quality failure |
| Playable rate after bounded repair | at least 80% on the fixed golden suite |
| Stale or duplicate revision promoted | zero |

The latency objectives assume the model provider normally answers an invocation
within 15 seconds and its p95 stays below 30 seconds. Provider degradation must
trigger admission backpressure; local workers cannot compensate for an
arbitrarily slow or rate-limited upstream.

## Workload assumptions

The initial average model is deliberately explicit so it can be corrected with
telemetry:

| Operation per run | Expected calls | Input tokens per call | Output tokens per call | Mean service time |
| --- | ---: | ---: | ---: | ---: |
| Specification | 1.0 | 3,000 | 1,000 | 8 s |
| Planning | 1.0 | 4,000 | 1,500 | 8 s |
| Initial generation harness | 5.0 | 10,000 | 1,500 | 15 s |
| Repair harness, 40% × 3 calls | 1.2 | 12,000 | 1,000 | 15 s |
| **Expected total** | **8.2** | **71,400 per run** | **11,200 per run** | **109 model-seconds** |

The validation model assumes one initial validation, a first repair on 40% of
runs, and a second repair on 10% of runs: **1.5 browser validations per run**.
A browser validation averages 25 seconds, has a p95 of 40 seconds, and has a
hard deadline of 60 seconds.

The artifact model assumes an average retained footprint of 30 MiB per completed
run. The hard envelope is three 5 MiB revisions plus three 25 MiB evidence sets,
rounded to **100 MiB per run** including private metadata. These limits are
enforced independently of available disk space.

## Throughput calculation

Use Little's Law for a closed population of 10 users that immediately starts a
new run after the previous one completes:

```text
arrival rate = active runs / mean run duration
             = 10 / 180 seconds
             = 0.0556 runs/second
             = 3.33 runs/minute
```

This is the sustained upper bound implied by the latency target. The API must
also handle the separate cold burst of 10 admissions in one second.

### API, SSE, and preview traffic

| Surface | Derived load | Capacity target |
| --- | ---: | ---: |
| Run-creation writes | 10 requests in the first second | 20 write RPS |
| Authenticated dynamic API | normally below 5 RPS | 50 mixed RPS |
| SSE streams | 10 open connections, capped at 2 events/s/run | 10 connections and 50 events/s |
| Preview static requests | 10 users × 20 files / 2 s | 150 static RPS |
| Artifact delivery | 10 × 5 MiB / 5 s | 20 MiB/s |

The API emits coarse persisted progress, not model tokens or every internal tool
event. Preview files are served by the isolated preview server, not FastAPI.
SSE replaces status polling; clients reconnect with the last event ID and apply
exponential backoff.

### Model-provider capacity

At 3.33 completed runs per minute:

```text
requests/minute     = 3.33 × 8.2             = 27.3 RPM
input tokens/minute = 3.33 × 71,400          = 238,000 input TPM
output tokens/minute= 3.33 × 11,200          = 37,300 output TPM
concurrent calls    ≈ 0.0556 × 8.2 × 15      = 6.8
```

With approximately 50% headroom and rounding for synchronized bursts, the
selected provider account and model policy must support at least:

- **45 requests per minute**;
- **400,000 input tokens per minute**;
- **60,000 output tokens per minute**; and
- **12 simultaneous provider requests**.

Providers count cached tokens and quota windows differently, so admission uses
locally measured raw and billable-token buckets rather than assuming one vendor
formula. If the available quota is lower, reduce active-run admission from 10;
do not let Celery accumulate an unbounded model queue.

The estimated cost of one run is always computed from the configured model
policy:

```text
run cost = Σ(input tokens × input price
           + cached tokens × cached-input price
           + output tokens × output price
           + per-call or tool charges)
```

No dollar value belongs in the architecture until a provider and model are
selected. Admission checks both a per-run cost ceiling and the remaining
account-wide hourly and daily budgets.

### Browser-validation capacity

```text
validation arrivals = 0.0556 × 1.5 = 0.0833 jobs/second = 5 jobs/minute
occupied slots       = 0.0833 × 25 = 2.08 browser slots
```

Four slots provide normal steady-state headroom. The MVP provisions **five
isolated browser slots** so a synchronized burst of 10 p95-duration validations
drains in two 40-second waves. The last jobs wait about 40 seconds and complete
in about 80 seconds, within the queue and end-to-end objectives.

Start with a reservation of 1 vCPU and 768 MiB per sandbox. Five slots therefore
reserve 5 vCPU and 3.75 GiB before runner overhead. Actual CPU, RSS, file output,
and duration distributions decide whether these reservations can be reduced.

### Celery, PostgreSQL, Redis, and filesystem

An average run is expected to dispatch about 13 stage tasks and execute about
70 short database transactions, including model-invocation reservation and
completion:

```text
Celery deliveries = 3.33 × 13 / 60 = 0.72 tasks/second
database writes   = 3.33 × 70 / 60 = 3.89 transactions/second
artifact writes   = 3.33 × 30 / 60 = 1.67 MiB/second on average
```

Burst and fault-recovery targets are intentionally much higher:

| Resource | MVP target |
| --- | --- |
| Celery model worker slots | 10 active attempts; provider allowance 12 |
| Celery workflow worker slots | 2 |
| Celery validation slots | 5 isolated runners |
| Celery asset worker slots | 2 when generated assets are enabled |
| Celery maintenance worker slots | 1 plus one Beat scheduler |
| Broker delivery | 25 task messages/s burst |
| Redis operations | 500 operations/s burst, `noeviction` |
| PostgreSQL writes | 50 short transactions/s burst |
| PostgreSQL connections | application budget 40; server maximum at least 60 |
| Artifact filesystem | 20 MiB/s delivery and 10 MiB/s durable writes |

Workers claim and commit with short database transactions. They never hold a
database connection while waiting for a model, browser, asset provider, or
filesystem copy. Per-process connection pools must fit within the global
40-connection budget; use a small pool or PgBouncer before increasing worker
process count.

A reasonable single-node Phase 1 starting point is **8 vCPU, 16 GiB RAM, and
fast local SSD/NVMe**, with the validation processes isolated from control-plane
credentials. This is a provisioning hypothesis, not a substitute for the load
test. Production may move browser runners to a separate host without changing
the capacity model.

Concurrency alone cannot size retained storage. Use:

```text
required storage = completed runs/day × retained MiB/run × retention days
                   × replication/snapshot factor × safety factor
```

For example, 100 completed runs/day × 30 MiB × 30 days is 90 GiB before
snapshots and headroom. A 150 GiB volume is a reasonable starting point for that
specific business-volume assumption. The hard 100 MiB/run envelope would need
300 GiB for the same retention period before snapshots.

## Harness guardrails

These are starting limits for the first implementation. They are versioned
policy values, not constants embedded in domain code.

| Mode | Model turns | Tool calls | Quick checks | Wall time | Input tokens | Output tokens | Changed files |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Initial generation | 8 | 24 | 3 | 180 s | 80,000 | 16,000 | 30 |
| Local repair | 4 | 12 | 2 | 90 s | 40,000 | 8,000 | 5 |
| Structural repair or regenerate | 6 | 20 | 3 | 150 s | 60,000 | 12,000 | 20 |

The complete run, including specification, planning, initial generation, and at
most two semantic repairs, has hard ceilings of:

- 22 model invocations;
- 64 harness tool calls;
- 9 quick-check executions;
- 200,000 input and 36,000 output tokens;
- three candidate revisions;
- 100 MiB of retained artifacts and evidence; and
- 480 seconds wall-clock time.

Attempt limits do not add independently beyond the run ceiling. A fallback
model consumes the same run budget. Context utilization should remain below 70%
of the selected model's usable window at p95, leaving space for output and tool
results. Budget exhaustion produces a typed result and never silently extends a
run.

## Required metrics

### API and workflow

- `prompt2play.runs.active` gauge, split only by coarse workflow state;
- admitted, queued, rejected, cancelled, expired, succeeded, and failed run
  counters;
- admission, stage, queue-wait, end-to-end, and SSE-delivery histograms;
- Celery queue depth and oldest-message age per queue;
- stage lease renewal, expiration, redelivery, and stale-fence rejection
  counters;
- PostgreSQL transaction latency, pool usage, lock wait, and outbox age; and
- Redis memory, eviction, reconnect, command latency, and broker redelivery.

### Model gateway and generation harness

- attempts and duration by mode, terminal status, template profile, and model
  policy;
- model invocations, provider latency, time to first token, tokens/second, raw
  and billable input/output/cache tokens, estimated cost, retry, timeout, and
  rate-limit counters;
- current provider-request concurrency plus RPM and TPM bucket utilization;
- turns, tool calls, quick checks, files and bytes changed, and context-window
  utilization per attempt;
- repeated identical tool calls, no-op patches, unchanged findings, progress
  stalls, invalid tool arguments, and policy-denied operations;
- candidate submission rate, quick-check pass rate, release static pass rate,
  and first-pass playable rate;
- budget-exhausted attempts by the dimension that stopped them;
- reserved invocations recovered from cache, abandoned invocations, duplicate
  provider spend, and stale responses rejected by fencing; and
- repair yield, repair strategy, repeated-finding rate, and incremental cost per
  successful repair.

### Validation and storage

- browser queue time, boot time, scenario time, total duration, CPU, peak RSS,
  evidence bytes, timeout, crash, and sandbox-policy violation;
- validation count and pass rate by stable finding code, template, viewport, and
  validator version;
- artifact commit duration, pending-intent age, reconciliation result, bytes,
  files, inodes, and digest deduplication ratio; and
- filesystem free bytes/inodes, staging age, garbage-collection volume, backup
  age, and restore-test status.

Metrics must not use run, project, user, prompt, file path, or provider request
ID as labels. Those high-cardinality identifiers belong in traces and structured
logs. Prompts, source code, screenshots, and model responses are not telemetry
attributes.

## Alerts and backpressure

Initial operational thresholds:

- reject or queue new generation when 10 runs are active;
- stop admission when model-queue oldest age exceeds 30 seconds or its depth
  exceeds 10 for one minute;
- stop admission when validation-queue oldest age exceeds 60 seconds or depth
  exceeds 10;
- reduce admission when provider RPM or TPM utilization exceeds 80% for five
  minutes;
- alert when provider rate-limit responses exceed 1%, abandoned/duplicate spend
  exceeds 1% of model cost, or model p95 exceeds 30 seconds;
- alert when PostgreSQL pool usage exceeds 80%, outbox age exceeds 10 seconds,
  or any pending artifact commit exceeds two minutes;
- alert on any Redis eviction, stale worker commit acceptance, public/private
  artifact boundary violation, or failed restore test; and
- preserve API reads, cancellation, and status streams while generation
  admission is throttled.

Admission returns a stable error code and `Retry-After`; it never accepts work
that cannot fit within configured queue, token, cost, validation, storage, or
provider limits.

## Load-test release gates

The MVP is not considered capable of 10 concurrent users until all scenarios
pass against production-like limits:

1. **API burst:** submit 10 idempotent runs in one second while sustaining 50
   mixed API RPS for five minutes and 10 SSE streams.
2. **Closed-loop workflow:** keep 10 runs active for 30 minutes with a fake model
   that reproduces the latency and token distributions above.
3. **Provider quotas:** emulate 45 RPM, 400k input TPM, 60k output TPM, latency,
   429 responses, and `Retry-After`; verify bounded queues and token buckets.
4. **Validation burst:** release 10 browser jobs together; with five slots, all
   complete within 90 seconds and no sandbox exceeds its resource limit.
5. **Worst-case budgets:** run 10 workflows to the 22-call ceiling; every run
   terminates within 480 seconds without crossing token, cost, or artifact caps.
6. **Redelivery:** kill workers after provider response, candidate submission,
   filesystem rename, and database commit; only the current fence can finalize
   a revision and duplicate spend is measured.
7. **Cancellation:** cancel all 10 runs at different stages; no new expensive
   operation starts afterward and capacity is reclaimed within its deadline.
8. **Backpressure:** slow the provider and browser runners until thresholds are
   crossed; new generation is rejected or queued while reads and cancellation
   stay healthy.
9. **Storage recovery:** fill bytes and inodes independently, leave pending
   commits and expired staging workspaces, restore a backup, and verify that no
   referenced object is collected.

Publish p50, p95, and p99 results, throughput, error counts, queue ages, resource
peaks, tokens, and cost per successful run as a versioned capacity report. A
single successful burst without these distributions is not evidence of
capacity.

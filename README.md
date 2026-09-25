# Perry the Platypus

Perry is a small, **synthetic-only** alert pipeline built to show how to test and release a
platform service. It is inspired by an SDET/platform engineering role, not a clone of
ScienceLogic or a production incident detector.

```text
synthetic POST /events → CPU/error safety rules → Zen Jev Choice (alert|ignore)
                  → SQLite decision → GET /decisions/{event_id}
                  → approved event only → Apprise → ntfy + Telegram
```

**Current evidence:** local pytest/BDD, HTTP-contract fakes, a built-image smoke with fake
Jev and fake Apprise, and a dependency audit. The initial public GitHub Actions run
[passed](https://github.com/kavishwar-khankari/perry-the-platypus/actions/runs/36124340896),
including the built-image smoke and candidate-image publication. The protected real-Jev
contract check
[ran and passed](https://github.com/kavishwar-khankari/perry-the-platypus/actions/runs/36127778732)
on 2026-09-25 (model `jev-1.13-free`, one invented event, no notification). Perry has
**not** called real Apprise, sent a phone alert, deployed to Kubernetes, run a load gate,
or validated a rollback yet. Update this paragraph only when checks actually run.

## One exact scenario

Submit to Perry (not directly to Zen):

```json
{
  "event_id": "demo-001",
  "source": "synthetic",
  "node": "demo-web-1",
  "cpu_samples_percent": [94, 95, 96, 97, 96, 98],
  "sample_interval_seconds": 60,
  "http_error_percent": 8,
  "maintenance": false
}
```

Perry calculates 96% CPU over 360 seconds. It calls Jev only when CPU averages at
least 90% over at least 300 seconds, HTTP errors are at least 5%, maintenance is off,
and the event ID is the single authorized notification ID. Jev receives these **invented,
structured fields** and one predefined Choice question. A valid `alert` response with
confidence at least 0.7 lets Perry request a notification; `ignore`, malformed output,
timeout, an unexpected model ID, or a failed safety rule cannot send one. The confidence
is a decision statistic, **not** the probability an incident is real. The SQLite record
distinguishes `alert` (Apprise accepted an HTTP request) from actual phone delivery.

An identical event ID is read-only on replay; reusing it for different data yields HTTP
409. The other read endpoint is `GET /decisions/{event_id}`; `/healthz` checks the DB,
and `/metrics` exposes low-cardinality Prometheus counters and timing.

## Run fast, without a key or a homelab

```bash
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run ty check src
uv run pytest -q
docker build -t perry:local .
bash scripts/smoke-image.sh perry:local
```

The built-image smoke starts temporary fake Jev and fake Apprise HTTP endpoints on the
**local Linux machine**, sends one positive and one must-not-alert event, reads the saved
decision, checks deduplication, then removes its container. It never sends a phone alert.

`tests/features/decision.feature` contains the human-readable Given/When/Then journeys.
Fast tests exercise the API and SQLite; `tests/test_providers.py` verifies the outgoing
HTTP request shapes without any real network call.

## Check real Jev separately

The owner has already verified that their key can call
`https://opencode.ai/zen/v1/systemone` with model `jev-1.13-free`, and Perry's own
contract check has run the same way: the manually dispatched workflow passed on 2026-09-25.
To re-run it, place `PERRY_ZEN_API_KEY` in your **local environment** or the protected
GitHub `jev-contract` environment and run `uv run python scripts/check_zen.py` (or manually
dispatch the corresponding workflow). It sends exactly one small invented event and
**cannot notify Apprise**. Add required reviewers to the `jev-contract` environment so the
real call stays manually gated. Do not paste the key into an issue, file, or command
argument. Free-model availability and provider behavior may change. A successful contract
call checks protocol/authorization, not Jev's accuracy on real incidents.

To run the full app, use `uv run uvicorn perry.app:app --host 127.0.0.1 --port 8000`.
By default it has no configured key or notifier and authorizes **no event IDs**. To make
one manual, explicitly approved phone check, configure `PERRY_ZEN_API_KEY`,
`PERRY_APPRISE_URL` (the existing Apprise `/notify/global` URL), and
`PERRY_APPROVED_EVENT_ID` (the exact synthetic ID). Do so only after verifying the
destination; merely starting Perry never sends a message. Do not expose `/events` as a
public unauthenticated endpoint.

Other settings: `PERRY_DB_PATH` (SQLite path), `PERRY_JEV_MODEL` (default
`jev-1.13-free`), `PERRY_MIN_CONFIDENCE` (default `0.7`), and `PERRY_ZEN_URL` (default
Zen endpoint; override only for local HTTP fakes). Real telemetry is out of scope while
the decision model is externally hosted.

## Test and release environments

| Where | Model / notifier | What the check means |
| --- | --- | --- |
| Local and public PR CI | Deterministic fake / fake | Reproducible behavior; does not verify real services |
| Protected manual CI workflow | Real Jev / none | Synthetic API contract only (run 2026-09-25); no phone or homelab data |
| Built-image smoke | HTTP fakes / fake | The built container's API, DB, provider and notification wiring |
| GitOps staging **(review-only PR)** | Real Jev with synthetic input / disposable sidecar sink | In-cluster wiring and release smoke after ArgoCD sync |
| Homelab production **(planned)** | Real Jev with synthetic input / existing Apprise | One gated phone test; no live metric ingestion |

CI runs quick quality, dependency audit, and secret scanning in parallel; then builds
one candidate image and checks it with fake HTTP services. Successful `main` builds
publish a commit-SHA-tagged candidate to GHCR and report its immutable digest. **Image
publication is not a deployment.** Staging manifests are under review in
[kubernetes-homelab PR #157](https://github.com/kavishwar-khankari/kubernetes-homelab/pull/157),
pinned to the tested image digest; nothing is merged or deployed yet. Production promotion
and rollback remain unimplemented; no release parity or rollback is claimed.

`perry.staging_sink:app` is a staging-only in-memory fake receiver available in the
same image. It accepts notifications without contacting ntfy or Telegram and exposes a
counter for the GitOps PostSync smoke Job. It is never started in production.
`PERRY_STAGE_EVENT_PREFIX` authorizes only prefixed event IDs, and `from_environment`
refuses that prefix unless the notifier is loopback, so a staging misconfiguration cannot
reach a phone.

The eventual GitOps path is a reviewed PR updating the staging digest in
`kubernetes-homelab`, ArgoCD reconciliation and in-cluster smoke checks, followed by a
separate reviewed PR copying that **same digest** to production. Rollback changes the
desired digest back in Git. The GitOps repo must never contain the Zen key; its existing
DopplerSecret pattern supplies runtime credentials. No direct `kubectl apply`, patch, or
imperative rollout is part of the release plan.

## Failure reporting and scope

For a failing check, record the event ID, commit/image digest, model response version,
expected and observed status, sanitized logs, and whether fake or real services were
involved. Do not include credentials or raw provider HTTP headers. A future release note
should include the staging smoke result, promotion PR, production smoke result, and tested
rollback evidence—write **not run** when a check was skipped.

Planned after the core path: a defined k6 staging workload with latency, throughput,
error and resource baselines; a Grafana panel and Playwright only if a real browser journey
is delivered; and an executed GitOps rollback exercise. This is a personal learning
project, not a claim of professional SDET experience.

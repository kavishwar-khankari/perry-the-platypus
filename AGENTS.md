# Perry — synthetic decision pipeline

## Scope and safety

One path: synthetic event → Zen Jev Choice → hard fail-closed rules → SQLite decision →
Apprise. Accept only synthetic events while Jev is externally hosted. Keep credentials and
real homelab telemetry out of this public repository, model requests, logs, and test reports.
The `confidence` field is not a measured probability that an alert is correct.

## Tests and release evidence

Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check src`, and
`uv run pytest -q` before committing. CI uses a fake Jev and fake notification receiver.
Real Jev contract checks use invented input on a trusted runner; only an explicitly
authorized manual test reaches the real Apprise `global` key. Report simulated and real
checks separately. A release, performance gate, or rollback counts as validated only after
its check actually runs.

## Staging safety

Staging runs in its own namespace with the real Jev key from Doppler and a disposable fake
notification sink. It authorizes only event IDs with the configured `PERRY_STAGE_EVENT_PREFIX`,
and `from_environment` refuses that prefix unless the notifier URL is the loopback fake sink,
so a staging misconfiguration cannot message a phone.

## Homelab deployment

Before changing `../kubernetes-homelab`, read its `AGENTS.md` and
`graphify-out/GRAPH_REPORT.md`. Follow its GitOps-only rules: propose pinned image digests
in reviewed Git changes, allow ArgoCD to reconcile, and roll back by restoring the previous
digest in Git. A public PR or untrusted runner never receives Zen or homelab credentials.
Avoid modifying Frostbite for Perry work.

## Research

Delegate web research to the `websearch` agent: SearXNG first, Chrome DevTools fallback for
blocked or interactive pages, following the homelab AGENTS.md browser-page instructions.

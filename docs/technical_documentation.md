# Technical Documentation

> Synthetic data and simulated partner services only. Not intended for production clinical use.

## 1. Architecture
Flask app factory (`app.py: create_app`) -> `HospitalCoreService` -> (`ResilienceManager` | `BaselineClient`) -> `PartnerSimulator`. SQLite stores everything persistent. A `Clock` abstraction (`RealClock` live, `VirtualClock` in tests/experiments) is the only source of time and sleeping, so the same code runs live and in fast reproducible simulations.

## 2. Modules
| Path | Responsibility |
|---|---|
| `run.py` | One-command startup (dirs, DB, config, demo users, synthetic data, Flask, background health probe) |
| `app.py` | Routes, sessions, role checks, API |
| `src/auth/auth.py` | Roles, permission sets, decorators, page lists |
| `src/core/hospital_service.py` | Partner execution (both modes), patient-visit workflow, failure simulation + failure events, pending-sync queue, health, dependency map |
| `src/partners/partner_simulator.py` + `laboratory.py`, `pharmacy.py`, `insurance.py`, `telemedicine.py` | Simulated partners and their synthetic payloads |
| `src/resilience/` | `errors.py` (classification), `timeout.py`, `retry.py`, `circuit_breaker.py`, `fallback.py`, `resilience_manager.py`, `result.py` |
| `src/baseline/baseline_client.py` | Simple baseline |
| `src/monitoring/` | `recorder.py` (DB/memory logging), `metrics.py` (single source of metric formulas), `health.py`, `health_monitor.py` |
| `src/database/db.py` | Schema, seeding, queries |
| `src/utils/` | `config_manager.py` (load/validate/persist), `clock.py`, `validation_survey.py` |
| `experiments/` | `scenarios.py`, `runner.py`, `demo_trace.py`, `experiment.ipynb` |
| `scripts/` | `run_all_experiments.py`, `generate_docs.py`, `generate_feedback_summary.py` |

## 3. Database (`data/hospital_resilience.db`, created automatically)
`patients`, `appointments`, `partners`, `service_calls`, `failure_events`, `experiment_runs`, `user_feedback` (as specified) plus `users` (hashed passwords), `retry_attempts` (one row per attempt), `circuit_events` (state transitions) and `pending_actions` (deferred lab/insurance requests). `service_calls` also stores `mode`, `core_ok`, `status_code`, `source`. No patient names or clinical content are logged; patient IDs are synthetic and only appear in `pending_actions`.

## 4. Partner simulation
Per partner: configured `latency_ms` (+/-5% jitter) and `failure_rate` (background HTTP 502/503/504). Modes: `NORMAL`, `HIGH_LATENCY` (latency override), `TIMEOUT` (hang, 30 s), `INTERMITTENT` (error rate; ~35% of failures are hangs), `CONTINUOUS_FAILURE` (502 always), `UNAVAILABLE` (fast 503). Optional `duration_seconds` auto-recovers. Partner-side validation returns 400 when `patient_id` is missing. Randomness is seeded by `(seed, partner, request key, attempt)` so two systems issuing the same logical request see the same partner behaviour. A caller timeout is enforced like an HTTP socket timeout (waits `timeout` seconds, raises `PartnerTimeout`).

## 5. Timeout
Per-partner values from `resilience.timeout.<partner>` (validated > 0). A timed-out attempt is recorded (`error_type=TIMEOUT`), treated as transient (retryable), counts toward the breaker, and ends in a fallback if retries are exhausted - the core never waits indefinitely.

## 6. Retry
`retry.enabled`, `max_attempts` (0-5, retries after the first call), `backoff_seconds`, `backoff_multiplier` (delay before retry n = backoff x multiplier^(n-1)). Retried: timeout, 502, 503, 504. Not retried: 4xx (validation/auth) and other 5xx. Retries stop early if the breaker opens. Each attempt is stored in `retry_attempts` (`attempt`, `result`, `latency_ms`).

## 7. Circuit breaker
Real state machine per partner. CLOSED: `failure_threshold` consecutive failed calls (each failed attempt counts) -> OPEN. OPEN: calls rejected immediately (`CIRCUIT_OPEN`, the partner is not contacted) until `recovery_timeout_seconds`. Next call -> HALF_OPEN: at most `half_open_max_calls` trial calls; success -> CLOSED, failure -> OPEN. HTTP 4xx do not count against the partner. Transitions are persisted in `circuit_events`.

## 8. Fallback and statuses
Fallback text comes from `config.yaml` and never claims success. Final request statuses: `SUCCESS`, `RECOVERED` (success after retry or HALF_OPEN trial), `TIMEOUT`, `TEMPORARILY_UNAVAILABLE` (503), `DEGRADED` (502/504), `CIRCUIT_OPEN` (failed fast), `FALLBACK_ACTIVE` (other failure with fallback). `RETRYING` marks failed attempts that were retried (in attempt logs). `REJECTED` = invalid request (not a fallback). Laboratory and insurance fallbacks write a `pending_actions` row that is replayed (in the background in the live app) once the partner answers again; pharmacy and telemedicine do not queue (their messages say so).

## 9. Baseline
Direct call, `baseline.timeout_seconds` client timeout, `baseline.max_retries` immediate retries on timeout/5xx, no breaker, no fallback; a partner failure becomes a core failure (status `ERROR`).

## 10. Configuration
`config/config.yaml` validated by `ConfigManager` (timeouts > 0; retry attempts 0-5; failure threshold 1-20; error rate 0-1 or "0%-100%"; etc.). `POST /api/config` accepts a partial document, validates the merged result, persists it and calls `HospitalCoreService.reload_config()` which updates simulator parameters and reconfigures breakers in place (state preserved).

## 11. Health and dependency map
Health is computed from observed behaviour: breaker OPEN -> `CIRCUIT_OPEN` (gray); HALF_OPEN -> `DEGRADED`; otherwise from the last 10 calls/probes in the last `monitoring.health_window_seconds`: failure ratio >= 0.8 -> `UNAVAILABLE` (red); >= 0.2, many retried calls or average latency > 80% of the timeout -> `DEGRADED` (yellow); else `HEALTHY` (green); no data -> `UNKNOWN`. A background probe (`health_check` operation, every `probe_interval_seconds`) keeps health fresh. `GET /api/dependencies` returns the map.

## 12. Authentication and roles
Session cookies (`HttpOnly`, `SameSite=Lax`), PBKDF2-hashed passwords, permission sets per role (`src/auth/auth.py`). Every API route is permission-checked server-side (401 unauthenticated, 403 forbidden); the UI only hides what the server would refuse anyway. Clinical staff cannot select baseline mode. The manager has no access to patient data endpoints and uses synthetic test traffic instead.

## 13. API
| Method & path | Permission |
|---|---|
| `GET /api/health` | public |
| `GET /api/partners`, `GET /api/partners/<p>/health[?probe=1]` | partner_status (probe: manager/admin; clinicians get a reduced view) |
| `POST /api/partners/<p>/simulate` `{mode, latency_ms, error_rate, duration_seconds}` | simulate |
| `POST /api/partners/<p>/recover`, `POST /api/partners/<p>/test-call` | simulate |
| `GET /api/dependencies`, `GET /api/metrics`, `GET /api/logs`, `GET /api/status` | manager/admin |
| `GET /api/config`, `POST /api/config` | config_read / config_write |
| `GET|POST /api/patients`, `GET /api/patients/<id>`, `POST /api/patients/<id>/visit`, `POST /api/appointments` | clinical |
| `POST /api/laboratory/request`, `/api/pharmacy/check`, `/api/insurance/verify`, `/api/telemedicine/book` | clinical |
| `GET /api/experiments`, `POST /api/experiments/run` | experiments_view / experiments_run |
| `GET /api/validation/questions`, `GET|POST /api/validation`, `POST /api/validation/summary` | submit: both roles; read: manager |
| `GET /api/reports`, `GET /api/reports/<key>` | manager/admin |

## 14. Logging
Every partner request: timestamp, request_id, partner, operation, latency, status, error type, retry count, final circuit state, fallback used (`service_calls`); each attempt (`retry_attempts`); each circuit transition (`circuit_events`); simulated failures (`failure_events`). Viewable on the Logs page / `GET /api/logs`.

## 15. Metrics
Defined once in `src/monitoring/metrics.py` and used by both the dashboard and the experiments: core availability, request success/failure rate, average and P95 latency, timeout count, retry count, circuit-open count, fail-fast count, fallback count, errors propagated to core; experiments add recovery time, cascading-failure count and within-SLO percentage.

## 16. Testing
`pytest -q` - unit tests for partners, resilience, config and DB; API tests for authentication, authorization and every endpoint family; experiment reproducibility/fairness tests; and `tests/test_e2e.py`, the full failure -> retry -> circuit open -> fallback -> core continues -> recovery -> HALF_OPEN -> CLOSED lifecycle via HTTP with both roles.

## 17. Experiments
See `docs/experiment_report.md` and the README. Same workload, fault timeline and partner randomness for both modes; virtual clock; 5 seeds; everything computed from logs.

## 18. Limitations
Simulated partners; sequential visits; Flask dev server; demo accounts; no CSRF tokens; in-process breaker state (run one worker); saving config from the UI drops YAML comments.

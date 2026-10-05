# From Operational Pain to Working Product: Hospital Dependency Resilience Platform
*Dependency Resilience Layer for a Hospital Connecting Laboratory, Pharmacy, Insurance and Telemedicine Vendors*

> This system uses synthetic data and simulated partner services. It is not intended for production clinical use. All figures below are generated from executed experiments (`python scripts/run_all_experiments.py`).

## 1. Abstract
A hospital core application depends on external laboratory, pharmacy, insurance and telemedicine services. When a partner becomes slow or unavailable, the failure propagates into the core workflow. We built a Flask/SQLite platform that wraps every partner call in a resilience layer - per-partner timeouts, bounded retries with back-off, a circuit breaker (CLOSED/OPEN/HALF_OPEN) and truthful fallbacks - together with health monitoring, a dependency map, configurable rules, failure simulation, role-based access and a reproducible baseline-vs-resilient experiment. Over 8 failure scenarios x 5 seeds (2400 patient visits per mode), core-service availability was **59.33%** for the baseline and **100.00%** for the resilient system (target 95.00%): an improvement of **40.67 percentage points**; target **Achieved**.

## 2. Introduction
Hospitals integrate many vendors. Each integration is a dependency that can fail independently. Resilience engineering contains such failures so that the part of the system that must keep working (registration, appointments, consultation) does.

## 3. Problem Statement
Partner failures currently cascade into the hospital core application without graceful degradation. We need a dependency-resilience layer and evidence - from experiments against a simple baseline - that core availability improves sufficiently during simulated partner failures.

## 4. Existing Situation
Direct synchronous calls: a slow partner blocks the user, a failing partner is called again and again, users see raw errors, operations staff have no dependency view. The project started from a partially implemented prototype; an audit found that its "timeout" did not actually time out (a 0.3 s limit returned after 2.0 s), retry counts were lost when retries were exhausted (so the breaker saw one failure per request and rarely opened), there was no database or authentication, the experiment showed almost no retries, and a validation document contained fabricated survey statistics. These were fixed or replaced.

## 5. Proposed Solution
A resilience layer in front of all partner calls, deterministic and explainable: timeout -> controlled retry -> circuit breaker -> truthful fallback, plus monitoring, configuration, simulation and experiments. The immediate operational problem is failure propagation between the hospital core application and external partner services. Therefore, deterministic resilience engineering using timeouts, controlled retries, circuit breakers and fallbacks is more appropriate than an AI-first solution.

## 6. Objectives
Contain failures; keep the core workflow running; be honest to users; make dependency health visible; make rules configurable; simulate realistic failures; measure improvement against a fair baseline; run on modest hardware with no paid services.

## 7. Scope
In scope: four simulated partners, the resilience layer, baseline, dashboard/roles/config/simulation, experiments, tests, documentation. Out of scope: real integrations, real patient data, production hardening, regulatory compliance.

## 8. Field Workflow
Registration -> Appointment -> Doctor consultation -> Laboratory -> Pharmacy -> Insurance -> Telemedicine (see `docs/field_workflow.md`). The first three steps are local; the last four call partners.

## 9. Architecture
Browser UI -> Flask (sessions, roles) -> HospitalCoreService -> ResilienceManager or BaselineClient -> PartnerSimulator; SQLite persistence; a clock abstraction (real or virtual). See `docs/technical_documentation.md`.

## 10. Technology Stack
Python, Flask, SQLite, PyYAML, pandas, matplotlib, pytest, HTML/CSS/vanilla JS. CPU only, 4-8 GB RAM, no Docker, no paid APIs.

## 11. Data Generation
Only synthetic data: ~24 patients ("(synthetic)" names), appointments and partner payloads generated with fixed seeds at first start. Experiments use fixed seeds 11, 12, 13, 14, 15; partner randomness is derived from (seed, partner, request, attempt) so both systems face identical conditions. No real patient, insurance or medical data is used.

## 12. Baseline
A reasonable simple integration: direct call, 10.00 s client timeout, 1 immediate retry on timeout/5xx, no circuit breaker, no fallback. A partner failure becomes a core failure. It is not artificially weakened.

## 13. Resilience Layer
`ResilienceManager.execute`: circuit check -> call with per-partner timeout -> classify outcome -> retry if transient and allowed -> update breaker -> fallback if the operation cannot complete. Every request, attempt and transition is logged.

## 14. Timeout
Per-partner, configurable (laboratory 2.0s, pharmacy 2.0s, insurance 3.0s, telemedicine 2.0s). An attempt that exceeds its timeout ends at the timeout and is recorded as `TIMEOUT`.

## 15. Retry
Up to 2 retries after the first call, back-off 0.20 s (x2 per retry). Only timeouts and HTTP 502/503/504 are retried; validation/authentication errors and other 5xx are not. Example (executed):

| Step | Attempts | Retry count | Status | Circuit |
|---|---|---|---|---|
| Insurance transient failure (timeout, timeout, success) | 1:TIMEOUT -> 2:TIMEOUT -> 3:SUCCESS | 2 | RECOVERED | CLOSED |
| Laboratory failure: retries exhaust, circuit opens, fallback | 1:HTTP_502 -> 2:HTTP_502 -> 3:HTTP_502 | 2 | DEGRADED | OPEN |
| Laboratory: circuit OPEN -> fail fast, no partner call | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Partner recovered, but circuit still OPEN (timeout not elapsed) | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Recovery timeout passed -> HALF_OPEN trial succeeds -> CLOSED | 1:SUCCESS | 0 | RECOVERED | CLOSED |
| Normal operation resumed | 1:SUCCESS | 0 | SUCCESS | CLOSED |

## 16. Circuit Breaker
CLOSED -> OPEN after 3 consecutive failed calls; OPEN rejects instantly for 10.00 s; then HALF_OPEN allows one trial call; success -> CLOSED, failure -> OPEN. The request logic follows the state; the UI only displays it.

## 17. Fallback
Truthful, configured messages. Insurance example: "Insurance verification is temporarily unavailable. The request has been recorded for later verification." - and the request really is stored and replayed on recovery. Insurance is never shown as verified while unreachable.

## 18. Configurable Rules
`config/config.yaml`, editable from the Configuration page with validation; changes are applied to the running simulation and are used by the next experiment run.

## 19. Roles
**Operations Manager**: dashboard, partner health, dependency map, failure simulation, configuration, experiments, logs, metrics, validation, reports. **Clinical Staff**: patient workflow, appointments, partner requests, partner status, plain-language failure messages; cannot change configuration, simulate failures or run experiments. Enforced server-side (401/403) and covered by tests. An optional Administrator holds both sets.

## 20. Failure Simulation
Partner x mode (Normal, High Latency, Timeout, Intermittent, Continuous Failure, Unavailable, Recovery) with latency, error rate and duration; Start / Stop / Recover. The simulation changes real partner behaviour (sleep time, HTTP status), not a label.

## 21. Experimental Methodology
Scenarios S1-S8 (normal; lab high latency; pharmacy intermittent; insurance outage; telemedicine timeout; partner recovery; insurance transient failures; lab consecutive failures). 60 visits per scenario per seed, one every 5.00 s, 5 seeds, first 5 visits healthy. Identical workload, fault timeline and partner randomness for both modes; virtual clock; all metrics computed from the logs.

## 22. Metrics
Primary: **core availability** = successful core requests / total core requests x 100 (core request = patient visit; success = no partner error reached the core, fallbacks allowed and reported as degraded). Secondary: within-SLO (5.00 s), request success/failure rate, average and P95 latency, timeouts, retries, circuit opens, fail-fast rejections, fallbacks, recovery time, cascading failures.

## 23. Results
**Baseline:** 59.33% | **Target:** 95.00% | **Resilient:** 100.00% | **Improvement:** 40.67 pp | **Target:** Achieved

Visits within the 5.00 s SLO: baseline 45.92%, resilient 98.00%.

| Scenario | Baseline avail. % | Resilient avail. % | Improvement (pp) | Baseline p95 ms | Resilient p95 ms | Retries (res.) | Fallbacks (res.) | Circuit opens (res.) |
|---|---|---|---|---|---|---|---|---|
| S1 Normal operation | 99.00 | 100.00 | 1.00 | 524 | 524 | 59 | 0 | 0 |
| S2 Laboratory high latency | 99.33 | 100.00 | 0.67 | 5157 | 2000 | 54 | 275 | 90 |
| S3 Pharmacy intermittent failure | 77.33 | 100.00 | 22.67 | 10387 | 1796 | 175 | 111 | 37 |
| S4 Insurance complete outage | 8.33 | 100.00 | 91.67 | 484 | 495 | 52 | 275 | 95 |
| S5 Telemedicine timeout | 8.00 | 100.00 | 92.00 | 20000 | 2000 | 53 | 275 | 90 |
| S6 Partner recovery | 66.00 | 100.00 | 34.00 | 524 | 524 | 64 | 103 | 35 |
| S7 Insurance transient failures | 66.67 | 100.00 | 33.33 | 10491 | 1225 | 143 | 161 | 52 |
| S8 Laboratory consecutive failures | 50.00 | 100.00 | 50.00 | 613 | 525 | 66 | 150 | 50 |

Charts: `outputs/figures/` (availability, average and P95 latency, error rate, retries, circuit events, fallback usage, recovery time).

## 24. Error Analysis
Full computed analysis in `docs/experiment_report.md`. Key honest points: (a) the resilient system's 100%-style availability is a consequence of design - fallbacks keep the core running - so full-fidelity partner success must be read alongside it (it can be *lower* than the baseline when slow-but-valid responses are cut off by timeouts); (b) retries and back-off add latency before the breaker opens; (c) recovery is slower than the baseline because the breaker waits before testing the partner (S6: baseline 0.88 s vs resilient 3.82 s); (d) the S1 baseline benefits from its single immediate retry, so the gap there is small.

## 25. Failure Mode Analysis
See `docs/failure_mode_analysis.md` (high latency, timeout, intermittent, continuous, unavailable, recovery, invalid request).

## 26. User Validation
**Prototype/simulated user validation.** A 7-question questionnaire for Operations Manager and Clinical Staff (status understandable? failure messages clear? dashboard useful? fallback sensible? simulation useful? operational awareness? what to improve?) stores responses in SQLite (`user_feedback`) and generates `docs/user_feedback_summary.md`. No hospital stakeholder interviews were conducted and no responses are pre-filled; the summary reports exactly what has been collected. Earlier fabricated survey figures were removed.

## 27. Testing
Automated tests (`pytest -q`, 52 automated tests, all passing) cover partners, timeout, retry and limits, circuit states, fallback, configuration, simulation, baseline, resilient flow, database, authentication, authorization, API and a full end-to-end lifecycle.

## 28. Limitations
Simulated partners and parametric failure models; sequential visits; virtual-clock experiments (live app uses real time); demo authentication on the Flask dev server; a fallback-completed visit counts as available; small prototype validation; in-process breaker state.

## 29. Future Scope
Concurrency and load experiments; bulkheads/rate limiting; adaptive timeouts and anomaly detection (where AI/ML could be justified); real partner adapters behind the same interface; persistent circuit state across workers; alerting; stronger auth with CSRF protection; a real stakeholder study.

## 30. Conclusion
In the simulated experiments the resilience layer raised core-service availability from 59.33% to 100.00% (target 95.00%: Achieved) by containing partner failures with timeouts, bounded retries, circuit breaking and truthful fallbacks, at the cost of degraded partner functionality during outages, extra latency before the breaker opens and slower return to full service. The result is demonstrated on simulators; validating it against real partners is future work.

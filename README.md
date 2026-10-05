# Hospital Dependency Resilience Platform

**From Operational Pain to Working Product** - a dependency-resilience layer for a hospital core application that connects to **Laboratory, Pharmacy, Insurance and Telemedicine** vendors.

> **Academic prototype.** This system uses synthetic data and simulated partner services. It is not intended for production clinical use. It makes no HIPAA/GDPR/clinical-safety/regulatory claims.

## 1. Problem
When an external partner is slow or down, the failure cascades into the hospital core application: screens hang, workflows stop, and staff cannot tell what is wrong. The immediate operational problem is failure propagation between the core application and external partner services. Therefore deterministic resilience engineering (timeouts, controlled retries, circuit breakers, truthful fallbacks) is more appropriate than an AI-first solution. (AI is listed only as future scope.)

## 2. Objectives
1. Contain partner failures with **timeouts, bounded retries, circuit breakers and fallbacks**.
2. Show **truthful, realistic status messages** (never claim a failed operation succeeded).
3. Monitor **dependency health**, show a **dependency map**, expose **configurable rules**.
4. Provide **failure simulation** and **measurable baseline-vs-resilient experiments**.
5. Support **two organisational roles** with real access control; run on a student laptop, free, offline.

## 3. Headline result (measured, regenerated on every experiment run)
Primary metric - **core-service availability during simulated partner failures** = successful core requests / total core requests x 100 (a core request is one patient visit across the 4 partner steps).

| | |
|---|---|
| Baseline | **59.33%** |
| Target | **95.00%** |
| Resilient | **100.00%** |
| Improvement | **40.67 percentage points** |
| Target | **Achieved** |

Pooled over 8 scenarios x 5 seeds x 60 visits per mode. Read the caveats in [docs/experiment_report.md](docs/experiment_report.md): a visit that completes using a truthful fallback counts as *completed but degraded*; the resilient layer keeps the **core** running, it does not make partners work. In the same runs, visits finishing within the 5.00 s latency SLO were 45.92% (baseline) vs 98.00% (resilient).

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

## 4. Architecture
```
Browser UI (HTML/CSS/JS)  --->  Flask app (app.py)  --- sessions + role-based access
                                      |
                              HospitalCoreService  --- SQLite (data/hospital_resilience.db)
                               |                |
              mode = resilient            mode = baseline
                               |                |
                      ResilienceManager   BaselineClient (direct call, 1 retry, no breaker/fallback)
          [circuit breaker -> timeout -> bounded retry -> fallback]
                               |
                      PartnerSimulator  (Laboratory | Pharmacy | Insurance | Telemedicine)
                        latency, error rate, failure modes, timeouts
```
Dependency map: `Hospital Core -> {Laboratory, Pharmacy, Insurance, Telemedicine}` (all non-critical to the core workflow).

## 5. Technology
Python 3.10+, Flask, SQLite (stdlib `sqlite3`), PyYAML, pandas, matplotlib, pytest, vanilla HTML/CSS/JS. No Docker, GPU, paid API or external service is required.

## 6. Installation
Windows:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
macOS/Linux:
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```
**Database setup is automatic**: `python run.py` creates directories, `data/hospital_resilience.db`, all tables, demo users and ~24 synthetic patients on first start, loads `config/config.yaml`, then starts Flask at **http://127.0.0.1:5000**.

## 6a. Demo accounts
| Role | Username | Password | Access |
|---|---|---|---|
| Operations Manager | `manager` | `manager123` | Dashboard, partner health, dependency map, failure simulation, configuration, experiments, logs, metrics, user validation, reports |
| Clinical Staff | `clinician` | `clinician123` | Patient workflow, patients, appointments, lab/pharmacy/insurance/telemedicine requests, partner status, user-friendly failure messages. **Cannot** change configuration, simulate failures, run experiments or read logs |
| Administrator (optional) | `admin` | `admin123` | Everything |

Passwords are stored as salted PBKDF2 hashes. These are demo accounts for a local prototype.

## 7. Using the application
1. Sign in as **manager** -> *Failure Simulation*: choose a partner, a mode (Normal, High Latency, Timeout, Intermittent, Continuous Failure, Unavailable, Recovery), optional latency / error rate / duration, **START SIMULATION**, then **Send test traffic**.
2. Watch *Dashboard*, *Partner Health* and *Dependency Map* (green healthy, yellow degraded, red unavailable, gray circuit open) and *Logs* (every request, every retry attempt, every circuit transition).
3. **RECOVER SERVICE** (or STOP) and keep sending traffic: the breaker goes OPEN -> HALF_OPEN -> CLOSED on its own.
4. Sign in as **clinician** -> *Patient Workflow*: select a patient, run lab/pharmacy/insurance/telemedicine requests or the full visit. During an outage the core workflow still works and statuses stay honest (e.g. insurance `PENDING`, never `SUCCESS`).
5. *Configuration* (manager): edit timeouts, retries, back-off, circuit threshold/recovery timeout, partner latency and error rate. Values are validated and applied immediately to the running simulation.

## 8. Experiments
```
python scripts/run_all_experiments.py
```
Generates data, runs baseline and resilient systems on identical workloads, compares, computes metrics, draws charts and writes the report (about 2 s - a virtual clock replaces sleeping; the real code paths run).
Outputs: `data/results/{baseline,resilient,comparison}_results.csv`, `data/results/experiment_summary.json`, `data/results/retry_trace_demo.csv`, `outputs/figures/*.png` (8 charts), `docs/experiment_report.md`, and refreshed `docs/*` / `presentation/*`. The notebook `experiments/experiment.ipynb` reproduces the analysis. The *Experiments* page can also re-run the suite.

Scenarios: S1 normal, S2 laboratory high latency, S3 pharmacy intermittent failure, S4 insurance complete outage, S5 telemedicine timeout, S6 partner recovery, S7 insurance transient failures (retry demonstration), S8 laboratory consecutive failures (retry -> breaker -> fallback -> failed HALF_OPEN trials).

Retry / circuit trace from real execution:

| Step | Attempts | Retry count | Status | Circuit |
|---|---|---|---|---|
| Insurance transient failure (timeout, timeout, success) | 1:TIMEOUT -> 2:TIMEOUT -> 3:SUCCESS | 2 | RECOVERED | CLOSED |
| Laboratory failure: retries exhaust, circuit opens, fallback | 1:HTTP_502 -> 2:HTTP_502 -> 3:HTTP_502 | 2 | DEGRADED | OPEN |
| Laboratory: circuit OPEN -> fail fast, no partner call | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Partner recovered, but circuit still OPEN (timeout not elapsed) | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Recovery timeout passed -> HALF_OPEN trial succeeds -> CLOSED | 1:SUCCESS | 0 | RECOVERED | CLOSED |
| Normal operation resumed | 1:SUCCESS | 0 | SUCCESS | CLOSED |

## 9. Tests
```
pip install -r requirements.txt
pytest -q
```
Covers partners, timeout, retry and limits, circuit CLOSED/OPEN/HALF_OPEN/recovery, fallback truthfulness, configuration validation, failure simulation, baseline, resilient flow, database, authentication, role authorization, API, experiments, and a full end-to-end lifecycle test.

## 10. Configuration
Everything lives in `config/config.yaml` (defaults with comments in `config/config.default.yaml`): per-partner timeouts, retry (`max_attempts` = retries after the first call, `backoff_seconds`, `backoff_multiplier`), circuit breaker (`failure_threshold`, `recovery_timeout_seconds`, `half_open_max_calls`), simulated partner latency / error rate, fallback messages, baseline settings, experiment parameters. Saving from the UI rewrites the file without comments.

## 11. API summary
`GET /api/health`, `GET /api/partners`, `GET /api/partners/<p>/health[?probe=1]`, `POST /api/partners/<p>/simulate`, `POST /api/partners/<p>/recover`, `GET /api/dependencies`, `GET /api/metrics`, `GET /api/logs`, `GET|POST /api/config`, `GET /api/patients`, `GET /api/patients/<id>`, `POST /api/appointments`, `POST /api/laboratory/request`, `POST /api/pharmacy/check`, `POST /api/insurance/verify`, `POST /api/telemedicine/book`, plus `/api/validation`, `/api/experiments`, `/api/reports`. See [docs/technical_documentation.md](docs/technical_documentation.md).

## 12. Documentation
[Technical documentation](docs/technical_documentation.md) | [Project report](docs/project_report.md) | [Failure-mode analysis](docs/failure_mode_analysis.md) | [Experiment report](docs/experiment_report.md) | [User feedback summary](docs/user_feedback_summary.md) | [Presentation outline](presentation/presentation_outline.md)

## 13. Limitations
- Partners are simulators with parametric failure models, not real systems; results depend on the configured models.
- Experiments process visits sequentially (no concurrency / queueing contention) on a virtual clock.
- A visit completed with a truthful fallback counts toward core availability (design decision, reported alongside full-fidelity success).
- User validation is a *prototype/simulated* questionnaire; no hospital stakeholder interviews were conducted, and no feedback is pre-filled.
- Flask development server, demo accounts, no CSRF tokens, no TLS: suitable for a local demo only.
- Deferred (queued) laboratory/insurance requests are replayed against the *simulated* partner on recovery.

## 14. Deployment (optional, free tier)
Local use needs nothing else. For a free-tier host (e.g. Render, Railway, PythonAnywhere): set `SECRET_KEY`, start with `gunicorn "app:create_app()" --workers 1 --threads 8` (single worker: circuit-breaker state is in-process), and note SQLite storage on free tiers may be ephemeral. Docker is not required.

## 15. Academic disclaimer
This is a student project. It uses only synthetic data and simulated partner services, makes no medical, insurance, legal or regulatory claims, and must not be used for real clinical decisions.

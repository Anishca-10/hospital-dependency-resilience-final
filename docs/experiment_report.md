# Experiment Report (generated)

_Generated 2026-10-05 09:37:38 by `python scripts/run_all_experiments.py`. Every number below is computed from the call, retry-attempt and circuit-event logs of the executed simulations; nothing is typed in by hand._

## 1. Design

- **Systems compared:** `baseline` (direct call, 10.0 s client timeout, 1 immediate retry, no circuit breaker, no fallback) vs `resilient` (per-partner timeouts {'laboratory': 2.0, 'pharmacy': 2.0, 'insurance': 3.0, 'telemedicine': 2.0}, up to 2 retries with 0.2 s back-off, circuit breaker threshold 3 / recovery 10.0 s, truthful fallbacks).
- **Workload:** 60 patient visits per scenario per seed, one visit every 5.0 s; each visit = registration -> appointment -> consultation -> laboratory -> pharmacy -> insurance -> telemedicine.
- **Repetitions:** 5 seeds ([11, 12, 13, 14, 15]); each scenario x mode = 300 visits.
- **Fairness:** identical workload, identical fault timeline (by visit index) and identical per-request partner randomness for both modes (same seed). Background failure rate follows `config.yaml`.
- **Core request** = one patient visit. **Core success** = the visit completed without a partner error reaching the core application (a visit using truthful fallbacks counts as completed but *degraded*).
- **Primary metric:** core-service availability = successful core requests / total core requests x 100.
- **Secondary metrics:** visits completed within the latency SLO, request-level success (full-fidelity partner success), latency, retries, timeouts, circuit events, fallbacks, recovery time.
- **Clock:** virtual clock - the real code paths run, but sleeping is simulated, so results are exactly reproducible.

## 2. Target / result / error analysis

| | Core availability |
|---|---|
| **Baseline** (measured) | 59.33% |
| **Target** | 95.00% |
| **Resilient** (measured) | 100.00% |
| **Improvement** | 40.67 percentage points |
| **Target** | **Achieved** |

Pooled over all 8 scenarios and 5 seeds (2400 visits per mode). The 95% target was fixed before running: a core service that loses more than 1 visit in 20 because of a *non-critical* partner outage is not meaningfully protected.

Scenarios meeting the target - baseline: 2/8, resilient: 8/8.
Visits completed within the 5.0 s latency SLO (secondary) - baseline 45.92%, resilient 98.00%.

## 3. Per-scenario results

| Scenario | Base avail % | Res avail % | Base within SLO % | Res within SLO % | Base cascading failures | Res cascading failures | Res degraded visits |
|---|---|---|---|---|---|---|---|
| S1 Normal operation | 99.00 (+/-0.82) | 100.00 (+/-0.00) | 99.00 | 100.00 | 3 | 0 | 0 |
| S2 Laboratory high latency | 99.33 (+/-0.82) | 100.00 (+/-0.00) | 8.00 | 98.33 | 2 | 0 | 275 |
| S3 Pharmacy intermittent failure | 77.33 (+/-6.29) | 100.00 (+/-0.00) | 69.00 | 95.67 | 68 | 0 | 108 |
| S4 Insurance complete outage | 8.33 (+/-0.00) | 100.00 (+/-0.00) | 8.33 | 100.00 | 275 | 0 | 275 |
| S5 Telemedicine timeout | 8.00 (+/-0.67) | 100.00 (+/-0.00) | 8.00 | 98.33 | 276 | 0 | 275 |
| S6 Partner recovery | 66.00 (+/-0.82) | 100.00 (+/-0.00) | 66.00 | 100.00 | 102 | 0 | 103 |
| S7 Insurance transient failures | 66.67 (+/-5.27) | 100.00 (+/-0.00) | 59.00 | 91.67 | 100 | 0 | 161 |
| S8 Laboratory consecutive failures | 50.00 (+/-0.00) | 100.00 (+/-0.00) | 50.00 | 100.00 | 150 | 0 | 150 |

(+/- = standard deviation of availability across seeds, in percentage points.)

### Latency, retries and circuit activity

| Scenario | Base avg ms | Res avg ms | Base p95 ms | Res p95 ms | Base retries | Res retries | Res timeouts | Res fallbacks | Res circuit opens | Res fail-fast | Base/Res recovery s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 406 | 417 | 524 | 524 | 56 | 59 | 0 | 0 | 0 | 0 | n/a / n/a |
| S2 | 1550 | 511 | 5157 | 2000 | 59 | 54 | 100 | 275 | 90 | 185 | n/a / n/a |
| S3 | 1045 | 531 | 10387 | 1796 | 160 | 175 | 55 | 111 | 37 | 74 | n/a / n/a |
| S4 | 290 | 299 | 484 | 495 | 301 | 52 | 0 | 275 | 95 | 180 | n/a / n/a |
| S5 | 4911 | 497 | 20000 | 2000 | 317 | 53 | 100 | 275 | 90 | 185 | n/a / n/a |
| S6 | 365 | 384 | 524 | 524 | 144 | 64 | 0 | 103 | 35 | 68 | 0.9 / 3.8 |
| S7 | 1265 | 533 | 10491 | 1225 | 197 | 143 | 51 | 161 | 52 | 109 | n/a / n/a |
| S8 | 443 | 395 | 613 | 525 | 177 | 66 | 0 | 150 | 50 | 100 | 0.3 / 0.3 |

Latency columns are per partner request (ms). Recovery time = seconds from partner restoration to the first fully successful call.

### Partner-operation quality (full-fidelity success)

| Scenario | Base request success % | Res request success % | Res fallback % of requests |
|---|---|---|---|
| S1 | 99.75 | 100.00 | 0.00 |
| S2 | 99.83 | 77.08 | 22.92 |
| S3 | 93.63 | 90.75 | 9.25 |
| S4 | 70.24 | 77.08 | 22.92 |
| S5 | 76.96 | 77.08 | 22.92 |
| S6 | 89.74 | 91.42 | 8.58 |
| S7 | 90.87 | 86.58 | 13.42 |
| S8 | 80.00 | 87.50 | 12.50 |

Core availability and partner-operation success measure different things: the resilient layer keeps the *core* running by converting partner failures into truthful degraded outcomes; it does **not** make the partner itself work.

## 4. Error analysis (computed from logs)

**S1 Normal operation**
- Baseline: 3 of 300 visits failed (cascade); failing step: laboratory x1, insurance x1, pharmacy x1. Failed-attempt causes: HTTP_503 x40, HTTP_502 x15, HTTP_504 x4.
- Resilient: 0 failed visits, 0 degraded visits; request outcomes: RECOVERED x56, SUCCESS x1144.
- Observations: resilient average request latency is HIGHER than baseline (417 vs 406 ms) - retries and back-off cost time before the breaker opens.

**S2 Laboratory high latency**
- Baseline: 2 of 300 visits failed (cascade); failing step: insurance x1, laboratory x1. Failed-attempt causes: HTTP_503 x34, HTTP_502 x22, HTTP_504 x5.
- Resilient: 0 failed visits, 275 degraded visits; request outcomes: CIRCUIT_OPEN x185, RECOVERED x43, SUCCESS x882, TIMEOUT x90.
- Observations: resilient full-fidelity success is LOWER (77.1% vs 99.8%) because slow-but-valid or flaky responses are cut off by timeouts/breaker and replaced by fallbacks.

**S3 Pharmacy intermittent failure**
- Baseline: 68 of 300 visits failed (cascade); failing step: pharmacy x64, insurance x2, telemedicine x1, laboratory x1. Failed-attempt causes: HTTP_503 x97, TIMEOUT x67, HTTP_502 x49, HTTP_504 x15.
- Resilient: 0 failed visits, 108 degraded visits; request outcomes: CIRCUIT_OPEN x74, DEGRADED x13, RECOVERED x123, SUCCESS x966, TEMPORARILY_UNAVAILABLE x14, TIMEOUT x10.
- Observations: resilient full-fidelity success is LOWER (90.8% vs 93.6%) because slow-but-valid or flaky responses are cut off by timeouts/breaker and replaced by fallbacks.

**S4 Insurance complete outage**
- Baseline: 275 of 300 visits failed (cascade); failing step: insurance x274, pharmacy x1. Failed-attempt causes: HTTP_503 x567, HTTP_502 x8, HTTP_504 x1.
- Resilient: 0 failed visits, 275 degraded visits; request outcomes: CIRCUIT_OPEN x180, RECOVERED x41, SUCCESS x884, TEMPORARILY_UNAVAILABLE x95.
- Observations: resilient average request latency is HIGHER than baseline (299 vs 290 ms) - retries and back-off cost time before the breaker opens; resilient P95 latency is HIGHER than baseline (495 vs 484 ms).

**S5 Telemedicine timeout**
- Baseline: 276 of 300 visits failed (cascade); failing step: telemedicine x275, pharmacy x1. Failed-attempt causes: TIMEOUT x550, HTTP_503 x27, HTTP_502 x11, HTTP_504 x5.
- Resilient: 0 failed visits, 275 degraded visits; request outcomes: CIRCUIT_OPEN x185, RECOVERED x42, SUCCESS x883, TIMEOUT x90.

**S6 Partner recovery**
- Baseline: 102 of 300 visits failed (cascade); failing step: pharmacy x100, laboratory x2. Failed-attempt causes: HTTP_503 x225, HTTP_502 x17, HTTP_504 x4.
- Resilient: 0 failed visits, 103 degraded visits; request outcomes: CIRCUIT_OPEN x68, RECOVERED x56, SUCCESS x1041, TEMPORARILY_UNAVAILABLE x35.
- Observations: resilient average request latency is HIGHER than baseline (384 vs 365 ms) - retries and back-off cost time before the breaker opens; resilient P95 latency is HIGHER than baseline (524 vs 524 ms); after the partner was restored, the resilient system needed 3.8 s to resume full service vs 0.9 s for the baseline (the breaker waits for its recovery timeout before testing the partner) - the price of protection.

**S7 Insurance transient failures**
- Baseline: 100 of 300 visits failed (cascade); failing step: insurance x96, pharmacy x3, laboratory x1. Failed-attempt causes: HTTP_503 x132, TIMEOUT x91, HTTP_502 x61, HTTP_504 x13.
- Resilient: 0 failed visits, 161 degraded visits; request outcomes: CIRCUIT_OPEN x109, DEGRADED x16, RECOVERED x103, SUCCESS x936, TEMPORARILY_UNAVAILABLE x25, TIMEOUT x11.
- Observations: resilient full-fidelity success is LOWER (86.6% vs 90.9%) because slow-but-valid or flaky responses are cut off by timeouts/breaker and replaced by fallbacks.

**S8 Laboratory consecutive failures**
- Baseline: 150 of 300 visits failed (cascade); failing step: laboratory x150. Failed-attempt causes: HTTP_502 x310, HTTP_503 x16, HTTP_504 x1.
- Resilient: 0 failed visits, 150 degraded visits; request outcomes: CIRCUIT_OPEN x100, DEGRADED x50, RECOVERED x59, SUCCESS x991.

## 5. Retry and circuit-breaker trace (scripted, deterministic)

| Step | Request | Partner | t (s) | Attempts | Retry count | Status | Fallback | Circuit | Latency ms |
|---|---|---|---|---|---|---|---|---|---|
| Insurance transient failure (timeout, timeout, success) | REQ001 | insurance | 7.09 | 1:TIMEOUT -> 2:TIMEOUT -> 3:SUCCESS | 2 | RECOVERED | no | CLOSED | 7092 |
| Laboratory failure: retries exhaust, circuit opens, fallback | REQ002 | laboratory | 8.61 | 1:HTTP_502 -> 2:HTTP_502 -> 3:HTTP_502 | 2 | DEGRADED | yes | OPEN | 1519 |
| Laboratory: circuit OPEN -> fail fast, no partner call | REQ003 | laboratory | 8.61 | none (circuit open) | 0 | CIRCUIT_OPEN | yes | OPEN | 0 |
| Partner recovered, but circuit still OPEN (timeout not elapsed) | REQ004 | laboratory | 8.61 | none (circuit open) | 0 | CIRCUIT_OPEN | yes | OPEN | 0 |
| Recovery timeout passed -> HALF_OPEN trial succeeds -> CLOSED | REQ005 | laboratory | 18.9 | 1:SUCCESS | 0 | RECOVERED | no | CLOSED | 288 |
| Normal operation resumed | REQ006 | laboratory | 19.21 | 1:SUCCESS | 0 | SUCCESS | no | CLOSED | 307 |

Circuit transitions: t=8.61s laboratory CLOSED -> OPEN (3 consecutive failures); t=18.61s laboratory OPEN -> HALF_OPEN (recovery timeout elapsed); t=18.9s laboratory HALF_OPEN -> CLOSED (trial call succeeded).

## 6. Threats to validity / limitations

- Partners are simulators with parametric failure models, not real laboratory/pharmacy/insurance/telemedicine systems.
- Visits are processed sequentially (no concurrency or queueing contention).
- A visit is counted as completed when it finishes with truthful fallbacks; this is a design decision (partners are non-critical to the core workflow) and is reported alongside the full-fidelity request success rate.
- Baseline and resilient parameters come from `config.yaml`; different timeouts/retry settings would change the numbers (use the Configuration page and re-run).
- Synthetic data only; not a clinical or regulatory evaluation.

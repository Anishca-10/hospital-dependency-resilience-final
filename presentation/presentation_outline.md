# Presentation Outline (15 slides)
_Numbers are generated from measured experiment results._

## 1. Title
**From Operational Pain to Working Product: Hospital Dependency Resilience Platform** - dependency resilience layer for laboratory, pharmacy, insurance and telemedicine vendors. Synthetic data, simulated partners.

## 2. Problem
Partner failures cascade into the hospital core application: no timeouts, no graceful degradation, no visibility.

## 3. Operational Pain
Screens hang on slow partners; failing partners are hammered with repeat calls; raw errors; staff unsure what was saved; operations blind to dependency health.

## 4. Field Workflow
Registration -> Appointment -> Consultation -> Laboratory -> Pharmacy -> Insurance -> Telemedicine. First three local; last four external.

## 5. Existing Architecture
Direct synchronous partner calls. Baseline here: 10.00 s client timeout + 1 immediate retry; failure propagates to the core.

## 6. Proposed Solution
Resilience layer + monitoring + configurable rules + failure simulation + experiments + role-based UI. Deterministic engineering, not AI-first: the problem is failure propagation.

## 7. Resilience Architecture
Core -> ResilienceManager [circuit breaker -> timeout -> retry -> fallback] -> partner. SQLite logs every request, attempt and circuit transition. Dependency map and health from observed behaviour.

## 8. Timeout / Retry / Circuit Breaker / Fallback
- Timeouts: laboratory 2.0s, pharmacy 2.0s, insurance 3.0s, telemedicine 2.0s
- Retry: up to 2, back-off 0.20 s x2; transient errors only
- Breaker: 3 failures -> OPEN; 10.00 s -> HALF_OPEN -> trial -> CLOSED
- Fallback: truthful messages, deferred requests recorded and replayed

| Step | Attempts | Retry count | Status | Circuit |
|---|---|---|---|---|
| Insurance transient failure (timeout, timeout, success) | 1:TIMEOUT -> 2:TIMEOUT -> 3:SUCCESS | 2 | RECOVERED | CLOSED |
| Laboratory failure: retries exhaust, circuit opens, fallback | 1:HTTP_502 -> 2:HTTP_502 -> 3:HTTP_502 | 2 | DEGRADED | OPEN |
| Laboratory: circuit OPEN -> fail fast, no partner call | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Partner recovered, but circuit still OPEN (timeout not elapsed) | none (circuit open) | 0 | CIRCUIT_OPEN | OPEN |
| Recovery timeout passed -> HALF_OPEN trial succeeds -> CLOSED | 1:SUCCESS | 0 | RECOVERED | CLOSED |
| Normal operation resumed | 1:SUCCESS | 0 | SUCCESS | CLOSED |

## 9. Failure Simulation (live demo)
Manager: Insurance -> Unavailable -> send traffic -> retries -> circuit OPEN -> fail-fast -> Recover -> HALF_OPEN -> CLOSED. Clinician: patient workflow continues, insurance shows PENDING.

## 10. Experimental Methodology
8 scenarios x 5 seeds x 60 visits per mode; identical workload, faults and partner randomness; virtual clock; metrics computed from logs. Primary metric: core availability.

## 11. Baseline vs Resilient Results
Baseline **59.33%** | Target **95.00%** | Resilient **100.00%** | Improvement **40.67 pp** | Target **Achieved**.
Within 5.00 s SLO: 45.92% -> 98.00%.

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

## 12. Error Analysis
Honest costs: retries add latency before the breaker opens; full-fidelity partner success can drop when slow-but-valid responses are cut off; recovery is slower (S6: 0.88 s baseline vs 3.82 s resilient); availability counts fallback-completed visits as degraded-but-available.

## 13. User Validation
Prototype/simulated questionnaire (7 questions, two roles) stored in SQLite; summary generated from real responses only. No stakeholder interviews claimed.

## 14. Limitations
Simulated partners; sequential visits; dev-server demo auth; small prototype validation; fallback visits count as available.

## 15. Conclusion
Resilience layer raised core availability from 59.33% to 100.00% in simulation, at identifiable costs. Next: concurrency tests, real partner adapters, stakeholder study.

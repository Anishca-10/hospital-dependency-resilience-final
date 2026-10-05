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
Direct synchronous partner calls. Baseline here: {{cfg_baseline_timeout_s}} s client timeout + {{cfg_baseline_max_retries}} immediate retry; failure propagates to the core.

## 6. Proposed Solution
Resilience layer + monitoring + configurable rules + failure simulation + experiments + role-based UI. Deterministic engineering, not AI-first: the problem is failure propagation.

## 7. Resilience Architecture
Core -> ResilienceManager [circuit breaker -> timeout -> retry -> fallback] -> partner. SQLite logs every request, attempt and circuit transition. Dependency map and health from observed behaviour.

## 8. Timeout / Retry / Circuit Breaker / Fallback
- Timeouts: {{timeouts}}
- Retry: up to {{cfg_retry_max_attempts}}, back-off {{cfg_retry_backoff_s}} s x2; transient errors only
- Breaker: {{cfg_cb_threshold}} failures -> OPEN; {{cfg_cb_recovery_s}} s -> HALF_OPEN -> trial -> CLOSED
- Fallback: truthful messages, deferred requests recorded and replayed

{{trace_table}}

## 9. Failure Simulation (live demo)
Manager: Insurance -> Unavailable -> send traffic -> retries -> circuit OPEN -> fail-fast -> Recover -> HALF_OPEN -> CLOSED. Clinician: patient workflow continues, insurance shows PENDING.

## 10. Experimental Methodology
{{n_scenarios}} scenarios x {{n_seeds}} seeds x {{visits_per_scenario}} visits per mode; identical workload, faults and partner randomness; virtual clock; metrics computed from logs. Primary metric: core availability.

## 11. Baseline vs Resilient Results
Baseline **{{baseline_core_availability_pct}}%** | Target **{{target_core_availability_pct}}%** | Resilient **{{resilient_core_availability_pct}}%** | Improvement **{{improvement_pp}} pp** | Target **{{target_status}}**.
Within {{latency_slo_s}} s SLO: {{baseline_within_slo_pct}}% -> {{resilient_within_slo_pct}}%.

{{scenario_table}}

## 12. Error Analysis
Honest costs: retries add latency before the breaker opens; full-fidelity partner success can drop when slow-but-valid responses are cut off; recovery is slower (S6: {{S6.baseline_recovery_time_s}} s baseline vs {{S6.resilient_recovery_time_s}} s resilient); availability counts fallback-completed visits as degraded-but-available.

## 13. User Validation
Prototype/simulated questionnaire (7 questions, two roles) stored in SQLite; summary generated from real responses only. No stakeholder interviews claimed.

## 14. Limitations
Simulated partners; sequential visits; dev-server demo auth; small prototype validation; fallback visits count as available.

## 15. Conclusion
Resilience layer raised core availability from {{baseline_core_availability_pct}}% to {{resilient_core_availability_pct}}% in simulation, at identifiable costs. Next: concurrency tests, real partner adapters, stakeholder study.

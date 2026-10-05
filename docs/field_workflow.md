# Field Workflow

A patient visit passes through local hospital steps and four external partners:

1. **Registration** (local) -> 2. **Appointment** (local) -> 3. **Doctor consultation** (local)
4. **Laboratory** - order tests; results arrive from the lab vendor
5. **Pharmacy** - check / refresh prescription information
6. **Insurance** - verify eligibility
7. **Telemedicine** - schedule remote consultation

## Operational pain (before)
- A slow or failing partner blocks the screen the clinician is using; the core application waits.
- Repeated calls to a failing partner add load and delay and make the outage worse.
- Staff receive technical errors or silence and cannot tell whether work was saved.
- Operations staff have no single view of which dependency is unhealthy.

## Roles
- **Clinical staff** run the workflow and need plain, honest status ("pending", "try again later").
- **Operations manager** watches dependency health, tunes rules, simulates failures and reviews logs/experiments.

## Design response
The core workflow continues when a non-critical partner fails; affected steps show a truthful degraded status; deferred requests are recorded and replayed on recovery; operations see health, circuit state, retries and logs.

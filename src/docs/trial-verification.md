# Trial project verification — 19 September 2026

This report covers the `Trial/bobathon` application after the 2021 replay,
comparison, and copilot corrections.

## Delivered

- Added **2021 LA/LB · Actual vs proposed** to the top dataset selector. Switching
  datasets changes every dashboard API to the isolated historical database and
  can switch back to the synthetic demo without stale run or port state.
- Added an integrated comparison with headline cohort totals, vessel-level actual
  and proposed berth/waiting rows, filters, pagination, CSV export, queue and berth
  utilisation charts, and all nine supervisor shifts.
- Made the historical view read-only: users can inspect and export the proposal,
  but cannot review, approve, replan, acknowledge, or mutate the preserved replay.
- Expanded the operations copilot beyond its example prompts. It now routes natural
  questions about capacity/utilisation, vessel names and call IDs, shifts, FCFS,
  risks, and the 2021 actual/proposed comparison to bounded read tools.
- Kept IBM Granite as an optional presentation layer over canonical, cited facts.
  Responses are accepted only when every required sentence and evidence ID is
  returned exactly; provider failures fall back to the same useful local answer.
- Corrected replay leakage and accounting: future terminal destinations are not
  used for planning, waiting time cannot become negative, deferred work remains in
  the backlog, and known-but-unmodelled calls are not mislabeled as future arrivals.

## Verified 2021 replay

The replay cutoff is `2021-09-13T00:00:00Z`; the visible comparison window is the
following 72 hours. The corrected processed set contains 209 vessels and 174 calls.
There are no negative derived waits.

| Measure | Result |
| --- | ---: |
| Calls modelled at cutoff | 60 |
| Proposed assignments | 46 |
| Proposed deferrals | 14 |
| Known calls excluded for unresolved berth identity | 25 |
| Calls first arriving after cutoff | 33 |
| Actual cohort waiting within 72 hours | 3,441.80 h |
| Proposed cohort waiting within 72 hours | 2,548.50 h |
| Queue MAE | 8.50 vessels |
| Waiting MAE | 21.32 h across 8 matched berth starts |
| Proposed crane utilisation | 78.38% |
| Schedule validation | pass; 0 constraint violations |

The waiting comparison uses the same 60-call cutoff cohort and the same 72-hour
censoring window. A proposed deferral counts as waiting through the end of that
window; it does not disappear. All-outcome metrics retain later-known calls for
forecast evaluation, while the main comparison explicitly separates those calls.

Congestion precision/recall/F1 are all 1.0 in this particular coarse, continuously
critical window, and warning lead time is 0 hours because congestion is already
present at the cutoff. These values are not evidence of general predictive skill.

## Evidence boundary

“Actual” means outcomes derived from official NOAA Marine Cadastre AIS positions.
AIS does not include the port's historical appointment plan, crane ledger, yard
inventory, or authoritative terminal event feed. Berth starts and waiting are
spatial proxies; terminal resources, workloads, weather/tide defaults and the
proposed schedule are calibrated simulation inputs. The UI states this boundary
instead of presenting the proposal as a realized historical improvement.

The previous processed data and replay were retained as
`data/real/processed/la_lb_2021_before_verification_20260919` and
`artifacts/historical-replay-before-verification-20260919`; no source AIS data was
deleted.

## IBM copilot checks

Authenticated Granite calls were exercised for free-form operational questions,
including crane utilisation, ship counts, a named vessel, shift 4, FCFS comparison,
planned-delay ranking, and 2021 actual-versus-proposed waiting. A single bounded
format-repair request now handles an incomplete Granite ID envelope; it contains
only opaque IDs and must pass the same exact-permutation validator. The final live
browser question about MAERSK ELBA returned **Connected / Active** with a validated
Granite response. Repeated invalid output still fails closed to the complete local
answer. Credentials remain server-side and are never placed in prompts, logs, or
the browser.

## Automated verification

Final results:

- Backend: **261 passed, 6 skipped**. The six skips require a dedicated PostgreSQL
  test instance. JUnit: `src/artifacts/trial-verification/backend-tests.xml`.
- Final copilot/provider-focused regression after the format-repair addition:
  **35 passed, 1 skipped**; its dedicated repair test also passed in isolation.
- Frontend: **36 passed** across 8 test files.
- TypeScript and Vite production build: passed.
- Ruff and ESLint: passed.

The backend run includes the targeted historical, copilot, dashboard, forecast,
read-only API, and replay-leakage coverage as part of the complete suite.

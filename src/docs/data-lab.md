# Data Lab: test your own vessel calls

Open Data Lab in the main dashboard. Upload a UTF-8 CSV/JSON file or paste rows,
validate them, and run a simulation. The example button uses the selected plan's
terminal ID and UTC origin. JSON input is an array of objects; CSV uses a header row.

## Required fields

Each row needs id, terminal_id, scheduled_eta (ISO timestamp with timezone),
length_m, draft_m, capacity_teu, onboard_teu, unload_moves and load_moves.
Optional priority is 1–5 (1 highest), cargo_type is general/reefer/hazardous,
teu_per_move defaults to 1.5, max_cranes defaults to 3, and required_equipment
defaults to panamax_sts (or choose super_post_panamax_sts).

## Validation and limits

Use a unique call ID, a terminal in the source plan, and an ETA within its next
72 hours. Uploads are limited to 100 rows and 250 KB of text. Capacity and
discharge/loading balances are checked before solving. Validation reports row
and field errors. All rows must pass before simulation begins.

## What simulation means

Uploaded calls are added to the selected immutable snapshot. QUAY solves a
matched baseline and the increased-demand case with the same resources and
constraints. Approved commitments and in-progress work remain fixed. Uploaded
records, assignments and plans are not saved to the operational database.
No imported future outcomes enter the planner. Stale source ML predictions are
removed for both solves; these are baseline scheduling outcomes, not new ML forecasts.

Inspect feasibility, deferred demand, maximum waiting and served average wait
together. These waits describe different served sets when deferrals change.
Download JSON to retain the result. A simulation is not an approved operating plan.

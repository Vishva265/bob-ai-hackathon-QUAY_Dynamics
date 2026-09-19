# Synthetic operations data dictionary

Generated from `backend/app/synthetic/schema.py`; CSV UTF-8, empty = SQL NULL.
All instants are UTC, all operational intervals are half-open. IDs are stable
strings, NOT IMO numbers. All data is synthetic. Floats retain full precision.

Canonical tables live at dataset root. `historical/` contains pre-cutoff
schedule/observations and completed outcomes. `upcoming/vessel_calls.csv`
is the separate 7-day published schedule with no actual outcomes.
`simulated_future/` contains future truth, including carry-over historical
calls completed after the epoch; exclude these labels from training.

Each scenario is a separate database/dataset. Joining across scenarios
requires the scenario directory/manifest key, since common IDs are reused.

## ports.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| name | str | text | Fictional demo port name. |
| latitude | float | degrees north | Map latitude; fictional infrastructure near a coastal location. |
| longitude | float | degrees east | Map longitude. |
| timezone | str | IANA timezone | Display timezone only; storage is always UTC. |

## terminals.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| port_id | str | identifier | Owning port. FK -> ports.id. |
| name | str | text | Terminal name, unique within port. |
| yard_capacity_teu | float | TEU | Hard maximum terminal yard inventory. |
| initial_yard_teu | float | TEU | Inventory at simulation start. |
| gate_capacity_teu_per_hour | float | TEU/hour | Maximum truck/rail outflow; slowed by congestion events. |

## berths.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| terminal_id | str | identifier | Owning terminal. FK -> terminals.id. |
| length_m | float | m | Maximum supported vessel length. |
| depth_m | float | m chart datum | Water depth before tide adjustment. |
| under_keel_clearance_m | float | m | Required depth margin below vessel draft. |
| equipment | str | enum | panamax_sts or super_post_panamax_sts. |
| max_cranes | int | cranes | Maximum simultaneous assigned cranes. |

## berth_cargo_compatibility.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| berth_id | str | identifier | Compatible berth. FK -> berths.id. |
| cargo_type | str | enum | general, reefer or hazardous; one row per supported type. |

## cranes.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| berth_id | str | identifier | Fixed home berth; demo cranes do not transfer. FK -> berths.id. |
| equipment | str | enum | Equipment class; matches home berth. |
| productivity_moves_per_hour | float | moves/hour | Unimpeded single-crane handling rate. |

## vessels.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| name | str | text | Fictional vessel; one visit per generated vessel. |
| size_class | str | enum | feeder, panamax or ultra_large. |
| length_m | float | m | Vessel length overall. |
| draft_m | float | m | Operating draft for its generated visit. |
| capacity_teu | int | TEU | Nominal onboard container capacity. |
| required_equipment | str | enum | Minimum STS reach class. |
| max_cranes | int | cranes | Maximum useful assigned crane count. |

## vessel_calls.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| vessel_id | str | identifier | Visiting vessel. FK -> vessels.id. |
| terminal_id | str | identifier | Requested terminal; compatible berths exist there. FK -> terminals.id. |
| period | str | enum | historical or upcoming based on scheduled ETA. |
| scheduled_eta | time | UTC RFC3339 | Published ETA, hour-aligned. |
| priority | int | rank 1..5 | 1 is highest; same-terminal queue dispatch uses priority then actual arrival. |
| cargo_type | str | enum | general, reefer or hazardous. |
| onboard_teu | int | TEU | Onboard load, at most vessel capacity. |
| unload_moves | int | container moves | Requested discharge containers. |
| load_moves | int | container moves | Requested load containers. |
| teu_per_move | float | TEU/move | Mean size of handled containers, between 1 and 2. |

## weather.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| port_id | str | identifier | Observed port. FK -> ports.id. |
| timestamp | time | UTC RFC3339 | Hourly interval start; conditions apply for one hour. |
| period | str | enum | historical_observation or simulated_future_truth, never a real forecast. |
| wind_mps | float | m/s | Wind; >=20 closes handling and >=10 reduces productivity. |
| rain_mm_per_hour | float | mm/hour | Rain reduces handling, bounded multiplier. |
| visibility_m | float | m | Visibility; below 500 blocks vessel movement. |

## tides.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| port_id | str | identifier | Observed port. FK -> ports.id. |
| timestamp | time | UTC RFC3339 | Hourly interval start. |
| height_m | float | m chart datum | Signed semidiurnal tide height; negative height is valid. |

## crane_availability.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| crane_id | str | identifier | Affected crane. FK -> cranes.id. |
| start | time | UTC RFC3339 | Unavailable interval start, inclusive. |
| end | time | UTC RFC3339 | Unavailable interval end, exclusive. |
| reason | str | enum | maintenance or breakdown; available outside listed intervals. |
| disruption_id | str | identifier | Breakdown event; null for planned maintenance. FK -> disruptions.id. Nullable. |

## disruptions.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| port_id | str | identifier | Affected port. FK -> ports.id. |
| terminal_id | str | identifier | Affected terminal if scoped. FK -> terminals.id. Nullable. |
| crane_id | str | identifier | Affected crane for breakdown. FK -> cranes.id. Nullable. |
| call_id | str | identifier | Affected call for late arrival. FK -> vessel_calls.id. Nullable. |
| kind | str | enum | late_arrival, crane_breakdown, storm, yard_congestion or arrival_surge. |
| start | time | UTC RFC3339 | Event start. |
| end | time | UTC RFC3339 | Event end, exclusive. |
| value | float | kind-dependent | Delay hours, unavailable-crane fraction=1, storm wind m/s, gate capacity fraction, or extra-call count. |

## call_outcomes.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| call_id | str | identifier | Completed visit. FK -> vessel_calls.id. |
| berth_id | str | identifier | Actual compatible berth. FK -> berths.id. |
| period | str | enum | historical or simulated_future_truth; future labels are NOT observed training data. |
| actual_arrival | time | UTC RFC3339 | ETA plus generated late-arrival delay. |
| berth_start | time | UTC RFC3339 | Actual berth entry after queue and weather checks. |
| service_completion | time | UTC RFC3339 | End of last handling interval. |
| departure | time | UTC RFC3339 | Berth released after completion and safe weather/tide. |
| waiting_hours | float | hours | berth_start minus actual_arrival. |
| assigned_cranes | int | cranes | Fixed reserved bundle; outages pause affected units. |
| crane_hours | float | crane-hours | Sum active crane count times productive interval fraction. |

## crane_assignments.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| call_id | str | identifier | Served visit. FK -> vessel_calls.id. |
| crane_id | str | identifier | Reserved crane, compatible with outcome berth. FK -> cranes.id. |
| start | time | UTC RFC3339 | Reservation start, includes outages. |
| end | time | UTC RFC3339 | Reservation released on service completion. |

## handling_log.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| call_id | str | identifier | Active visit. FK -> vessel_calls.id. |
| timestamp | time | UTC RFC3339 | One-hour handling interval start. |
| active_cranes | int | cranes | Reserved units available during this interval. |
| base_rate | float | moves/hour | Sum productivity of active cranes. |
| weather_factor | float | ratio | Wind/rain productivity multiplier in [0,1]. |
| yard_factor | float | ratio | 1 - 0.75 * occupancy_fraction^3 before this call handles. |
| coordination_factor | float | ratio | active_cranes^-0.18, or 0 for no cranes; diminishing returns. |
| productive_fraction | float | hours | Working fraction within the hour, 0..1; capacity/demand limited. |
| handled_moves | float | moves | base_rate * factors * productive_fraction. |
| inbound_teu | float | TEU | Discharged portion of handled_moves times mean container size. |
| outbound_teu | float | TEU | Loaded portion of handled_moves times mean container size. |

## yard_snapshots.csv

| Field | Type | Unit | Meaning / relationship |
| --- | --- | --- | --- |
| id | str | identifier | Deterministic primary key, unique within this table. |
| terminal_id | str | identifier | Terminal yard. FK -> terminals.id. |
| timestamp | time | UTC RFC3339 | One-hour interval start. |
| opening_teu | float | TEU | Inventory carried from previous closing or initial inventory. |
| gate_outbound_teu | float | TEU | Truck/rail removal during interval before vessel handling. |
| inbound_teu | float | TEU | Total vessel discharges in interval. |
| outbound_teu | float | TEU | Total vessel loadings in interval. |
| closing_teu | float | TEU | Opening - gate_outbound + inbound - outbound; cannot exceed capacity. |
| queued_vessels | int | vessels | Arrived but unberthed calls at dispatch for this terminal. |

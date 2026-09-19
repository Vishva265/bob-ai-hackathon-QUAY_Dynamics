import csv
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import models as m
from app.database import make_engine, migrate
from app.optimisation.config import ObjectiveWeights, OptimisationPolicy
from app.schemas import OptimisationInput
from app.services.planning import PlanningService
from app.synthetic.simulator import parse, stamp

from .config import CUTOFF, END, SEED, TERMINALS, iso
from .prepare import planning_terminal


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def calibration_manifest():
    return {
        "classification": "CALIBRATED_NOT_REAL",
        "seed": SEED,
        "basis": {
            "terminal_count": "Representative terminal groups for spatial attribution, not surveyed operating units.",
            "berths_and_cranes": "Anchored to published Port of Los Angeles terminal and infrastructure facts; simplified for the optimizer.",
            "yard_capacity": "Deterministic planning proxy informed by published terminal acreage/storage examples.",
            "staffing": "Three eight-hour shifts; one supervisor role per task. No historical labor roster was available.",
            "weather_and_tide": "Neutral required model inputs, explicitly calibrated because this AIS package contains neither source. Twelve pre-cutoff tide observations prevent the optimizer from using its conservative missing-tide fallback.",
            "carry_in_operations": "Latest pre-cutoff berth-start per proxy berth reserves its berth and two home cranes. Remaining workload is calibrated from elapsed time and handling rate; no future departure observations are used.",
            "yard_policy": "Uses the same default safe-yard and demand-derived productivity margins as the main optimizer, rather than assuming every yard is fully saturated for all 120 hours.",
        },
        "sources": [
            "https://www.portoflosangeles.org/business/statistics/facts-and-figures",
            "https://www.portoflosangeles.org/business/terminals/container/wbct-la-til",
            "https://www.portoflosangeles.org/facilities/ter_",
        ],
        "resources": list(TERMINALS),
    }


def replay_policy():
    return OptimisationPolicy(
        weights=ObjectiveWeights(deferral=1_000_000, fairness_delay=10),
    )


def started_observations(observation_rows):
    started, departed = {}, set()
    for observation in observation_rows:
        timestamp = parse(observation["timestamp"])
        if timestamp > CUTOFF:
            continue
        if observation["kind"] == "departure":
            departed.add(observation["call_id"])
        elif observation["kind"] == "berth_start":
            previous = started.get(observation["call_id"])
            if previous is None or timestamp > parse(previous["timestamp"]):
                started[observation["call_id"]] = observation
    return {call_id: row for call_id, row in started.items() if call_id not in departed}, departed


def select_carry_in_calls(calls, observation_rows):
    terminal_ids = {terminal["id"] for terminal in TERMINALS}
    berth_counts = {terminal["id"]: terminal["berths"] for terminal in TERMINALS}
    started, departed = started_observations(observation_rows)
    calls_by_id = {call["id"]: call for call in calls}
    candidates = []
    for call_id, observation in started.items():
        call = calls_by_id.get(call_id)
        if not call:
            continue
        berth_id = observation["berth_id"] or f'{call["terminal_id"]}-B1'
        terminal_id, _, berth_number = berth_id.rpartition("-B")
        if terminal_id not in terminal_ids or not berth_number.isdigit() or int(berth_number) > berth_counts[terminal_id]:
            berth_id = f'{call["terminal_id"]}-B1'
        candidates.append((berth_id, parse(observation["timestamp"]), call_id, observation))
    selected = {}
    for berth_id, timestamp, call_id, observation in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True):
        selected.setdefault(berth_id, (call_id, observation))
    return {call_id: dict(observation, berth_id=berth_id) for berth_id, (call_id, observation) in selected.items()}, departed


def build_database(processed: Path, database: Path):
    processed, database = Path(processed).resolve(), Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True); database.unlink(missing_ok=True)
    engine = make_engine(f"sqlite:///{database.as_posix()}")
    migrate(engine)
    all_calls = rows(processed / "vessel_calls.csv")
    observation_rows = rows(processed / "vessel_call_observations.csv")
    started, departed = started_observations(observation_rows)
    # Do not trust a processed call's future-derived terminal destination.
    for call in all_calls:
        if call['id'] in started:
            terminal_id=started[call['id']]['berth_id'].rpartition('-B')[0]
            if terminal_id in {t['id'] for t in TERMINALS}:call['terminal_id']=terminal_id
        elif call['id'] not in departed:
            call['terminal_id']=planning_terminal(call['vessel_id'])
    selected_carry, _ = select_carry_in_calls(all_calls, observation_rows)
    known_observations = {}
    for observation in observation_rows:
        if parse(observation["timestamp"]) <= CUTOFF:
            known_observations.setdefault(observation["call_id"], []).append(observation)
    visible = [c for c in all_calls if parse(c["scheduled_eta"]) <= CUTOFF and c["id"] not in departed and (
        c["id"] not in started or c["id"] in selected_carry)]
    vessel_ids = {c["vessel_id"] for c in visible}
    vessel_rows = {v["id"]: v for v in rows(processed / "vessels.csv") if v["id"] in vessel_ids}
    with sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(m.Port(id="LA_LB", name="Los Angeles / Long Beach historical replay",
            latitude=33.74, longitude=-118.23, timezone="America/Los_Angeles"))
        berth_ids = {}
        for terminal in TERMINALS:
            session.add(m.Terminal(id=terminal["id"], port_id="LA_LB", name=terminal["name"],
                yard_capacity_teu=terminal["yard_teu"], initial_yard_teu=terminal["yard_teu"] * .55,
                gate_capacity_teu_per_hour=max(300, terminal["yard_teu"] / 100)))
            berth_ids[terminal["id"]] = []
            for index in range(terminal["berths"]):
                bid = f'{terminal["id"]}-B{index + 1}'
                berth_ids[terminal["id"]].append(bid)
                session.add(m.Berth(id=bid, terminal_id=terminal["id"], length_m=420,
                    depth_m=16.5, under_keel_clearance_m=1.3, equipment="super_post_panamax_sts", max_cranes=5))
                session.add(m.BerthCargoCompatibility(id=f"{bid}-general", berth_id=bid, cargo_type="general"))
            for index in range(terminal["cranes"]):
                bid = berth_ids[terminal["id"]][index % len(berth_ids[terminal["id"]])]
                session.add(m.Crane(id=f'{terminal["id"]}-C{index + 1}', berth_id=bid,
                    equipment="super_post_panamax_sts", productivity_moves_per_hour=27))
            session.add(m.YardSnapshot(id=f'{terminal["id"]}-yard-cutoff', terminal_id=terminal["id"],
                timestamp=CUTOFF - timedelta(hours=1), opening_teu=terminal["yard_teu"] * .55,
                gate_outbound_teu=terminal["yard_teu"] * .004, inbound_teu=terminal["yard_teu"] * .003,
                outbound_teu=terminal["yard_teu"] * .003, closing_teu=terminal["yard_teu"] * .55,
                queued_vessels=sum(c["terminal_id"] == terminal["id"] for c in visible)))
        session.add(m.WeatherObservation(id="LA_LB-weather-cutoff", port_id="LA_LB", timestamp=CUTOFF,
            period="historical_observation", wind_mps=4, rain_mm_per_hour=0, visibility_m=16000))
        for index in range(12):
            session.add(m.TideObservation(id=f"LA_LB-tide-{index}", port_id="LA_LB",
                timestamp=CUTOFF - timedelta(hours=11 - index), height_m=1.2))
        for vessel in vessel_rows.values():
            session.add(m.Vessel(id=vessel["id"], name=vessel["name"], size_class=vessel["size_class"],
                length_m=float(vessel["length_m"]), draft_m=float(vessel["draft_m"]),
                capacity_teu=int(vessel["capacity_teu"]), required_equipment="super_post_panamax_sts", max_cranes=4))
        for call in visible:
            session.add(m.VesselCall(id=call["id"], vessel_id=call["vessel_id"], terminal_id=call["terminal_id"],
                period="historical", scheduled_eta=parse(call["scheduled_eta"]), priority=int(call["priority"]),
                cargo_type="general", onboard_teu=int(call["onboard_teu"]), unload_moves=int(call["unload_moves"]),
                load_moves=int(call["load_moves"]), teu_per_move=float(call["teu_per_move"])))
        visible_ids = {c["id"] for c in visible}
        for observation in observation_rows:
            if observation["call_id"] in visible_ids and parse(observation["timestamp"]) <= CUTOFF:
                berth_id = (selected_carry[observation['call_id']]['berth_id']
                    if observation['kind']=='berth_start' and observation['call_id'] in selected_carry
                    else observation['berth_id'] or None)
                session.add(m.VesselCallObservation(id=observation["id"], call_id=observation["call_id"],
                    kind=observation["kind"], timestamp=parse(observation["timestamp"]),
                    berth_id=berth_id))
        call_map = {c["id"]: c for c in visible}
        crane_ids_by_berth = {}
        for terminal in TERMINALS:
            for berth_id in berth_ids[terminal["id"]]:
                crane_ids_by_berth[berth_id] = [f'{terminal["id"]}-C{index + 1}' for index in range(terminal["cranes"])
                    if berth_ids[terminal["id"]][index % len(berth_ids[terminal["id"]])] == berth_id][:2]
        for call_id, berth_observation in selected_carry.items():
            if call_id in visible_ids:
                call = call_map[call_id]
                total = int(call["unload_moves"]) + int(call["load_moves"])
                elapsed_hours = max(0, (CUTOFF - parse(berth_observation["timestamp"])).total_seconds() / 3600)
                crane_ids = crane_ids_by_berth.get(berth_observation["berth_id"]) or [f'{call["terminal_id"]}-C1']
                completed = int(elapsed_hours * 27 * max(1, len(crane_ids)) * .85)
                remaining = max(1, min(total, total - completed))
                unload_fraction = int(call["unload_moves"]) / max(1, total)
                remaining_unload = int(remaining * unload_fraction)
                session.add(m.CarryInOperation(id=f"carry-{call_id}", call_id=call_id,
                    berth_id=berth_observation["berth_id"], known_at=CUTOFF,
                    started_at=parse(berth_observation["timestamp"]), remaining_moves=remaining,
                    crane_ids=crane_ids,
                    remaining_unload_moves=remaining_unload,
                    remaining_load_moves=remaining - remaining_unload))
        session.add(m.SeedProvenance(id=1, scenario="la_lb_2021_historical_replay",
            epoch=CUTOFF, input_hash="external-noaa-ais"))
        state = session.get(m.PlanningState, 1)
        if state is None:
            session.add(m.PlanningState(id=1, revision=1))
        else:
            state.revision = 1
        session.commit()
    manifest = calibration_manifest()
    (processed / "calibration.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    engine.dispose()
    return {"visible_calls": len(visible), "visible_vessels": len(vessel_ids), "database": str(database),
        "excluded_started_call_ids": sorted(set(started)-set(selected_carry)),
        "terminal_basis": "Pre-cutoff berth observations for started work; seed-42 destination proxies for other calls. No future berth destination is a planning input."}


def serialize_plan(run):
    timestamp = lambda value: stamp(parse(value))
    observations = run.input_snapshot.get('known_call_observations', [])
    arrivals = {e['call_id'] for e in observations if e['kind'] == 'arrival'}
    started = {e['call_id'] for e in observations if e['kind'] in ('berth_start', 'departure')}
    return {
        "run_id": run.id, "as_of": timestamp(run.as_of), "end": timestamp(run.end), "status": run.status,
        "solver_status": run.solver_status, "schedule_source": run.diagnostics.get("schedule_source"),
        "diagnostics": run.diagnostics,
        "known_queue_call_ids": sorted(arrivals - started),
        "assignments": [{"call_id": a.call_id, "berth_id": a.berth_id, "start": timestamp(a.start),
            "end": timestamp(a.end), "waiting_minutes": a.waiting_minutes, "planned_moves": a.planned_moves,
            "crane_ids": sorted({c.crane_id for c in a.cranes})} for a in run.assignments],
        "shifts": [{"shift_index": s.shift_index, "start": timestamp(s.start), "end": timestamp(s.end),
            "tasks": s.tasks} for s in (run.plan.shifts if run.plan else [])],
    }


def run_replay(processed: Path, database: Path, artifact_directory: Path, time_limit=10):
    prepared = build_database(processed, database)
    engine = make_engine(f"sqlite:///{Path(database).resolve().as_posix()}")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        payload = OptimisationInput(as_of=CUTOFF, port_ids=["LA_LB"], predictor="baseline",
                                    time_limit_seconds=time_limit, policy=replay_policy())
        run = PlanningService(session).run(payload)
        session.commit(); result = serialize_plan(run)
    engine.dispose()
    artifact_directory = Path(artifact_directory).resolve(); artifact_directory.mkdir(parents=True, exist_ok=True)
    result["data_policy"] = {
        "cutoff": iso(CUTOFF), "horizon_end": iso(END),
        "planning_input": "Only calls and observations timestamped at or before the cutoff are loaded into the planning database.",
        "future_truth": "Post-cutoff AIS outcomes remain in processed CSV files and are read only by evaluation.",
        "unknown_future_arrivals": "Excluded from optimization because no historical schedule feed was supplied.",
    }
    result["prepared"] = prepared
    (artifact_directory / "plan.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def predicted_hourly(plan):
    assignments = plan["assignments"]
    rows_out = []
    total_berths = sum(t["berths"] for t in TERMINALS)
    for offset in range(72):
        timestamp = CUTOFF + timedelta(hours=offset)
        starts = {a['call_id']: parse(a['start']) for a in assignments}
        # Known backlog cannot disappear simply because the solver deferred it.
        queued = plan.get('known_queue_call_ids', list(starts))
        waiting = sum(call_id not in starts or starts[call_id] > timestamp for call_id in queued)
        occupied = sum(parse(a["start"]) <= timestamp < parse(a["end"]) for a in assignments)
        utilization = occupied / total_berths
        level = "CRITICAL" if waiting >= 4 else "HIGH" if waiting >= 2 or utilization >= .95 else "MEDIUM" if waiting or utilization >= .75 else "LOW"
        rows_out.append({"timestamp": iso(timestamp), "predicted_queue_count": waiting,
            "predicted_berth_utilization": round(utilization, 6), "predicted_congestion_level": level})
    return rows_out


def vessel_comparison(processed, plan):
    """Compare identical known demand, keeping censored waits and deferrals visible."""
    assignments = {a['call_id']: a for a in plan['assignments']}
    known = set(assignments) | set(plan.get('diagnostics', {}).get('unscheduled_call_ids', [])) | set(plan.get('known_queue_call_ids', []))
    calls = {c['id']: c for c in rows(processed / 'vessel_calls.csv')}
    vessels = {v['id']: v for v in rows(processed / 'vessels.csv')}
    compared = []
    for outcome in rows(processed / 'actual_outcomes.csv'):
        arrival = parse(outcome['actual_arrival'])
        departure = parse(outcome['departure']) if outcome['departure'] else None
        if arrival >= END or (departure and departure <= CUTOFF):
            continue
        call_id = outcome['call_id']; assignment = assignments.get(call_id)
        berth = parse(outcome['berth_start']) if outcome['berth_start'] else None
        actual_window_wait = max(0, (min(berth or END, END) - max(arrival, CUTOFF)).total_seconds() / 3600)
        proposed_window_wait = max(0, (min(parse(assignment['start']) if assignment else END, END) - max(arrival, CUTOFF)).total_seconds() / 3600) if call_id in known else None
        status = 'PROPOSED' if assignment else 'DEFERRED' if call_id in known else 'NOT_MODELLED' if arrival<=CUTOFF else 'UNKNOWN_AT_CUTOFF'
        call = calls.get(call_id, {}); vessel = vessels.get(call.get('vessel_id'), {})
        compared.append(dict(call_id=call_id, vessel_name=vessel.get('name', call_id),
            terminal_id=outcome['terminal_id'], actual_arrival=outcome['actual_arrival'],
            actual_berth_start=outcome['berth_start'] or None, actual_departure=outcome['departure'] or None,
            actual_wait_hours=float(outcome['waiting_hours']) if outcome['waiting_hours'] else None,
            actual_wait_censored=berth is None,
            proposed_berth_id=assignment['berth_id'] if assignment else None,
            proposed_start=assignment['start'] if assignment else None,
            proposed_end=assignment['end'] if assignment else None,
            proposed_wait_hours=assignment['waiting_minutes']/60 if assignment else None,
            actual_window_wait_hours=round(actual_window_wait, 6),
            proposed_window_wait_hours=round(proposed_window_wait, 6) if proposed_window_wait is not None else None,
            window_wait_change_hours=round(proposed_window_wait-actual_window_wait, 6) if proposed_window_wait is not None else None,
            status=status, known_at_cutoff=arrival<=CUTOFF, modelled_at_cutoff=call_id in known))
    return sorted(compared, key=lambda r: (not r['modelled_at_cutoff'], r['actual_arrival'], r['call_id']))


def evaluate(processed: Path, artifact_directory: Path):
    processed, artifact_directory = Path(processed), Path(artifact_directory)
    plan = json.loads((artifact_directory / "plan.json").read_text(encoding="utf-8"))
    predictions = predicted_hourly(plan)
    actual_by_time = {r["timestamp"]: r for r in rows(processed / "hourly_metrics.csv")}
    joined = []
    for predicted in predictions:
        actual = actual_by_time.get(predicted["timestamp"])
        if actual is None:
            raise ValueError('Missing withheld hourly truth at '+predicted['timestamp']+'; evaluation cannot substitute zero congestion.')
        joined.append({**predicted, "actual_queue_count": int(actual.get("queue_count", 0)),
            "actual_berth_utilization": float(actual.get("berth_utilization", 0)),
            "actual_congestion_level": actual.get("congestion_level", "LOW")})
    queue_mae = sum(abs(r["predicted_queue_count"] - r["actual_queue_count"]) for r in joined) / len(joined)
    actual_positive = [r["actual_congestion_level"] in ("HIGH", "CRITICAL") for r in joined]
    predicted_positive = [r["predicted_congestion_level"] in ("HIGH", "CRITICAL") for r in joined]
    tp = sum(a and p for a, p in zip(actual_positive, predicted_positive))
    fp = sum(not a and p for a, p in zip(actual_positive, predicted_positive))
    fn = sum(a and not p for a, p in zip(actual_positive, predicted_positive))
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    truth = {r["call_id"]: r for r in rows(processed / "actual_outcomes.csv")}
    actual_waits, errors = [], []
    for assignment in plan["assignments"]:
        outcome = truth.get(assignment["call_id"])
        if not outcome or not outcome["waiting_hours"] or not outcome["berth_start"]: continue
        berth_time = parse(outcome["berth_start"])
        if CUTOFF <= berth_time < END:
            actual_wait = float(outcome["waiting_hours"]); predicted_wait = assignment["waiting_minutes"] / 60
            actual_waits.append(actual_wait); errors.append(abs(predicted_wait - actual_wait))
    event_times = [i for i, value in enumerate(actual_positive) if value and (i == 0 or not actual_positive[i - 1])]
    leads = []
    for event in event_times:
        if predicted_positive[event]:
            warning_start = event
            while warning_start and predicted_positive[warning_start - 1]: warning_start -= 1
            leads.append(event - warning_start)
    actual_outcomes = rows(processed / "actual_outcomes.csv")
    total_wait = 0
    for outcome in actual_outcomes:
        waiting_start = max(parse(outcome["actual_arrival"]), CUTOFF)
        waiting_end = min(parse(outcome["berth_start"]) if outcome["berth_start"] else END, END)
        if waiting_end > waiting_start:
            total_wait += (waiting_end - waiting_start).total_seconds() / 3600
    diagnostics = plan.get("diagnostics", {})
    compared = vessel_comparison(processed, plan)
    matched = [r for r in compared if r['modelled_at_cutoff']]
    report = {
        "source_run_id": plan['run_id'],
        "replay": {"cutoff": iso(CUTOFF), "end": iso(END), "hours": 72},
        "vessel_comparison": compared,
        "comparison_summary": {
            "known_calls": len(matched),
            "proposed_calls": sum(r['status']=='PROPOSED' for r in matched),
            "deferred_calls": sum(r['status']=='DEFERRED' for r in matched),
            "unknown_future_calls": sum(not r['known_at_cutoff'] for r in compared),
            "excluded_known_calls": sum(r['status']=='NOT_MODELLED' for r in compared),
            "known_actual_window_wait_hours": round(sum(r['actual_window_wait_hours'] for r in matched), 6),
            "known_proposed_window_wait_hours": round(sum(r['proposed_window_wait_hours'] for r in matched), 6),
            "basis": "Same modelled calls known at cutoff; waiting accumulated only within the 72-hour horizon. Deferred calls remain queued to horizon end. Unknown future arrivals and observed calls with unresolved berth identity are excluded from proposed totals. Negative change means less proposed waiting; it is a calibrated simulation, not a realised improvement.",
        },
        "metrics": {
            "queue_count_mae": round(queue_mae, 6),
            "vessel_waiting_time_mae_hours": round(sum(errors) / len(errors), 6) if errors else None,
            "waiting_time_compared_vessels": len(errors),
            "congestion_precision": round(precision, 6), "congestion_recall": round(recall, 6),
            "congestion_f1": round(f1, 6),
            "congestion_warning_lead_time_hours": round(sum(leads) / len(leads), 6) if leads else None,
            "total_actual_vessel_waiting_hours": round(total_wait, 6),
            "actual_mean_berth_utilization": round(sum(r["actual_berth_utilization"] for r in joined) / len(joined), 6),
            "planned_mean_berth_utilization": round(sum(r["predicted_berth_utilization"] for r in joined) / len(joined), 6),
            "planned_crane_utilization": diagnostics.get("metrics", {}).get("crane_utilisation"),
            "constraint_violations": 0 if diagnostics.get("metrics", {}).get("validation_passed") else 1,
            "schedule_validation_passed": bool(diagnostics.get("metrics", {}).get("validation_passed")),
            "deferral_explanations": len(diagnostics.get("infeasibility_explanations", [])),
            "unscheduled_calls": len(diagnostics.get("unscheduled_call_ids", [])),
        },
        "interpretation": [
            "Known queued calls remain in predicted backlog when deferred. Feasible deferrals are not schedule constraint violations; a failed validation is recorded as one validation failure.",
            "Unknown post-cutoff arrivals are intentionally absent from the plan and remain present in actual AIS evaluation.",
            "A null waiting-time MAE means no planned pre-cutoff vessel obtained an AIS-derived berth start during the evaluation window.",
            "AIS-derived berth occupancy and container-vessel classification are spatial proxies, not terminal operating-system records.",
        ],
    }
    fields = list(joined[0])
    with (artifact_directory / "hourly_comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(joined)
    (artifact_directory / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

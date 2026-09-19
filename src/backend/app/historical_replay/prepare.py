import csv
import hashlib
import json
import math
import sqlite3
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import CUTOFF, END, PORT_BOUNDS, RAW_FIELDS, REGION_BOUNDS, SEED, TERMINALS, iso
from .download import daily_urls


def parse_time(value):
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def integer(value):
    value = number(value)
    return int(value) if value is not None else None


def within(lat, lon, bounds):
    south, west, north, east = bounds
    return south <= lat <= north and west <= lon <= east


def kilometres(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def terminal_at(lat, lon, sog):
    if sog is not None and sog > 3:
        return None
    nearest = min(TERMINALS, key=lambda t: kilometres(lat, lon, t["lat"], t["lon"]))
    return nearest["id"] if kilometres(lat, lon, nearest["lat"], nearest["lon"]) <= 1.8 else None


def cargo_type(code):
    return code is not None and 70 <= code <= 79


def normalized(raw):
    lookup = {key.casefold(): value for key, value in raw.items()}
    return {field: lookup.get(field.casefold(), "") for field in RAW_FIELDS}


def stage(raw_directory: Path, database: Path, progress=print, require_complete=True):
    expected = {name for _, name, _ in daily_urls()}
    available = {path.name: path for path in Path(raw_directory).glob("AIS_2021_09_*.zip") if path.name in expected}
    missing = sorted(expected - set(available))
    if require_complete and missing:
        raise FileNotFoundError(f"Missing {len(missing)} required NOAA archives: {', '.join(missing)}")
    archives = [available[name] for name in sorted(available)]
    if not archives:
        raise FileNotFoundError(f"No NOAA ZIP files found in {Path(raw_directory).resolve()}")
    database.parent.mkdir(parents=True, exist_ok=True)
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE points (mmsi TEXT, timestamp TEXT, lat REAL, lon REAL, sog REAL, cog REAL, heading REAL, vessel_name TEXT, imo TEXT, call_sign TEXT, vessel_type INTEGER, nav_status INTEGER, length_m REAL, width_m REAL, draft_m REAL, cargo INTEGER, transceiver_class TEXT, PRIMARY KEY(mmsi,timestamp,lat,lon))")
    count = 0
    try:
        for archive in archives:
            progress(f"Filtering {archive.name}")
            with zipfile.ZipFile(archive) as bundle:
                names = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
                if not names:
                    raise ValueError(f"{archive.name} contains no CSV")
                with bundle.open(names[0]) as binary:
                    import io
                    reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""))
                    batch = []
                    for source in reader:
                        row = normalized(source)
                        lat, lon = number(row["LAT"]), number(row["LON"])
                        vessel_type = integer(row["VesselType"])
                        if lat is None or lon is None or not within(lat, lon, REGION_BOUNDS) or not cargo_type(vessel_type):
                            continue
                        try:
                            timestamp = iso(parse_time(row["BaseDateTime"]))
                        except (TypeError, ValueError):
                            continue
                        mmsi = row["MMSI"].strip()
                        if not mmsi:
                            continue
                        batch.append((mmsi, timestamp, lat, lon, number(row["SOG"]), number(row["COG"]),
                            number(row["Heading"]), row["VesselName"].strip(), row["IMO"].strip(),
                            row["CallSign"].strip(), vessel_type, integer(row["Status"]), number(row["Length"]),
                            number(row["Width"]), number(row["Draft"]), integer(row["Cargo"]), row["TransceiverClass"].strip()))
                        if len(batch) == 5000:
                            connection.executemany("INSERT OR IGNORE INTO points VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                            count += len(batch); batch.clear()
                    if batch:
                        connection.executemany("INSERT OR IGNORE INTO points VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                        count += len(batch)
            connection.commit()
        connection.execute("CREATE INDEX idx_points_track ON points(mmsi,timestamp)")
        connection.execute("CREATE INDEX idx_points_time ON points(timestamp)")
        connection.commit()
        actual = connection.execute("SELECT count(*) FROM points").fetchone()[0]
        return {"candidate_rows_read": count, "unique_filtered_points": actual, "archives": len(archives)}
    finally:
        connection.close()


def size_class(length):
    if length is None: return "panamax"
    if length < 180: return "feeder"
    if length < 300: return "panamax"
    return "ultra_large"


def capacity(length):
    # Deterministic planning proxy, never a claimed vessel specification.
    if length is None: return 5000
    if length < 180: return 1800
    if length < 250: return 4500
    if length < 300: return 8000
    if length < 350: return 12000
    return 16000


def planning_terminal(vessel_id):
    """Unknown destination is an explicit reproducible proxy, never future truth."""
    index=int(hashlib.sha256(f'{SEED}:{vessel_id}'.encode()).hexdigest()[:8],16)%len(TERMINALS)
    return TERMINALS[index]['id']


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def derive(staging_database: Path, output: Path):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(staging_database); connection.row_factory = sqlite3.Row
    vessels, calls, outcomes, observations, episodes = [], [], [], [], []
    hourly = defaultdict(lambda: {"vessels": set(), "waiting": set(), "berthed": set(), "berths": set()})
    try:
        ids = [r[0] for r in connection.execute("SELECT DISTINCT mmsi FROM points ORDER BY mmsi")]
        for mmsi in ids:
            track = [dict(r) for r in connection.execute("SELECT * FROM points WHERE mmsi=? ORDER BY timestamp", (mmsi,))]
            known_track = [r for r in track if parse_time(r['timestamp'])<=CUTOFF]
            representative = max(known_track or track, key=lambda r: sum(v is not None and v != "" for v in r.values()))
            vessels.append({"id": f"AIS-{mmsi}", "mmsi": mmsi, "imo": representative["imo"],
                "call_sign": representative["call_sign"], "name": representative["vessel_name"] or f"MMSI {mmsi}",
                "size_class": size_class(representative["length_m"]), "length_m": representative["length_m"] or 240,
                "width_m": representative["width_m"] or "", "draft_m": representative["draft_m"] or 10,
                "capacity_teu": capacity(representative["length_m"]), "required_equipment": "super_post_panamax_sts",
                "max_cranes": 4, "field_classification": "mixed_real_and_calibrated"})
            states = []
            for row in track:
                ts = parse_time(row["timestamp"]); in_port = within(row["lat"], row["lon"], PORT_BOUNDS)
                terminal = terminal_at(row["lat"], row["lon"], row["sog"])
                waiting = not in_port and ((row["nav_status"] in (1, 5)) or (row["sog"] is not None and row["sog"] <= .5))
                states.append((ts, in_port, terminal, waiting, row))
                hour = ts.replace(minute=0, second=0, microsecond=0); metric = hourly[hour]
                metric["vessels"].add(mmsi)
                if waiting: metric["waiting"].add(mmsi)
                if terminal:
                    metric["berthed"].add(mmsi); metric["berths"].add(terminal)
            groups, current = [], []
            for state in states:
                if current and state[0] - current[-1][0] > timedelta(hours=12):
                    groups.append(current); current = []
                current.append(state)
            if current: groups.append(current)
            for sequence, group in enumerate(groups, 1):
                berth_points = [s for s in group if s[2]]
                waiting_points = [s for s in group if s[3]]
                if not berth_points and not waiting_points: continue
                terminal = berth_points[0][2] if berth_points else "LA_APM"
                berth_start = berth_points[0][0] if berth_points else None
                # Later anchorage observations cannot move arrival after berthing.
                arrival = min((s[0] for s in waiting_points if berth_start is None or s[0]<=berth_start), default=group[0][0])
                known_berths=[s for s in berth_points if s[0]<=CUTOFF]
                plan_terminal=known_berths[0][2] if known_berths else planning_terminal(f'AIS-{mmsi}')
                last_berth = berth_points[-1][0] if berth_points else None
                after = [s[0] for s in group if last_berth and s[0] > last_berth and not s[1]]
                departure = after[0] if after else None
                call_id = f"AIS-{mmsi}-{arrival:%Y%m%dT%H%M}-{sequence}"
                calls.append({"id": call_id, "vessel_id": f"AIS-{mmsi}", "terminal_id": plan_terminal,
                    "planning_terminal_basis": "pre_cutoff_berth_observation" if known_berths else "seeded_destination_proxy",
                    "period": "historical" if arrival <= CUTOFF else "future_truth", "scheduled_eta": iso(arrival),
                    "priority": 3, "cargo_type": "general", "onboard_teu": int(capacity(representative["length_m"]) * .65),
                    "unload_moves": max(100, int(capacity(representative["length_m"]) * .12)),
                    "load_moves": max(100, int(capacity(representative["length_m"]) * .10)), "teu_per_move": 1.6,
                    "classification": "real_identity_derived_call_calibrated_workload"})
                observations.append({"id": call_id + "-arrival", "call_id": call_id, "kind": "arrival",
                    "timestamp": iso(arrival), "berth_id": ""})
                if berth_start:
                    observations.append({"id": call_id + "-berth", "call_id": call_id, "kind": "berth_start",
                        "timestamp": iso(berth_start), "berth_id": terminal + "-B1"})
                if departure:
                    observations.append({"id": call_id + "-departure", "call_id": call_id, "kind": "departure",
                        "timestamp": iso(departure), "berth_id": terminal + "-B1"})
                waiting_hours = ((berth_start - arrival).total_seconds() / 3600) if berth_start else None
                outcomes.append({"call_id": call_id, "actual_arrival": iso(arrival),
                    "berth_start": iso(berth_start) if berth_start else "", "departure": iso(departure) if departure else "",
                    "waiting_hours": "" if waiting_hours is None else round(waiting_hours, 6),
                    "terminal_id": terminal, "source": "derived_from_noaa_ais"})
                episodes.append({"call_id": call_id, "mmsi": mmsi, "port_zone_entry": iso(min(s[0] for s in group if s[1])) if any(s[1] for s in group) else "",
                    "port_zone_exit": iso(after[0]) if after else "", "arrival": iso(arrival),
                    "berth_start": iso(berth_start) if berth_start else "", "departure": iso(departure) if departure else "",
                    "anchored_observations": len(waiting_points), "waiting_hours": "" if waiting_hours is None else round(waiting_hours, 6)})
        metric_rows = []
        for hour in sorted(hourly):
            values = hourly[hour]; queue = len(values["waiting"])
            occupied = min(len(values["berthed"]), sum(t["berths"] for t in TERMINALS))
            utilization = occupied / sum(t["berths"] for t in TERMINALS)
            level = "CRITICAL" if queue >= 4 else "HIGH" if queue >= 2 or utilization >= .95 else "MEDIUM" if queue or utilization >= .75 else "LOW"
            metric_rows.append({"timestamp": iso(hour), "hourly_vessel_count": len(values["vessels"]),
                "queue_count": queue, "berthed_vessel_count": len(values["berthed"]), "occupied_berth_proxies": occupied,
                "berth_utilization": round(utilization, 6), "congestion_level": level, "source": "derived_from_noaa_ais"})
        write_csv(output / "vessels.csv", list(vessels[0]) if vessels else ["id"], vessels)
        write_csv(output / "vessel_calls.csv", list(calls[0]) if calls else ["id"], calls)
        write_csv(output / "actual_outcomes.csv", list(outcomes[0]) if outcomes else ["call_id"], outcomes)
        write_csv(output / "vessel_call_observations.csv", list(observations[0]) if observations else ["id"], observations)
        write_csv(output / "port_episodes.csv", list(episodes[0]) if episodes else ["call_id"], episodes)
        write_csv(output / "hourly_metrics.csv", list(metric_rows[0]) if metric_rows else ["timestamp"], metric_rows)
        provenance = {"source": "NOAA Marine Cadastre 2021 daily AIS CSV", "real_fields": list(RAW_FIELDS),
            "derived_fields": ["port_zone_entry", "port_zone_exit", "arrival", "berth_start", "departure", "waiting_hours", "hourly_vessel_count", "queue_count", "berth_utilization", "congestion_level"],
            "calibrated_fields": ["terminal_id", "berth_id", "size_class", "capacity_teu", "max_cranes", "priority", "onboard_teu", "unload_moves", "load_moves", "teu_per_move"],
            "cutoff": iso(CUTOFF), "evaluation_end": iso(END), "seed": SEED,
            "limits": ["AIS cargo codes do not reliably identify container ships; berth occupancy is a spatial proxy, not terminal operating-system ground truth.",
                "Vessel metadata uses pre-cutoff messages when available. Unknown terminal destinations use a seed-42 proxy; later observed terminals remain evaluation-only.",
                "Only one carry-in can own a proxy berth. Additional observed started calls with unresolved berth identity are reported as not modelled, not future arrivals."]}
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        return {"vessels": len(vessels), "calls": len(calls), "outcomes": len(outcomes), "hours": len(metric_rows)}
    finally:
        connection.close()


def prepare(raw_directory: Path, output: Path, progress=print, require_complete=True):
    staging = Path(output) / "ais_staging.sqlite"
    staged = stage(raw_directory, staging, progress, require_complete)
    derived = derive(staging, output)
    return {**staged, **derived, "processed_directory": str(Path(output).resolve())}

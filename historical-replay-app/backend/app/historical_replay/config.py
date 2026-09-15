from datetime import datetime, timezone

START = datetime(2021, 9, 10, tzinfo=timezone.utc)
CUTOFF = datetime(2021, 9, 13, tzinfo=timezone.utc)
END = datetime(2021, 9, 16, tzinfo=timezone.utc)
DOWNLOAD_END = datetime(2021, 9, 20, tzinfo=timezone.utc)
SEED = 42

# Download filtering boundary. It deliberately includes the offshore anchorage and
# both Los Angeles and Long Beach approaches. It is a replay study boundary, not
# an official port limit.
REGION_BOUNDS = (33.25, -118.75, 34.15, -117.70)  # south, west, north, east
PORT_BOUNDS = (33.68, -118.31, 33.80, -118.12)

# Representative container-terminal centroids used only for spatial attribution
# and calibrated resources. They are not claimed as surveyed berth polygons.
TERMINALS = (
    {"id": "LA_APM", "name": "APM Pier 400 proxy", "lat": 33.7274, "lon": -118.2510,
     "berths": 6, "cranes": 19, "yard_teu": 52000},
    {"id": "LA_P300", "name": "Pier 300 proxy", "lat": 33.7388, "lon": -118.2690,
     "berths": 4, "cranes": 24, "yard_teu": 52000},
    {"id": "LA_WBCT", "name": "West Basin proxy", "lat": 33.7488, "lon": -118.2705,
     "berths": 2, "cranes": 5, "yard_teu": 24000},
    {"id": "LB_CT", "name": "Long Beach container-terminal proxy", "lat": 33.7542, "lon": -118.2030,
     "berths": 5, "cranes": 20, "yard_teu": 48000},
)

RAW_FIELDS = (
    "MMSI", "BaseDateTime", "LAT", "LON", "SOG", "COG", "Heading",
    "VesselName", "IMO", "CallSign", "VesselType", "Status", "Length",
    "Width", "Draft", "Cargo", "TransceiverClass",
)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import requests

from .config import DOWNLOAD_END, START

BASE_URL = "https://www.coast.noaa.gov/htdata/CMSP/AISDataHandler/2021"


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def daily_urls(start=START, end=DOWNLOAD_END):
    day = start
    while day.date() <= end.date():
        name = f"AIS_{day:%Y_%m_%d}.zip"
        yield day.date().isoformat(), name, f"{BASE_URL}/{name}"
        day += timedelta(days=1)


def _download_one(item, directory, overwrite, timeout, progress):
    day, name, url = item
    destination = directory / name
    if destination.exists() and not overwrite:
        return {"date": day, "file": str(destination), "status": "existing",
                "bytes": destination.stat().st_size, "sha256": file_hash(destination), "source_url": url}
    temporary = destination.with_suffix(destination.suffix + ".part")
    if overwrite:
        temporary.unlink(missing_ok=True)
    offset = temporary.stat().st_size if temporary.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    progress(f"Downloading {url}" + (f" (resuming at {offset} bytes)" if offset else ""))
    with requests.get(url, headers=headers, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        resumed = offset > 0 and response.status_code == 206
        mode = "ab" if resumed else "wb"
        if not resumed:
            offset = 0
        with temporary.open(mode) as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    size = temporary.stat().st_size
    digest = file_hash(temporary)
    temporary.replace(destination)
    return {"date": day, "file": str(destination), "status": "downloaded",
            "bytes": size, "sha256": digest, "source_url": url}


def download(directory: Path, overwrite=False, timeout=120, workers=3, progress=print):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    items = list(daily_urls())
    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_download_one, item, directory, overwrite, timeout, progress) for item in items]
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            progress(f'Ready {Path(result["file"]).name} ({result["bytes"]} bytes)')
    return sorted(results, key=lambda value: value["date"])

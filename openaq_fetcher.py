"""
openaq_fetcher.py
-----------------
Pulls REAL reference air-quality data for Pakistan from the OpenAQ v3 API and
writes it in the RAW.OPENAQ_RAW shape (one row per pollutant reading).

Flow (per the spec):
    Step 1  GET /v3/locations?iso=PK&limit=100      -> Pakistan stations
    Step 2  read each station's `sensors` list       -> sensor_id -> parameter
    Step 3  GET /v3/locations/{id}/latest            -> latest value per sensor
    (Step 4 historical /v3/sensors/{id}/measurements is optional; not needed here)

Auth: every request sends the `X-API-Key` header. Get a free key at
explore.openaq.org and put it in .env as OPENAQ_API_KEY. We sleep 1s between
calls to stay inside the free tier (60/min, 2000/hr).

NOTE: OpenAQ's public API is not reachable from every sandbox; run this on your
own laptop/network with your key. The code is defensive — it logs and skips
stations that error out rather than crashing the whole run.

Usage:
    python openaq_fetcher.py                 # CSV only
    python openaq_fetcher.py --to-snowflake  # also load RAW.OPENAQ_RAW
    python openaq_fetcher.py --limit 50
"""
import argparse
import time
import sys

import pandas as pd
import requests

import config

WANTED_PARAMS = {"pm25", "pm10", "co2"}
OUT_COLS = ["location_id", "station_name", "city", "country_code", "latitude",
            "longitude", "pollutant_type", "pollutant_value", "unit", "recorded_at"]


def _headers():
    if not config.OPENAQ_API_KEY:
        print("[error] OPENAQ_API_KEY missing. Add it to your .env file.")
        sys.exit(1)
    return {"X-API-Key": config.OPENAQ_API_KEY}


def _get(url: str, params: dict = None):
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_locations(limit: int) -> list:
    """Step 1: all OpenAQ stations in Pakistan (each already carries `sensors`)."""
    url = f"{config.OPENAQ_BASE_URL}/locations"
    params = {"iso": config.OPENAQ_COUNTRY_ISO, "limit": limit}
    data = _get(url, params)
    locations = data.get("results", [])
    print(f"[openaq] found {len(locations)} Pakistan stations")
    return locations


def fetch_latest_for_location(location_id: int) -> list:
    """Step 3: latest reading for every sensor at a station."""
    url = f"{config.OPENAQ_BASE_URL}/locations/{location_id}/latest"
    return _get(url).get("results", [])


def build_rows(locations: list) -> list:
    rows = []
    for loc in locations:
        location_id = loc.get("id")
        station_name = loc.get("name")
        # v3 uses `locality` for the town/city; fall back to station name
        city = loc.get("locality") or loc.get("name")
        country = (loc.get("country") or {}).get("code", config.OPENAQ_COUNTRY_ISO)
        coords = loc.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")

        # Step 2: map each sensor id -> (parameter name, units) from the station
        sensor_map = {}
        for s in loc.get("sensors", []):
            p = s.get("parameter", {})
            sensor_map[s.get("id")] = (p.get("name"), p.get("units"))

        try:
            latest = fetch_latest_for_location(location_id)
        except Exception as e:
            print(f"[warn] station {location_id} latest failed: {e}")
            time.sleep(config.OPENAQ_RATE_SLEEP)
            continue

        for m in latest:
            sid = m.get("sensorsId") or m.get("sensors_id")
            pname, punit = sensor_map.get(sid, (None, None))
            if pname not in WANTED_PARAMS:
                continue
            dt = m.get("datetime") or {}
            rows.append({
                "location_id": location_id,
                "station_name": station_name,
                "city": city,
                "country_code": country,
                "latitude": lat, "longitude": lon,
                "pollutant_type": pname,
                "pollutant_value": m.get("value"),
                "unit": punit,
                "recorded_at": dt.get("utc") or dt.get("local"),
            })

        time.sleep(config.OPENAQ_RATE_SLEEP)  # respect the rate limit
    return rows


def main():
    ap = argparse.ArgumentParser(description="OpenAQ v3 Pakistan fetcher")
    ap.add_argument("--limit", type=int, default=100, help="max stations")
    ap.add_argument("--to-snowflake", action="store_true")
    args = ap.parse_args()

    locations = fetch_locations(args.limit)
    rows = build_rows(locations)
    df = pd.DataFrame(rows, columns=OUT_COLS)
    df.to_csv(config.OPENAQ_CSV, index=False)
    print(f"[done] wrote {len(df)} pollutant readings to {config.OPENAQ_CSV}")

    if args.to_snowflake:
        if not config.snowflake_ready():
            print("[warn] Snowflake creds missing; skipping load.")
        elif not df.empty:
            import snowflake_utils as sf
            sf.load_dataframe(df, "RAW", "OPENAQ_RAW")


if __name__ == "__main__":
    main()

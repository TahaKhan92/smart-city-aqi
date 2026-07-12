"""
iot_simulator.py
----------------
Simulates 10 IoT air-quality sensors (2 per city) with realistic behaviour:

  * zone-based pollution baselines (industrial > traffic > residential > park)
  * time-of-day effect (traffic peaks ~8am and ~6pm) via a sine wave
  * +/- 15% random noise on every reading
  * 15% chance of an anomaly spike (PM2.5 x 2.5-4.0) = real pollution events
  * EPA AQI computed from PM2.5 (shared aqi_utils, same maths as the ETL)

Every loop = 1 reading per sensor (10 rows) every 10 seconds. Rows are appended
to data/iot_readings.csv and, if Snowflake creds are present and enabled,
inserted straight into RAW.IOT_READINGS.

Usage:
    python iot_simulator.py                 # run 30 min, CSV only
    python iot_simulator.py --minutes 2     # short test run
    python iot_simulator.py --to-snowflake  # also insert into Bronze
"""
import argparse
import csv
import math
import random
import signal
import sys
import time
from datetime import datetime, timezone

import config
from aqi_utils import calculate_aqi, classify

FIELDS = ["sensor_id", "city", "zone_type", "pm25", "pm10", "co2_ppm",
          "temperature_c", "humidity_pct", "wind_speed_kmh", "aqi_value",
          "severity", "recorded_at"]

_running = True  # flipped by Ctrl+C for a clean shutdown


def _time_of_day_factor(now: datetime) -> float:
    """Peaks (~1.3x) around 8am and 6pm, dips at night. Spec formula."""
    hour = now.hour + now.minute / 60.0
    return 1.0 + 0.3 * math.sin((hour - 8) * math.pi / 12)


def generate_reading(sensor: dict, now: datetime) -> dict:
    """Build one realistic reading for a single sensor."""
    zone = sensor["zone_type"]
    pm_lo, pm_hi, co2_lo, co2_hi, t_lo, t_hi = config.ZONE_RANGES[zone]
    tod = _time_of_day_factor(now)

    def noisy(value):
        return value * (1 + random.uniform(-config.NOISE_PCT, config.NOISE_PCT))

    # PM2.5: base -> time-of-day -> noise
    pm25 = noisy(random.uniform(pm_lo, pm_hi) * tod)

    # 15% chance of a pollution spike
    if random.random() < config.ANOMALY_CHANCE:
        pm25 *= random.uniform(config.ANOMALY_MIN, config.ANOMALY_MAX)

    pm25 = round(min(pm25, 500.0), 1)                 # clamp to sensor ceiling
    pm10 = round(pm25 * random.uniform(1.1, 1.6), 1)  # pm10 always >= pm25
    pm10 = min(pm10, 600.0)

    co2 = round(min(max(noisy(random.uniform(co2_lo, co2_hi) * tod), 400), 2000), 1)
    temp = round(random.uniform(t_lo, t_hi), 1)
    humidity = round(random.uniform(10, 90), 1)
    wind = round(random.uniform(0, 60), 1)

    aqi = calculate_aqi(pm25)
    _, severity, _ = classify(pm25)

    return {
        "sensor_id": sensor["sensor_id"],
        "city": sensor["city"],
        "zone_type": zone,
        "pm25": pm25, "pm10": pm10, "co2_ppm": co2,
        "temperature_c": temp, "humidity_pct": humidity, "wind_speed_kmh": wind,
        "aqi_value": aqi, "severity": severity,
        "recorded_at": now.isoformat(),
    }


def _handle_sigint(signum, frame):
    global _running
    _running = False
    print("\n[stop] Ctrl+C received — finishing current batch and exiting...")


def main():
    ap = argparse.ArgumentParser(description="Smart City IoT AQI simulator")
    ap.add_argument("--minutes", type=float, default=config.DEFAULT_RUN_MINUTES,
                    help="how long to run (default 30)")
    ap.add_argument("--interval", type=float, default=config.READING_INTERVAL_SEC,
                    help="seconds between batches (default 10)")
    ap.add_argument("--to-snowflake", action="store_true",
                    help="also insert each batch into RAW.IOT_READINGS")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _handle_sigint)

    sf = None
    if args.to_snowflake:
        if not config.snowflake_ready():
            print("[warn] --to-snowflake set but Snowflake creds missing; CSV only.")
        else:
            import snowflake_utils as sf  # lazy import (heavy dependency)

    # open CSV once, write header if new
    new_file = not config.IOT_CSV.exists()
    fh = open(config.IOT_CSV, "a", newline="")
    writer = csv.DictWriter(fh, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()

    deadline = time.time() + args.minutes * 60
    batch_no, total = 0, 0
    print(f"[start] simulating {len(config.SENSORS)} sensors for {args.minutes} min "
          f"(every {args.interval}s) -> {config.IOT_CSV.name}")

    while _running and time.time() < deadline:
        now = datetime.now(timezone.utc)
        rows = [generate_reading(s, now) for s in config.SENSORS]
        writer.writerows(rows)
        fh.flush()
        total += len(rows)
        batch_no += 1

        # print any dangerous readings as they happen
        for r in rows:
            if r["severity"] in ("UNHEALTHY", "VERY UNHEALTHY", "HAZARDOUS"):
                print(f"  ALERT {r['city']:<9} {r['sensor_id']}  "
                      f"PM2.5={r['pm25']:>5}  AQI={r['aqi_value']:>5}  {r['severity']}")

        if sf:
            try:
                sf.load_records("RAW", "IOT_READINGS", rows, FIELDS)
            except Exception as e:
                print(f"[warn] Snowflake insert failed (continuing on CSV): {e}")

        print(f"[batch {batch_no}] {len(rows)} readings  |  total={total}")
        if _running and time.time() < deadline:
            time.sleep(args.interval)

    fh.close()
    print(f"[done] wrote {total} readings to {config.IOT_CSV}")


if __name__ == "__main__":
    main()

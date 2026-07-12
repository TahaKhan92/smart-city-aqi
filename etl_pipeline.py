"""
etl_pipeline.py
---------------
Bronze -> Silver transform in Pandas. Reads both raw sources, cleans and
validates each, enriches with AQI category + health risk, unions them into one
tidy CLEAN.AQI_CLEAN shape, and writes data/aqi_clean.csv (and optionally loads
Snowflake CLEAN.AQI_CLEAN).

Reads from local CSVs by default (offline-friendly for demos). Use --from-snowflake
to read the RAW tables instead.

IoT rules:   drop null pm25/aqi_value; validate pm25 0-500, co2 400-2000,
             humidity 0-100; add aqi_category + health_risk; dedupe on
             (sensor_id, recorded_at); add processed_at.
OpenAQ rules: keep pm25/pm10 only; UTC timestamps; drop value<=0; pivot to wide
             (pm25/pm10 columns); source='openaq_v3'; country_code='PK'.

Usage:
    python etl_pipeline.py                  # CSV in -> CSV out
    python etl_pipeline.py --to-snowflake   # also load CLEAN.AQI_CLEAN
    python etl_pipeline.py --from-snowflake # read RAW.* from Snowflake
"""
import argparse

import numpy as np
import pandas as pd

import config
from aqi_utils import calculate_aqi, classify, category_from_aqi, nearest_city

SILVER_COLS = ["source", "city", "sensor_id", "pm25", "pm10", "co2_ppm",
               "aqi_value", "aqi_category", "health_risk", "latitude",
               "longitude", "recorded_at"]


# ---------------------------------------------------------------------------
# IoT: Bronze -> Silver
# ---------------------------------------------------------------------------
def transform_iot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=SILVER_COLS)

    df = df.copy()
    # 1) drop rows missing the essentials
    df = df.dropna(subset=["pm25", "aqi_value"])
    # 2) range validation
    df = df[df["pm25"].between(0, 500)]
    df = df[df["co2_ppm"].between(400, 2000)]
    df = df[df["humidity_pct"].between(0, 100)]
    # 3) enrich: recompute category + health risk from pm25 (single source of truth)
    cls = df["pm25"].apply(classify)
    df["aqi_category"] = cls.apply(lambda t: t[0])
    df["health_risk"] = cls.apply(lambda t: t[2])
    # 4) dedupe on (sensor_id, recorded_at)
    df = df.drop_duplicates(subset=["sensor_id", "recorded_at"], keep="last")
    # 5) coordinates from city centroid so the map visual works
    df["latitude"] = df["city"].map(lambda c: config.CITY_COORDS.get(c, (None, None))[0])
    df["longitude"] = df["city"].map(lambda c: config.CITY_COORDS.get(c, (None, None))[1])
    df["source"] = "iot_simulator"

    out = df[["source", "city", "sensor_id", "pm25", "pm10", "co2_ppm",
              "aqi_value", "aqi_category", "health_risk", "latitude",
              "longitude", "recorded_at"]].copy()
    return out


# ---------------------------------------------------------------------------
# OpenAQ: Bronze -> Silver  (long -> wide pivot, then derive AQI)
# ---------------------------------------------------------------------------
def transform_openaq(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=SILVER_COLS)

    df = df.copy()
    df = df[df["pollutant_type"].isin(["pm25", "pm10"])]     # pm25/pm10 only
    df = df[df["pollutant_value"] > 0]                        # drop <=0
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["recorded_at"])

    keys = ["location_id", "station_name", "city", "country_code",
            "latitude", "longitude", "recorded_at"]
    wide = (df.pivot_table(index=keys, columns="pollutant_type",
                           values="pollutant_value", aggfunc="mean")
              .reset_index())
    if "pm25" not in wide:
        wide["pm25"] = np.nan
    if "pm10" not in wide:
        wide["pm10"] = np.nan

    # derive AQI from pm25 where available
    wide["aqi_value"] = wide["pm25"].apply(lambda v: calculate_aqi(v) if pd.notna(v) else None)
    cat = wide["aqi_value"].apply(lambda a: category_from_aqi(a) if pd.notna(a) else (None, None, None))
    wide["aqi_category"] = cat.apply(lambda t: t[0])
    wide["health_risk"] = cat.apply(lambda t: t[2])

    # OpenAQ's `locality`/station-name city field is often a building or area
    # name (e.g. "BUITEMS", "WASA Head Office"), not one of our 5 target
    # cities. Snap each row to the nearest hackathon city using its
    # lat/lon instead of trusting that text field.
    wide["city"] = wide.apply(lambda r: nearest_city(r["latitude"], r["longitude"]), axis=1)
    wide = wide.dropna(subset=["city"])

    wide["source"] = "openaq_v3"
    wide["sensor_id"] = None            # NULL for OpenAQ rows (per spec)
    wide["co2_ppm"] = np.nan
    wide["recorded_at"] = wide["recorded_at"].astype(str)

    out = wide[["source", "city", "sensor_id", "pm25", "pm10", "co2_ppm",
                "aqi_value", "aqi_category", "health_risk", "latitude",
                "longitude", "recorded_at"]].copy()
    return out


def run(from_snowflake: bool = False, to_snowflake: bool = False):
    if from_snowflake:
        import snowflake_utils as sf
        iot = sf.query("SELECT * FROM RAW.IOT_READINGS")
        iot.columns = [c.lower() for c in iot.columns]
        openaq = sf.query("SELECT * FROM RAW.OPENAQ_RAW")
        openaq.columns = [c.lower() for c in openaq.columns]
    else:
        iot = pd.read_csv(config.IOT_CSV) if config.IOT_CSV.exists() else pd.DataFrame()
        openaq = pd.read_csv(config.OPENAQ_CSV) if config.OPENAQ_CSV.exists() else pd.DataFrame()

    iot_clean = transform_iot(iot)
    openaq_clean = transform_openaq(openaq)

    silver = pd.concat([iot_clean, openaq_clean], ignore_index=True)
    # normalize timestamps so Snowflake gets a clean datetime (not mixed str/int).
    # format="mixed" is required here because IoT rows use isoformat()
    # ("...+00:00") while OpenAQ rows use a "...Z" suffix — without it, pandas
    # can silently turn valid timestamps into NaT instead of raising an error.
    before = len(silver)
    silver["recorded_at"] = pd.to_datetime(
        silver["recorded_at"], utc=True, errors="coerce", format="mixed"
    )
    dropped = silver["recorded_at"].isna().sum()
    if dropped:
        print(f"[warn] {dropped}/{before} rows had an unparseable recorded_at (set to NaT)")
    silver["processed_at"] = pd.Timestamp.now("UTC")
    silver.to_csv(config.CLEAN_CSV, index=False)

    print(f"[etl] IoT rows: {len(iot_clean)}  |  OpenAQ rows: {len(openaq_clean)}  "
          f"|  Silver total: {len(silver)}")
    print(f"[etl] wrote {config.CLEAN_CSV}")

    if to_snowflake:
        if not config.snowflake_ready():
            print("[warn] Snowflake creds missing; skipping load.")
        else:
            import snowflake_utils as sf
            sf.load_dataframe(silver, "CLEAN", "AQI_CLEAN")

    return silver


def main():
    ap = argparse.ArgumentParser(description="IoT + OpenAQ -> Silver ETL")
    ap.add_argument("--from-snowflake", action="store_true")
    ap.add_argument("--to-snowflake", action="store_true")
    args = ap.parse_args()
    run(from_snowflake=args.from_snowflake, to_snowflake=args.to_snowflake)


if __name__ == "__main__":
    main()
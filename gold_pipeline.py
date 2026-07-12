"""
gold_pipeline.py
-----------------
Silver -> Gold transform. Reads CLEAN.AQI_CLEAN (either from Snowflake or the
local data/aqi_clean.csv written by etl_pipeline.py), aggregates it into one
row per (city, report_date), and writes ANALYTICS.CITY_DAILY.

Aggregates per the spec:
    avg_aqi, max_aqi, min_aqi   -> from aqi_value
    avg_pm25, avg_co2           -> from pm25 / co2_ppm
    dominant_risk                -> most common health_risk that day
    reading_count                -> total rows from both sources

Usage:
    python gold_pipeline.py                   # CSV in -> CSV out
    python gold_pipeline.py --to-snowflake    # also load ANALYTICS.CITY_DAILY
    python gold_pipeline.py --from-snowflake  # read CLEAN.AQI_CLEAN from Snowflake
"""
import argparse

import pandas as pd

import config

GOLD_COLS = ["city", "report_date", "avg_aqi", "max_aqi", "min_aqi",
             "avg_pm25", "avg_co2", "dominant_risk", "reading_count"]


def _dominant_risk(series: pd.Series):
    """Most frequent health_risk value for the group (ignores nulls)."""
    clean = series.dropna()
    if clean.empty:
        return None
    return clean.mode().iloc[0]  # mode() can return multiple ties; take the first


def build_gold(silver: pd.DataFrame, recent_days: int = None) -> pd.DataFrame:
    if silver.empty:
        return pd.DataFrame(columns=GOLD_COLS)

    df = silver.copy()
    # recorded_at may already be datetime (from etl_pipeline) or a string
    # (if read back from CSV) — normalize either way before grouping.
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["recorded_at"])

    # OpenAQ "latest" readings can come from stations that haven't reported in
    # months/years, spreading rows across many old dates. For a clean,
    # demo-friendly dashboard, optionally keep only the last N days.
    if recent_days is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(f"{int(recent_days)}D")
        before = len(df)
        df = df[df["recorded_at"] >= cutoff]
        print(f"[gold] recent_days={recent_days}: kept {len(df)}/{before} silver rows")

    df["report_date"] = df["recorded_at"].dt.date

    grouped = (
        df.groupby(["city", "report_date"])
          .agg(
              avg_aqi=("aqi_value", "mean"),
              max_aqi=("aqi_value", "max"),
              min_aqi=("aqi_value", "min"),
              avg_pm25=("pm25", "mean"),
              avg_co2=("co2_ppm", "mean"),
              dominant_risk=("health_risk", _dominant_risk),
              reading_count=("city", "size"),
          )
          .reset_index()
    )

    # round the float columns for a tidier dashboard
    for col in ("avg_aqi", "max_aqi", "min_aqi", "avg_pm25", "avg_co2"):
        grouped[col] = grouped[col].round(1)

    return grouped[GOLD_COLS]


def run(from_snowflake: bool = False, to_snowflake: bool = False, recent_days: int = None):
    if from_snowflake:
        import snowflake_utils as sf
        silver = sf.query("SELECT * FROM CLEAN.AQI_CLEAN")
        silver.columns = [c.lower() for c in silver.columns]
    else:
        silver = pd.read_csv(config.CLEAN_CSV) if config.CLEAN_CSV.exists() else pd.DataFrame()

    gold = build_gold(silver, recent_days=recent_days)
    gold.to_csv(config.GOLD_CSV, index=False)

    print(f"[gold] cities x days: {len(gold)} rows  (from {len(silver)} silver rows)")
    print(f"[gold] wrote {config.GOLD_CSV}")

    if to_snowflake:
        if not config.snowflake_ready():
            print("[warn] Snowflake creds missing; skipping load.")
        elif gold.empty:
            print("[warn] Gold dataframe is empty; nothing to load.")
        else:
            import snowflake_utils as sf
            sf.load_dataframe(gold, "ANALYTICS", "CITY_DAILY")

    return gold


def main():
    ap = argparse.ArgumentParser(description="Silver -> Gold daily aggregation")
    ap.add_argument("--from-snowflake", action="store_true")
    ap.add_argument("--to-snowflake", action="store_true")
    ap.add_argument("--recent-days", type=int, default=None,
                     help="only keep silver rows from the last N days (e.g. 2)")
    args = ap.parse_args()
    run(from_snowflake=args.from_snowflake, to_snowflake=args.to_snowflake,
        recent_days=args.recent_days)


if __name__ == "__main__":
    main()          
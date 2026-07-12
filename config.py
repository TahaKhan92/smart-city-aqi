"""
config.py
---------
Single source of truth for the whole pipeline: sensor network, zone-based
pollution ranges, EPA AQI breakpoints, city coordinates, file paths, and all
environment-driven settings (Snowflake creds + OpenAQ key).

Nothing here should be hardcoded elsewhere — import from this file so the
simulator, ETL and dashboard all stay perfectly consistent.
"""
import os
from pathlib import Path

try:
    # optional: load a local .env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

IOT_CSV = DATA_DIR / "iot_readings.csv"
OPENAQ_CSV = DATA_DIR / "openaq_raw.csv"
CLEAN_CSV = DATA_DIR / "aqi_clean.csv"
GOLD_CSV = DATA_DIR / "city_daily.csv"

# ---------------------------------------------------------------------------
# Sensor network (exactly as per the hackathon spec)
#   id, city, zone_type, base_level (label only)
# ---------------------------------------------------------------------------
SENSORS = [
    {"sensor_id": "PKS_KHI_IND_01", "city": "Karachi",   "zone_type": "industrial"},
    {"sensor_id": "PKS_KHI_TRF_02", "city": "Karachi",   "zone_type": "traffic"},
    {"sensor_id": "PKS_LHR_RES_01", "city": "Lahore",    "zone_type": "residential"},
    {"sensor_id": "PKS_LHR_IND_02", "city": "Lahore",    "zone_type": "industrial"},
    {"sensor_id": "PKS_ISB_PRK_01", "city": "Islamabad", "zone_type": "park"},
    {"sensor_id": "PKS_ISB_TRF_02", "city": "Islamabad", "zone_type": "traffic"},
    {"sensor_id": "PKS_PEW_IND_01", "city": "Peshawar",  "zone_type": "industrial"},
    {"sensor_id": "PKS_PEW_RES_02", "city": "Peshawar",  "zone_type": "residential"},
    {"sensor_id": "PKS_MUL_TRF_01", "city": "Multan",    "zone_type": "traffic"},
    {"sensor_id": "PKS_MUL_PRK_02", "city": "Multan",    "zone_type": "park"},
]

# Zone-based base ranges: (pm25_lo, pm25_hi, co2_lo, co2_hi, temp_lo, temp_hi)
ZONE_RANGES = {
    "industrial":  (80, 120, 600, 900, 30, 42),
    "traffic":     (55,  80, 500, 700, 28, 40),
    "residential": (25,  50, 420, 500, 25, 38),
    "park":        ( 8,  20, 400, 430, 22, 35),
}

# City centroids — used to give IoT rows coordinates so the map visual works
CITY_COORDS = {
    "Karachi":   (24.8607, 67.0011),
    "Lahore":    (31.5204, 74.3587),
    "Islamabad": (33.6844, 73.0479),
    "Peshawar":  (34.0151, 71.5249),
    "Multan":    (30.1575, 71.5249),
}

# ---------------------------------------------------------------------------
# EPA PM2.5 -> AQI breakpoints
#   (conc_lo, conc_hi, aqi_lo, aqi_hi, category, severity, health_risk)
# ---------------------------------------------------------------------------
EPA_BREAKPOINTS = [
    (0.0,   12.0,   0,   50,  "Good",                    "GOOD",                    "LOW"),
    (12.1,  35.4,   51,  100, "Moderate",                "MODERATE",                "LOW"),
    (35.5,  55.4,   101, 150, "Unhealthy for Sensitive", "UNHEALTHY FOR SENSITIVE", "MEDIUM"),
    (55.5,  150.4,  151, 200, "Unhealthy",               "UNHEALTHY",               "HIGH"),
    (150.5, 250.4,  201, 300, "Very Unhealthy",          "VERY UNHEALTHY",          "HIGH"),
    (250.5, 500.4,  301, 500, "Hazardous",               "HAZARDOUS",               "CRITICAL"),
]

# ---------------------------------------------------------------------------
# Simulator behaviour
# ---------------------------------------------------------------------------
NOISE_PCT = 0.15          # +/- 15% random noise
ANOMALY_CHANCE = 0.15     # 15% chance of a pollution spike
ANOMALY_MIN, ANOMALY_MAX = 2.5, 4.0
READING_INTERVAL_SEC = 10
DEFAULT_RUN_MINUTES = 30

# ---------------------------------------------------------------------------
# OpenAQ
# ---------------------------------------------------------------------------
OPENAQ_BASE_URL = "https://api.openaq.org/v3"
OPENAQ_API_KEY = os.environ.get("OPENAQ_API_KEY", "")
OPENAQ_COUNTRY_ISO = "PK"
OPENAQ_RATE_SLEEP = 1.0   # seconds between calls (free tier: 60/min)

# ---------------------------------------------------------------------------
# Snowflake (read from environment — never hardcode)
# ---------------------------------------------------------------------------
SNOWFLAKE = {
    "account":   os.environ.get("SNOWFLAKE_ACCOUNT", ""),
    "user":      os.environ.get("SNOWFLAKE_USER", ""),
    "password":  os.environ.get("SNOWFLAKE_PASSWORD", ""),
    "role":      os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    "database":  os.environ.get("SNOWFLAKE_DATABASE", "SMART_CITY_AQI"),
}

def snowflake_ready() -> bool:
    """True only if the essential Snowflake creds are present."""
    s = SNOWFLAKE
    return bool(s["account"] and s["user"] and s["password"])

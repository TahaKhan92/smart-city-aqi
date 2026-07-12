# Smart City Air Quality Monitoring System 🌫️

End-to-end data engineering pipeline that monitors air quality across five
Pakistani cities — **Karachi, Lahore, Islamabad, Peshawar, Multan** — by
combining simulated IoT sensor data with real reference data from the
**OpenAQ v3** API, processing it through a **Snowflake medallion architecture**
(Bronze → Silver → Gold), and serving it on an interactive **Streamlit**
dashboard.

---

## Architecture

```
 Source 1: IoT Simulator (Python) ─┐
   10 sensors, 2 per city          │
   reading every 10s               │        ┌── RAW.IOT_READINGS ─┐
                                    ├─ Bronze┤                     │
 Source 2: OpenAQ v3 API ──────────┘        └── RAW.OPENAQ_RAW ────┤
   real PK station data                                            │
                                                                   ▼
                                              Python ETL (Pandas): clean,
                                              validate, tag AQI, dedupe, union
                                                                   │
                                                          Silver ──▼
                                                     CLEAN.AQI_CLEAN
                                                                   │
                                              SQL aggregation (per city/day)
                                                                   │
                                                          Gold ────▼
                                                   ANALYTICS.CITY_DAILY
                                                                   │
                                                                   ▼
                                              Streamlit dashboard (KPIs,
                                              bar, line, map, severity table)
```

Both sources load **independently** into Bronze. Silver validates, enriches and
unions them. Gold aggregates per city per day for the dashboard KPIs.

---

## Project structure

```
smart-city-aqi/
├── config.py            # sensors, zone ranges, EPA breakpoints, env, paths
├── aqi_utils.py         # EPA AQI formula + category/health-risk mapping (shared)
├── iot_simulator.py     # Source 1 — IoT sensor simulator
├── openaq_fetcher.py    # Source 2 — OpenAQ v3 API fetcher
├── etl_pipeline.py      # Bronze → Silver transform (Pandas)
├── snowflake_utils.py   # Snowflake connection / load / query helpers
├── sql/
│   └── snowflake_schema.sql   # DDL + Bronze→Silver + Silver→Gold
├── dashboard/
│   └── app.py           # Streamlit dashboard (Snowflake or CSV fallback)
├── data/                # CSV outputs (git-ignored, created at runtime)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

```bash
# 1. clone + enter
git clone <your-repo-url> && cd smart-city-aqi

# 2. virtual env (optional but recommended)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. install
pip install -r requirements.txt

# 4. configure credentials
cp .env.example .env        # then edit .env with your OpenAQ key + Snowflake creds
```

Get a free OpenAQ key at <https://explore.openaq.org/register>.

---

## How to run (full pipeline)

```bash
# 0) create the Snowflake schema (run once, in a Snowflake worksheet
#    OR: python -c "import snowflake_utils as s; s.run_sql_file('sql/snowflake_schema.sql')")

# 1) Source 1 — generate IoT data (30 min for the hackathon; add --to-snowflake to load Bronze)
python iot_simulator.py --minutes 30 --to-snowflake

# 2) Source 2 — fetch real OpenAQ Pakistan data (run on your own network)
python openaq_fetcher.py --to-snowflake

# 3) ETL — Bronze → Silver (CLEAN.AQI_CLEAN)
python etl_pipeline.py --to-snowflake          # or --from-snowflake to read RAW.* first

# 4) Gold — run the Silver→Gold INSERT at the bottom of sql/snowflake_schema.sql

# 5) Dashboard
streamlit run dashboard/app.py
```

### Run it without Snowflake (offline demo)
Every script writes to `data/*.csv`, and both the ETL and the dashboard read
those CSVs when Snowflake creds are absent. So you can demo the whole flow with
zero cloud setup:

```bash
python iot_simulator.py --minutes 2      # writes data/iot_readings.csv
python openaq_fetcher.py                 # writes data/openaq_raw.csv (needs OpenAQ key)
python etl_pipeline.py                   # writes data/aqi_clean.csv
streamlit run dashboard/app.py           # reads the CSVs, builds Gold on the fly
```

---

## Data model

| Layer | Object | Purpose |
|-------|--------|---------|
| Bronze | `RAW.IOT_READINGS` | raw simulated sensor readings, as-is |
| Bronze | `RAW.OPENAQ_RAW` | raw OpenAQ pollutant readings, as-is |
| Silver | `CLEAN.AQI_CLEAN` | validated + enriched, unified from both sources |
| Gold | `ANALYTICS.CITY_DAILY` | daily per-city aggregates for the dashboard |

**AQI** is computed from PM2.5 using the EPA linear-interpolation formula
(`aqi_utils.py`), and every row is tagged with an `aqi_category`
(Good … Hazardous) and a `health_risk` (LOW / MEDIUM / HIGH / CRITICAL).

---

## Dashboard

- **Metric cards** — highest-AQI city, total readings, % CRITICAL, avg PM2.5
- **Bar chart** — average AQI per city
- **Map** — cities coloured by AQI
- **Line chart** — AQI trend per sensor, last 6 hours
- **Severity table** — latest readings with colour-coded badges

---

## Submission deliverables checklist

- [x] IoT simulator script (`iot_simulator.py`)
- [x] OpenAQ fetcher (`openaq_fetcher.py`)
- [x] ETL pipeline (`etl_pipeline.py`)
- [x] Snowflake SQL (`sql/snowflake_schema.sql`)
- [x] Dashboard (`dashboard/app.py`)
- [x] README (this file)
- [ ] Screenshots of all 6 deliverables
- [ ] 5-minute live demo (run simulator → data into Snowflake → open dashboard)

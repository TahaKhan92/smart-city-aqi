-- ============================================================================
-- Smart City AQI — Snowflake Medallion Schema (Bronze / Silver / Gold)
-- Run this ONCE in a Snowflake worksheet before loading any data.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS SMART_CITY_AQI;
CREATE SCHEMA  IF NOT EXISTS SMART_CITY_AQI.RAW;        -- Bronze
CREATE SCHEMA  IF NOT EXISTS SMART_CITY_AQI.CLEAN;      -- Silver
CREATE SCHEMA  IF NOT EXISTS SMART_CITY_AQI.ANALYTICS;  -- Gold

USE DATABASE SMART_CITY_AQI;

-- ---------------------------------------------------------------------------
-- BRONZE — raw, as-is
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW.IOT_READINGS (
    reading_id      NUMBER AUTOINCREMENT PRIMARY KEY,
    sensor_id       VARCHAR(30),
    city            VARCHAR(100),
    zone_type       VARCHAR(30),
    pm25            FLOAT,
    pm10            FLOAT,
    co2_ppm         FLOAT,
    temperature_c   FLOAT,
    humidity_pct    FLOAT,
    wind_speed_kmh  FLOAT,
    aqi_value       FLOAT,
    severity        VARCHAR(30),
    recorded_at     TIMESTAMP_NTZ,
    ingested_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE RAW.OPENAQ_RAW (
    raw_id          NUMBER AUTOINCREMENT PRIMARY KEY,
    location_id     INTEGER,
    station_name    VARCHAR(200),
    city            VARCHAR(100),
    country_code    VARCHAR(5),
    latitude        FLOAT,
    longitude       FLOAT,
    pollutant_type  VARCHAR(20),
    pollutant_value FLOAT,
    unit            VARCHAR(20),
    recorded_at     TIMESTAMP_NTZ,
    ingested_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ---------------------------------------------------------------------------
-- SILVER — validated + enriched (unified from both sources)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE CLEAN.AQI_CLEAN (
    clean_id      NUMBER AUTOINCREMENT PRIMARY KEY,
    source        VARCHAR(20),        -- iot_simulator | openaq_v3
    city          VARCHAR(100),
    sensor_id     VARCHAR(30),        -- NULL for OpenAQ rows
    pm25          FLOAT,
    pm10          FLOAT,
    co2_ppm       FLOAT,
    aqi_value     FLOAT,
    aqi_category  VARCHAR(40),
    health_risk   VARCHAR(10),        -- LOW | MEDIUM | HIGH | CRITICAL
    latitude      FLOAT,
    longitude     FLOAT,
    recorded_at   TIMESTAMP_NTZ,
    processed_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ---------------------------------------------------------------------------
-- GOLD — daily aggregates per city (dashboard KPIs)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE ANALYTICS.CITY_DAILY (
    daily_id      NUMBER AUTOINCREMENT PRIMARY KEY,
    city          VARCHAR(100),
    report_date   DATE,
    avg_aqi       FLOAT,
    max_aqi       FLOAT,
    min_aqi       FLOAT,
    avg_pm25      FLOAT,
    avg_co2       FLOAT,
    dominant_risk VARCHAR(10),
    reading_count NUMBER,
    created_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


-- ============================================================================
-- OPTIONAL: pure-SQL Bronze -> Silver transform.
-- (Only needed if you load Silver via SQL instead of the Python ETL. The
--  Python ETL already produces CLEAN.AQI_CLEAN, so you can skip this block.)
-- ============================================================================

-- IoT: validate, enrich, dedupe -> Silver
INSERT INTO CLEAN.AQI_CLEAN
    (source, city, sensor_id, pm25, pm10, co2_ppm, aqi_value,
     aqi_category, health_risk, latitude, longitude, recorded_at)
SELECT
    'iot_simulator', city, sensor_id, pm25, pm10, co2_ppm, aqi_value,
    CASE
        WHEN pm25 <= 12.0  THEN 'Good'
        WHEN pm25 <= 35.4  THEN 'Moderate'
        WHEN pm25 <= 55.4  THEN 'Unhealthy for Sensitive'
        WHEN pm25 <= 150.4 THEN 'Unhealthy'
        WHEN pm25 <= 250.4 THEN 'Very Unhealthy'
        ELSE 'Hazardous'
    END AS aqi_category,
    CASE
        WHEN pm25 <= 35.4  THEN 'LOW'
        WHEN pm25 <= 55.4  THEN 'MEDIUM'
        WHEN pm25 <= 250.4 THEN 'HIGH'
        ELSE 'CRITICAL'
    END AS health_risk,
    NULL, NULL, recorded_at
FROM RAW.IOT_READINGS
WHERE pm25 IS NOT NULL
  AND aqi_value IS NOT NULL
  AND pm25 BETWEEN 0 AND 500
  AND co2_ppm BETWEEN 400 AND 2000
  AND humidity_pct BETWEEN 0 AND 100
QUALIFY ROW_NUMBER() OVER (
        PARTITION BY sensor_id, recorded_at ORDER BY ingested_at DESC) = 1;

-- OpenAQ: pm25/pm10 only, pivot to wide, derive AQI -> Silver
INSERT INTO CLEAN.AQI_CLEAN
    (source, city, sensor_id, pm25, pm10, co2_ppm, aqi_value,
     aqi_category, health_risk, latitude, longitude, recorded_at)
WITH wide AS (
    SELECT
        city,
        ANY_VALUE(latitude)  AS latitude,
        ANY_VALUE(longitude) AS longitude,
        recorded_at,
        AVG(CASE WHEN pollutant_type = 'pm25' THEN pollutant_value END) AS pm25,
        AVG(CASE WHEN pollutant_type = 'pm10' THEN pollutant_value END) AS pm10
    FROM RAW.OPENAQ_RAW
    WHERE pollutant_type IN ('pm25', 'pm10')
      AND pollutant_value > 0
    GROUP BY city, recorded_at
)
SELECT
    'openaq_v3', city, NULL, pm25, pm10, NULL,
    ROUND(CASE
        WHEN pm25 <= 12.0  THEN (50-0)/(12.0-0)*(pm25-0)+0
        WHEN pm25 <= 35.4  THEN (100-51)/(35.4-12.1)*(pm25-12.1)+51
        WHEN pm25 <= 55.4  THEN (150-101)/(55.4-35.5)*(pm25-35.5)+101
        WHEN pm25 <= 150.4 THEN (200-151)/(150.4-55.5)*(pm25-55.5)+151
        WHEN pm25 <= 250.4 THEN (300-201)/(250.4-150.5)*(pm25-150.5)+201
        ELSE (500-301)/(500.4-250.5)*(LEAST(pm25,500.4)-250.5)+301
    END, 1) AS aqi_value,
    CASE
        WHEN pm25 <= 12.0  THEN 'Good'
        WHEN pm25 <= 35.4  THEN 'Moderate'
        WHEN pm25 <= 55.4  THEN 'Unhealthy for Sensitive'
        WHEN pm25 <= 150.4 THEN 'Unhealthy'
        WHEN pm25 <= 250.4 THEN 'Very Unhealthy'
        ELSE 'Hazardous'
    END,
    CASE
        WHEN pm25 <= 35.4  THEN 'LOW'
        WHEN pm25 <= 55.4  THEN 'MEDIUM'
        WHEN pm25 <= 250.4 THEN 'HIGH'
        ELSE 'CRITICAL'
    END,
    latitude, longitude, recorded_at
FROM wide
WHERE pm25 IS NOT NULL;


-- ============================================================================
-- REQUIRED: Silver -> Gold daily aggregation.
-- Re-runnable: clears today's rows first, then rebuilds from Silver.
-- ============================================================================
TRUNCATE TABLE ANALYTICS.CITY_DAILY;

INSERT INTO ANALYTICS.CITY_DAILY
    (city, report_date, avg_aqi, max_aqi, min_aqi, avg_pm25, avg_co2,
     dominant_risk, reading_count)
SELECT
    city,
    CAST(recorded_at AS DATE)      AS report_date,
    ROUND(AVG(aqi_value), 1)       AS avg_aqi,
    MAX(aqi_value)                 AS max_aqi,
    MIN(aqi_value)                 AS min_aqi,
    ROUND(AVG(pm25), 1)            AS avg_pm25,
    ROUND(AVG(co2_ppm), 1)         AS avg_co2,
    MODE(health_risk)              AS dominant_risk,
    COUNT(*)                       AS reading_count
FROM CLEAN.AQI_CLEAN
GROUP BY city, CAST(recorded_at AS DATE);

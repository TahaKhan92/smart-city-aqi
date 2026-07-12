"""
aqi_utils.py
------------
The EPA AQI maths, in ONE place. Both the IoT simulator and the ETL import
these functions so the numbers can never drift apart.

EPA formula (linear interpolation inside a breakpoint band):

    AQI = (I_hi - I_lo) / (C_hi - C_lo) * (C - C_lo) + I_lo

where C is the PM2.5 concentration and the (C_lo, C_hi, I_lo, I_hi) band is
picked from config.EPA_BREAKPOINTS.
"""
from config import EPA_BREAKPOINTS, CITY_COORDS


def nearest_city(lat, lon):
    """Map any (lat, lon) to the closest of our 5 target cities.

    OpenAQ's `locality`/station name is often a building or area name (e.g.
    "BUITEMS", "WASA Head Office"), not a city — so instead of trusting that
    text field, we snap each station to the nearest of the 5 hackathon
    cities using straight-line distance on lat/lon. Pakistan is small enough
    that simple Euclidean distance (no haversine needed) gives the right
    answer for this use case.
    """
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    best_city, best_dist = None, float("inf")
    for city, (c_lat, c_lon) in CITY_COORDS.items():
        dist = (lat - c_lat) ** 2 + (lon - c_lon) ** 2
        if dist < best_dist:
            best_city, best_dist = city, dist
    return best_city


def _band_for_pm25(pm25: float):
    """Return the breakpoint tuple that contains this PM2.5 value."""
    if pm25 is None:
        return None
    pm25 = max(0.0, float(pm25))
    for band in EPA_BREAKPOINTS:
        c_lo, c_hi = band[0], band[1]
        if c_lo <= pm25 <= c_hi:
            return band
    # above the top breakpoint -> clamp to the worst band (Hazardous)
    return EPA_BREAKPOINTS[-1]


def calculate_aqi(pm25: float) -> float:
    """PM2.5 concentration (ug/m3) -> AQI value, rounded to 1 dp."""
    band = _band_for_pm25(pm25)
    if band is None:
        return None
    c_lo, c_hi, i_lo, i_hi = band[0], band[1], band[2], band[3]
    pm25 = min(max(0.0, float(pm25)), c_hi)  # clamp inside the band
    aqi = (i_hi - i_lo) / (c_hi - c_lo) * (pm25 - c_lo) + i_lo
    return round(aqi, 1)


def classify(pm25: float):
    """PM2.5 -> (aqi_category, severity, health_risk)."""
    band = _band_for_pm25(pm25)
    if band is None:
        return (None, None, None)
    return (band[4], band[5], band[6])  # category, severity, health_risk


def category_from_aqi(aqi: float):
    """AQI value -> (aqi_category, severity, health_risk).

    Useful when only the AQI number is available (e.g. OpenAQ rows where we
    still derive risk from AQI). Uses the AQI index ranges directly.
    """
    if aqi is None:
        return (None, None, None)
    for band in EPA_BREAKPOINTS:
        i_lo, i_hi = band[2], band[3]
        if i_lo <= aqi <= i_hi:
            return (band[4], band[5], band[6])
    return (EPA_BREAKPOINTS[-1][4], EPA_BREAKPOINTS[-1][5], EPA_BREAKPOINTS[-1][6])


if __name__ == "__main__":
    # quick self-check against known EPA anchor points
    checks = [(0, 0), (12.0, 50), (12.1, 51), (35.4, 100),
              (55.4, 150), (150.4, 200), (250.4, 300), (500.4, 500)]
    print("PM2.5  -> AQI (expected)")
    for pm, expected in checks:
        print(f"{pm:>6} -> {calculate_aqi(pm):>6}  (~{expected})  {classify(pm)}")
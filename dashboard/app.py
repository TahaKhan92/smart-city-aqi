"""
dashboard/app.py  (v2)
----------------------
Smart City AQI — monitoring console.

v2 additions:
  * Pipeline health strip — Bronze -> Silver -> Gold row counts (proves the
    medallion is working; key for a data-engineering hackathon).
  * Live auto-refresh every 30s (needs `pip install streamlit-autorefresh`;
    degrades gracefully to the manual Refresh button if not installed).
  * Anomaly detection — flags pollution spikes per sensor and marks them on the
    trend chart, with a count for the last hour.
  * Health advisory — plain-language recommendation for the worst current AQI.

Reads Gold + Silver from Snowflake, else local CSVs. Run:
    streamlit run dashboard/app.py
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

st.set_page_config(page_title="Smart City AQI — Pakistan",
                   layout="wide", page_icon="🛰️",
                   initial_sidebar_state="expanded")

# ---- live auto-refresh (optional dependency) ------------------------------
LIVE = False
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=30000, key="auto_refresh")
    LIVE = True
except Exception:
    LIVE = False

# ---------------------------------------------------------------------------
INK, PANEL, BORDER = "#0e1420", "#161d2e", "#263149"
TEXT, MUTED, CYAN = "#e6ebf5", "#8a93a8", "#22d3ee"
BRONZE, SILVER, GOLD = "#cd7f32", "#b8c0cc", "#e8b923"
AQI_COLORS = {
    "Good": "#00e400", "Moderate": "#f2e400",
    "Unhealthy for Sensitive": "#ff7e00", "Unhealthy": "#ff2d2d",
    "Very Unhealthy": "#8f3f97", "Hazardous": "#7e0023",
}
AQI_SCALE = ["#00e400", "#f2e400", "#ff7e00", "#ff2d2d", "#8f3f97", "#7e0023"]
RISK_BADGE = {"LOW": "#00e400", "MEDIUM": "#f2e400", "HIGH": "#ff2d2d",
              "CRITICAL": "#8f3f97"}
ADVICE = {
    "Good": "Air quality is good — enjoy outdoor activities.",
    "Moderate": "Acceptable. Unusually sensitive people should limit prolonged outdoor exertion.",
    "Unhealthy for Sensitive": "Sensitive groups (children, elderly, respiratory patients) should limit prolonged outdoor activity.",
    "Unhealthy": "Everyone should reduce prolonged outdoor exertion; sensitive groups should avoid it.",
    "Very Unhealthy": "Health alert — avoid outdoor exertion and wear an N95 mask outdoors.",
    "Hazardous": "Emergency conditions — stay indoors, seal windows, use air purifiers / N95 masks.",
}


def aqi_color(v):
    if v is None or pd.isna(v):
        return MUTED
    for hi, c in zip([50, 100, 150, 200, 300, 501], AQI_SCALE):
        if v <= hi:
            return c
    return AQI_SCALE[-1]


st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap');
html, body, [class*="css"] {{ font-family:'Inter',sans-serif; }}
[data-testid="stToolbar"], #MainMenu, footer {{ visibility:hidden; }}
[data-testid="stHeader"] {{ background:transparent; }}
.stApp {{ background:
    radial-gradient(1200px 500px at 15% -10%, #16233d 0%, transparent 60%),
    radial-gradient(900px 500px at 100% 0%, #1a1330 0%, transparent 55%), {INK}; }}
.block-container {{ padding-top:1.6rem; padding-bottom:2rem; }}
.hero-title {{ font-family:'Space Grotesk',sans-serif; font-size:34px; font-weight:700;
    color:{TEXT}; letter-spacing:-.5px; margin:0; }}
.hero-sub {{ color:{MUTED}; font-size:14px; margin-top:2px; }}
.badge {{ display:inline-block; padding:4px 11px; border-radius:20px; font-size:12px;
    font-weight:600; margin-right:6px; border:1px solid {BORDER}; color:{TEXT}; background:{PANEL}; }}
.badge .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }}
.sec {{ display:flex; align-items:center; gap:10px; margin:22px 0 8px; }}
.sec .bar {{ width:5px; height:20px; border-radius:3px; background:{CYAN}; }}
.sec h3 {{ font-family:'Space Grotesk',sans-serif; margin:0; font-size:19px; font-weight:600; color:{TEXT}; }}
.kpi {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:14px; padding:16px 18px 14px; height:100%; }}
.kpi .label {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:{MUTED}; }}
.kpi .value {{ font-family:'JetBrains Mono',monospace; font-size:30px; font-weight:700; color:{TEXT}; margin-top:6px; line-height:1; }}
.kpi .unit {{ font-size:14px; color:{MUTED}; font-weight:500; }}
.kpi .accent {{ height:4px; border-radius:4px; margin-top:14px; }}
.flow {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:14px; padding:16px 18px; text-align:center; }}
.flow .layer {{ font-family:'Space Grotesk',sans-serif; font-size:12px; letter-spacing:.08em; text-transform:uppercase; }}
.flow .n {{ font-family:'JetBrains Mono',monospace; font-size:26px; font-weight:700; color:{TEXT}; margin-top:4px; }}
.flow .d {{ font-size:11px; color:{MUTED}; margin-top:2px; }}
.arrow {{ color:{MUTED}; font-size:26px; text-align:center; padding-top:26px; }}
.alert {{ border-radius:12px; padding:13px 18px; margin-top:6px; font-size:14px; color:#fff; font-weight:500;
    background:linear-gradient(90deg, rgba(126,0,35,.25), rgba(126,0,35,.55)); border:1px solid #7e0023; }}
.alert b {{ font-family:'JetBrains Mono',monospace; }}
.advice {{ border-radius:12px; padding:14px 18px; margin-top:6px; font-size:14px; color:{TEXT};
    background:{PANEL}; border:1px solid {BORDER}; border-left-width:5px; }}
.advice .h {{ font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:{MUTED}; margin-bottom:3px; }}
.legend {{ font-size:12px; color:{MUTED}; }}
.legend span {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 5px 0 12px; vertical-align:middle; }}
.foot {{ color:{MUTED}; font-size:12px; text-align:center; margin-top:26px; padding-top:14px; border-top:1px solid {BORDER}; }}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=30)
def load_data():
    if config.snowflake_ready():
        try:
            import snowflake_utils as sf
            gold = sf.query("SELECT * FROM ANALYTICS.CITY_DAILY")
            silver = sf.query("SELECT * FROM CLEAN.AQI_CLEAN")
            gold.columns = [c.lower() for c in gold.columns]
            silver.columns = [c.lower() for c in silver.columns]
            return gold, silver, "Snowflake (live)"
        except Exception as e:
            st.warning(f"Snowflake read failed, using local CSV. ({e})")
    silver = pd.read_csv(config.CLEAN_CSV) if config.CLEAN_CSV.exists() else pd.DataFrame()
    gold = pd.DataFrame()
    if not silver.empty:
        silver["recorded_at"] = pd.to_datetime(silver["recorded_at"], utc=True, errors="coerce")
        s = silver.dropna(subset=["recorded_at"]).copy()
        s["report_date"] = s["recorded_at"].dt.date
        gold = (s.groupby(["city", "report_date"])
                  .agg(avg_aqi=("aqi_value", "mean"), max_aqi=("aqi_value", "max"),
                       min_aqi=("aqi_value", "min"), avg_pm25=("pm25", "mean"),
                       avg_co2=("co2_ppm", "mean"),
                       dominant_risk=("health_risk", lambda x: x.mode().iat[0] if not x.mode().empty else None),
                       reading_count=("aqi_value", "count"))
                  .reset_index())
    return gold, silver, "Local CSV"


@st.cache_data(ttl=30)
def pipeline_stats():
    """Row counts at each medallion layer."""
    if config.snowflake_ready():
        try:
            import snowflake_utils as sf
            b_iot = int(sf.query("SELECT COUNT(*) C FROM RAW.IOT_READINGS").iloc[0, 0])
            b_oaq = int(sf.query("SELECT COUNT(*) C FROM RAW.OPENAQ_RAW").iloc[0, 0])
            s_cnt = int(sf.query("SELECT COUNT(*) C FROM CLEAN.AQI_CLEAN").iloc[0, 0])
            g_cnt = int(sf.query("SELECT COUNT(*) C FROM ANALYTICS.CITY_DAILY").iloc[0, 0])
            return b_iot, b_oaq, s_cnt, g_cnt
        except Exception:
            pass
    b_iot = sum(1 for _ in open(config.IOT_CSV)) - 1 if config.IOT_CSV.exists() else 0
    b_oaq = sum(1 for _ in open(config.OPENAQ_CSV)) - 1 if config.OPENAQ_CSV.exists() else 0
    s_cnt = sum(1 for _ in open(config.CLEAN_CSV)) - 1 if config.CLEAN_CSV.exists() else 0
    return max(b_iot, 0), max(b_oaq, 0), max(s_cnt, 0), None


def flag_anomalies(df):
    """Per-sensor spike flag: pm25 >= 2x that sensor's median (simulator injects 2.5-4x)."""
    df = df.copy()
    df["is_anomaly"] = False
    for sid, grp in df.groupby("sensor_id"):
        med = grp["pm25"].median()
        if med and med > 0:
            df.loc[grp.index, "is_anomaly"] = grp["pm25"] >= 2.0 * med
    return df


def theme_fig(fig, h=360):
    fig.update_layout(height=h, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, sans-serif", color=TEXT, size=13),
                      margin=dict(l=10, r=10, t=10, b=10), legend=dict(bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor=BORDER, zeroline=False)
    fig.update_yaxes(gridcolor=BORDER, zeroline=False)
    return fig


gold, silver, src = load_data()

# ---- sidebar --------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛰️ Controls")
    if st.button("↻ Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(("🟢 Live · auto-refresh 30s" if LIVE else "Manual refresh")
               + f" · {datetime.now().strftime('%H:%M:%S')}")
    st.divider()
    if not silver.empty:
        cities = sorted(silver["city"].dropna().unique())
        sel_cities = st.multiselect("City", cities, default=cities)
    else:
        sel_cities = []
    st.divider()
    st.markdown("**AQI scale**")
    st.markdown("".join(f'<div class="legend"><span style="background:{c}"></span>{k}</div>'
                        for k, c in AQI_COLORS.items()), unsafe_allow_html=True)

# ---- header ---------------------------------------------------------------
n_iot = int((silver["source"] == "iot_simulator").sum()) if not silver.empty else 0
n_oaq = int((silver["source"] == "openaq_v3").sum()) if not silver.empty else 0
live_badge = ('<span class="badge"><span class="dot" style="background:#00e400"></span>Live · 30s</span>'
              if LIVE else "")
st.markdown(f"""
<div class="hero-title">Smart City Air Quality Monitoring</div>
<div class="hero-sub">Real-time AQI across five Pakistani cities · Bronze → Silver → Gold medallion pipeline</div>
<div style="margin-top:12px">
  {live_badge}
  <span class="badge"><span class="dot" style="background:{CYAN}"></span>{src}</span>
  <span class="badge">IoT sensors · {n_iot}</span>
  <span class="badge">OpenAQ real · {n_oaq}</span>
</div>
""", unsafe_allow_html=True)

if silver.empty:
    st.info("No data yet. Run the simulator and ETL, then hit Refresh.")
    st.stop()

silver["recorded_at"] = pd.to_datetime(silver["recorded_at"], utc=True, errors="coerce")
sil = silver[silver["city"].isin(sel_cities)] if sel_cities else silver
gld = gold[gold["city"].isin(sel_cities)] if (not gold.empty and sel_cities) else gold

# ---- alert + advisory -----------------------------------------------------
worst_row = sil.sort_values("aqi_value", ascending=False).iloc[0]
worst_cat = worst_row["aqi_category"]
a1, a2 = st.columns([1.3, 1])
a1.markdown(f'<div class="alert">⚠ Highest current reading — <b>{worst_row["city"]}</b>'
            f' · AQI <b>{worst_row["aqi_value"]:.0f}</b> · {worst_cat} '
            f'({worst_row["health_risk"]})</div>', unsafe_allow_html=True)
a2.markdown(f'<div class="advice" style="border-left-color:{AQI_COLORS.get(worst_cat, MUTED)}">'
            f'<div class="h">Health advisory</div>{ADVICE.get(worst_cat, "—")}</div>',
            unsafe_allow_html=True)


# anomalies (needed for KPI + chart)
iot_all = sil[(sil["source"] == "iot_simulator") & sil["sensor_id"].notna()].copy()
iot_all = flag_anomalies(iot_all) if not iot_all.empty else iot_all
if not iot_all.empty:
    hr_cut = iot_all["recorded_at"].max() - pd.Timedelta(hours=1)
    anom_last_hr = int(iot_all[(iot_all["recorded_at"] >= hr_cut) & iot_all["is_anomaly"]].shape[0])
else:
    anom_last_hr = 0


# ---- KPI readouts ---------------------------------------------------------
def kpi(col, label, value, unit="", accent=CYAN):
    col.markdown(f'<div class="kpi"><div class="label">{label}</div>'
                 f'<div class="value">{value}<span class="unit"> {unit}</span></div>'
                 f'<div class="accent" style="background:{accent}"></div></div>', unsafe_allow_html=True)


st.markdown('<div class="sec"><div class="bar"></div><h3>Live snapshot</h3></div>', unsafe_allow_html=True)
k1, k2, k3, k4 = st.columns(4)
worst_city = worst_val = None
if not gld.empty:
    means = gld.groupby("city")["avg_aqi"].mean()
    worst_city, worst_val = means.idxmax(), means.max()
    kpi(k1, "Highest-AQI City", worst_city, f"· {worst_val:.0f}", aqi_color(worst_val))
crit = 100 * (sil["health_risk"] == "CRITICAL").mean()
kpi(k2, "Total Readings", f"{len(sil):,}", "", CYAN)
kpi(k3, "Anomalies (1h)", f"{anom_last_hr}", "spikes", "#ff2d2d" if anom_last_hr else "#00e400")
kpi(k4, "Avg PM2.5", f"{sil['pm25'].mean():.1f}", "µg/m³", aqi_color(sil["pm25"].mean() * 2))

# ---- gauge + bar ----------------------------------------------------------
left, right = st.columns([1, 1.25])
with left:
    st.markdown('<div class="sec"><div class="bar"></div><h3>Worst city — AQI</h3></div>', unsafe_allow_html=True)
    if worst_val is not None:
        g = go.Figure(go.Indicator(
            mode="gauge+number", value=float(worst_val),
            number={"font": {"family": "JetBrains Mono", "size": 44, "color": TEXT}},
            gauge={"axis": {"range": [0, 400], "tickcolor": MUTED},
                   "bar": {"color": "rgba(255,255,255,.85)", "thickness": 0.18}, "borderwidth": 0,
                   "steps": [{"range": [0, 50], "color": "#00e400"},
                             {"range": [50, 100], "color": "#f2e400"},
                             {"range": [100, 150], "color": "#ff7e00"},
                             {"range": [150, 200], "color": "#ff2d2d"},
                             {"range": [200, 300], "color": "#8f3f97"},
                             {"range": [300, 400], "color": "#7e0023"}]}))
        g.update_layout(height=300, paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=10, b=0), font=dict(color=TEXT))
        st.plotly_chart(g, use_container_width=True)
        st.caption(f"{worst_city} · daily average")

with right:
    st.markdown('<div class="sec"><div class="bar"></div><h3>Average AQI per city</h3></div>', unsafe_allow_html=True)
    if not gld.empty:
        bar = gld.groupby("city", as_index=False)["avg_aqi"].mean().sort_values("avg_aqi")
        bar["c"] = bar["avg_aqi"].apply(aqi_color)
        fig = go.Figure(go.Bar(x=bar["avg_aqi"], y=bar["city"], orientation="h",
                               marker=dict(color=bar["c"]), text=bar["avg_aqi"].round(0),
                               textposition="outside", texttemplate="%{text}", cliponaxis=False))
        theme_fig(fig, 300)
        fig.update_layout(xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

# ---- map ------------------------------------------------------------------
st.markdown('<div class="sec"><div class="bar"></div><h3>Station map</h3></div>', unsafe_allow_html=True)
mp = sil.dropna(subset=["latitude", "longitude"])
if not mp.empty:
    agg = mp.groupby(["city", "latitude", "longitude"], as_index=False)["aqi_value"].mean()
    fig = px.scatter_map(agg, lat="latitude", lon="longitude", size="aqi_value",
                         color="aqi_value", color_continuous_scale=AQI_SCALE, range_color=[0, 300],
                         hover_name="city", size_max=34, zoom=4.3,
                         center={"lat": 30.4, "lon": 69.3}, map_style="carto-darkmatter")
    theme_fig(fig, 420)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), coloraxis_colorbar=dict(title="AQI"))
    st.plotly_chart(fig, use_container_width=True)

# ---- 6-hour trend with anomaly markers ------------------------------------
title = "AQI trend — last 6 hours (per sensor)"
if anom_last_hr:
    title += f"  ·  {anom_last_hr} spike(s) flagged in last hour"
st.markdown(f'<div class="sec"><div class="bar"></div><h3>{title}</h3></div>', unsafe_allow_html=True)
if not iot_all.empty:
    cutoff = iot_all["recorded_at"].max() - pd.Timedelta(hours=6)
    recent = iot_all[iot_all["recorded_at"] >= cutoff].sort_values("recorded_at")
    fig = px.line(recent, x="recorded_at", y="aqi_value", color="sensor_id")
    anom = recent[recent["is_anomaly"]]
    if not anom.empty:
        fig.add_trace(go.Scatter(x=anom["recorded_at"], y=anom["aqi_value"], mode="markers",
                                 name="Anomaly", marker=dict(symbol="x", size=11, color="#ffffff",
                                 line=dict(width=2, color="#ff2d2d"))))
    theme_fig(fig, 360)
    fig.update_layout(xaxis_title=None, yaxis_title="AQI", legend_title="Sensor")
    st.plotly_chart(fig, use_container_width=True)

# ---- severity table -------------------------------------------------------
st.markdown('<div class="sec"><div class="bar"></div><h3>Latest readings</h3></div>', unsafe_allow_html=True)
latest = (sil.sort_values("recorded_at", ascending=False)
             .head(25)[["recorded_at", "city", "sensor_id", "source", "pm25",
                        "aqi_value", "aqi_category", "health_risk"]])


def _risk(v):
    c = RISK_BADGE.get(v, PANEL)
    return f"background-color:{c};color:{'#000' if v == 'MEDIUM' else '#fff'};font-weight:700;"


def _cat(v):
    c = AQI_COLORS.get(v, PANEL)
    return f"background-color:{c};color:{'#000' if v in ('Good', 'Moderate') else '#fff'};"


styled = (latest.style.map(_risk, subset=["health_risk"]).map(_cat, subset=["aqi_category"])
          .format({"pm25": "{:.1f}", "aqi_value": "{:.0f}"}))
st.dataframe(styled, use_container_width=True, hide_index=True)

st.markdown('<div class="foot">DataVault · Smart City AQI · IoT + OpenAQ v3 → '
            'Snowflake medallion → Streamlit</div>', unsafe_allow_html=True)
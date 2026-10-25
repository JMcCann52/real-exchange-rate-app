"""Real Exchange Rate (RER) explorer built on IMF SDMX 3.0 data.

Definitions
-----------
S(t)        units of Country 2 currency per 1 unit of Country 1 currency
P1(t), P2(t) monthly CPIs of Country 1 and Country 2
RER(t)      = S(t) * P1(t) / P2(t)
RER*        = mean of RER(t) over valid months in the selected window
Real Index  = 100 * RER(t) / RER*

IMF exchange rates (key {ISO3}.XDC_USD.PA_RT.M) are local currency per USD, so
S(t) = (Country 2 per USD) / (Country 1 per USD).
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

IMF_BASE = "https://api.imf.org/external/sdmx/3.0"
START_PERIOD = pd.Timestamp("1976-01-01")
EURO_AREA = "G163"
TIMEOUT = 60
LOGO_FILE = Path(__file__).parent / "kellogg_logo.png"  # add the official logo file to the repo

# Northwestern / Kellogg brand palette
PURPLE = "#4E2A84"
PURPLE_DARK = "#401F68"
PURPLE_LIGHT = "#B6ACD1"
ACCENT = "#CA7C1B"
GREY = "#716C6B"

INFLATION_LOOKBACK = 60  # months used for the relative price trend in forecasts
BACKTEST_MIN_HISTORY = 60  # months of history required before the first backtest forecast


# ISO 4217 currency codes for labels; countries not listed fall back to their name.
CURRENCY = {
    "G163": "EUR", "USA": "USD", "GBR": "GBP", "JPN": "JPY", "CHN": "CNY", "CAN": "CAD",
    "AUS": "AUD", "NZL": "NZD", "CHE": "CHF", "SWE": "SEK", "NOR": "NOK", "DNK": "DKK",
    "ISL": "ISK", "POL": "PLN", "CZE": "CZK", "HUN": "HUF", "ROU": "RON", "BGR": "BGN",
    "TUR": "TRY", "RUS": "RUB", "UKR": "UAH", "ISR": "ILS", "SAU": "SAR", "ARE": "AED",
    "QAT": "QAR", "KWT": "KWD", "EGY": "EGP", "ZAF": "ZAR", "NGA": "NGN", "KEN": "KES",
    "MAR": "MAD", "IND": "INR", "PAK": "PKR", "BGD": "BDT", "LKA": "LKR", "IDN": "IDR",
    "MYS": "MYR", "SGP": "SGD", "THA": "THB", "PHL": "PHP", "VNM": "VND", "KOR": "KRW",
    "HKG": "HKD", "TWN": "TWD", "MEX": "MXN", "BRA": "BRL", "ARG": "ARS", "CHL": "CLP",
    "COL": "COP", "PER": "PEN", "URY": "UYU", "VEN": "VES",
    # euro-area members (national currencies before euro adoption)
    "DEU": "EUR", "FRA": "EUR", "ITA": "EUR", "ESP": "EUR", "NLD": "EUR", "BEL": "EUR",
    "AUT": "EUR", "PRT": "EUR", "IRL": "EUR", "FIN": "EUR", "GRC": "EUR", "LUX": "EUR",
    "SVN": "EUR", "SVK": "EUR", "EST": "EUR", "LVA": "EUR", "LTU": "EUR", "CYP": "EUR",
    "MLT": "EUR", "HRV": "EUR",
}

HEADERS_UA = {"User-Agent": "real-exchange-rate-app/1.0 (Streamlit; educational use)"}

ACCEPT_CSV = "application/vnd.sdmx.data+csv;version=2.0.0"
ACCEPT_JSON = "application/vnd.sdmx.data+json;version=2.0.0"


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def parse_period(value: str) -> pd.Timestamp | None:
    """Convert IMF period strings (2020-M01, 2020M01, 2020-01) to month start."""
    m = re.match(r"^\s*(\d{4})-?M?(\d{1,2})\s*$", str(value))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return pd.Timestamp(year=year, month=month, day=1)


def _to_series(periods, values) -> pd.Series:
    dates, vals = [], []
    for p, v in zip(periods, values):
        d = parse_period(p)
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if d is None or pd.isna(x):
            continue
        dates.append(d)
        vals.append(x)
    s = pd.Series(vals, index=pd.DatetimeIndex(dates), dtype="float64")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s.index >= START_PERIOD]


def parse_sdmx_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    cols = {c.upper(): c for c in df.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
        raise ValueError("CSV response lacks TIME_PERIOD/OBS_VALUE columns")
    return _to_series(df[cols["TIME_PERIOD"]], df[cols["OBS_VALUE"]])


def parse_sdmx_json(payload: dict) -> pd.Series:
    data = payload.get("data", payload)
    structures = data.get("structures") or [data.get("structure", {})]
    dims = structures[0].get("dimensions", {})
    datasets = data.get("dataSets", [])
    if not datasets:
        return pd.Series(dtype="float64")
    ds = datasets[0]

    periods, values = [], []
    if "series" in ds:  # TIME_PERIOD at observation level
        obs_dims = dims.get("observation", [])
        time_idx = next((i for i, d in enumerate(obs_dims) if d.get("id") == "TIME_PERIOD"), 0)
        time_vals = [v.get("id") or v.get("value") for v in obs_dims[time_idx]["values"]]
        for series in ds["series"].values():
            for key, obs in (series.get("observations") or {}).items():
                t = int(str(key).split(":")[time_idx])
                periods.append(time_vals[t])
                values.append(obs[0] if isinstance(obs, list) else obs)
    elif "observations" in ds:  # flat: all dimensions in the key
        obs_dims = dims.get("observation", [])
        time_idx = next(i for i, d in enumerate(obs_dims) if d.get("id") == "TIME_PERIOD")
        time_vals = [v.get("id") or v.get("value") for v in obs_dims[time_idx]["values"]]
        for key, obs in ds["observations"].items():
            t = int(str(key).split(":")[time_idx])
            periods.append(time_vals[t])
            values.append(obs[0] if isinstance(obs, list) else obs)
    return _to_series(periods, values)


# --------------------------------------------------------------------------
# IMF fetching
# --------------------------------------------------------------------------
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_imf_series(dataflow: str, key: str) -> tuple[pd.Series, list[str]]:
    """Return (series, log). Tries CSV then JSON, latest stable then latest version."""
    log: list[str] = []
    for version in ("+", "~"):
        url = f"{IMF_BASE}/data/dataflow/IMF.STA/{dataflow}/{version}/{key}"
        for accept in (ACCEPT_CSV, ACCEPT_JSON):
            try:
                r = requests.get(url, headers={**HEADERS_UA, "Accept": accept}, timeout=TIMEOUT)
                log.append(f"GET {url} [{accept.split(';')[0]}] -> {r.status_code}")
                if r.status_code == 404:
                    break  # no data for this key; trying another format won't help
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype or r.text.lstrip().startswith("{"):
                    s = parse_sdmx_json(r.json())
                else:
                    s = parse_sdmx_csv(r.text)
                if not s.empty:
                    return s, log
                log.append("  parsed OK but no observations")
            except (requests.RequestException, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
                log.append(f"  error: {type(e).__name__}: {str(e)[:200]}")
    return pd.Series(dtype="float64"), log


def get_cpi(iso3: str):
    return fetch_imf_series("CPI", f"{iso3}.CPI._T.IX.M")


def get_lcu_per_usd(iso3: str):
    if iso3 == "USA":  # the USD per USD rate is 1 by definition
        idx = pd.date_range(START_PERIOD, pd.Timestamp.today().normalize(), freq="MS")
        return pd.Series(1.0, index=idx), ["USA: exchange rate set to 1.0 (USD per USD)"]
    return fetch_imf_series("ER", f"{iso3}.XDC_USD.PA_RT.M")


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def country_list() -> dict[str, str]:
    """Map display name -> code. Tries the IMF country codelist, falls back to ISO 3166."""
    names: dict[str, str] = {}
    for agency in ("IMF", "IMF.STA"):
        try:
            r = requests.get(
                f"{IMF_BASE}/structure/codelist/{agency}/CL_COUNTRY/+",
                headers={**HEADERS_UA, "Accept": "application/vnd.sdmx.structure+json;version=2.0.0"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            for cl in r.json().get("data", {}).get("codelists", []):
                for code in cl.get("codes", []):
                    cid = code.get("id", "")
                    nm = code.get("name") or (code.get("names") or {}).get("en") or cid
                    if isinstance(nm, dict):
                        nm = nm.get("en", cid)
                    if re.fullmatch(r"[A-Z]{3}", cid) or cid == EURO_AREA:
                        names[f"{nm} ({cid})"] = cid
            if names:
                break
        except Exception:
            continue
    if not names:
        import pycountry

        names = {f"{c.name} ({c.alpha_3})": c.alpha_3 for c in pycountry.countries}
    names[f"Euro area ({EURO_AREA})"] = EURO_AREA
    return dict(sorted(names.items(), key=lambda kv: (kv[1] != EURO_AREA, kv[0])))


# --------------------------------------------------------------------------
# Economics
# --------------------------------------------------------------------------
def build_panel(p1, p2, e1, e2) -> pd.DataFrame:
    """Merge monthly series and compute S(t) and RER(t) for every month."""
    df = pd.concat(
        {"P1": p1, "P2": p2, "C1_per_USD": e1, "C2_per_USD": e2}, axis=1, sort=True
    )
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="MS"))
    df.index.name = "month"
    df["S"] = df["C2_per_USD"] / df["C1_per_USD"]  # Country 2 per 1 unit of Country 1
    df["RER"] = df["S"] * df["P1"] / df["P2"]
    return df


def apply_window(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                 base_month: pd.Timestamp | None = None) -> tuple[pd.DataFrame, float]:
    """Slice the window and compute RER*, the Real Index and the PPP-implied rate.

    RER* is the average RER over valid months in the window, or RER in base_month if given.
    S_PPP(t) = RER* x P2(t) / P1(t) is the rate that would put RER(t) exactly at RER*.
    """
    w = df.loc[start:end].copy()
    valid = w["RER"].dropna()
    if base_month is not None:
        rer_star = float(w.loc[base_month, "RER"])
    else:
        rer_star = float(valid.mean()) if not valid.empty else float("nan")
    w["RER_star"] = rer_star
    w["Real_Index"] = 100 * w["RER"] / rer_star
    w["S_PPP"] = rer_star * w["P2"] / w["P1"]
    w["Misvaluation"] = w["S"] / w["S_PPP"] - 1  # equals RER/RER* - 1
    return w, rer_star


def half_life(rer: pd.Series) -> dict:
    """AR(1) on log RER using consecutive monthly pairs: x(t) = a + rho * x(t-1) + e.

    Half-life (months) = ln(0.5) / ln(rho): time for half of a deviation to disappear.
    """
    x = np.log(rer)
    pairs = pd.concat({"x": x, "x_lag": x.shift(1)}, axis=1).dropna()
    if len(pairs) < 24:
        return {"rho": np.nan, "half_life": np.nan, "n": len(pairs)}
    X = np.column_stack([np.ones(len(pairs)), pairs["x_lag"].to_numpy()])
    a, rho = np.linalg.lstsq(X, pairs["x"].to_numpy(), rcond=None)[0]
    hl = np.log(0.5) / np.log(rho) if 0 < rho < 1 else np.inf
    return {"rho": float(rho), "half_life": float(hl), "n": len(pairs)}


def price_trend(w: pd.DataFrame, lookback: int = INFLATION_LOOKBACK) -> float:
    """Average monthly change in ln(P2/P1) over the last `lookback` months with data."""
    lr = np.log(w["P2"] / w["P1"]).dropna()
    if len(lr) < 2:
        return 0.0
    recent = lr.loc[lr.index >= lr.index[-1] - pd.DateOffset(months=lookback)]
    months_span = (recent.index[-1].year - recent.index[0].year) * 12 + recent.index[-1].month - recent.index[0].month
    return float((recent.iloc[-1] - recent.iloc[0]) / months_span) if months_span > 0 else 0.0


def forecast_path(w: pd.DataFrame, rer_star: float, rho: float, horizon: int) -> pd.DataFrame:
    """Project S(t) for `horizon` months after the last valid month.

    The real gap ln(RER/RER*) shrinks by a factor rho each month (no shrinkage if rho >= 1),
    and ln(P2/P1) keeps growing at its recent trend. Then S = RER x P2 / P1.
    """
    last = w.dropna(subset=["RER"]).iloc[-1]
    t0 = last.name
    gap0 = np.log(last["RER"] / rer_star)
    lr0 = np.log(last["P2"] / last["P1"])
    g = price_trend(w)
    decay = rho if 0 < rho < 1 else 1.0
    h = np.arange(0, horizon + 1)
    gap = gap0 * decay ** h
    lr = lr0 + g * h
    idx = pd.date_range(t0, periods=horizon + 1, freq="MS")
    return pd.DataFrame({
        "S_forecast": np.exp(np.log(rer_star) + gap + lr),
        "S_PPP_forecast": np.exp(np.log(rer_star) + lr),
        "Real_Index_forecast": 100 * np.exp(gap),
    }, index=idx)


def backtest(w: pd.DataFrame, horizon: int, min_history: int = BACKTEST_MIN_HISTORY) -> pd.DataFrame:
    """Real-time test of the RER forecast against a random walk.

    At each origin month t, using only data up to t: RER* = average RER so far, rho from the
    AR(1) so far, price trend from the last 5 years. Forecast S(t+h); the random walk
    forecast is S(t). Errors are measured in logs (approximately percent).
    """
    rows = []
    rer = w["RER"]
    for i, t in enumerate(w.index):
        target = t + pd.DateOffset(months=horizon)
        if target not in w.index or pd.isna(w.at[target, "S"]) or pd.isna(rer.iloc[i]):
            continue
        hist = w.iloc[: i + 1]
        if hist["RER"].notna().sum() < min_history:
            continue
        star = float(hist["RER"].mean())
        rho = half_life(hist["RER"])["rho"]
        path = forecast_path(hist.assign(RER_star=star), star, rho, horizon)
        rows.append({
            "origin": t,
            "target": target,
            "S_origin": w.at[t, "S"],
            "S_actual": w.at[target, "S"],
            "S_model": path["S_forecast"].iloc[-1],
        })
    bt = pd.DataFrame(rows)
    if bt.empty:
        return bt
    bt["err_model"] = np.log(bt["S_model"] / bt["S_actual"])
    bt["err_rw"] = np.log(bt["S_origin"] / bt["S_actual"])
    return bt


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="Real Exchange Rate Explorer", layout="wide")
if LOGO_FILE.exists():
    st.logo(str(LOGO_FILE), size="large")
st.markdown(
    f"""
    <style>
      h1, [data-testid="stHeading"] h1 {{ color: {PURPLE} !important; }}
      h2, h3 {{ color: {PURPLE_DARK}; }}
      [data-testid="stMetricValue"] {{ color: {PURPLE_DARK}; }}
      [data-testid="stHeader"] {{ border-bottom: 4px solid {PURPLE}; }}
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Real Exchange Rate Explorer")
st.caption(
    "IMF monthly CPI and exchange rates from January 1976 where available. "
    "S(t) = Country 2 currency per 1 unit of Country 1 currency. "
    "RER(t) = S(t) × P1(t) / P2(t). Real Index(t) = 100 × RER(t) / RER*, "
    "where RER* is the average RER over the selected window (or a chosen base month)."
)

with st.spinner("Loading IMF country list…"):
    countries = country_list()
labels = list(countries)


def default_index(code: str) -> int:
    return next((i for i, l in enumerate(labels) if countries[l] == code), 0)


c1, c2 = st.columns(2)
lab1 = c1.selectbox("Country 1 (base currency)", labels, index=default_index(EURO_AREA))
lab2 = c2.selectbox("Country 2 (quote currency)", labels, index=default_index("USA"))
iso1, iso2 = countries[lab1], countries[lab2]

if iso1 == iso2:
    st.warning("Choose two different countries.")
    st.stop()

with st.spinner("Fetching IMF data…"):
    p1, log_p1 = get_cpi(iso1)
    p2, log_p2 = get_cpi(iso2)
    e1, log_e1 = get_lcu_per_usd(iso1)
    e2, log_e2 = get_lcu_per_usd(iso2)

missing = [
    name
    for name, s in [
        (f"CPI for {lab1}", p1),
        (f"CPI for {lab2}", p2),
        (f"exchange rate for {lab1}", e1),
        (f"exchange rate for {lab2}", e2),
    ]
    if s.empty
]

with st.expander("IMF request log"):
    st.code("\n".join(log_p1 + log_p2 + log_e1 + log_e2) or "(cached)")

if missing:
    st.error("The IMF returned no data for: " + "; ".join(missing) + ". Try another country.")
    st.stop()

panel = build_panel(p1, p2, e1, e2)
valid_months = panel["RER"].dropna().index
if valid_months.empty:
    st.error("The CPI and exchange-rate series do not overlap in any month.")
    st.stop()

months = list(pd.date_range(valid_months.min(), valid_months.max(), freq="MS"))
fmt = lambda d: d.strftime("%b %Y")  # noqa: E731
start, end = st.select_slider(
    "Sample period (RER* is recalculated for this window)",
    options=months,
    value=(months[0], months[-1]),
    format_func=fmt,
)
if start >= end:
    st.warning("Pick an end month after the start month.")
    st.stop()

b1, b2, b3 = st.columns([2, 2, 2])
bench = b1.radio("Benchmark RER*", ["Window average", "Single base month"], horizontal=True,
                 help="Window average is the assignment default. A single base month treats that "
                      "month as fairly priced (e.g. Jan 1999 for the euro).")
base_month = None
if bench == "Single base month":
    window_valid = [m for m in valid_months if start <= m <= end]
    base_month = b2.selectbox("Base month", window_valid, index=0, format_func=fmt)
horizon = b3.slider("Forecast horizon (months)", 12, 60, 24, step=6)

window, rer_star = apply_window(panel, start, end, base_month)
n_valid = int(window["RER"].notna().sum())
n_total = len(window)
latest = window.dropna(subset=["RER"]).iloc[-1]
cur1 = lab1.split(" (")[0]  # country names, for prose
cur2 = lab2.split(" (")[0]
ccy1 = CURRENCY.get(iso1, f"{cur1} currency")
ccy2 = CURRENCY.get(iso2, f"{cur2} currency")
unit = f"{ccy2} per {ccy1}"
hl = half_life(window["RER"])
path = forecast_path(window, rer_star, hl["rho"], horizon)
bench_label = "window average" if base_month is None else f"{fmt(base_month)} base"

m1, m2, m3, m4 = st.columns(4)
m1.metric(f"RER* ({bench_label})", f"{rer_star:,.4f}")
m2.metric(f"Latest Real Index ({fmt(latest.name)})", f"{latest['Real_Index']:.1f}",
          f"{latest['Real_Index'] - 100:+.1f} vs. 100", delta_color="off")
m3.metric(f"Latest S(t): {unit}", f"{latest['S']:,.4f}")
m4.metric("Valid months", f"{n_valid} of {n_total}")

m5, m6, m7, m8 = st.columns(4)
m5.metric("PPP-implied S (RER at RER*)", f"{latest['S_PPP']:,.4f}",
          help="S_PPP(t) = RER* × P2(t) / P1(t)")
m6.metric("Actual vs. PPP-implied", f"{latest['Misvaluation']:+.1%}",
          help="S / S_PPP − 1. Negative means Country 1's currency is cheap in real terms.")
if np.isfinite(hl["half_life"]) and hl["half_life"] > 600:
    m7.metric(f"Half-life of RER deviations (ρ = {hl['rho']:.3f})", "Over 50 years",
              help="Deviations barely shrink in this window, so the forecast assumes almost no reversion.")
elif np.isfinite(hl["half_life"]):
    m7.metric(f"Half-life of RER deviations (ρ = {hl['rho']:.3f})", f"{hl['half_life'] / 12:.1f} years",
              help="From an AR(1) on log RER over the window. Studies typically find 3 to 5 years.")
else:
    m7.metric(f"Half-life of RER deviations (ρ = {hl['rho']:.3f})", "No reversion")
m8.metric(f"Forecast S in {horizon} months ({fmt(path.index[-1])})", f"{path['S_forecast'].iloc[-1]:,.4f}",
          f"{path['S_forecast'].iloc[-1] / latest['S'] - 1:+.1%} vs. today", delta_color="off")

side = "above" if latest["Real_Index"] > 100 else "below"
strength = "strong (overvalued)" if side == "above" else "weak (undervalued)"
st.info(f"The Real Index is {side} 100: {cur1}'s currency is {strength} in real terms against {cur2} "
        f"relative to the {bench_label} benchmark. Relative PPP points to {unit} of "
        f"{latest['S_PPP']:,.4f}, versus {latest['S']:,.4f} actual.")

view = st.radio("Chart", ["Real", "Nominal", "Both"], horizontal=True)
show_fc = st.checkbox(f"Show {horizon}-month forecast and PPP-implied rate", value=True)
x = window.index
real_trace = go.Scatter(x=x, y=window["Real_Index"], name="Real Index (RER*=100)",
                        mode="lines", line=dict(width=2.5, color=PURPLE), connectgaps=False)
nom_trace = go.Scatter(x=x, y=window["S"], name=f"S(t): {unit}",
                       mode="lines", line=dict(width=2, color=ACCENT), connectgaps=False)
ppp_trace = go.Scatter(x=x, y=window["S_PPP"], name="PPP-implied S", mode="lines",
                       line=dict(width=1.5, color=GREY, dash="dash"), connectgaps=False)
fc_nom = go.Scatter(x=path.index, y=path["S_forecast"], name="Forecast S", mode="lines",
                    line=dict(width=2, color=ACCENT, dash="dot"))
fc_ppp = go.Scatter(x=path.index, y=path["S_PPP_forecast"], name="PPP-implied S (projected)",
                    mode="lines", line=dict(width=1.5, color=GREY, dash="dot"), showlegend=False)
fc_real = go.Scatter(x=path.index, y=path["Real_Index_forecast"], name="Forecast Real Index",
                     mode="lines", line=dict(width=2, color=PURPLE, dash="dot"))

if view == "Both":
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(real_trace, secondary_y=False)
    fig.add_trace(nom_trace, secondary_y=True)
    if show_fc:
        fig.add_trace(fc_real, secondary_y=False)
        fig.add_trace(fc_nom, secondary_y=True)
    fig.update_yaxes(title_text="Real Index", secondary_y=False)
    fig.update_yaxes(title_text=unit, secondary_y=True, showgrid=False)
    fig.add_hline(y=100, line_dash="dash", line_color=PURPLE_LIGHT, secondary_y=False)
elif view == "Real":
    fig = go.Figure([real_trace] + ([fc_real] if show_fc else []))
    fig.update_yaxes(title_text="Real Index (RER* = 100)")
    fig.add_hline(y=100, line_dash="dash", line_color=PURPLE_LIGHT)
else:
    fig = go.Figure([nom_trace] + ([ppp_trace, fc_ppp, fc_nom] if show_fc else []))
    fig.update_yaxes(title_text=unit)
fig.update_layout(height=520, hovermode="x unified", legend=dict(orientation="h", y=-0.15),
                  margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, width="stretch")
st.caption(
    f"Forecast: the gap between RER and RER* shrinks by ρ each month (half-life above), and "
    f"relative prices P2/P1 keep growing at their trend over the last {INFLATION_LOOKBACK // 12} years "
    f"({price_trend(window) * 1200:+.2f}% a year). The PPP-implied rate is the rate that would put the RER "
    f"exactly at RER*."
)

out = window.reset_index()[
    ["month", "C1_per_USD", "C2_per_USD", "S", "P1", "P2", "RER", "RER_star", "Real_Index",
     "S_PPP", "Misvaluation"]
].rename(columns={
    "C1_per_USD": f"{iso1}_{CURRENCY.get(iso1, 'LCU')}_per_USD",
    "C2_per_USD": f"{iso2}_{CURRENCY.get(iso2, 'LCU')}_per_USD",
    "S": f"S_{CURRENCY.get(iso2, iso2)}_per_{CURRENCY.get(iso1, iso1)}",
    "P1": f"P1_CPI_{iso1}",
    "P2": f"P2_CPI_{iso2}",
    "S_PPP": "S_PPP_implied",
    "Misvaluation": "Actual_vs_PPP",
})
out["month"] = out["month"].dt.strftime("%Y-%m")
st.download_button(
    "Download CSV (selected period)",
    out.to_csv(index=False).encode("utf-8"),
    file_name=f"rer_{iso1}_{iso2}_{start:%Y%m}_{end:%Y%m}.csv",
    mime="text/csv",
)

with st.expander("Data table"):
    st.dataframe(out, width="stretch", hide_index=True)

# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------
st.subheader("Backtest: does the RER beat a random walk?")
st.caption(
    f"At every month in the window with at least {BACKTEST_MIN_HISTORY // 12} years of history, the model "
    f"forecasts S {horizon} months ahead using only data available at that month: RER* is the average RER "
    "up to then, and ρ and the price trend are estimated from the same history. The random walk forecasts "
    "no change. Errors are in logs (about percent)."
)
bt = backtest(window, horizon)
if bt.empty:
    st.warning("The window is too short for a backtest at this horizon. Widen the sample period.")
else:
    rmse_m = float(np.sqrt((bt["err_model"] ** 2).mean()))
    rmse_rw = float(np.sqrt((bt["err_rw"] ** 2).mean()))
    hit = float((np.sign(bt["S_model"] - bt["S_origin"]) == np.sign(bt["S_actual"] - bt["S_origin"])).mean())
    closer = float((bt["err_model"].abs() < bt["err_rw"].abs()).mean())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("RMSE: RER model", f"{rmse_m:.1%}")
    k2.metric("RMSE: random walk", f"{rmse_rw:.1%}")
    winner = "model better" if rmse_m < rmse_rw else "random walk better"
    k3.metric(f"Theil ratio, model ÷ random walk ({winner})", f"{rmse_m / rmse_rw:.2f}",
              help="Below 1 means the RER model forecasts more accurately than assuming no change.")
    k4.metric("Direction correct", f"{hit:.0%}",
              help=f"Share of forecasts that got the direction of the move right. The model was closer "
                   f"than the random walk in {closer:.0%} of months.")

    bfig = go.Figure([
        go.Scatter(x=bt["target"], y=bt["S_actual"], name="Actual S", mode="lines",
                   line=dict(width=2, color=ACCENT)),
        go.Scatter(x=bt["target"], y=bt["S_model"], name=f"RER model forecast ({horizon}m earlier)",
                   mode="lines", line=dict(width=2, color=PURPLE)),
        go.Scatter(x=bt["target"], y=bt["S_origin"], name=f"Random walk ({horizon}m earlier)",
                   mode="lines", line=dict(width=1.5, color=GREY, dash="dot")),
    ])
    bfig.update_layout(height=420, hovermode="x unified", legend=dict(orientation="h", y=-0.2),
                       margin=dict(l=10, r=10, t=30, b=10), yaxis_title=unit)
    st.plotly_chart(bfig, width="stretch")
    bt_out = bt.assign(origin=bt["origin"].dt.strftime("%Y-%m"), target=bt["target"].dt.strftime("%Y-%m"))
    st.download_button("Download backtest CSV", bt_out.to_csv(index=False).encode("utf-8"),
                       file_name=f"rer_backtest_{iso1}_{iso2}_{horizon}m.csv", mime="text/csv")

st.caption(
    "Source: IMF SDMX 3.0 API (dataflows CPI and ER, agency IMF.STA). Months where any input is "
    "missing are left blank and excluded from RER*. CPI base years differ across countries; this "
    "only shifts the RER level, which the Real Index normalizes away."
)

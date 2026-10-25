# Real Exchange Rate App

A Streamlit app that computes and plots the real exchange rate (RER) between any two IMF countries, or the Euro area, using monthly IMF CPI and exchange-rate data from January 1976 where available.

## Economics

| Symbol | Definition |
|---|---|
| S(t) | Units of Country 2 currency per 1 unit of Country 1 currency |
| P1(t), P2(t) | Monthly CPIs of Country 1 and Country 2 |
| RER(t) | S(t) × P1(t) / P2(t) |
| RER* | Average of RER(t) over valid months in the selected start and end months |
| Real Index(t) | 100 × RER(t) / RER* |

IMF exchange rates are reported as local currency per USD, so the app converts them:

S(t) = (Country 2 currency per USD) / (Country 1 currency per USD)

When the U.S. is selected, its rate is set to 1 USD per USD.

A Real Index above 100 means Country 1's currency is strong in real terms relative to its average over the window (overvalued on this benchmark). Below 100 means it is weak (undervalued). RER* is recalculated whenever the dates change. The nominal rate S(t) is plotted in actual currency units and is not normalized.

## Features

- Country 1 and Country 2 selectors covering IMF countries plus the Euro area (IMF code `G163`)
- Start and end month slider. RER* updates with the window.
- Chart toggle: Real, Nominal, or Both (Both uses separate left and right axes)
- CSV download of every observation and calculation in the selected period: per-USD rates, S(t), P1, P2, RER, RER*, and the Real Index
- Benchmark toggle, PPP-implied rate, half-life, forecast path, and a random-walk backtest (see below)
- Request log showing each IMF call and its status, for debugging gaps

## Forecasting and diagnostics

| Feature | What it does |
|---|---|
| Benchmark toggle | RER* is the window average (assignment default) or the RER in a single base month, such as January 1999 for the euro. |
| PPP-implied rate | S_PPP(t) = RER* × P2(t) / P1(t), the rate that would put RER(t) exactly at RER*. "Actual vs. PPP-implied" = S / S_PPP − 1. |
| Half-life | AR(1) regression on log RER over the window, ln RER(t) = a + ρ ln RER(t−1) + e. Half-life = ln(0.5) / ln(ρ), the months for half of a deviation to disappear. |
| Forecast | For a 12 to 60 month horizon, the gap ln(RER / RER*) shrinks by ρ each month and ln(P2 / P1) continues at its trend over the last five years. Forecast S = RER × P2 / P1. |
| Backtest | At each month with at least five years of history, forecasts S at the chosen horizon using only data available then (RER* = average RER to date, ρ and the price trend from the same history), and compares the errors with a random walk (no change). Reports RMSE, the Theil ratio (below 1 means the model wins) and the share of correct directions. |

Euro area vs. U.S., Jan 1999 to Sep 2026 (FRED data used as a check): the half-life is about 4.4 years; with a January 1999 base month the PPP-implied rate is 1.3008 USD per EUR and the euro is 11.6% undervalued, matching the spreadsheet. At a 24-month horizon the backtest Theil ratio is about 1.05, so over this sample the RER model does not beat a random walk at two years. This is consistent with the forecasting literature and is worth testing at longer horizons.

## Theme and logo

Colors follow the Northwestern/Kellogg purple palette (`#4E2A84`), set in `.streamlit/config.toml` and in `app.py`. To show the school logo in the top-left corner, add an image named `kellogg_logo.png` to the repo next to `app.py`. If the file is missing, the app runs without it.

## Data

IMF SDMX 3.0 API: `https://api.imf.org/external/sdmx/3.0`

| Series | Dataflow | Key |
|---|---|---|
| CPI, all items, index, monthly | `IMF.STA/CPI` | `{ISO3}.CPI._T.IX.M` |
| Exchange rate, local currency per USD, period average, monthly | `IMF.STA/ER` | `{ISO3}.XDC_USD.PA_RT.M` |

The app requests SDMX-CSV first and falls back to SDMX-JSON. Responses are cached for 24 hours. The country list comes from the IMF country codelist, with ISO 3166 names (via `pycountry`) as a fallback.

**Known limitations.** IMF coverage varies by country. Some countries lack monthly CPI or have gaps, and months with any missing input are left blank and excluded from RER*. Euro-area aggregate data begins around 1999. Countries that adopted the euro may show a break where their national currency was replaced. CPI base years differ by country, which shifts the RER level but not the Real Index.

## Run it

**Streamlit Community Cloud (no local Python):**
1. Upload `app.py`, `requirements.txt`, `README.md`, and `.streamlit/config.toml` (plus `kellogg_logo.png` if you use it) to the public GitHub repo `real-exchange-rate-app`.
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub, click **Create app**, choose the repo, branch `main`, main file `app.py`, and under Advanced settings choose Python 3.12.
3. Click **Deploy**.

**Locally (optional):**
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Verification

The calculation was checked against a FRED-based spreadsheet for Euro area vs. U.S. (CP0000EZ19M086NEST, CPIAUCNS, DEXUSEU):
- RER for January 1999 = 0.4026, matching the spreadsheet.
- With Country 1 = Euro area and Country 2 = U.S., S(t) is USD per EUR (1.1505 for September 2026, matching FRED's monthly average).
- Swapping Country 1 and Country 2 gives the reciprocal RER.
- The Real Index averages exactly 100 over any selected window.

## Prompt log

| Date | Model | Prompt |
|---|---|---|
| 2026-10-25 | Claude (claude-opus-5-5) | Build a real exchange rate Streamlit app with IMF data. Let users choose Country 1 and Country 2 from IMF countries and the Euro area, and retrieve monthly IMF CPI and exchange-rate data from January 1976 where available. Define S(t) as units of Country 2 currency per one unit of Country 1 currency, with P1(t) and P2(t) as the monthly CPIs, and calculate RER(t) = S(t) × P1(t) / P2(t). Over user-selected start and end months, calculate RER* as the average RER over valid months and plot Real Index(t) = 100 × RER(t) / RER*, recalculating RER* when dates change. Plot nominal S(t) in actual currency units without normalizing it. Let users choose Real, Nominal, or Both (separate axes for Both) and provide a CSV download of all observations and calculations in the sample period. Use the IMF API at https://api.imf.org/external/sdmx/3.0 with CPI key {ISO3}.CPI._T.IX.M and exchange-rate key {ISO3}.XDC_USD.PA_RT.M, G163 for the Euro area, and convert IMF local-currency-per-USD rates to the S(t) direction. Return complete app.py, requirements.txt, and README.md files compatible with Python 3.12. |

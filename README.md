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

Euro area vs. U.S., Jan 1999 to Sep 2026 (FRED data used as a check): the half-life is about 4.4 years; with a January 1999 base month the PPP-implied rate is 1.3008 USD per EUR and the euro is 11.6% undervalued, matching the spreadsheet. The backtest Theil ratio is 1.02 at 12 months, 1.05 at 24 months and about 1.13 at 60 months, so over this sample the RER model does not beat a random walk. The main reason is the real-time benchmark: in the mid-2000s the average RER to date was dominated by the weak euro of 1999 to 2002, so the model kept predicting a euro decline while the euro rose to 1.60 by 2008. Pairs with longer IMF histories (back to 1976) give the benchmark more data and may behave differently.

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

Model: Claude (configured as `claude-opus-5-5`; the serving model may differ). Prompts are cleaned up for clarity and listed in order. Each entry notes what the model returned and how it was checked.

### Session 1: October 18, 2026 (FRED spreadsheet, parts a and b)

**Prompt 1.** I'm working on an international finance assignment (attached PDF). Explain how to compute the euro's real exchange rate, RER(t) = P_Euro(t) × S(t) / P_US(t) with S in USD per EUR, using FRED series CPIAUCNS, CP0000EZ19M086NEST and DEXUSEU. Then explain how to use January 1999 as the benchmark to find the USD/EUR rate implied by relative PPP and decide whether the euro is over- or undervalued.

> Returned the data-prep steps (convert daily DEXUSEU to monthly averages, align from January 1999, stop at the last month with both CPIs), the RER formula, and the implied-rate formula S_PPP(t) = RER(Jan 1999) × CPI_US(t) / HICP(t).

**Prompt 2.** Here are my three FRED CSV downloads. Build the spreadsheet.

> Flagged two download problems before building: the U.S. file was CPIAUCSL_PC1 (percent change from a year ago) instead of the CPIAUCNS index level, and DEXUSEU only started in October 2021 (FRED's five-year default). Also noted that FRED has no October 2025 U.S. CPI because of the federal government shutdown.

**Prompt 3.** Here are the corrected CPIAUCNS and DEXUSEU (monthly average, from 1999) files.

> Built an Excel workbook with live formulas: a monthly data tab, an RER chart against the January 1999 benchmark, and an actual vs. PPP-implied rate chart. Result for September 2026: benchmark RER 0.4026, PPP-implied rate 1.3008 USD per EUR, actual 1.1505, so the euro was 11.6% undervalued against the dollar.

**Prompt 4.** Explain why in-sample and out-of-sample performance can differ. Then: make it much more concise.

> Four reasons: overfitting, look-ahead bias, structural breaks and data mining, plus a horizon effect for slow-reverting RERs (noise dominates at short horizons).

### Session 2: October 25, 2026 (Streamlit app)

**Prompt 5.** Build a real exchange rate Streamlit app with IMF data. Let users choose Country 1 and Country 2 from IMF countries and the Euro area, and retrieve monthly IMF CPI and exchange-rate data from January 1976 where available. Define S(t) as units of Country 2 currency per one unit of Country 1 currency, with P1(t) and P2(t) the monthly CPIs, and calculate RER(t) = S(t) × P1(t) / P2(t). Over user-selected start and end months, calculate RER* as the average RER over valid months and plot Real Index(t) = 100 × RER(t) / RER*, recalculating RER* when the dates change. Plot nominal S(t) in actual currency units without normalizing it. Let users choose Real, Nominal or Both (separate axes for Both) in interactive charts, and provide a CSV download of all observations and calculations in the sample period. Use the IMF SDMX 3.0 API at https://api.imf.org/external/sdmx/3.0 with CPI key {ISO3}.CPI._T.IX.M and exchange-rate key {ISO3}.XDC_USD.PA_RT.M, G163 for the Euro area, and convert the IMF's local-currency-per-USD rates to the S(t) direction. IMF data may have gaps. Return complete app.py, requirements.txt and README.md files compatible with Python 3.12.

> Returned the three files. S(t) is computed as (Country 2 per USD) / (Country 1 per USD), with the U.S. rate fixed at 1. The IMF API could not be reached from the model's environment, so the app reads both SDMX-CSV and SDMX-JSON and shows a request log for debugging. Verified by feeding the FRED data in IMF format: RER for January 1999 = 0.4026 and S for September 2026 = 1.1505 (both match the spreadsheet), swapping countries gives the reciprocal RER, and the Real Index averages exactly 100 over any window.

**Prompt 6.** I'm posting this to a public GitHub repo. Make sure nothing in it exposes my Claude account or details, and that no one can run up charges on my account.

> Scanned the files for keys, tokens, email addresses and account details and found none. The app never calls Claude; the IMF API is free and keyless, and Streamlit Community Cloud is free.

**Prompt 7.** Can we demo the app here?

> Ran the actual app.py with FRED data standing in for the IMF API and returned screenshots of the Real, Nominal and Both views for Euro area vs. U.S.

**Prompt 8.** Make it color-themed to the Kellogg School of Management and put the logo in the top left of the page.

> Applied the Northwestern purple palette (#4E2A84) through `.streamlit/config.toml` and the chart colors. The model did not reproduce the trademarked logo; instead the app shows `kellogg_logo.png` in the top left if that file is added to the repo.

**Prompt 9.** What else could we add to make the app more useful? What other metrics do economists analyze alongside the real exchange rate?

> Suggested a benchmark toggle (base month vs. window average, from the assignment's benchmark strategies), the PPP-implied rate with a forecast, a random-walk backtest (Meese and Rogoff), the half-life of RER deviations, the inflation differential, the real effective exchange rate, the current account, interest rate differentials and rolling volatility.

**Prompt 10.** Build the benchmark toggle, PPP-implied rate and forecast, half-life, and backtest.

> Added all four (see "Forecasting and diagnostics"). Checks: a January 1999 base month reproduces part (b) exactly (1.3008, −11.6%); the half-life is 4.4 years, inside the 3 to 5 year range in the literature; the backtest shows the RER model does not beat a random walk for the euro since 1999 at 12 to 60 month horizons.

**Prompt 11.** Create a README with a cleaned-up prompt log that covers the entire conversation.

> This section.

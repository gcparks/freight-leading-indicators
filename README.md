# Leading Indicators of North American Freight Rate Pressure

A multi-source statistical analysis identifying predictive signals for freight rate movements across major North American logistics corridors.

---

## Thesis

Freight rate movements are predictable when you layer in signals that most logistics analysts aren't watching — crop progress, refinery utilization, river gauge levels, regional manufacturing indices, and retail inventory ratios — alongside traditional freight metrics. This project quantifies those leading relationships using cross-correlation analysis, Granger causality testing, regime detection, and multivariate regression.

## Key Findings

Five independent signals **Granger-cause** truckload trucking costs at p < 0.05:

| Leading Indicator | Lead Time | p-value | Mechanism |
|---|---|---|---|
| Personal Consumption Expenditures | 8 months | 0.005 | Consumer spending → supply chain pull-through → freight demand |
| Retail Inventory/Sales Ratio | 2 months | 0.020 | Shelves emptying → restocking orders → trucking demand spike |
| Durable Goods Manufacturing Orders | 1 month | 0.020 | Factory order books fill → freight follows |
| Philly Fed Delivery Times | 1 month | 0.048 | Supply chain congestion signal → trucking impact |
| Philly Fed Future New Orders | 2 months | 0.021 | Forward-looking manufacturing sentiment → freight demand |

A sixth signal — **Consumer Sentiment** — leads the overall Freight Transportation Services Index by 3 months (p = 0.022), suggesting household confidence is an early demand signal for the entire freight market.

> **What does "Granger-cause" mean?** A signal Granger-causes another if knowing its past values improves your forecast *beyond what the target's own history provides*. It's not just correlation — it's statistically validated predictive power.

## Data Sources

All sources are free, public, and from government or industry-standard providers.

| Source | Signal | Frequency |
|---|---|---|
| EIA / FRED | Diesel prices (national + PADD regions) | Weekly |
| Federal Reserve | Refinery production index | Monthly |
| Philly Fed | Mfg delivery times, future new orders | Monthly |
| Dallas Fed | Mfg delivery times, new orders | Monthly |
| U.S. Census | Durable goods orders | Monthly |
| U.S. Census | Retail inventory/sales ratio | Monthly |
| BEA | Personal consumption expenditures | Monthly |
| U. of Michigan | Consumer sentiment index | Monthly |
| BTS | Freight Transportation Services Index | Monthly |
| BLS | Trucking PPI (truckload and LTL) | Monthly |
| USDA NASS | Crop harvest progress by state | Weekly (seasonal) |
| NOAA / NWS | Severe weather alerts by zone | Real-time |

## Analysis Pipeline

```
Data Sources (11)          Analysis                    Output
─────────────────     ─────────────────────     ──────────────────
EIA Diesel      ─┐    STL Seasonal               Methodology Doc
FRED (16 series) ┤    Decomposition               (docs/)
NOAA Weather    ─┤         │
USDA Crop       ─┤    Cross-Correlation           Analysis JSON
                 │    at 0–12 month lags          (data/processed/)
                 │         │
                 ├──▶ Granger Causality           Weekly Report
                 │    Testing (p < 0.05)          (reports/)
                 │         │
                 │    Regime Detection
                 │    (Hidden Markov Model)
                 │         │
                 └    Multivariate OLS
                      Regression
```

## Architecture

```
freight-leading-indicators/
├── src/
│   ├── ingest/              # One module per data source
│   │   ├── fred_series.py   # 16 FRED series in one pull
│   │   ├── eia_diesel.py    # Regional diesel by PADD
│   │   ├── noaa_weather.py  # Severe weather → freight corridors
│   │   ├── usda_crop.py     # Grain belt harvest progress
│   │   ├── usace_rivers.py  # Mississippi River gauges (stub)
│   │   ├── aar_rail.py      # Rail carloads (stub)
│   │   └── bts_transborder.py
│   ├── analysis/
│   │   └── analyze.py       # STL, cross-correlation, Granger, HMM, OLS
│   ├── report/
│   │   └── render.py        # Jinja2 → Markdown/HTML
│   ├── init_db.py           # DuckDB schema
│   └── run_pipeline.py      # Orchestrator
├── docs/
│   └── Freight_Leading_Indicators_Methodology.docx
├── data/                    # Generated at runtime
├── reports/                 # Published weekly
├── templates/
├── .github/workflows/
│   └── weekly_analysis.yml  # Tuesday 15:00 UTC cron
├── requirements.txt
└── .env.example
```

## Tech Stack

- **Python** — pandas, statsmodels, scipy, hmmlearn, matplotlib, seaborn
- **DuckDB** — analytical data store (single portable file, no server)
- **GitHub Actions** — weekly automated ingestion + analysis
- **Jinja2** — report rendering

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/freight-leading-indicators.git
cd freight-leading-indicators

pip install -r requirements.txt

cp .env.example .env
# Add free API keys: EIA, FRED, USDA (see .env.example for links)

python src/init_db.py
python src/run_pipeline.py
```

## Roadmap

- [x] FRED multi-series ingestion (16 series)
- [x] EIA regional diesel ingestion
- [x] NOAA weather alerts → freight corridor mapping
- [x] USDA crop progress ingestion
- [x] Seasonal decomposition (STL)
- [x] Cross-correlation at multiple lags
- [x] Granger causality testing
- [x] Regime detection (HMM) — needs more history
- [x] Methodology document
- [ ] Mississippi River gauge integration (barge-to-truck diversion signal)
- [ ] AAR weekly rail carload data (cross-modal capacity shifts)
- [ ] BTS transborder freight flows
- [ ] Multivariate OLS model (needs 5+ year history)
- [ ] Published weekly report on GitHub Pages
- [ ] Visualization layer (correlation heatmaps, regime charts)

## Limitations

The current dataset covers approximately three years of monthly observations. While the Granger results are statistically significant, a longer historical window (5–10 years) would strengthen confidence and enable the regime detection and multivariate modeling components. The consistency of findings across multiple independent signals supports their credibility despite the sample size constraint.

## Author

**Grayson Parks** — Principal Strategic Advisor, Customer Analytics

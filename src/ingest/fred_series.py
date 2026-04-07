"""
Ingest multiple time series from the FRED API.

This single module pulls the majority of our signals — diesel prices,
refinery production, manufacturing indices, retail inventory ratios,
and freight volume indices — all from one API.

Source: Federal Reserve Bank of St. Louis (FRED)
Auth: Free API key (https://fred.stlouisfed.org/docs/api/api_key.html)

Usage:
    python -m src.ingest.fred_series
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "lane_health.duckdb"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# ── Series Catalog ─────────────────────────────────────────────────
# Each entry: (series_id, human name, units, category)
# All IDs verified against FRED as of April 2026.

SERIES_CATALOG = [
    # ── Diesel & Energy Costs ──
    ("GASDESW", "US Diesel Sales Price", "$/gal", "energy"),
    ("DDFUELUSGULF", "Ultra-Low Sulfur Diesel - Gulf Coast", "$/gal", "energy"),

    # ── Refinery Production (proxy for utilization) ──
    ("IPG32411S", "Industrial Production: Petroleum Refineries", "Index", "energy"),

    # ── Federal Reserve Manufacturing Indices ──
    # Philly Fed (District 3: DE, southern NJ, eastern/central PA)
    ("DTCDFSA066MSFRBPHI", "Philly Fed Mfg: Delivery Times (Diffusion, SA)", "Index", "manufacturing"),
    ("NOFDFSA066MSFRBPHI", "Philly Fed Mfg: Future New Orders (Diffusion, SA)", "Index", "manufacturing"),

    # Dallas Fed (Texas manufacturing — Gulf Coast corridor)
    ("DTMSAMFRBDAL", "Dallas Fed Mfg: Delivery Times (Diffusion)", "Index", "manufacturing"),
    ("VNWOSAMFRBDAL", "Dallas Fed Mfg: New Orders (Diffusion, SA)", "Index", "manufacturing"),

    # National durable goods orders (broad manufacturing demand signal)
    ("DGORDER", "Mfg New Orders: Durable Goods", "$M", "manufacturing"),

    # ── Retail Inventory ──
    # When inventory-to-sales drops, restocking drives import/freight demand
    ("RETAILIRSA", "Retail Inventories/Sales Ratio", "Ratio", "demand"),
    ("RETAILIMSA", "Retail Inventories (ex auto)", "$M", "demand"),
    ("RSAFS", "Advance Retail Sales", "$M", "demand"),

    # ── Freight Volume Indices ──
    ("TSIFRGHT", "Freight Transportation Services Index", "Index (2000=100)", "freight"),

    # ── Trucking Producer Prices ──
    # Direct measure of trucking cost pressure — our primary target variable
    ("PCU484121484121", "PPI: General Freight Trucking, Long-Distance TL", "Index", "freight"),
    ("PCU484122484122", "PPI: General Freight Trucking, Long-Distance LTL", "Index", "freight"),

    # ── Consumer Demand Signals ──
    ("UMCSENT", "U of Michigan Consumer Sentiment", "Index", "demand"),
    ("PCE", "Personal Consumption Expenditures", "$B", "demand"),
]


def fetch_series(api_key: str, series_id: str, start_date: str) -> pd.DataFrame:
    """Fetch a single FRED series."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "desc",
    }

    response = requests.get(FRED_BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    observations = data.get("observations", [])
    if not observations:
        return pd.DataFrame()

    df = pd.DataFrame(observations)
    df = df[df["value"] != "."]  # FRED uses "." for missing
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[["date", "value"]].dropna()

    return df


def fetch_all_series(api_key: str, lookback_years: int = 3) -> pd.DataFrame:
    """
    Fetch all series in the catalog and return a unified long-format DataFrame.
    """
    start_date = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")
    all_rows = []

    for series_id, name, units, category in SERIES_CATALOG:
        try:
            logger.info(f"Fetching {series_id}: {name}")
            df = fetch_series(api_key, series_id, start_date)

            if df.empty:
                logger.warning(f"  No data returned for {series_id}")
                continue

            df["series_id"] = series_id
            df["series_name"] = name
            df["units"] = units
            df["frequency"] = "Weekly" if len(df) > 100 else "Monthly"

            all_rows.append(df)
            logger.info(f"  {len(df)} observations")

        except Exception as e:
            logger.error(f"  Failed to fetch {series_id}: {e}")
            continue

    if not all_rows:
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    logger.info(f"Total: {len(combined)} observations across {len(all_rows)} series")
    return combined


def save_raw(df: pd.DataFrame):
    """Save raw FRED data snapshot."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"fred_series_{ts}.parquet"
    df.to_parquet(path, index=False)
    logger.info(f"Raw data saved: {path}")


def load_to_duckdb(df: pd.DataFrame):
    """Upsert FRED series into DuckDB."""
    con = duckdb.connect(str(DB_PATH))
    con.register("staging", df)

    con.execute("""
        INSERT OR REPLACE INTO fred_series (date, series_id, series_name, value, units, frequency)
        SELECT date, series_id, series_name, value, units, frequency
        FROM staging
    """)

    count = con.execute("SELECT COUNT(*) FROM fred_series").fetchone()[0]
    series_count = con.execute("SELECT COUNT(DISTINCT series_id) FROM fred_series").fetchone()[0]
    logger.info(f"fred_series table: {count} rows across {series_count} series")
    con.close()


def run(lookback_years: int = 3):
    """Full FRED ingestion pipeline."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FRED_API_KEY not set. Get a free key at "
            "https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    df = fetch_all_series(api_key, lookback_years=lookback_years)

    if df.empty:
        logger.warning("No data fetched from FRED")
        return

    save_raw(df)
    load_to_duckdb(df)
    logger.info("FRED ingestion complete")
    return df


if __name__ == "__main__":
    run()

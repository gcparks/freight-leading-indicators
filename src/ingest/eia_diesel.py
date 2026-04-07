"""
Ingest weekly retail on-highway diesel prices by PADD region from EIA API.
This provides regional granularity beyond what FRED carries.

Source: U.S. Energy Information Administration (api.eia.gov/v2/)
Frequency: Weekly (published Tuesdays)
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

EIA_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"

REGION_MAP = {
    "R00": "US Average",
    "R10": "East Coast (PADD 1)",
    "R1X": "New England (PADD 1A)",
    "R1Y": "Central Atlantic (PADD 1B)",
    "R1Z": "Lower Atlantic (PADD 1C)",
    "R20": "Midwest (PADD 2)",
    "R30": "Gulf Coast (PADD 3)",
    "R40": "Rocky Mountain (PADD 4)",
    "R50": "West Coast (PADD 5)",
    "R5XCA": "California",
}


def fetch_diesel_prices(api_key: str, start_date: str = None) -> pd.DataFrame:
    if not start_date:
        start_date = (datetime.now() - timedelta(weeks=156)).strftime("%Y-%m-%d")  # 3 years

    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[duoarea][]": list(REGION_MAP.keys()),
        "facets[product][]": ["EPD2D"],
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "start": start_date,
        "length": 5000,
    }

    logger.info(f"Fetching EIA diesel prices from {start_date}")
    response = requests.get(EIA_BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    records = data.get("response", {}).get("data", [])
    logger.info(f"Received {len(records)} records")

    if not records:
        return pd.DataFrame(columns=["date", "region", "price_per_gal"])

    df = pd.DataFrame(records)
    df = df.rename(columns={"period": "date", "duoarea": "region_id", "value": "price_per_gal"})
    df["region"] = df["region_id"].map(REGION_MAP)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["price_per_gal"] = pd.to_numeric(df["price_per_gal"], errors="coerce")
    df = df.dropna(subset=["price_per_gal", "region"])

    return df[["date", "region", "price_per_gal"]].sort_values(["date", "region"])


def load_to_duckdb(df: pd.DataFrame):
    con = duckdb.connect(str(DB_PATH))
    con.register("staging", df)
    con.execute("""
        INSERT OR REPLACE INTO diesel_prices (date, region, price_per_gal)
        SELECT date, region, price_per_gal FROM staging
    """)
    count = con.execute("SELECT COUNT(*) FROM diesel_prices").fetchone()[0]
    logger.info(f"diesel_prices: {count} rows")
    con.close()


def run():
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        raise EnvironmentError("EIA_API_KEY not set")

    df = fetch_diesel_prices(api_key)
    if df.empty:
        logger.warning("No diesel data fetched")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(RAW_DIR / f"eia_diesel_{datetime.now():%Y%m%d_%H%M%S}.parquet", index=False)
    load_to_duckdb(df)
    logger.info("EIA diesel ingestion complete")
    return df


if __name__ == "__main__":
    run()

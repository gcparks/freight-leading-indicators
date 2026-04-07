"""
Ingest USDA crop progress data from the NASS QuickStats API.

Tracks harvest progress for key freight-driving commodities (corn,
soybeans, winter wheat). Early/late harvests shift truck demand across
Midwest corridors by weeks.

Source: USDA National Agricultural Statistics Service
API: https://quickstats.nass.usda.gov/api/
Frequency: Weekly (Monday, April–November)
Auth: Free API key
"""

import os
import logging
from datetime import datetime
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

NASS_BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

# Key freight-driving crops and the measures that matter
TARGET_COMMODITIES = ["CORN", "SOYBEANS", "WHEAT"]

# States along major grain freight corridors
GRAIN_BELT_STATES = [
    "IOWA", "ILLINOIS", "INDIANA", "OHIO", "MINNESOTA",
    "NEBRASKA", "KANSAS", "MISSOURI", "SOUTH DAKOTA", "NORTH DAKOTA",
]


def fetch_crop_progress(api_key: str, year: int = None) -> pd.DataFrame:
    """
    Fetch crop progress data for grain belt states.
    Pulls harvest % and condition ratings.
    """
    if year is None:
        year = datetime.now().year

    all_data = []

    for commodity in TARGET_COMMODITIES:
        params = {
            "key": api_key,
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "group_desc": "FIELD CROPS",
            "commodity_desc": commodity,
            "statisticcat_desc": "PROGRESS",
            "unit_desc": "PCT HARVESTED",
            "freq_desc": "WEEKLY",
            "year": year,
            "format": "JSON",
        }

        try:
            logger.info(f"Fetching {commodity} progress for {year}")
            response = requests.get(NASS_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json().get("data", [])
            logger.info(f"  {len(data)} records")
            all_data.extend(data)
        except Exception as e:
            logger.error(f"  Failed for {commodity}: {e}")

    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data)

    # Filter to grain belt states
    df = df[df["state_name"].str.upper().isin(GRAIN_BELT_STATES)]

    # Parse week ending date
    df["week_ending"] = pd.to_datetime(df["week_ending"]).dt.date
    df["value"] = pd.to_numeric(df["Value"], errors="coerce")

    result = df[[
        "week_ending", "state_name", "commodity_desc", "unit_desc", "value"
    ]].rename(columns={
        "state_name": "state",
        "commodity_desc": "commodity",
        "unit_desc": "measure",
    }).dropna(subset=["value"])

    return result


def load_to_duckdb(df: pd.DataFrame):
    con = duckdb.connect(str(DB_PATH))
    con.register("staging", df)
    con.execute("""
        INSERT OR REPLACE INTO crop_progress (week_ending, state, commodity, measure, value)
        SELECT week_ending, state, commodity, measure, value FROM staging
    """)
    count = con.execute("SELECT COUNT(*) FROM crop_progress").fetchone()[0]
    logger.info(f"crop_progress: {count} rows")
    con.close()


def run():
    api_key = os.getenv("USDA_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "USDA_API_KEY not set. Get a free key at "
            "https://quickstats.nass.usda.gov/api/"
        )

    # Fetch current and prior year for YoY comparison
    current_year = datetime.now().year
    frames = []
    for year in [current_year - 1, current_year]:
        df = fetch_crop_progress(api_key, year)
        if not df.empty:
            frames.append(df)

    if not frames:
        logger.warning("No crop progress data fetched")
        return

    combined = pd.concat(frames, ignore_index=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(RAW_DIR / f"usda_crop_{datetime.now():%Y%m%d_%H%M%S}.parquet", index=False)
    load_to_duckdb(combined)
    logger.info("USDA crop progress ingestion complete")
    return combined


if __name__ == "__main__":
    run()

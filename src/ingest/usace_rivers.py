"""
Ingest Mississippi River gauge levels from USACE.

Low water on the Mississippi forces grain and bulk commodities from
barge to truck/rail — a massive demand shock for interior corridors.

Source: U.S. Army Corps of Engineers
API: https://rivergages.mvr.usace.army.mil/watercontrol/webservices/
Frequency: Daily (we pull latest readings at pipeline run)
Auth: None required
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "lane_health.duckdb"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Key Mississippi River gauges for freight impact
# These are the choke points where low water restricts barge traffic
GAUGES = {
    "01300": {"name": "Memphis, TN", "river": "Mississippi", "flood": 34.0, "low_water": -10.0},
    "01100": {"name": "Cairo, IL", "river": "Mississippi", "flood": 40.0, "low_water": -10.0},
    "04025": {"name": "St. Louis, MO", "river": "Mississippi", "flood": 30.0, "low_water": -2.0},
    "04245": {"name": "Vicksburg, MS", "river": "Mississippi", "flood": 43.0, "low_water": 0.0},
    "01545": {"name": "Baton Rouge, LA", "river": "Mississippi", "flood": 35.0, "low_water": 2.0},
    "76060": {"name": "New Orleans, LA (Carrollton)", "river": "Mississippi", "flood": 17.0, "low_water": -1.0},
}

# USACE provides data via their Water Management web services
# Alternative: NOAA Advanced Hydrologic Prediction Service
NOAA_AHPS_URL = "https://api.water.noaa.gov/nwps/v1/gauges/{gauge_id}/stageflow"


def fetch_gauge_data_noaa(gauge_nws_id: str, days_back: int = 90) -> pd.DataFrame:
    """
    Fetch river stage data from NOAA's National Water Prediction Service.

    Note: NOAA gauge IDs differ from USACE IDs. This is a placeholder
    for the correct mapping. The NOAA NWPS API provides observed and
    forecast stage/flow data.
    """
    # TODO: Map USACE gauge IDs to NOAA NWS location IDs
    # Example NWS IDs: MEMM6 (Memphis), CIRL1 (Cairo), EADM7 (St. Louis)
    raise NotImplementedError(
        "River gauge fetch needs USACE-to-NOAA ID mapping. "
        "Alternative: scrape USACE rivergages directly."
    )


def load_from_csv(csv_path: str) -> pd.DataFrame:
    """
    Load manually downloaded gauge data.
    Expected columns: date, gauge_id, stage_ft
    """
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_to_duckdb(df: pd.DataFrame):
    con = duckdb.connect(str(DB_PATH))
    con.register("staging", df)
    con.execute("""
        INSERT OR REPLACE INTO river_gauges
            (date, gauge_id, gauge_name, river, stage_ft, flood_stage_ft, low_water_ft)
        SELECT date, gauge_id, gauge_name, river, stage_ft, flood_stage_ft, low_water_ft
        FROM staging
    """)
    count = con.execute("SELECT COUNT(*) FROM river_gauges").fetchone()[0]
    logger.info(f"river_gauges: {count} rows")
    con.close()


def run():
    logger.warning(
        "River gauge ingestion not yet fully implemented. "
        "Next step: map USACE gauge IDs to NOAA NWS location IDs, "
        "or implement direct USACE web service scraper."
    )


if __name__ == "__main__":
    run()

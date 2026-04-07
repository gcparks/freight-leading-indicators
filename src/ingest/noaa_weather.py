"""
Ingest active severe weather alerts from the NWS API and map them
to major freight corridors.

Source: National Weather Service (api.weather.gov)
Frequency: Real-time (pulled at pipeline run)
Auth: No API key required, just a User-Agent header

Usage:
    python -m src.ingest.noaa_weather
    python src/ingest/noaa_weather.py
"""

import os
import json
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

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

# ── Freight Corridor Definitions ───────────────────────────────────
# Map NWS state/zone codes to major freight corridors.
# These are the corridors where weather disruption has the most
# impact on truck freight and intermodal operations.

CORRIDOR_STATE_MAP = {
    "I-10 Gulf Coast": ["TX", "LA", "MS", "AL", "FL"],
    "I-35 Central": ["TX", "OK", "KS", "MO", "IA", "MN"],
    "I-65 Midwest-South": ["AL", "TN", "KY", "IN"],
    "I-70 East-West": ["KS", "MO", "IL", "IN", "OH", "PA"],
    "I-75 Great Lakes": ["FL", "GA", "TN", "KY", "OH", "MI"],
    "I-80 Northern": ["NJ", "PA", "OH", "IN", "IL", "IA", "NE", "WY", "UT", "NV", "CA"],
    "I-90 Northern Tier": ["MA", "NY", "PA", "OH", "IN", "IL", "WI", "MN", "SD", "WY", "MT", "WA"],
    "I-95 Eastern Seaboard": ["FL", "GA", "SC", "NC", "VA", "DC", "MD", "DE", "PA", "NJ", "NY", "CT", "RI", "MA"],
    "Port of LA/Long Beach": ["CA"],
    "Port of Houston/Gulf": ["TX", "LA"],
    "Port of Savannah/Charleston": ["GA", "SC"],
    "Port of NY/NJ": ["NJ", "NY"],
}

# Weather event types most likely to disrupt freight
FREIGHT_RELEVANT_EVENTS = {
    "Winter Storm Warning", "Winter Storm Watch", "Blizzard Warning",
    "Ice Storm Warning", "Freezing Rain Advisory",
    "Hurricane Warning", "Hurricane Watch", "Tropical Storm Warning",
    "Tornado Warning", "Tornado Watch", "Severe Thunderstorm Warning",
    "Flood Warning", "Flash Flood Warning", "Flood Watch",
    "Extreme Wind Warning", "High Wind Warning",
    "Dense Fog Advisory",  # major cause of highway pileups
}


def map_state_to_corridors(state_code: str) -> list[str]:
    """Given a 2-letter state code, return all freight corridors it belongs to."""
    corridors = []
    for corridor, states in CORRIDOR_STATE_MAP.items():
        if state_code in states:
            corridors.append(corridor)
    return corridors


def extract_state_from_zone(zone_id: str) -> str | None:
    """
    Extract state code from NWS zone ID.
    Zone IDs look like 'TXZ104' (Texas zone 104) or 'TXC201' (Texas county 201).
    """
    if zone_id and len(zone_id) >= 2:
        return zone_id[:2]
    return None


def fetch_active_alerts(user_agent: str) -> list[dict]:
    """
    Fetch all active weather alerts from NWS, filtered to
    freight-relevant event types.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}

    logger.info("Fetching active NWS weather alerts")
    response = requests.get(NWS_ALERTS_URL, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()
    features = data.get("features", [])
    logger.info(f"Received {len(features)} total active alerts")

    # Filter to freight-relevant events
    relevant = []
    for feature in features:
        props = feature.get("properties", {})
        event = props.get("event", "")
        if event in FREIGHT_RELEVANT_EVENTS:
            relevant.append(props)

    logger.info(f"Filtered to {len(relevant)} freight-relevant alerts")
    return relevant


def alerts_to_dataframe(alerts: list[dict]) -> pd.DataFrame:
    """Convert NWS alert properties to a structured DataFrame."""
    records = []

    for alert in alerts:
        # NWS provides affected zones as a list of zone URLs
        zone_ids = []
        zone_names = []

        # geocode contains UGC zone codes
        geocode = alert.get("geocode", {})
        ugc_codes = geocode.get("UGC", [])

        # Determine affected states and corridors
        affected_states = set()
        for code in ugc_codes:
            state = extract_state_from_zone(code)
            if state:
                affected_states.add(state)

        corridors = set()
        for state in affected_states:
            corridors.update(map_state_to_corridors(state))

        # Create one record per corridor affected
        corridor_str = "; ".join(sorted(corridors)) if corridors else "Unknown"

        records.append({
            "alert_id": alert.get("id", ""),
            "effective": alert.get("effective"),
            "expires": alert.get("expires"),
            "event_type": alert.get("event", ""),
            "severity": alert.get("severity", ""),
            "urgency": alert.get("urgency", ""),
            "zone_id": ", ".join(ugc_codes[:5]),  # first 5 zones
            "zone_name": alert.get("areaDesc", "")[:500],
            "headline": alert.get("headline", "")[:500],
            "description": (alert.get("description", "") or "")[:2000],
            "corridor": corridor_str,
        })

    df = pd.DataFrame(records)

    if not df.empty:
        df["effective"] = pd.to_datetime(df["effective"], utc=True)
        df["expires"] = pd.to_datetime(df["expires"], utc=True, errors="coerce")

    return df


def save_raw(df: pd.DataFrame):
    """Save raw alerts snapshot."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"noaa_alerts_{ts}.parquet"
    df.to_parquet(path, index=False)
    logger.info(f"Raw alerts saved: {path}")


def load_to_duckdb(df: pd.DataFrame):
    """Upsert weather alerts into DuckDB."""
    con = duckdb.connect(str(DB_PATH))
    con.register("staging", df)

    con.execute("""
        INSERT OR REPLACE INTO weather_alerts
            (alert_id, effective, expires, event_type, severity,
             urgency, zone_id, zone_name, headline, description, corridor)
        SELECT alert_id, effective, expires, event_type, severity,
               urgency, zone_id, zone_name, headline, description, corridor
        FROM staging
    """)

    count = con.execute("SELECT COUNT(*) FROM weather_alerts").fetchone()[0]
    logger.info(f"weather_alerts table now has {count} rows")
    con.close()


def run():
    """Full ingestion pipeline for NOAA weather alerts."""
    user_agent = os.getenv("NOAA_USER_AGENT", "(lane-health-briefing, contact@example.com)")

    alerts = fetch_active_alerts(user_agent)

    if not alerts:
        logger.info("No freight-relevant weather alerts currently active")
        return pd.DataFrame()

    df = alerts_to_dataframe(alerts)
    save_raw(df)
    load_to_duckdb(df)
    logger.info("NOAA weather ingestion complete")

    return df


if __name__ == "__main__":
    run()

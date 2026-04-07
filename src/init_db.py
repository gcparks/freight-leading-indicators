"""
Initialize the DuckDB database with schema for all data sources.
Safe to re-run (IF NOT EXISTS throughout).
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "lane_health.duckdb"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    # ── FRED time series (catches diesel, mfg indices, inventory, TSI, refinery) ──
    # Generic table for any FRED series — normalized for cross-correlation
    con.execute("""
        CREATE TABLE IF NOT EXISTS fred_series (
            date          DATE NOT NULL,
            series_id     VARCHAR NOT NULL,    -- e.g. 'GASDESW', 'AWHMAN'
            series_name   VARCHAR,
            value         DOUBLE NOT NULL,
            units         VARCHAR,
            frequency     VARCHAR,             -- 'Weekly', 'Monthly'
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, series_id)
        )
    """)

    # ── EIA Diesel Prices (regional detail beyond what FRED carries) ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS diesel_prices (
            date          DATE NOT NULL,
            region        VARCHAR NOT NULL,
            price_per_gal DOUBLE NOT NULL,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, region)
        )
    """)

    # ── EIA Refinery Utilization ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS refinery_utilization (
            date          DATE NOT NULL,
            padd          VARCHAR NOT NULL,    -- 'PADD 1', 'PADD 3', etc.
            utilization_pct DOUBLE NOT NULL,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, padd)
        )
    """)

    # ── Container Rates (FBX) ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS container_rates (
            date          DATE NOT NULL,
            lane_code     VARCHAR NOT NULL,
            lane_name     VARCHAR,
            rate_per_feu  DOUBLE NOT NULL,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, lane_code)
        )
    """)

    # ── AAR Rail Carloads ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS rail_volumes (
            week_ending   DATE NOT NULL,
            category      VARCHAR NOT NULL,    -- 'Total Carloads', 'Intermodal', commodity types
            volume        DOUBLE NOT NULL,
            yoy_change_pct DOUBLE,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (week_ending, category)
        )
    """)

    # ── USDA Crop Progress ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS crop_progress (
            week_ending   DATE NOT NULL,
            state         VARCHAR NOT NULL,
            commodity     VARCHAR NOT NULL,    -- 'CORN', 'SOYBEANS', 'WINTER WHEAT'
            measure       VARCHAR NOT NULL,    -- 'PCT HARVESTED', 'PCT GOOD/EXCELLENT'
            value         DOUBLE NOT NULL,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (week_ending, state, commodity, measure)
        )
    """)

    # ── USACE River Gauge Levels ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS river_gauges (
            date          DATE NOT NULL,
            gauge_id      VARCHAR NOT NULL,
            gauge_name    VARCHAR,
            river         VARCHAR,             -- 'Mississippi', 'Ohio', 'Missouri'
            stage_ft      DOUBLE NOT NULL,
            flood_stage_ft DOUBLE,
            low_water_ft  DOUBLE,
            ingested_at   TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, gauge_id)
        )
    """)

    # ── NOAA Weather Alerts ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS weather_alerts (
            alert_id      VARCHAR PRIMARY KEY,
            effective     TIMESTAMP NOT NULL,
            expires       TIMESTAMP,
            event_type    VARCHAR NOT NULL,
            severity      VARCHAR,
            urgency       VARCHAR,
            zone_id       VARCHAR,
            zone_name     VARCHAR,
            headline      VARCHAR,
            description   TEXT,
            corridor      VARCHAR,
            ingested_at   TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # ── BTS Transborder Freight ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS transborder_freight (
            month         DATE NOT NULL,
            border        VARCHAR NOT NULL,
            mode          VARCHAR NOT NULL,
            commodity     VARCHAR,
            port          VARCHAR,
            value_usd     DOUBLE NOT NULL,
            ingested_at   TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # ── Analysis Results (materialized for report rendering) ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            run_date      DATE NOT NULL,
            analysis_name VARCHAR NOT NULL,    -- 'granger_causality', 'cross_correlation', etc.
            parameters    VARCHAR,             -- JSON of params used
            results       VARCHAR,             -- JSON of results
            PRIMARY KEY (run_date, analysis_name)
        )
    """)

    con.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    init_db()

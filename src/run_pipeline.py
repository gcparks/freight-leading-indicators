"""
Run the full Leading Indicators pipeline.

Steps:
  1. Initialize database
  2. Ingest data from all active sources
  3. Run statistical analysis
  4. (Future) Render report

Usage:
    python src/run_pipeline.py                # full pipeline
    python src/run_pipeline.py --ingest-only  # just pull data
    python src/run_pipeline.py --analyze-only # re-run analysis on existing data
"""

import argparse
import logging
import sys
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_ingest():
    logger.info("=" * 60)
    logger.info("PHASE 1: Data Ingestion")
    logger.info("=" * 60)

    modules = [
        ("FRED multi-series", "src.ingest.fred_series"),
        ("EIA diesel (regional)", "src.ingest.eia_diesel"),
        ("NOAA weather alerts", "src.ingest.noaa_weather"),
        ("USDA crop progress", "src.ingest.usda_crop"),
        ("USACE river gauges", "src.ingest.usace_rivers"),
        ("AAR rail carloads", "src.ingest.aar_rail"),
        ("BTS transborder", "src.ingest.bts_transborder"),
    ]

    for name, module_path in modules:
        try:
            logger.info(f"── {name} ──")
            mod = __import__(module_path, fromlist=["run"])
            mod.run()
        except NotImplementedError:
            logger.info(f"  {name}: not yet implemented — skipping")
        except EnvironmentError as e:
            logger.warning(f"  {name}: {e}")
        except Exception as e:
            logger.error(f"  {name} failed: {e}")


def run_analysis():
    logger.info("=" * 60)
    logger.info("PHASE 2: Statistical Analysis")
    logger.info("=" * 60)

    from src.analysis.analyze import run_full_analysis
    return run_full_analysis()


def main():
    parser = argparse.ArgumentParser(description="Freight Leading Indicators Pipeline")
    parser.add_argument("--ingest-only", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()

    logger.info("Freight Leading Indicators Pipeline — Starting")
    logger.info(f"Date: {date.today()}")

    from src.init_db import init_db
    init_db()

    if args.analyze_only:
        run_analysis()
    elif args.ingest_only:
        run_ingest()
    else:
        run_ingest()
        run_analysis()

    logger.info("Pipeline complete")


if __name__ == "__main__":
    main()

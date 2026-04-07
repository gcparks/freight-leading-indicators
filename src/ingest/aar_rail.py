"""
Ingest AAR weekly rail carload and intermodal volume data.

When rail intermodal drops, freight shifts to trucks and tightens
the spot market. Rail carloads by commodity type (grain, chemicals,
coal) signal sector-level demand shifts.

Source: Association of American Railroads (aar.org)
Frequency: Weekly (Wednesdays)
Access: Public weekly reports (PDF/press releases); historical
        data may require AAR membership or manual collection.

TODO:
  - AAR publishes weekly press releases with top-line numbers
  - Implement scraper for weekly carload/intermodal totals
  - Alternative: FRED carries some rail freight series
    (check RAILFRTCARLOADSD11 and similar)
  - BTS also publishes seasonally adjusted rail data monthly

Usage:
    python -m src.ingest.aar_rail
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run():
    logger.warning(
        "AAR rail ingestion not yet implemented. "
        "Check FRED for rail series (RAILFRTCARLOADSD11) as alternative, "
        "or scrape AAR weekly press releases."
    )


if __name__ == "__main__":
    run()

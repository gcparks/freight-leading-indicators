"""
Ingest BTS Transborder Freight Data.

Source: Bureau of Transportation Statistics
Frequency: Monthly (~2 month lag)
Access: CSV download from https://data.bts.gov/stories/s/myhq-rm6q

TODO: Implement BTS Socrata API or CSV download
"""

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run():
    logging.getLogger(__name__).warning("BTS transborder ingestion not yet implemented.")


if __name__ == "__main__":
    run()

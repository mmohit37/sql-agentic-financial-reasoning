"""
Allows running ace_research.xbrl.ingest as a module:

    python -m ace_research.xbrl.ingest --company Microsoft --file data/sec/msft.htm

This file simply invokes the main() function from ingest.py
"""

from ace_research.xbrl.ingest import main

if __name__ == "__main__":
    main()

# ace_research/xbrl/mappings.py

XBRL_METRIC_MAP = {
    # Income Statement
    "Revenues": "revenue",
    "NetIncomeLoss": "net_income",
    "OperatingIncomeLoss": "operating_income",
    "GrossProfit": "gross_profit",

    # Balance Sheet
    "Assets": "total_assets",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "total_equity",
    "AssetsCurrent": "current_assets",
    "LiabilitiesCurrent": "current_liabilities",

    # Cash / derived support
    "EarningsBeforeInterestTaxesDepreciationAmortization": "ebitda",
}
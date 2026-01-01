# ace_research/xbrl/mappings.py

XBRL_METRIC_MAP = {
    # Revenue
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue",

    # Income
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "OperatingIncomeLoss": "operating_income",

    # Balance Sheet
    "Assets": "total_assets",
    "AssetsCurrent": "current_assets",

    "Liabilities": "total_liabilities",
    "LiabilitiesCurrent": "current_liabilities",

    "StockholdersEquity": "total_equity",

    # Cash & equivalents (optional but useful)
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "ShortTermInvestments": "short_term_investments",
    "LongTermInvestments": "long_term_investments",
}
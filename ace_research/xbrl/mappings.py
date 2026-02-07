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

    # --- Piotroski F-Score inputs ---

    # Cash flow from operations
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",

    # Debt
    "LongTermDebt": "long_term_debt",
    "LongTermDebtNoncurrent": "long_term_debt",

    # Profitability
    "GrossProfit": "gross_profit",
    "CostOfRevenue": "cost_of_revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",

    # Shares outstanding
    "CommonStockSharesOutstanding": "shares_outstanding",
    "EntityCommonStockSharesOutstanding": "shares_outstanding",
}
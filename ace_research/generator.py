def format_comparison_answer(metric, year, results):
    valid = {k: v for k, v in results.items() if v is not None}

    if len(valid) < 2:
        return {
            "answer": valid,
            "winner": None,
            "explanation": "Insufficient comparable data across companies."
        }

    winner = max(valid, key=lambda k: valid[k])
    loser = min(valid, key=lambda k: valid[k])

    return {
        "metric": metric,
        "year": year,
        "winner": winner,
        "winner_value": valid[winner],
        "loser": loser,
        "loser_value": valid[loser],
        "all_values": valid,
        "explanation": (
            f"{winner} has a higher {metric.replace('_',' ')} "
            f"than {loser} in {year}."
        )
    }
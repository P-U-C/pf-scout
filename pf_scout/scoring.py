"""Shared scoring logic for pf-scout.

This module provides reusable scoring functions for evaluating contacts
against rubric dimensions. Used by prospect, report, and other commands.
"""

# ---------------------------------------------------------------------------
# Default keyword sets for heuristic scoring
# ---------------------------------------------------------------------------

TECH_KEYWORDS = [
    "infrastructure", "devops", "backend", "engineering", "smart contract",
    "blockchain", "solidity", "rust", "python", "go", "typescript",
    "kubernetes", "docker", "cloud", "aws", "api", "protocol", "security",
    "cryptography", "zk", "evm", "validator", "rpc",
]

QUANT_KEYWORDS = [
    "quant", "quantitative", "machine learning", "ml", "statistics",
    "trading", "signal", "forecasting", "data science", "analytics",
    "on-chain", "onchain", "backtesting", "risk management", "portfolio",
    "financial modeling", "time series", "alpha", "macro", "research",
    "modeling", "prediction", "probability",
]

# ---------------------------------------------------------------------------
# Default dimensions (used when no rubric YAML provided)
# ---------------------------------------------------------------------------

DEFAULT_DIMENSIONS = [
    {"key": "technical_depth", "label": "Technical Depth", "weight": 1},
    {"key": "forecasting", "label": "Forecasting / Quantitative Potential", "weight": 1},
    {"key": "operational_reliability", "label": "Operational Reliability", "weight": 1},
    {"key": "engagement_consistency", "label": "Engagement Consistency", "weight": 1},
]


# ---------------------------------------------------------------------------
# Text extraction and keyword utilities
# ---------------------------------------------------------------------------

def get_text_blob(row: dict) -> str:
    """Concatenate all text fields from a leaderboard row for keyword search.
    
    Args:
        row: A leaderboard row dictionary with summary, capabilities, etc.
    
    Returns:
        Lowercased concatenated text for keyword matching.
    """
    parts = []
    if row.get("summary"):
        parts.append(str(row["summary"]))
    for cap in row.get("capabilities") or []:
        if isinstance(cap, dict):
            parts.append(" ".join(str(v) for v in cap.values()))
        else:
            parts.append(str(cap))
    for ek in row.get("expert_knowledge") or []:
        if isinstance(ek, dict):
            parts.append(" ".join(str(v) for v in ek.values()))
        else:
            parts.append(str(ek))
    return " ".join(parts).lower()


def apply_keyword_heuristics(text: str, keywords: list[str]) -> int:
    """Count keyword hits and convert to a 1-5 score.
    
    Args:
        text: The lowercased text to search in.
        keywords: List of keywords to look for.
    
    Returns:
        Score from 1-5 based on number of keyword matches.
    """
    hits = sum(1 for kw in keywords if kw in text)
    if hits == 0:
        return 1
    if hits == 1:
        return 2
    if hits == 2:
        return 3
    if hits <= 4:
        return 4
    return 5


def count_keyword_hits(text: str, keywords: list[str]) -> int:
    """Count how many distinct keywords appear in text.
    
    Args:
        text: The lowercased text to search in.
        keywords: List of keywords to look for.
    
    Returns:
        Number of keyword matches.
    """
    return sum(1 for kw in keywords if kw in text)


def get_matching_keywords(text: str, keywords: list[str], limit: int = 5) -> list[str]:
    """Get list of matching keywords from text.
    
    Args:
        text: The lowercased text to search in.
        keywords: List of keywords to look for.
        limit: Maximum number of matches to return.
    
    Returns:
        List of matched keywords (up to limit).
    """
    return [kw for kw in keywords if kw in text][:limit]


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------

def score_technical_depth(row: dict) -> int:
    """Score technical depth (1-5) based on tech keywords and sybil score.
    
    Args:
        row: Leaderboard row with capabilities, summary, sybil_score.
    
    Returns:
        Score from 1-5.
    """
    text = get_text_blob(row)
    base = apply_keyword_heuristics(text, TECH_KEYWORDS)
    if (row.get("sybil_score") or 0) >= 85:
        base += 1
    return min(base, 5)


def score_forecasting(row: dict) -> int:
    """Score quantitative/forecasting potential (1-5).
    
    Args:
        row: Leaderboard row with capabilities, alignment_score, monthly_rewards.
    
    Returns:
        Score from 1-5.
    """
    text = get_text_blob(row)
    base = apply_keyword_heuristics(text, QUANT_KEYWORDS)
    if (row.get("alignment_score") or 0) >= 90:
        base += 1
    if (row.get("monthly_rewards") or 0) > 500000:
        base += 1
    return min(base, 5)


def score_operational_reliability(row: dict) -> int:
    """Score operational reliability (1-5) based on leaderboard metrics.
    
    Args:
        row: Leaderboard row with leaderboard_score_month, monthly_tasks, rewards.
    
    Returns:
        Score from 1-5.
    """
    lsm = row.get("leaderboard_score_month") or 0
    if lsm < 15:
        base = 1
    elif lsm < 40:
        base = 2
    elif lsm < 60:
        base = 3
    elif lsm < 80:
        base = 4
    else:
        base = 5
    if (row.get("monthly_tasks") or 0) >= 30:
        base += 1
    monthly = row.get("monthly_rewards") or 0
    weekly = row.get("weekly_rewards") or 0
    if monthly > 0:
        ratio = weekly / monthly
        if 0.2 <= ratio <= 0.35:
            base += 1
    return min(base, 5)


def score_engagement_consistency(row: dict) -> int:
    """Score engagement consistency (1-5) based on weekly activity.
    
    Args:
        row: Leaderboard row with weekly_rewards, leaderboard_score_week.
    
    Returns:
        Score from 1-5.
    """
    weekly = row.get("weekly_rewards") or 0
    if weekly <= 0:
        base = 1
    elif weekly <= 50000:
        base = 2
    elif weekly <= 150000:
        base = 3
    elif weekly <= 300000:
        base = 4
    else:
        base = 5
    if (row.get("leaderboard_score_week") or 0) > 50:
        base += 1
    return min(base, 5)


# ---------------------------------------------------------------------------
# Scorer registry
# ---------------------------------------------------------------------------

SCORERS = {
    "technical_depth": score_technical_depth,
    "forecasting": score_forecasting,
    "operational_reliability": score_operational_reliability,
    "engagement_consistency": score_engagement_consistency,
}


# ---------------------------------------------------------------------------
# High-level scoring functions
# ---------------------------------------------------------------------------

def score_dimension(row: dict, dimension_key: str, keywords: list[str] | None = None) -> int:
    """Score a single dimension (1-5).
    
    If a registered scorer exists for the dimension_key, use it.
    Otherwise, fall back to keyword heuristics if keywords are provided.
    
    Args:
        row: The data row to score.
        dimension_key: The dimension identifier (e.g., 'technical_depth').
        keywords: Optional list of keywords for heuristic scoring.
    
    Returns:
        Score from 1-5.
    """
    scorer = SCORERS.get(dimension_key)
    if scorer:
        return scorer(row)
    
    # Fallback to keyword heuristics
    if keywords:
        text = get_text_blob(row)
        return apply_keyword_heuristics(text, keywords)
    
    return 1  # Default score if no scorer and no keywords


def score_contact(row: dict, dimensions: list[dict]) -> dict:
    """Score all dimensions for a contact, return scores and tier.
    
    Args:
        row: The contact/leaderboard row to score.
        dimensions: List of dimension dicts with 'key', 'label', 'weight'.
    
    Returns:
        Dict with:
            - scores: {dimension_key: score} mapping
            - composite: sum of all scores
            - max: maximum possible score
            - pct: composite as percentage of max
            - tier: tier label based on percentage
    """
    scores = {}
    for dim in dimensions:
        key = dim["key"]
        keywords = dim.get("keywords")  # Optional custom keywords
        scores[key] = score_dimension(row, key, keywords)
    
    composite = sum(scores.values())
    max_possible = len(dimensions) * 5
    pct = composite / max_possible if max_possible else 0
    
    if pct >= 0.8:
        tier = "🔴 Top Tier"
    elif pct >= 0.6:
        tier = "🟡 Mid Tier"
    else:
        tier = "⚪ Speculative"
    
    return {
        "scores": scores,
        "composite": composite,
        "max": max_possible,
        "pct": pct,
        "tier": tier,
    }


def evidence_sentence(row: dict, dim_key: str) -> str:
    """Generate a brief evidence sentence for a dimension score.
    
    Args:
        row: The data row.
        dim_key: The dimension key.
    
    Returns:
        Human-readable evidence string.
    """
    text = get_text_blob(row)
    
    if dim_key == "technical_depth":
        hits = get_matching_keywords(text, TECH_KEYWORDS, limit=5)
        if hits:
            return f"Keywords matched: {', '.join(hits)}."
        return "No technical keywords found in profile."
    
    if dim_key == "forecasting":
        hits = get_matching_keywords(text, QUANT_KEYWORDS, limit=5)
        if hits:
            return f"Keywords matched: {', '.join(hits)}."
        return "No quantitative keywords found in profile."
    
    if dim_key == "operational_reliability":
        lsm = row.get("leaderboard_score_month") or 0
        mt = row.get("monthly_tasks") or 0
        return f"Leaderboard score (month): {lsm}, monthly tasks: {mt}."
    
    if dim_key == "engagement_consistency":
        wr = row.get("weekly_rewards") or 0
        lsw = row.get("leaderboard_score_week") or 0
        return f"Weekly rewards: {wr:,.0f}, leaderboard score (week): {lsw}."
    
    return "No evidence available."


def infer_role(row: dict) -> str:
    """Infer a likely role based on profile keywords.
    
    Args:
        row: The data row with capabilities, summary, etc.
    
    Returns:
        Role string like 'Signal / Quant', 'Infrastructure', etc.
    """
    text = get_text_blob(row)
    
    if any(kw in text for kw in ["trading", "quant", "alpha", "signal"]):
        return "Signal / Quant"
    if any(kw in text for kw in ["infrastructure", "devops", "kubernetes", "docker"]):
        return "Infrastructure"
    if any(kw in text for kw in ["smart contract", "solidity", "evm", "blockchain"]):
        return "Protocol Engineer"
    if any(kw in text for kw in ["research", "analytics", "data science"]):
        return "Researcher"
    
    return "Contributor"

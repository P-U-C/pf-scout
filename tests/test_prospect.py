"""Tests for the prospect pipeline scoring and document generation."""

from pf_scout.commands.prospect import (
    DEFAULT_DIMENSIONS,
    generate_document,
    score_engagement_consistency,
    score_forecasting,
    score_operational_reliability,
    score_row,
    score_technical_depth,
)


def _make_row(**overrides):
    """Create a mock leaderboard row with sensible defaults."""
    row = {
        "wallet_address": "rMockWallet123",
        "summary": "A contributor",
        "capabilities": [],
        "expert_knowledge": [],
        "monthly_rewards": 100000,
        "monthly_tasks": 10,
        "weekly_rewards": 25000,
        "alignment_score": 70,
        "alignment_tier": "medium",
        "sybil_score": 60,
        "sybil_risk": "low",
        "leaderboard_score_month": 50,
        "leaderboard_score_week": 30,
        "is_published": True,
        "user_id": "user-1",
    }
    row.update(overrides)
    return row


class TestScoringDimensions:
    """Test individual dimension scoring functions."""

    def test_technical_depth_no_keywords(self):
        row = _make_row(capabilities=[], expert_knowledge=[], summary="hello")
        assert score_technical_depth(row) == 1

    def test_technical_depth_many_keywords(self):
        row = _make_row(
            capabilities=["python", "rust", "docker", "kubernetes", "aws", "solidity"],
            summary="blockchain infrastructure engineer",
        )
        score = score_technical_depth(row)
        assert score >= 4

    def test_technical_depth_sybil_bonus(self):
        row = _make_row(capabilities=["python"], sybil_score=90)
        score_with_bonus = score_technical_depth(row)
        row2 = _make_row(capabilities=["python"], sybil_score=50)
        score_without = score_technical_depth(row2)
        assert score_with_bonus >= score_without

    def test_forecasting_no_keywords(self):
        row = _make_row(capabilities=[], summary="gardener")
        assert score_forecasting(row) == 1

    def test_forecasting_with_keywords_and_bonuses(self):
        row = _make_row(
            capabilities=["quant", "machine learning", "trading", "backtesting", "signal"],
            alignment_score=95,
            monthly_rewards=600000,
        )
        assert score_forecasting(row) == 5  # capped

    def test_operational_reliability_low_score(self):
        row = _make_row(leaderboard_score_month=10, monthly_tasks=5, weekly_rewards=0)
        assert score_operational_reliability(row) == 1

    def test_operational_reliability_high_score(self):
        row = _make_row(
            leaderboard_score_month=85,
            monthly_tasks=35,
            monthly_rewards=100000,
            weekly_rewards=25000,  # ratio = 0.25
        )
        score = score_operational_reliability(row)
        assert score == 5  # 5 base + 1 tasks + 1 ratio = 7 → capped at 5

    def test_engagement_consistency_zero_weekly(self):
        row = _make_row(weekly_rewards=0)
        assert score_engagement_consistency(row) == 1

    def test_engagement_consistency_high(self):
        row = _make_row(weekly_rewards=400000, leaderboard_score_week=60)
        assert score_engagement_consistency(row) == 5  # 5 + 1 → capped


class TestCompositeAndTiers:
    """Test composite scoring and tier assignment."""

    def test_composite_is_sum_of_dimensions(self):
        row = _make_row(
            capabilities=["python", "rust"],
            leaderboard_score_month=50,
            weekly_rewards=100000,
        )
        result = score_row(row, DEFAULT_DIMENSIONS)
        expected_sum = sum(result["scores"].values())
        assert result["composite"] == expected_sum

    def test_max_is_dimensions_times_five(self):
        row = _make_row()
        result = score_row(row, DEFAULT_DIMENSIONS)
        assert result["max"] == len(DEFAULT_DIMENSIONS) * 5

    def test_top_tier_threshold(self):
        # Force high scores everywhere
        row = _make_row(
            capabilities=[
                "python", "rust", "docker", "kubernetes", "aws", "solidity",
                "quant", "machine learning", "trading", "backtesting", "signal",
            ],
            summary="blockchain infrastructure quant engineer",
            sybil_score=90,
            alignment_score=95,
            monthly_rewards=600000,
            leaderboard_score_month=90,
            monthly_tasks=40,
            weekly_rewards=400000,
            leaderboard_score_week=60,
        )
        result = score_row(row, DEFAULT_DIMENSIONS)
        assert result["tier"] == "🔴 Top Tier"

    def test_speculative_tier(self):
        row = _make_row(
            capabilities=[],
            summary="newbie",
            leaderboard_score_month=5,
            monthly_tasks=2,
            weekly_rewards=0,
        )
        result = score_row(row, DEFAULT_DIMENSIONS)
        assert result["tier"] == "⚪ Speculative"

    def test_mid_tier(self):
        # Medium scores: need composite/max >= 0.6 but < 0.8
        # Max = 20, so need 12-15
        row = _make_row(
            capabilities=["python", "rust", "docker"],
            summary="engineer with trading experience",
            leaderboard_score_month=60,
            monthly_tasks=20,
            weekly_rewards=100000,
            leaderboard_score_week=30,
        )
        result = score_row(row, DEFAULT_DIMENSIONS)
        assert result["tier"] in ("🟡 Mid Tier", "🔴 Top Tier")


class TestDocumentGeneration:
    """Test that the output document contains required sections."""

    def test_document_has_required_sections(self):
        rows = [
            _make_row(
                wallet_address="rWallet1",
                summary="Alice",
                capabilities=["python"],
                leaderboard_score_month=50,
                weekly_rewards=100000,
            ),
            _make_row(
                wallet_address="rWallet2",
                summary="Bob",
                capabilities=["rust", "docker"],
                leaderboard_score_month=70,
                weekly_rewards=200000,
            ),
        ]
        doc = generate_document(rows, DEFAULT_DIMENSIONS, "test-rubric", "Test", 0)

        assert "## Executive Summary" in doc
        assert "## Scoring Rubric" in doc
        assert "## Scored Prospect Table" in doc
        assert "## Prospect Profiles" in doc

    def test_document_contains_contributors(self):
        rows = [_make_row(wallet_address="rW1", summary="Charlie")]
        doc = generate_document(rows, DEFAULT_DIMENSIONS, "test", "Test", 0)
        assert "Charlie" in doc
        assert "rW1" in doc

    def test_min_composite_filters(self):
        rows = [_make_row(summary="LowScorer", capabilities=[], weekly_rewards=0,
                          leaderboard_score_month=5)]
        doc = generate_document(rows, DEFAULT_DIMENSIONS, "test", "Test", 99)
        assert "LowScorer" not in doc

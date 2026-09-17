# -*- coding: utf-8 -*-
"""Market Intelligence Package — EPIC 04."""

from __future__ import annotations

from .intelligence import (
    AnalystReport,
    CommitteeDecision,
    MarketDepartment,
    MarketLead,
    NewsSentimentAnalyst,
    StructureAnalyst,
    TechnicalAnalyst,
    VolatilityAnalyst,
)
from .news_feed import NewsFeedProvider, get_news_feed_provider, score_headline_sentiment

__all__ = [
    "MarketLead",
    "MarketDepartment",
    "TechnicalAnalyst",
    "StructureAnalyst",
    "VolatilityAnalyst",
    "NewsSentimentAnalyst",
    "AnalystReport",
    "CommitteeDecision",
    "NewsFeedProvider",
    "get_news_feed_provider",
    "score_headline_sentiment",
]

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

RouteName = Literal[
    "local_knowledge",
    "live_data",
    "current_facts",
    "news_research",
    "browser_task",
]

@dataclass
class RouteDecision:
    route: RouteName
    reason: str
    confidence: float
    topic: Optional[str] = None
    location: Optional[str] = None
    timeframe: Optional[str] = None

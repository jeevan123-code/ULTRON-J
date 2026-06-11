"""Phase 6 world-event dataclass.

A `WorldEvent` is one item produced by a source adapter (RSS feed,
NewsAPI, Alpha Vantage). The poller scores them via `interest_matcher`
and persists matched ones to `worldfeed_store`.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


@dataclass
class WorldEvent:
    title: str
    summary: str
    url: str
    source: str
    ts: float
    tickers: List[str] = field(default_factory=list)
    score: float = 0.0

    def __post_init__(self) -> None:
        self.score = _clamp(self.score)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "ts": self.ts,
            "tickers": list(self.tickers),
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorldEvent":
        return cls(
            title=d.get("title", ""),
            summary=d.get("summary", ""),
            url=d.get("url", ""),
            source=d.get("source", ""),
            ts=float(d.get("ts", 0.0)),
            tickers=list(d.get("tickers") or []),
            score=float(d.get("score", 0.0)),
        )

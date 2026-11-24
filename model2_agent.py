from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from model2_agent_data import (
    candidate_ranking,
    collector_health,
    load_fills,
    load_orders,
    load_portfolio,
    load_rejections,
    order_explanation,
    session_summary,
    system_snapshot,
)


NEW_YORK = ZoneInfo("America/New_York")

KNOWN_TICKERS = {
    "AAPL", "MSFT", "NVDA", "AVGO", "GOOGL", "META", "AMZN", "TSLA",
    "PLTR", "ORCL", "AMD", "MU", "TSM", "QCOM", "ASML", "LRCX", "AMAT",
    "KLAC", "LITE", "VRT", "ETN", "EQIX", "DLR", "CEG", "VST", "GEV",
    "JPM", "BAC", "C", "WFC", "GS", "MS", "JNJ", "LLY", "UNH", "ABBV",
    "XOM", "CVX", "COP", "CAT", "GE", "HON", "WMT", "COST", "HD", "NFLX",
    "LIN", "NUE", "PG", "NEE",
}

DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


@dataclass
class AgentReply:
    kind: str
    title: str
    text: str
    data: Any = None
    suggestions: tuple[str, ...] = ()


def _extract_ticker(prompt: str) -> str | None:
    tokens = re.findall(r"\b[A-Za-z]{1,5}\b", prompt)

    for token in tokens:
        ticker = token.upper()
        if ticker in KNOWN_TICKERS:
            return ticker

    return None


def _extract_date(prompt: str) -> str | None:
    match = DATE_RE.search(prompt)
    if match:
        return match.group(1)

    text = prompt.lower()
    today = datetime.now(timezone.utc).astimezone(NEW_YORK).date()

    if "today" in text:
        return today.isoformat()

    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()

    return None


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _status_summary(snapshot: dict[str, Any]) -> str:
    p = snapshot["portfolio"]
    c = snapshot["collector"]
    pending = len(snapshot["pending_orders"])

    health = "healthy" if c["healthy"] else "needs attention"

    return (
        f"Model 2 is {health}. "
        f"Portfolio value is ${p['total_equity']:,.2f}, "
        f"cash is ${p['cash']:,.2f}, "
        f"there are {len(p['positions'])} open position(s), "
        f"and {pending} pending order(s)."
    )


def _ticker_explanation(ticker: str) -> AgentReply:
    data = order_explanation(ticker)

    orders = data["orders"]
    fills = data["fills"]
    rejections = data["rejections"]

    if not orders and not fills and not rejections:
        return AgentReply(
            kind="message",
            title=f"{ticker}",
            text=f"I could not find any Model 2 trading history for {ticker}.",
            suggestions=(
                "Show strongest signals",
                "Show my latest trades",
            ),
        )

    latest_order = orders[0] if orders else None
    latest_fill = fills[0] if fills else None
    latest_rejection = rejections[0] if rejections else None

    parts: list[str] = []

    if latest_order:
        parts.append(
            f"The latest {ticker} order was "
            f"{latest_order['side']} {latest_order['quantity']} share(s) "
            f"for the {latest_order['session']} execution session, "
            f"and its final status is {latest_order['status']}."
        )

    if latest_fill:
        parts.append(
            f"It filled at ${latest_fill['fill_price']:.2f} "
            f"against a ${latest_fill['reference_price']:.2f} reference price."
        )

    if latest_rejection:
        parts.append(
            f"The latest rejection code is {latest_rejection['code']}. "
            f"{latest_rejection['reason']}"
        )

    # Be explicit about what is and is not persisted.
    parts.append(
        "This answer is based on persisted orders, fills, and rejection records. "
        "The database does not store a full natural-language explanation of the "
        "historical signal at decision time."
    )

    return AgentReply(
        kind="ticker",
        title=f"{ticker} Explanation",
        text=" ".join(parts),
        data=data,
        suggestions=(
            f"Show {ticker} trade history",
            "Show strongest signals",
            "Show portfolio",
        ),
    )


def answer(prompt: str) -> AgentReply:
    raw = prompt.strip()
    text = _normalize(raw)

    if not raw:
        return AgentReply(
            kind="message",
            title="Model 2",
            text="Ask me about the portfolio, trades, signals, rejections, collector, or a specific ticker.",
        )

    if text in {"help", "?", "commands"} or "what can you do" in text:
        return AgentReply(
            kind="help",
            title="What you can ask",
            text=(
                "You can ask naturally. Examples: "
                "'How is the agent doing?', 'What do I own?', "
                "'Why was HON rejected?', 'What happened today?', "
                "'Show GE history', 'What are the strongest signals?', "
                "or 'How much cash do I have?'."
            ),
            suggestions=(
                "Give me a full status report",
                "What do I currently own?",
                "Show my latest trades",
                "Show strongest signals",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "full status",
            "system status",
            "status report",
            "how is the agent",
            "how are we doing",
            "is the system healthy",
            "system healthy",
            "overall status",
            "agent status",
        )
    ) or text == "status":
        snapshot = system_snapshot()
        return AgentReply(
            kind="status",
            title="Model 2 System Status",
            text=_status_summary(snapshot),
            data=snapshot,
            suggestions=(
                "Show portfolio",
                "Show pending orders",
                "Is the collector healthy?",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "collector",
            "data fresh",
            "data current",
            "freshness",
            "observations current",
        )
    ):
        return AgentReply(
            kind="collector",
            title="Collector Health",
            text="Current intraday observation health.",
            data=collector_health(),
            suggestions=(
                "Give me a full status report",
                "Show strongest signals",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "candidate",
            "signal",
            "strongest",
            "best opportunities",
            "best stocks",
            "buy ideas",
            "trade ideas",
        )
    ):
        return AgentReply(
            kind="candidates",
            title="Strongest Trade Candidates",
            text=(
                "Current read-only ranking from the existing Model 2 "
                "20-session momentum and SMA signal scan."
            ),
            data=candidate_ranking(top_n=10),
            suggestions=(
                "Show portfolio",
                "Show pending orders",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "pending",
            "next trades",
            "next orders",
            "waiting to execute",
            "awaiting execution",
        )
    ):
        rows = load_orders(status="PENDING", limit=100)
        return AgentReply(
            kind="orders",
            title="Pending Orders",
            text=(
                "There are no pending Model 2 orders."
                if not rows
                else f"There are {len(rows)} pending Model 2 order(s)."
            ),
            data=rows,
            suggestions=(
                "Show latest trades",
                "Give me a full status report",
            ),
        )

    ticker = _extract_ticker(raw)

    if any(
        phrase in text
        for phrase in (
            "rejection",
            "rejected",
            "expired",
            "why did",
            "why was",
        )
    ) and ticker:
        return _ticker_explanation(ticker)

    if any(
        phrase in text
        for phrase in (
            "rejection",
            "rejected",
            "expired",
        )
    ):
        rows = load_rejections(limit=25)
        return AgentReply(
            kind="rejections",
            title="Recent Rejections",
            text=f"Showing {len(rows)} recent rejection record(s).",
            data=rows,
            suggestions=(
                "Why was HON rejected?",
                "Show latest trades",
            ),
        )

    session = _extract_date(raw)

    if session and any(
        phrase in text
        for phrase in (
            "what happened",
            "summary",
            "trades",
            "orders",
            "session",
            "today",
            "yesterday",
        )
    ):
        data = session_summary(session)

        return AgentReply(
            kind="session",
            title=f"Session {session}",
            text=(
                f"For {session}, Model 2 recorded "
                f"{len(data['orders'])} order(s), "
                f"{len(data['fills'])} fill(s), and "
                f"{len(data['rejections'])} rejection(s)."
            ),
            data=data,
            suggestions=(
                "Show portfolio",
                "Show strongest signals",
            ),
        )

    if ticker and any(
        phrase in text
        for phrase in (
            "why",
            "explain",
            "what happened",
            "history",
            "trade",
            "fill",
            "order",
        )
    ):
        return _ticker_explanation(ticker)

    if any(
        phrase in text
        for phrase in (
            "what do i own",
            "what am i holding",
            "what are we holding",
            "portfolio",
            "positions",
            "holdings",
            "performance",
            "profit",
            "return",
            "p/l",
            "pnl",
        )
    ):
        portfolio = load_portfolio()

        return AgentReply(
            kind="portfolio",
            title="Model 2 Portfolio",
            text=(
                f"Portfolio value is ${portfolio['total_equity']:,.2f}. "
                f"Total P/L is ${portfolio['total_pnl']:,.2f} "
                f"({portfolio['total_return']:.2f}%)."
            ),
            data=portfolio,
            suggestions=(
                "How much cash do I have?",
                "Show latest trades",
                "Show strongest signals",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "cash",
            "available money",
            "buying power",
            "how much money",
        )
    ):
        portfolio = load_portfolio()

        return AgentReply(
            kind="message",
            title="Available Cash",
            text=(
                f"Model 2 currently has ${portfolio['cash']:,.2f} in cash. "
                f"Market exposure is {portfolio['exposure']:.2f}%."
            ),
            data=portfolio,
            suggestions=(
                "Show portfolio",
                "Show pending orders",
            ),
        )

    if any(
        phrase in text
        for phrase in (
            "latest trades",
            "recent trades",
            "latest fills",
            "recent fills",
            "what did we trade",
        )
    ):
        rows = load_fills(limit=15)
        return AgentReply(
            kind="fills",
            title="Recent Fills",
            text=f"Showing the {len(rows)} most recent fill(s).",
            data=rows,
            suggestions=(
                "Show portfolio",
                "Show recent rejections",
            ),
        )

    if "orders" in text:
        rows = load_orders(limit=20)
        return AgentReply(
            kind="orders",
            title="Recent Orders",
            text=f"Showing {len(rows)} recent order(s).",
            data=rows,
            suggestions=(
                "Show pending orders",
                "Show latest trades",
            ),
        )

    return AgentReply(
        kind="message",
        title="I didn't fully understand that",
        text=(
            "Try asking naturally about status, portfolio, cash, trades, "
            "pending orders, rejections, strongest signals, collector health, "
            "a ticker such as 'why GE?', or a date such as "
            "'what happened on 2026-11-20?'."
        ),
        suggestions=(
            "Give me a full status report",
            "What do I currently own?",
            "Show my latest trades",
        ),
    )

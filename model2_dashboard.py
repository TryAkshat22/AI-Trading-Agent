from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)

from model2_candidate_ranking import (
    scan_model2_candidates,
)


# ============================================================
# CONFIGURATION
# ============================================================

NEW_YORK = ZoneInfo("America/New_York")
ZERO = Decimal("0")

EXECUTION_TASK = (
    "Paper Trading - Model 2 Guarded Execution"
)

DECISION_TASK = (
    "Paper Trading - Model 2 Daily Decision"
)


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Model 2 Trading Dashboard",
    page_icon="📈",
    layout="wide",
)


st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }

        div[data-testid="stMetric"] {
            background-color: rgba(128,128,128,0.08);
            border: 1px solid rgba(128,128,128,0.18);
            padding: 15px;
            border-radius: 10px;
        }

        .status-good {
            padding: 10px 14px;
            border-radius: 8px;
            background: rgba(0, 180, 90, 0.10);
            border: 1px solid rgba(0, 180, 90, 0.30);
        }

        .status-info {
            padding: 10px 14px;
            border-radius: 8px;
            background: rgba(80, 120, 220, 0.10);
            border: 1px solid rgba(80, 120, 220, 0.30);
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Lot:
    quantity: int
    price: Decimal


# ============================================================
# HELPERS
# ============================================================

def decimal_value(value) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def percent(value: Decimal) -> str:
    return f"{value:.2f}%"


def get_paths():
    paths = get_model2_paths()

    return (
        Path(
            paths.model2_database
        ).expanduser().resolve(),
        Path(
            paths.observation_database
        ).expanduser().resolve(),
    )


def ro_connection(database: Path):
    connection = sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True,
        timeout=10,
    )

    connection.execute(
        "PRAGMA query_only = ON"
    )

    return connection


# ============================================================
# PORTFOLIO
# ============================================================

@st.cache_data(ttl=30)
def load_portfolio():
    model2_db, observation_db = get_paths()

    with ro_connection(model2_db) as connection:

        account = connection.execute(
            """
            SELECT starting_cash
            FROM paper_accounts
            WHERE account_id = ?
            """,
            (MODEL_2_ACCOUNT_ID,),
        ).fetchone()

        if account is None:
            raise RuntimeError(
                "Model 2 account not found."
            )

        starting_cash = decimal_value(
            account[0]
        )

        fills = connection.execute(
            """
            SELECT
                fill_id,
                order_id,
                ticker,
                side,
                quantity,
                fill_price,
                created_at_utc
            FROM paper_fills
            ORDER BY created_at_utc, fill_id
            """
        ).fetchall()

    cash = starting_cash
    realized_pnl = ZERO

    lots = defaultdict(deque)

    for (
        fill_id,
        order_id,
        ticker,
        side,
        quantity,
        fill_price,
        created_at,
    ) in fills:

        ticker = ticker.upper()
        side = side.upper()

        quantity = int(quantity)
        price = decimal_value(fill_price)

        if side == "BUY":

            cash -= (
                Decimal(quantity)
                * price
            )

            lots[ticker].append(
                Lot(
                    quantity=quantity,
                    price=price,
                )
            )

        elif side == "SELL":

            cash += (
                Decimal(quantity)
                * price
            )

            remaining = quantity

            while remaining > 0:

                if not lots[ticker]:
                    raise RuntimeError(
                        f"SELL exceeds position: {ticker}"
                    )

                lot = lots[ticker][0]

                used = min(
                    remaining,
                    lot.quantity,
                )

                realized_pnl += (
                    Decimal(used)
                    * (
                        price
                        - lot.price
                    )
                )

                lot.quantity -= used
                remaining -= used

                if lot.quantity == 0:
                    lots[ticker].popleft()

    position_rows = []

    market_value = ZERO
    unrealized_pnl = ZERO

    with ro_connection(
        observation_db
    ) as connection:

        for ticker in sorted(lots):

            ticker_lots = [
                lot
                for lot in lots[ticker]
                if lot.quantity > 0
            ]

            if not ticker_lots:
                continue

            quantity = sum(
                lot.quantity
                for lot in ticker_lots
            )

            cost_basis = sum(
                Decimal(lot.quantity)
                * lot.price
                for lot in ticker_lots
            )

            average_cost = (
                cost_basis
                / Decimal(quantity)
            )

            price_row = connection.execute(
                """
                SELECT
                    close_price,
                    bar_start_utc
                FROM intraday_observations
                WHERE ticker = ?
                ORDER BY
                    bar_start_utc DESC,
                    retrieved_at_utc DESC
                LIMIT 1
                """,
                (ticker,),
            ).fetchone()

            price_source = "Intraday"

            if price_row is None:

                price_row = connection.execute(
                    """
                    SELECT
                        close,
                        session_date
                    FROM market_bars
                    WHERE ticker = ?
                    ORDER BY
                        session_date DESC,
                        id DESC
                    LIMIT 1
                    """,
                    (ticker,),
                ).fetchone()

                price_source = "Daily"

            if price_row is None:
                raise RuntimeError(
                    "No price available for "
                    f"{ticker}."
                )

            current_price = decimal_value(
                price_row[0]
            )

            price_time = str(
                price_row[1]
            )

            position_value = (
                Decimal(quantity)
                * current_price
            )

            pnl = (
                position_value
                - cost_basis
            )

            return_pct = (
                pnl
                / cost_basis
                * Decimal("100")
            )

            market_value += position_value
            unrealized_pnl += pnl

            position_rows.append(
                {
                    "Ticker": ticker,
                    "Shares": quantity,
                    "Average Cost": float(
                        average_cost
                    ),
                    "Current Price": float(
                        current_price
                    ),
                    "Market Value": float(
                        position_value
                    ),
                    "P/L": float(pnl),
                    "Return %": float(
                        return_pct
                    ),
                    "Price Source": price_source,
                    "Price Time": price_time,
                }
            )

    total_equity = (
        cash
        + market_value
    )

    total_pnl = (
        total_equity
        - starting_cash
    )

    total_return = (
        (
            total_pnl
            / starting_cash
        )
        * Decimal("100")
        if starting_cash
        else ZERO
    )

    exposure = (
        (
            market_value
            / total_equity
        )
        * Decimal("100")
        if total_equity
        else ZERO
    )

    return {
        "starting_cash": starting_cash,
        "cash": cash,
        "market_value": market_value,
        "total_equity": total_equity,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "total_return": total_return,
        "exposure": exposure,
        "positions": position_rows,
    }


# ============================================================
# ORDERS
# ============================================================

@st.cache_data(ttl=30)
def load_orders():

    model2_db, _ = get_paths()

    with ro_connection(
        model2_db
    ) as connection:

        pending = connection.execute(
            """
            SELECT
                order_id,
                ticker,
                side,
                quantity,
                execution_session
            FROM paper_orders
            WHERE model_version = ?
              AND status = 'PENDING'
            ORDER BY
                execution_session,
                ticker
            """,
            (MODEL_2_VERSION,),
        ).fetchall()

        recent = connection.execute(
            """
            SELECT
                order_id,
                ticker,
                side,
                quantity,
                execution_session,
                status
            FROM paper_orders
            WHERE model_version = ?
            ORDER BY
                execution_session DESC,
                order_id DESC
            LIMIT 20
            """,
            (MODEL_2_VERSION,),
        ).fetchall()

    pending_df = pd.DataFrame(
        pending,
        columns=[
            "Order ID",
            "Ticker",
            "Side",
            "Quantity",
            "Execution Session",
        ],
    )

    recent_df = pd.DataFrame(
        recent,
        columns=[
            "Order ID",
            "Ticker",
            "Side",
            "Quantity",
            "Session",
            "Status",
        ],
    )

    return (
        pending_df,
        recent_df,
    )


# ============================================================
# REJECTIONS
# ============================================================

@st.cache_data(ttl=30)
def load_rejections():

    model2_db, _ = get_paths()

    with ro_connection(
        model2_db
    ) as connection:

        rows = connection.execute(
            """
            SELECT
                p.ticker,
                r.order_id,
                r.rejection_code,
                r.rejection_reason,
                r.rejected_at_utc
            FROM order_rejections r
            JOIN paper_orders p
              ON p.order_id = r.order_id
            ORDER BY
                r.rejected_at_utc DESC
            LIMIT 10
            """
        ).fetchall()

    return pd.DataFrame(
        rows,
        columns=[
            "Ticker",
            "Order ID",
            "Code",
            "Reason",
            "Rejected At",
        ],
    )


# ============================================================
# FILLS
# ============================================================

@st.cache_data(ttl=30)
def load_recent_fills():

    model2_db, _ = get_paths()

    with ro_connection(
        model2_db
    ) as connection:

        rows = connection.execute(
            """
            SELECT
                ticker,
                side,
                quantity,
                reference_price,
                fill_price,
                execution_session,
                created_at_utc
            FROM paper_fills
            ORDER BY created_at_utc DESC
            LIMIT 10
            """
        ).fetchall()

    return pd.DataFrame(
        rows,
        columns=[
            "Ticker",
            "Side",
            "Quantity",
            "Reference Price",
            "Fill Price",
            "Session",
            "Filled At",
        ],
    )


# ============================================================
# STRONGEST TRADE CANDIDATES
# ============================================================

@st.cache_data(ttl=300)
def load_candidate_ranking():

    result = scan_model2_candidates(
        top_n=10
    )

    candidate_rows = []

    for candidate in result.candidates:
        candidate_rows.append(
            {
                "Rank": candidate.rank,
                "Ticker": candidate.ticker,
                "Momentum %": float(
                    candidate.momentum
                    * Decimal("100")
                ),
                "Close": float(
                    candidate.close
                ),
                "Group": candidate.group,
            }
        )

    exit_rows = []

    for item in result.exits:
        exit_rows.append(
            {
                "Ticker": item.ticker,
                "Momentum %": float(
                    item.momentum
                    * Decimal("100")
                ),
                "Group": item.group,
                "Reason": item.reason,
            }
        )

    candidate_df = pd.DataFrame(
        candidate_rows,
        columns=[
            "Rank",
            "Ticker",
            "Momentum %",
            "Close",
            "Group",
        ],
    )

    exit_df = pd.DataFrame(
        exit_rows,
        columns=[
            "Ticker",
            "Momentum %",
            "Group",
            "Reason",
        ],
    )

    return {
        "candidates": candidate_df,
        "exits": exit_df,
        "failures": result.failures,
        "scanned": result.scanned,
    }


# ============================================================
# WINDOWS TASK SCHEDULER
# ============================================================

def get_task_status(task_name: str):

    script = f"""
    $x = Get-ScheduledTaskInfo `
        -TaskName '{task_name}'

    $task = Get-ScheduledTask `
        -TaskName '{task_name}'

    [PSCustomObject]@{{
        State = $task.State.ToString()
        LastRunTime = $x.LastRunTime
        LastTaskResult = $x.LastTaskResult
        NextRunTime = $x.NextRunTime
    }} | ConvertTo-Json -Compress
    """

    try:

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return None

        return json.loads(
            result.stdout.strip()
        )

    except Exception:
        return None


# ============================================================
# HEADER
# ============================================================

now_et = datetime.now(
    NEW_YORK
)

title_col, button_col = st.columns(
    [8, 1]
)

with title_col:

    st.title(
        "Model 2 Trading Dashboard"
    )

    st.caption(
        "Read-only paper-trading monitor "
        f"• {now_et.strftime('%A, %B %d, %Y %I:%M %p %Z')}"
    )


with button_col:

    st.write("")

    if st.button(
        "Refresh",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()


# ============================================================
# LOAD DATA
# ============================================================

try:

    portfolio = load_portfolio()

    (
        pending_orders,
        recent_orders,
    ) = load_orders()

    recent_fills = load_recent_fills()

    rejections = load_rejections()

    candidate_ranking = load_candidate_ranking()

except Exception as exc:

    st.error(
        f"Dashboard could not load: {exc}"
    )

    st.stop()


# ============================================================
# TOP METRICS
# ============================================================

metric1, metric2, metric3, metric4, metric5 = (
    st.columns(5)
)

metric1.metric(
    "Portfolio Value",
    money(
        portfolio["total_equity"]
    ),
)

metric2.metric(
    "Total P/L",
    money(
        portfolio["total_pnl"]
    ),
    percent(
        portfolio["total_return"]
    ),
)

metric3.metric(
    "Cash",
    money(
        portfolio["cash"]
    ),
)

metric4.metric(
    "Market Exposure",
    percent(
        portfolio["exposure"]
    ),
)

metric5.metric(
    "Open Positions",
    len(
        portfolio["positions"]
    ),
)


st.divider()


# ============================================================
# POSITIONS + NEXT TRADES
# ============================================================

left, right = st.columns(
    [3, 2]
)


with left:

    st.subheader(
        "Open Positions"
    )

    if portfolio["positions"]:

        positions_df = pd.DataFrame(
            portfolio["positions"]
        )

        display_positions = (
            positions_df[
                [
                    "Ticker",
                    "Shares",
                    "Average Cost",
                    "Current Price",
                    "Market Value",
                    "P/L",
                    "Return %",
                ]
            ]
        )

        st.dataframe(
            display_positions,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Average Cost":
                    st.column_config.NumberColumn(
                        format="$%.2f"
                    ),
                "Current Price":
                    st.column_config.NumberColumn(
                        format="$%.2f"
                    ),
                "Market Value":
                    st.column_config.NumberColumn(
                        format="$%.2f"
                    ),
                "P/L":
                    st.column_config.NumberColumn(
                        format="$%.2f"
                    ),
                "Return %":
                    st.column_config.NumberColumn(
                        format="%.2f%%"
                    ),
            },
        )

        chart_data = (
            positions_df[
                [
                    "Ticker",
                    "P/L",
                ]
            ]
            .set_index("Ticker")
        )

        st.bar_chart(
            chart_data
        )

    else:

        st.info(
            "No open positions."
        )


with right:

    st.subheader(
        "Next Trades"
    )

    if pending_orders.empty:

        st.markdown(
            """
            <div class="status-info">
            No pending Model 2 orders.
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:

        st.dataframe(
            pending_orders[
                [
                    "Ticker",
                    "Side",
                    "Quantity",
                    "Execution Session",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            f"{len(pending_orders)} order(s) "
            "currently awaiting execution."
        )


# ============================================================
# STRONGEST TRADE CANDIDATES
# ============================================================

st.divider()

st.subheader(
    "Strongest Trade Candidates"
)

st.caption(
    "Read-only ranking of qualifying new BUY signals "
    "using the existing 20-session momentum metric. "
    "This section does not create or modify orders."
)

candidate_df = candidate_ranking[
    "candidates"
]

if candidate_df.empty:

    st.info(
        "No qualifying new BUY candidates."
    )

else:

    st.dataframe(
        candidate_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Rank":
                st.column_config.NumberColumn(
                    format="%d"
                ),
            "Momentum %":
                st.column_config.NumberColumn(
                    format="%.2f%%"
                ),
            "Close":
                st.column_config.NumberColumn(
                    format="$%.2f"
                ),
        },
    )

    st.caption(
        f"Scanned {candidate_ranking['scanned']} "
        "Model 2 tickers. Top 10 shown."
    )

exit_df = candidate_ranking[
    "exits"
]

if not exit_df.empty:

    st.warning(
        "Existing holdings currently have EXIT signals."
    )

    st.dataframe(
        exit_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Momentum %":
                st.column_config.NumberColumn(
                    format="%.2f%%"
                ),
        },
    )

failures = candidate_ranking[
    "failures"
]

if failures:

    with st.expander(
        f"Candidate scan failures ({len(failures)})"
    ):

        failure_df = pd.DataFrame(
            failures,
            columns=[
                "Ticker",
                "Error",
            ],
        )

        st.dataframe(
            failure_df,
            hide_index=True,
            use_container_width=True,
        )


# ============================================================
# PERFORMANCE BREAKDOWN
# ============================================================

st.divider()

st.subheader(
    "Performance"
)

p1, p2, p3, p4 = st.columns(4)

p1.metric(
    "Realized P/L",
    money(
        portfolio["realized_pnl"]
    ),
)

p2.metric(
    "Unrealized P/L",
    money(
        portfolio["unrealized_pnl"]
    ),
)

p3.metric(
    "Market Value",
    money(
        portfolio["market_value"]
    ),
)

p4.metric(
    "Starting Capital",
    money(
        portfolio["starting_cash"]
    ),
)


# ============================================================
# AUTOMATION STATUS
# ============================================================

st.divider()

st.subheader(
    "Automation"
)

execution_status = get_task_status(
    EXECUTION_TASK
)

decision_status = get_task_status(
    DECISION_TASK
)

auto1, auto2 = st.columns(2)


def show_task(
    name,
    status,
):

    if status is None:

        st.warning(
            f"{name}: status unavailable"
        )

        return

    st.markdown(
        f"**{name}**"
    )

    st.write(
        f"State: `{status['State']}`"
    )

    st.write(
        "Next run: "
        f"`{status['NextRunTime']}`"
    )

    st.write(
        "Last result: "
        f"`{status['LastTaskResult']}`"
    )


with auto1:

    show_task(
        "Guarded Execution",
        execution_status,
    )


with auto2:

    show_task(
        "Daily Decision",
        decision_status,
    )


# ============================================================
# ACTIVITY TABS
# ============================================================

st.divider()

tab1, tab2, tab3 = st.tabs(
    [
        "Recent Fills",
        "Recent Orders",
        "Rejections",
    ]
)


with tab1:

    if recent_fills.empty:

        st.info(
            "No fills recorded."
        )

    else:

        st.dataframe(
            recent_fills,
            hide_index=True,
            use_container_width=True,
        )


with tab2:

    st.dataframe(
        recent_orders,
        hide_index=True,
        use_container_width=True,
    )


with tab3:

    if rejections.empty:

        st.info(
            "No rejection records."
        )

    else:

        st.dataframe(
            rejections,
            hide_index=True,
            use_container_width=True,
        )


# ============================================================
# SAFETY FOOTER
# ============================================================

st.divider()

st.caption(
    "READ ONLY • This dashboard does not create, "
    "modify, approve, reject, or execute Model 2 orders."
)
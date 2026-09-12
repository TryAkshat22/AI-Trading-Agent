# Autonomous Paper-Trading Research Agent

A research-focused paper-trading system built to evaluate whether a rule-based trading model can outperform simple benchmarks while maintaining acceptable risk.

The project is designed for experimentation, performance analysis, and portfolio research only. It does not place real-money trades.

---

## Project Goals

The system is intended to:

- Generate daily trading decisions from market data
- Apply deterministic position sizing and risk controls
- Simulate order execution using market-open observations
- Persist orders, fills, execution attempts, and portfolio history
- Rebuild portfolio state from recorded trades
- Track portfolio equity over time
- Compare performance against multiple benchmarks
- Measure risk-adjusted performance
- Export research-ready CSV files and charts

The long-term objective is to evaluate the strategy across a sufficiently large forward-testing sample rather than judging performance from a small number of trades.

---

## Current Model

### Model 1

The current model uses:

- Long-only positions
- Whole-share trading
- Daily after-market-close decisions
- Execution at the next valid NYSE opening session
- No real-money trading
- No leverage
- No short selling

### Trading Universe

The current stock universe is:

- AAPL
- MSFT
- NVDA
- AMZN
- GOOGL
- META
- JPM
- XOM
- JNJ
- WMT

### Starting Capital

$10,000

### Market Benchmark

SPY

### System Architecture
Market Data
    ↓
Data Quality Validation
    ↓
Signal Engine
    ↓
Decision Pipeline
    ↓
Position Sizing
    ↓
Risk Engine
    ↓
Order Creation
    ↓
Pending Order Storage
    ↓
Execution Observation
    ↓
Execution Validation
    ↓
Paper Fill / Rejection
    ↓
Portfolio Reconstruction
    ↓
Equity Tracking
    ↓
Performance Evaluation
    ↓
Benchmarks + Risk Metrics
    ↓
Research Report Export

### Core Design Principles

## Fail Closed

If required market data, timing information, execution observations, or quality checks are invalid, the system does not silently continue.

## Deterministic Trading Logic

Accounting, risk controls, execution, and portfolio calculations are deterministic.

## AI or LLM components are not allowed to directly control:

portfolio accounting
order execution
cash balances
position quantities
execution prices
Anti-Lookahead

Trading decisions are based only on information available at the decision timestamp.

Execution occurs using the next valid market session rather than using future data.

## Persistent Audit Trail

The system records:

orders
fills
rejected orders
execution attempts
market-data ingestion
equity snapshots

This allows portfolio state and strategy performance to be reconstructed later.


### Database

The live SQLite database is stored outside the project directory.

## Default Windows location:

%LOCALAPPDATA%\PaperTradingAgent\trading_agent.db

Example:

C:\Users\<username>\AppData\Local\PaperTradingAgent\trading_agent.db

This prevents the live trading database from being stored inside OneDrive or accidentally committed into Git.


### Running the Project

Activate the virtual environment first.

Example:

.venv\Scripts\Activate.ps1


### Check System Status
python app.py status

Displays information such as:

account
starting cash
total orders
pending orders
filled orders
rejected orders
fills
portfolio snapshots
execution attempts


### Run Daily Decision Cycle

Example:

python app.py decision --timestamp 2026-09-11T21:00:00Z

The decision cycle:

1. Retrieves market data
2. Validates data quality
3. Generates signals
4. Rebuilds current portfolio state
5. Calculates potential position size
6. Applies risk controls
7. Creates paper orders when appropriate
8. Persists the decision lineage


### Check Execution Readiness

Before executing pending orders:

python app.py execution-check --session 2026-09-14

This is a read-only safety check.

It should verify that:

the date is a valid NYSE session
pending orders exist
order state is valid
the execution window is currently available


### Run Execution
python app.py execution --session 2026-09-14

Execution is based on the near-open market observation.

The current paper execution provider uses:

Yahoo Finance 1-minute market data

Execution observations must fall within the configured opening window.

No fallback is made to:

previous close
later intraday bars
synthetic prices

if the required opening observation is unavailable.


### Portfolio Report

python app.py portfolio

Example output:

Portfolio Performance
=====================
Account: model1-paper

Starting cash:       $10,000.00
Current cash:        $8,250.00
Market value:        $1,790.00
Total equity:        $10,040.00

Realized P&L:        $0.00
Unrealized P&L:      $40.00
Total P&L:           $40.00
Total return:        0.40%
Exposure:            17.83%

Open positions:      4
Recorded fills:      4


### Record Daily Equity

After valid end-of-day pricing is available:

python app.py equity-snapshot --session 2026-09-14

Each valuation session may only have one immutable equity snapshot.

Exact duplicates are idempotent.

Conflicting snapshots for the same account, model, and session are rejected.


### View Equity History
python app.py equity-history

The history is used as the primary time series for performance evaluation.


### Benchmarks

## SPY Benchmark
python app.py benchmark

Model performance is compared against SPY using adjusted close data and exact session alignment.

## Equal-Weight Benchmark
python app.py equal-weight-benchmark

This benchmark assumes:

starting capital is divided equally across the 10-stock universe
fractional benchmark shares are allowed
the portfolio is purchased once
no rebalancing occurs

This provides a simple passive alternative to the active model.

## Cash Benchmark

The evaluation layer also compares the model against a zero-yield cash benchmark.

This answers a simple question:

Did taking market risk outperform doing nothing?

### Performance Metrics
python app.py metrics

Current metrics include:

total return
annualized volatility
Sharpe ratio
Sortino ratio
maximum drawdown
positive-day rate
negative-day rate
best day
worst day
average daily return


### Combined Evaluation
python app.py evaluation

The combined evaluation compares the model against:

SPY
cash
equal-weight buy-and-hold

while also displaying the main risk-adjusted performance metrics.

Example structure:

Model Evaluation
================

Account: model1-paper
Model:   model-1
Period:  2026-09-14 to 2026-11-30

Returns
-------
Model 1
SPY
Excess vs SPY

Cash
Excess vs Cash

Equal-Weight Portfolio
Excess vs Equal-Weight

Risk Metrics
------------
Annualized Volatility
Sharpe Ratio
Sortino Ratio
Maximum Drawdown

Daily Statistics
----------------
Positive Days
Negative Days
Best Day
Worst Day
Average Daily Return


### Export Research Report

Once equity history exists:

python app.py export-report

This generates:

reports/
├── equity_history.csv
├── evaluation_summary.csv
├── equity_curve.png
├── model_vs_spy.png
├── model_vs_equal_weight.png
└── drawdown.png

## equity_history.csv

Contains session-level data such as:

valuation date
starting cash
current cash
market value
total equity
realized P&L
unrealized P&L
total P&L
return
exposure
open positions

## evaluation_summary.csv

Contains headline research metrics including:

model return
SPY return
excess return
cash return
equal-weight return
volatility
Sharpe ratio
Sortino ratio
maximum drawdown
best and worst day
average daily return


### Generated Charts

## Equity Curve

Tracks total portfolio value over time.

Portfolio Equity
      |
      |                 ●
      |             ●
      |        ●
      |    ●
      | ●
      +-------------------------
          Trading Sessions

## Model vs SPY

Compares cumulative Model 1 return against SPY.

## Model vs Equal Weight

Compares the strategy against simply buying the same stock universe equally and holding it.

## Drawdown

Measures portfolio decline from the previous equity peak.

### Testing

Run the complete test suite:

python -m pytest -v

Current known-good state:

403 passed

The system should not be considered stable after code changes until the complete test suite passes again.

### Current Live Paper-Trading State

The current experiment uses:

Account:       model1-paper
Model:         model-1
Starting Cash: $10,000

The first forward execution cycle is scheduled for:

2026-09-14

The current experiment should be evaluated over a meaningful forward-testing sample rather than judged from the first few trades.

A target of approximately:

100–200+ completed forward trades

is more appropriate before drawing strong conclusions about model performance.


### Important Safeguards

The project currently includes protections against:

lookahead bias
invalid market sessions
stale market data
missing trading sessions
weekend market rows
invalid execution timing
duplicate execution lineage
invalid execution observations
duplicate equity snapshots
conflicting historical snapshots
negative or invalid market prices
inconsistent evaluation results
silent execution fallback

The system is intentionally conservative: when required information cannot be validated, it should fail rather than invent or approximate trading data.


### Research Limitations

This project is a paper-trading research system.

Important limitations include:

Yahoo Finance is not an institutional execution feed
simulated opening prices do not model the full bid/ask spread
slippage may differ from real trading
transaction costs may differ from actual brokerage costs
historical success does not imply future performance
a small number of forward trades is statistically weak
market regimes can materially affect results

The purpose of the project is to evaluate the model rigorously before considering any expansion.
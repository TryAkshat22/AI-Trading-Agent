"""Local stdio MCP only. No network listener, credentials or trading tools."""
from mcp.server.fastmcp import FastMCP
from .service import Intelligence

mcp=FastMCP('Model 2 Portfolio Intelligence')


def invoke(name,*args):
    try:
        return getattr(Intelligence.from_env(),name)(*args)
    except (ValueError, OSError, RuntimeError, ArithmeticError):
        return {'status':'unavailable','reason':'Configured data is unavailable or invalid. Check local configuration.'}
    except Exception:
        return {'status':'unavailable','reason':'Local data query failed. Check database schema and configuration.'}

@mcp.tool()
def get_portfolio() -> dict:
    """Saved paper portfolio valuation and available marked holdings; not live quotes."""
    return invoke('get_portfolio')

@mcp.tool()
def get_performance(period: str='ALL') -> dict:
    """Closing equity history, 1W, 1M, 3M, YTD or ALL."""
    return invoke('get_performance',period)

@mcp.tool()
def get_risk_metrics(period: str='ALL') -> dict:
    """Calendar-aware observed drawdown, volatility and optional risk-adjusted ratios."""
    return invoke('get_risk_metrics',period)

@mcp.tool()
def get_benchmark(period: str='ALL') -> dict:
    """Aligned user-configured benchmark returns, beta and optional alpha."""
    return invoke('get_benchmark',period)

@mcp.tool()
def get_trade_history(limit: int=25) -> dict:
    """Recent completed Model 2 fills, at most 100."""
    return invoke('get_trade_history',limit)

@mcp.tool()
def get_system_health() -> dict:
    """Saved data coverage, not scheduler status."""
    return invoke('get_system_health')

@mcp.tool()
def get_signals() -> dict:
    """Reports persisted signal availability; does not scan or trade."""
    return invoke('get_signals')

if __name__=='__main__':
    mcp.run(transport='stdio')

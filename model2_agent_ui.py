from __future__ import annotations

from decimal import Decimal
from typing import Any

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from model2_agent import AgentReply, answer
from model2_agent_data import brokerage_snapshot, system_snapshot


console = Console()


SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[Any], width: int = 38) -> str:
    if not values:
        return "—"

    nums = [float(value) for value in values]

    if len(nums) > width:
        step = (len(nums) - 1) / (width - 1) if width > 1 else 0
        nums = [
            nums[min(int(index * step), len(nums) - 1)]
            for index in range(width)
        ]

    low = min(nums)
    high = max(nums)

    if high == low:
        return SPARK_CHARS[3] * len(nums)

    result = []
    for value in nums:
        ratio = (value - low) / (high - low)
        index = min(
            len(SPARK_CHARS) - 1,
            int(ratio * (len(SPARK_CHARS) - 1)),
        )
        result.append(SPARK_CHARS[index])

    return "".join(result)


def allocation_bar(weight: Any, width: int = 18) -> str:
    pct = max(0.0, min(100.0, float(weight)))
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def format_task_time(value: Any) -> str:
    if value in (None, "", "null"):
        return "—"

    text = str(value)

    if text.startswith("/Date("):
        try:
            milliseconds = int(text.split("(")[1].split(")")[0])
            from datetime import datetime
            dt = datetime.fromtimestamp(milliseconds / 1000)
            return dt.strftime("%a %I:%M %p")
        except Exception:
            return text

    return text


def money(value: Any) -> str:
    return f"${Decimal(str(value)):,.2f}"


def percent(value: Any) -> str:
    return f"{Decimal(str(value)):.2f}%"


def status_badge(
    ok: bool,
    good: str = "HEALTHY",
    bad: str = "ATTENTION",
) -> Text:
    return Text(
        f"● {good if ok else bad}",
        style="bold green" if ok else "bold red",
    )


def print_banner() -> None:
    console.clear()

    banner = Text()
    banner.append("MODEL 2", style="bold bright_cyan")
    banner.append("  /  ", style="dim")
    banner.append("TRADING AGENT", style="bold white")

    console.print(
        Panel(
            Align.center(banner),
            subtitle="[dim]read-only paper trading console[/dim]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )


def print_home() -> None:
    try:
        snapshot = brokerage_snapshot()
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Could not load Model 2 state:[/red] {exc}",
                title="Startup Error",
                border_style="red",
            )
        )
        return

    portfolio = snapshot["portfolio"]
    collector = snapshot["collector"]
    tasks = snapshot["tasks"]
    movers = snapshot["movers"]
    history = snapshot["equity_history"]
    candidates = snapshot["candidates"]

    metrics = Table(
        box=box.ROUNDED,
        show_header=False,
        expand=True,
        padding=(0, 2),
    )
    for _ in range(5):
        metrics.add_column(justify="center")

    pnl_style = "green" if portfolio["total_pnl"] >= 0 else "red"

    metrics.add_row(
        f"[dim]PORTFOLIO VALUE[/dim]\n[bold]{money(portfolio['total_equity'])}[/bold]",
        f"[dim]CASH[/dim]\n[bold]{money(portfolio['cash'])}[/bold]",
        f"[dim]TOTAL P/L[/dim]\n[{pnl_style}][bold]"
        f"{money(portfolio['total_pnl'])}[/bold][/{pnl_style}]",
        f"[dim]RETURN[/dim]\n[{pnl_style}][bold]"
        f"{percent(portfolio['total_return'])}[/bold][/{pnl_style}]",
        f"[dim]POSITIONS[/dim]\n[bold]{len(portfolio['positions'])}[/bold]",
    )
    console.print(metrics)

    if history:
        values = [row["equity"] for row in history]
        first = values[0]
        last = values[-1]
        curve_style = "green" if last >= first else "red"

        console.print(
            Panel(
                f"[{curve_style}]{sparkline(values)}[/{curve_style}]\n"
                f"[dim]{history[0]['session']}[/dim]  "
                f"{money(first)}  →  [bold]{money(last)}[/bold]  "
                f"[dim]{history[-1]['session']}[/dim]",
                title="Portfolio Performance",
                border_style=curve_style,
            )
        )

    console.print(Text(snapshot["performance"]["message"], style="yellow" if snapshot["performance"]["missing"] else "dim"))

    left = Table(box=box.ROUNDED, expand=True)
    left.add_column("Top Gainers", style="bold green")
    left.add_column("Price", justify="right")
    left.add_column("Move", justify="right")

    for row in movers["gainers"][:5]:
        left.add_row(
            row["ticker"],
            money(row["price"]),
            f"[green]+{percent(row['change_pct'])}[/green]",
        )

    right = Table(box=box.ROUNDED, expand=True)
    right.add_column("Top Losers", style="bold red")
    right.add_column("Price", justify="right")
    right.add_column("Move", justify="right")

    for row in movers["losers"][:5]:
        right.add_row(
            row["ticker"],
            money(row["price"]),
            f"[red]{percent(row['change_pct'])}[/red]",
        )

    movers_grid = Table.grid(expand=True)
    movers_grid.add_column(ratio=1)
    movers_grid.add_column(ratio=1)
    movers_grid.add_row(left, right)

    breadth = (
        f"[green]{movers['positive']} up[/green]  •  "
        f"[red]{movers['negative']} down[/red]  •  "
        f"{movers['flat']} flat"
    )

    console.print(
        Panel(
            movers_grid,
            title="Market Movers",
            subtitle=breadth,
            border_style="blue",
        )
    )

    console.print(Text(movers["message"], style="dim"))

    if candidates["candidates"]:
        candidate_table = Table(
            box=box.SIMPLE,
            expand=True,
            show_edge=False,
        )
        candidate_table.add_column("#", justify="right", width=3)
        candidate_table.add_column("Best Opportunities", style="bold bright_cyan")
        candidate_table.add_column("Momentum", justify="right")
        candidate_table.add_column("Price", justify="right")
        candidate_table.add_column("Group")

        for row in candidates["candidates"][:5]:
            candidate_table.add_row(
                str(row["rank"]),
                row["ticker"],
                percent(row["momentum"]),
                money(row["close"]),
                row["group"],
            )

        console.print(
            Panel(
                candidate_table,
                title="Model 2 Opportunities",
                subtitle="signal ranking, not investment advice",
                border_style="bright_cyan",
            )
        )

    status = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        padding=(0, 1),
    )
    status.add_column("Component", style="bold")
    status.add_column("Status", width=16)
    status.add_column("Detail")

    status.add_row(
        "Intraday Collector",
        status_badge(collector["healthy"]),
        f"{collector['ticker_count']} tickers • {collector['age_seconds']}s old",
    )

    for key, label in (
        ("decision", "Decision Engine"),
        ("execution", "Guarded Execution"),
        ("expiry", "Stale Cleanup"),
        ("equity_intraday", "Intraday Equity"),
        ("equity_daily", "Daily Equity"),
    ):
        item = tasks.get(key)

        if item is None:
            status.add_row(
                label,
                Text("● UNKNOWN", style="bold yellow"),
                "Task status unavailable",
            )
            continue

        result = item.get("LastTaskResult")
        ok = result in (0, 267009)

        status.add_row(
            label,
            status_badge(ok, "READY", "CHECK"),
            f"Next: {format_task_time(item.get('NextRunTime'))}",
        )

    console.print(status)

    console.print(
        Panel(
            "[bold]Ask naturally[/bold]\n"
            "[bright_cyan]›[/bright_cyan] Show top movers\n"
            "[bright_cyan]›[/bright_cyan] What are the best investments?\n"
            "[bright_cyan]›[/bright_cyan] Show portfolio allocation\n"
            "[bright_cyan]›[/bright_cyan] Show performance graph (1D, 1W, 1M, 3M, YTD, ALL)\n"
            "[bright_cyan]›[/bright_cyan] What do I currently own?\n"
            "[bright_cyan]›[/bright_cyan] Why was HON rejected?\n\n"
            "[dim]help  •  refresh  •  clear  •  exit[/dim]",
            title="Conversation",
            border_style="blue",
        )
    )

def print_suggestions(reply: AgentReply) -> None:
    if not reply.suggestions:
        return

    console.print()
    console.print("[dim]You could also ask:[/dim]")

    for item in reply.suggestions[:4]:
        console.print(f"  [bright_cyan]›[/bright_cyan] {item}")


def table_positions(rows: list[dict[str, Any]]) -> Table:
    table = Table(
        box=box.ROUNDED,
        expand=True,
        row_styles=["", "dim"],
    )
    table.add_column("Ticker", style="bold bright_cyan")
    table.add_column("Shares", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Value", justify="right")
    table.add_column("P/L", justify="right")
    table.add_column("Return", justify="right")

    for row in rows:
        pnl = Decimal(str(row["pnl"]))
        pnl_style = "green" if pnl >= 0 else "red"

        table.add_row(
            row["ticker"],
            str(row["shares"]),
            money(row["average_cost"]),
            money(row["current_price"]),
            money(row["market_value"]),
            f"[{pnl_style}]{money(pnl)}[/{pnl_style}]",
            f"[{pnl_style}]{percent(row['return_pct'])}[/{pnl_style}]",
        )

    return table


def table_orders(rows: list[dict[str, Any]]) -> Table:
    table = Table(box=box.ROUNDED, expand=True)
    table.add_column("Session")
    table.add_column("Ticker", style="bold bright_cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Status")

    for row in rows:
        status = row["status"]
        style = {
            "FILLED": "green",
            "PENDING": "yellow",
            "REJECTED": "red",
        }.get(status, "white")

        table.add_row(
            str(row["session"]),
            str(row["ticker"]),
            str(row["side"]),
            str(row["quantity"]),
            f"[{style}]{status}[/{style}]",
        )

    return table


def table_fills(rows: list[dict[str, Any]]) -> Table:
    table = Table(box=box.ROUNDED, expand=True)
    table.add_column("Session")
    table.add_column("Ticker", style="bold bright_cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Reference", justify="right")
    table.add_column("Fill", justify="right")

    for row in rows:
        table.add_row(
            str(row["session"]),
            str(row["ticker"]),
            str(row["side"]),
            str(row["quantity"]),
            money(row["reference_price"]),
            money(row["fill_price"]),
        )

    return table


def table_rejections(rows: list[dict[str, Any]]) -> Table:
    table = Table(box=box.ROUNDED, expand=True)
    table.add_column("Session")
    table.add_column("Ticker", style="bold bright_cyan")
    table.add_column("Code")
    table.add_column("Reason", ratio=3)

    for row in rows:
        table.add_row(
            str(row["session"]),
            str(row["ticker"]),
            str(row["code"]),
            str(row["reason"]),
        )

    return table


def render(reply: AgentReply) -> None:
    console.print()

    if reply.kind in {"message", "help"}:
        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )
        print_suggestions(reply)
        return

    if reply.kind == "portfolio":
        p = reply.data
        pnl_style = "green" if p["total_pnl"] >= 0 else "red"

        summary = Table(show_header=False, box=box.SIMPLE, expand=True)
        for _ in range(4):
            summary.add_column(justify="center")

        summary.add_row(
            f"[dim]EQUITY[/dim]\n[bold]{money(p['total_equity'])}[/bold]",
            f"[dim]CASH[/dim]\n[bold]{money(p['cash'])}[/bold]",
            f"[dim]EXPOSURE[/dim]\n[bold]{percent(p['exposure'])}[/bold]",
            f"[dim]TOTAL P/L[/dim]\n[{pnl_style}]"
            f"[bold]{money(p['total_pnl'])}[/bold][/{pnl_style}]",
        )

        console.print(
            Panel(
                summary,
                title=f"[bold]{reply.title}[/bold]",
                subtitle=reply.text,
                border_style="bright_cyan",
            )
        )

        if p["positions"]:
            console.print(table_positions(p["positions"]))
        else:
            console.print("[dim]No open positions.[/dim]")

        print_suggestions(reply)
        return

    if reply.kind == "status":
        s = reply.data
        p = s["portfolio"]
        c = s["collector"]

        border = "green" if c["healthy"] else "yellow"

        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style=border,
                padding=(1, 2),
            )
        )

        summary = Table(box=box.ROUNDED, expand=True)
        summary.add_column("Portfolio")
        summary.add_column("Cash")
        summary.add_column("Positions")
        summary.add_column("Pending")
        summary.add_row(
            money(p["total_equity"]),
            money(p["cash"]),
            str(len(p["positions"])),
            str(len(s["pending_orders"])),
        )
        console.print(summary)

        task_table = Table(box=box.ROUNDED, expand=True)
        task_table.add_column("Task")
        task_table.add_column("State")
        task_table.add_column("Last Result")
        task_table.add_column("Next Run")

        for key, item in s["tasks"].items():
            if item is None:
                task_table.add_row(key, "UNKNOWN", "-", "-")
            else:
                task_table.add_row(
                    key,
                    str(item.get("State")),
                    str(item.get("LastTaskResult")),
                    format_task_time(item.get("NextRunTime")),
                )

        console.print(task_table)
        print_suggestions(reply)
        return

    if reply.kind == "collector":
        c = reply.data
        console.print(
            Panel(
                f"[bold]Status:[/bold] "
                f"{'[green]HEALTHY[/green]' if c['healthy'] else '[red]STALE[/red]'}\n"
                f"[bold]Latest retrieval:[/bold] {c['latest_retrieval']}\n"
                f"[bold]Age:[/bold] {c['age_seconds']} seconds\n"
                f"[bold]Tickers today:[/bold] {c['ticker_count']}\n"
                f"[bold]Observations today:[/bold] {c['today_count']}",
                title=f"[bold]{reply.title}[/bold]",
                border_style="green" if c["healthy"] else "red",
            )
        )
        print_suggestions(reply)
        return

    if reply.kind == "orders":
        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="bright_cyan",
            )
        )
        if reply.data:
            console.print(table_orders(reply.data))
        print_suggestions(reply)
        return

    if reply.kind == "fills":
        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="green",
            )
        )
        if reply.data:
            console.print(table_fills(reply.data))
        print_suggestions(reply)
        return

    if reply.kind == "rejections":
        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="red",
            )
        )
        if reply.data:
            console.print(table_rejections(reply.data))
        print_suggestions(reply)
        return

    if reply.kind == "movers":
        data = reply.data
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)

        gainers = Table(box=box.ROUNDED, expand=True)
        gainers.add_column("Gainer", style="bold green")
        gainers.add_column("Price", justify="right")
        gainers.add_column("Move", justify="right")
        for row in data["gainers"]:
            gainers.add_row(
                row["ticker"],
                money(row["price"]),
                f"[green]+{percent(row['change_pct'])}[/green]",
            )

        losers = Table(box=box.ROUNDED, expand=True)
        losers.add_column("Loser", style="bold red")
        losers.add_column("Price", justify="right")
        losers.add_column("Move", justify="right")
        for row in data["losers"]:
            losers.add_row(
                row["ticker"],
                money(row["price"]),
                f"[red]{percent(row['change_pct'])}[/red]",
            )

        grid.add_row(gainers, losers)
        console.print(
            Panel(
                grid,
                title=f"[bold]{reply.title}[/bold]",
                subtitle=(
                    f"{data['positive']} up • "
                    f"{data['negative']} down • "
                    f"{data['covered']} covered"
                ),
                border_style="blue",
            )
        )
        console.print(Text(data["message"], style="dim"))
        print_suggestions(reply)
        return

    if reply.kind == "allocation":
        table = Table(box=box.ROUNDED, expand=True)
        table.add_column("Asset", style="bold bright_cyan")
        table.add_column("Weight", justify="right")
        table.add_column("Allocation")
        table.add_column("Value", justify="right")

        for row in reply.data:
            table.add_row(
                row["name"],
                percent(row["weight_pct"]),
                allocation_bar(row["weight_pct"]),
                money(row["value"]),
            )

        console.print(
            Panel(
                table,
                title=f"[bold]{reply.title}[/bold]",
                border_style="bright_cyan",
            )
        )
        print_suggestions(reply)
        return

    if reply.kind == "equity":
        points = reply.data["points"]
        values = [row["equity"] for row in points]

        if values:
            first = values[0]
            last = values[-1]
            style = "green" if last >= first else "red"
            body = (
                f"[{style}]{sparkline(values, width=55)}[/{style}]\n\n"
                f"{points[0]['label']}  {money(first)}"
                f"  →  [bold]{money(last)}[/bold]  "
                f"{points[-1]['label']}"
            )
        else:
            style = "yellow"
            body = "No equity history is available."

        console.print(
            Panel(
                body,
                title=f"[bold]{reply.title}[/bold]",
                subtitle=reply.text,
                border_style=style,
                padding=(1, 2),
            )
        )
        console.print(Text(reply.data["message"], style="dim"))
        print_suggestions(reply)
        return

    if reply.kind == "candidates":
        data = reply.data

        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                subtitle=f"Scanned {data['scanned']} tickers",
                border_style="bright_cyan",
            )
        )

        table = Table(box=box.ROUNDED, expand=True)
        table.add_column("Rank", justify="right")
        table.add_column("Ticker", style="bold bright_cyan")
        table.add_column("Momentum", justify="right")
        table.add_column("Close", justify="right")
        table.add_column("Group")

        for row in data["candidates"]:
            table.add_row(
                str(row["rank"]),
                row["ticker"],
                percent(row["momentum"]),
                money(row["close"]),
                row["group"],
            )

        console.print(table)

        if data["exits"]:
            exit_table = Table(
                title="Current EXIT Signals",
                box=box.ROUNDED,
                expand=True,
            )
            exit_table.add_column("Ticker", style="bold yellow")
            exit_table.add_column("Momentum", justify="right")
            exit_table.add_column("Group")
            exit_table.add_column("Reason")

            for row in data["exits"]:
                exit_table.add_row(
                    row["ticker"],
                    percent(row["momentum"]),
                    row["group"],
                    row["reason"],
                )

            console.print(exit_table)

        print_suggestions(reply)
        return

    if reply.kind == "ticker":
        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )

        if reply.data["orders"]:
            console.print(
                Panel(
                    table_orders(reply.data["orders"]),
                    title="Orders",
                    border_style="blue",
                )
            )

        if reply.data["fills"]:
            console.print(
                Panel(
                    table_fills(reply.data["fills"]),
                    title="Fills",
                    border_style="green",
                )
            )

        if reply.data["rejections"]:
            console.print(
                Panel(
                    table_rejections(reply.data["rejections"]),
                    title="Rejections",
                    border_style="red",
                )
            )

        print_suggestions(reply)
        return

    if reply.kind == "session":
        data = reply.data

        console.print(
            Panel(
                reply.text,
                title=f"[bold]{reply.title}[/bold]",
                border_style="bright_cyan",
            )
        )

        if data["orders"]:
            console.print(
                Panel(
                    table_orders(data["orders"]),
                    title="Orders",
                    border_style="blue",
                )
            )

        if data["fills"]:
            console.print(
                Panel(
                    table_fills(data["fills"]),
                    title="Fills",
                    border_style="green",
                )
            )

        if data["rejections"]:
            console.print(
                Panel(
                    table_rejections(data["rejections"]),
                    title="Rejections",
                    border_style="red",
                )
            )

        print_suggestions(reply)
        return

    console.print(
        Panel(
            reply.text,
            title=reply.title,
            border_style="bright_cyan",
        )
    )
    print_suggestions(reply)


def main() -> None:
    print_banner()
    print_home()

    while True:
        console.print()
        prompt = Prompt.ask("[bold bright_cyan]You[/bold bright_cyan]").strip()

        command = prompt.lower()

        if command in {"exit", "quit", "q"}:
            console.print(
                "\n[dim]Agent console closed. "
                "No trading state was changed.[/dim]"
            )
            break

        if command in {"clear", "refresh", "home"}:
            print_banner()
            print_home()
            continue

        try:
            reply = answer(prompt)
            render(reply)

        except KeyboardInterrupt:
            console.print(
                "\n[dim]Request cancelled. No trading state was changed.[/dim]"
            )

        except Exception as exc:
            console.print(
                Panel(
                    f"[red]{type(exc).__name__}:[/red] {exc}\n\n"
                    "[dim]This console is read-only. "
                    "No order or fill was modified.[/dim]",
                    title="Agent Error",
                    border_style="red",
                )
            )


if __name__ == "__main__":
    main()

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
from model2_agent_data import system_snapshot


console = Console()


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
        snapshot = system_snapshot()
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

    metrics = Table(
        box=box.ROUNDED,
        show_header=False,
        expand=True,
        padding=(0, 2),
    )
    for _ in range(4):
        metrics.add_column(justify="center")

    pnl_style = "green" if portfolio["total_pnl"] >= 0 else "red"

    metrics.add_row(
        f"[dim]PORTFOLIO VALUE[/dim]\n[bold]{money(portfolio['total_equity'])}[/bold]",
        f"[dim]CASH[/dim]\n[bold]{money(portfolio['cash'])}[/bold]",
        f"[dim]TOTAL P/L[/dim]\n[{pnl_style}][bold]"
        f"{money(portfolio['total_pnl'])}[/bold][/{pnl_style}]",
        f"[dim]OPEN POSITIONS[/dim]\n[bold]{len(portfolio['positions'])}[/bold]",
    )
    console.print(metrics)

    status = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        padding=(0, 1),
    )
    status.add_column("Component", style="bold")
    status.add_column("Status", width=16)
    status.add_column("Detail")

    collector_detail = (
        f"{collector['ticker_count']} tickers • "
        f"{collector['age_seconds']}s old"
    )

    status.add_row(
        "Intraday Collector",
        status_badge(collector["healthy"]),
        collector_detail,
    )

    for key, label in (
        ("decision", "Decision Engine"),
        ("execution", "Guarded Execution"),
        ("expiry", "Stale Cleanup"),
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
            f"Next: {item.get('NextRunTime')}",
        )

    console.print(status)

    console.print(
        Panel(
            "[bold]Ask naturally[/bold]\n"
            "[bright_cyan]›[/bright_cyan] How is the agent doing?\n"
            "[bright_cyan]›[/bright_cyan] What do I currently own?\n"
            "[bright_cyan]›[/bright_cyan] Why was HON rejected?\n"
            "[bright_cyan]›[/bright_cyan] What happened today?\n"
            "[bright_cyan]›[/bright_cyan] Show the strongest signals.\n\n"
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
                    str(item.get("NextRunTime")),
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

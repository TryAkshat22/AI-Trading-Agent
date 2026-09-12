from __future__ import annotations

import inspect

from database.account_storage import (
    AccountStorage,
)
from database.storage import (
    get_default_database_path,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.portfolio_rebuilder import (
    PortfolioRebuilder,
)


def show_signature(
    label: str,
    obj,
) -> None:

    print()
    print("=" * 78)
    print(label)
    print("=" * 78)

    try:
        print(
            "Signature:",
            inspect.signature(
                obj
            ),
        )

    except Exception as exc:
        print(
            "Signature unavailable:",
            type(exc).__name__,
            str(exc),
        )


def show_methods(
    cls,
    names: list[str],
) -> None:

    for name in names:

        print()

        if not hasattr(
            cls,
            name,
        ):
            print(
                f"{name}: NOT FOUND"
            )
            continue

        method = getattr(
            cls,
            name,
        )

        try:
            print(
                f"{name}"
                f"{inspect.signature(method)}"
            )

        except Exception as exc:
            print(
                f"{name}: ERROR "
                f"{type(exc).__name__}: "
                f"{exc}"
            )


def print_record(
    label: str,
    record,
) -> None:

    print()
    print("=" * 78)
    print(label)
    print("=" * 78)

    if record is None:

        print(
            "NONE"
        )

        return

    print(
        "Type:",
        type(record),
    )

    if hasattr(
        record,
        "__dict__",
    ):
        print(
            "Fields:",
            record.__dict__,
        )

    else:

        print(
            "Value:",
            record,
        )


def main() -> None:

    database_path = (
        get_default_database_path()
    )

    print()
    print(
        "PaperTradingAgent "
        "Reporting Interface Inspection"
    )

    print()
    print(
        "Database:",
        database_path,
    )

    # ==========================================================
    # PORTFOLIO REBUILDER
    # ==========================================================

    show_signature(
        "PortfolioRebuilder",
        PortfolioRebuilder,
    )

    show_methods(
        PortfolioRebuilder,
        [
            "rebuild",
            "build",
            "rebuild_portfolio",
        ],
    )

    # ==========================================================
    # ACCOUNT STORAGE
    # ==========================================================

    show_signature(
        "AccountStorage",
        AccountStorage,
    )

    show_methods(
        AccountStorage,
        [
            "get_account",
            "get_or_create",
            "count_accounts",
        ],
    )

    accounts = (
        AccountStorage(
            database_path
        )
    )

    accounts.initialize()

    account = (
        accounts.get_account()
    )

    print_record(
        "Current AccountRecord",
        account,
    )

    # ==========================================================
    # TRADING STORAGE
    # ==========================================================

    show_signature(
        "TradingStorage",
        TradingStorage,
    )

    show_methods(
        TradingStorage,
        [
            "list_fills",
            "count_fills",
            "count_orders",
            "count_portfolio_snapshots",
        ],
    )

    trading = (
        TradingStorage(
            database_path
        )
    )

    trading.initialize()

    fills = (
        trading.list_fills()
    )

    print()
    print("=" * 78)
    print("Stored Fills")
    print("=" * 78)

    print(
        "Count:",
        len(
            fills
        ),
    )

    if fills:

        print_record(
            "First StoredFillRecord",
            fills[0],
        )

    else:

        print(
            "No fills yet."
        )

    # ==========================================================
    # PORTFOLIO OBJECT
    # ==========================================================

    print()
    print("=" * 78)
    print("Portfolio Object Inspection")
    print("=" * 78)

    try:

        rebuilder = (
            PortfolioRebuilder(
                account_storage=accounts,
                trading_storage=trading,
            )
        )

        print(
            "Rebuilder constructed with "
            "account_storage + trading_storage."
        )

        for method_name in (
            "rebuild",
            "build",
            "rebuild_portfolio",
        ):

            if not hasattr(
                rebuilder,
                method_name,
            ):
                continue

            method = getattr(
                rebuilder,
                method_name,
            )

            try:

                portfolio = method()

                print_record(
                    "Rebuilt Portfolio",
                    portfolio,
                )

                if hasattr(
                    portfolio,
                    "positions",
                ):

                    print()
                    print(
                        "Positions:",
                        portfolio.positions,
                    )

                break

            except TypeError as exc:

                print(
                    f"{method_name} could not be "
                    f"called with no arguments: "
                    f"{exc}"
                )

    except TypeError as exc:

        print(
            "Constructor requires different "
            "arguments:"
        )

        print(
            exc
        )

    print()
    print("=" * 78)
    print(
        "INSPECTION COMPLETE"
    )
    print("=" * 78)
    print()


if __name__ == "__main__":
    main()
from __future__ import annotations

from database.account_storage import (
    AccountStorage,
    DEFAULT_ACCOUNT_ID,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.orders import OrderSide
from trading.portfolio import (
    Portfolio,
    PortfolioError,
)


class PortfolioRebuildError(Exception):
    """Raised when persistent trade history cannot be replayed safely."""


class PortfolioRebuilder:

    def __init__(
        self,
        account_storage: AccountStorage,
        trading_storage: TradingStorage,
    ) -> None:

        self.account_storage = (
            account_storage
        )

        self.trading_storage = (
            trading_storage
        )

    def rebuild(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> Portfolio:

        account = (
            self.account_storage
            .get_account(account_id)
        )

        if account is None:
            raise PortfolioRebuildError(
                f"Paper account {account_id} "
                f"does not exist."
            )

        portfolio = Portfolio(
            starting_cash=(
                account.starting_cash
            )
        )

        fills = (
            self.trading_storage
            .list_fills()
        )

        for fill in fills:

            try:

                if fill.side == OrderSide.BUY.value:

                    portfolio.buy(
                        ticker=fill.ticker,
                        quantity=fill.quantity,
                        price=fill.fill_price,
                        fees=fill.fees,
                    )

                elif fill.side == OrderSide.SELL.value:

                    portfolio.sell(
                        ticker=fill.ticker,
                        quantity=fill.quantity,
                        price=fill.fill_price,
                        fees=fill.fees,
                    )

                else:
                    raise PortfolioRebuildError(
                        f"Unsupported stored side "
                        f"{fill.side} for "
                        f"fill {fill.fill_id}."
                    )

            except PortfolioError as exc:

                raise PortfolioRebuildError(
                    f"Failed while replaying "
                    f"fill {fill.fill_id}: {exc}"
                ) from exc

        return portfolio


def rebuild_portfolio(
    account_storage: AccountStorage,
    trading_storage: TradingStorage,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> Portfolio:

    rebuilder = PortfolioRebuilder(
        account_storage=account_storage,
        trading_storage=trading_storage,
    )

    return rebuilder.rebuild(
        account_id=account_id
    )
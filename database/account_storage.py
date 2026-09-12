from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Numeric,
    String,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    Mapped,
    Session,
    mapped_column,
)

from database.sqlite_engine import create_sqlite_engine
from database.storage import (
    Base,
    get_default_database_path,
    utc_iso,
)


DEFAULT_ACCOUNT_ID = "model1-paper"


class AccountStorageError(Exception):
    """Base exception for account-persistence failures."""


class DuplicateAccountError(AccountStorageError):
    """Raised when the requested account already exists."""

# Backward-compatible alias used by existing tests/callers.
AccountAlreadyExistsError = DuplicateAccountError

class MultipleAccountsNotAllowedError(AccountStorageError):
    """
    Raised when code attempts to create a second
    paper account inside the same Model 1 database.

    Model 1 invariant:
        one SQLite database = one paper account
    """


# Compatibility alias in case another module uses
# a more explicit duplicate-account name.
DuplicatePaperAccountError = DuplicateAccountError


class PaperAccount(Base):
    """
    Persistent Model 1 paper account.

    Model 1 intentionally permits only one row
    in this table per SQLite database.
    """

    __tablename__ = "paper_accounts"

    account_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    starting_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )


@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    starting_cash: Decimal
    created_at_utc: str


class AccountStorage:
    """
    Persistent repository for the Model 1 paper account.

    Current architecture intentionally enforces:

        one database
            =
        one paper account

    This prevents PortfolioRebuilder from accidentally
    combining fills belonging to multiple accounts.

    Multi-account support should only be added later
    alongside account_id foreign keys on orders,
    fills, and portfolio snapshots.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = get_default_database_path()

        self.database_path = Path(
            database_path
        ).expanduser()

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.engine = create_sqlite_engine(
            self.database_path
        )

    def initialize(self) -> None:
        """
        Create account table if it does not exist.
        """

        Base.metadata.create_all(
            self.engine
        )

    @staticmethod
    def _normalize_starting_cash(
        starting_cash,
    ) -> Decimal:

        value = Decimal(
            str(starting_cash)
        )

        if value <= Decimal("0"):
            raise ValueError(
                "starting_cash must be positive."
            )

        return value

    @staticmethod
    def _normalize_account_id(
        account_id: str,
    ) -> str:

        normalized = (
            account_id.strip()
        )

        if not normalized:
            raise ValueError(
                "account_id cannot be empty."
            )

        return normalized

    def create_account(
        self,
        starting_cash,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> AccountRecord:
        """
        Create the database's single paper account.

        Rules:

        No existing account:
            creation allowed

        Same account already exists:
            DuplicateAccountError

        Different account already exists:
            MultipleAccountsNotAllowedError
        """

        account_id = (
            self._normalize_account_id(
                account_id
            )
        )

        starting_cash = (
            self._normalize_starting_cash(
                starting_cash
            )
        )

        with Session(
            self.engine
        ) as session:

            existing_accounts = (
                session.scalars(
                    select(
                        PaperAccount
                    )
                )
                .all()
            )

            if existing_accounts:

                existing = (
                    existing_accounts[0]
                )

                if (
                    existing.account_id
                    == account_id
                ):
                    raise DuplicateAccountError(
                        f"Account {account_id} "
                        "already exists."
                    )

                raise MultipleAccountsNotAllowedError(
                    "Model 1 allows only one "
                    "paper account per database. "
                    f"Existing account: "
                    f"{existing.account_id}. "
                    f"Requested account: "
                    f"{account_id}."
                )

            account = PaperAccount(
                account_id=account_id,
                starting_cash=(
                    starting_cash
                ),
                created_at_utc=utc_iso(
                    datetime.now(
                        timezone.utc
                    )
                ),
            )

            session.add(
                account
            )

            try:
                session.commit()

            except IntegrityError as exc:
                session.rollback()

                raise DuplicateAccountError(
                    f"Account {account_id} "
                    "already exists."
                ) from exc

            return AccountRecord(
                account_id=(
                    account.account_id
                ),
                starting_cash=Decimal(
                    str(
                        account.starting_cash
                    )
                ),
                created_at_utc=(
                    account.created_at_utc
                ),
            )

    def get_account(
        self,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> AccountRecord | None:
        """
        Return an account by ID.
        """

        account_id = (
            self._normalize_account_id(
                account_id
            )
        )

        with Session(
            self.engine
        ) as session:

            account = session.get(
                PaperAccount,
                account_id,
            )

            if account is None:
                return None

            return AccountRecord(
                account_id=(
                    account.account_id
                ),
                starting_cash=Decimal(
                    str(
                        account.starting_cash
                    )
                ),
                created_at_utc=(
                    account.created_at_utc
                ),
            )

    def get_or_create(
        self,
        starting_cash,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> AccountRecord:
        """
        Return the requested account if it exists.

        If the database contains no account, create it.

        If the database already contains a different
        account, fail closed rather than silently
        introducing a second account.
        """

        account_id = (
            self._normalize_account_id(
                account_id
            )
        )

        starting_cash = (
            self._normalize_starting_cash(
                starting_cash
            )
        )

        existing = self.get_account(
            account_id
        )

        if existing is not None:
            return existing

        with Session(
            self.engine
        ) as session:

            any_account = (
                session.scalars(
                    select(
                        PaperAccount
                    )
                )
                .first()
            )

            if any_account is not None:
                raise MultipleAccountsNotAllowedError(
                    "Model 1 allows only one "
                    "paper account per database. "
                    f"Existing account: "
                    f"{any_account.account_id}. "
                    f"Requested account: "
                    f"{account_id}."
                )

        return self.create_account(
            starting_cash=starting_cash,
            account_id=account_id,
        )

    def count_accounts(
        self,
    ) -> int:
        """
        Primarily useful for invariant checks/tests.
        """

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        PaperAccount
                    )
                ).all()
            )
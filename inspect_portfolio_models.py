from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass

from trading.portfolio import (
    Portfolio,
    Position,
)


def show_class(
    label: str,
    cls,
) -> None:

    print()
    print("=" * 78)
    print(label)
    print("=" * 78)

    print(
        "Signature:",
        inspect.signature(
            cls
        ),
    )

    print()
    print(
        "Dataclass:",
        is_dataclass(
            cls
        ),
    )

    if is_dataclass(
        cls
    ):

        print(
            "Fields:"
        )

        for field in fields(
            cls
        ):

            print(
                f"  {field.name}: "
                f"{field.type}"
            )

    print()
    print(
        "Public methods/properties:"
    )

    for name in dir(
        cls
    ):

        if name.startswith(
            "_"
        ):
            continue

        attr = getattr(
            cls,
            name,
        )

        if callable(
            attr
        ):

            try:

                signature = (
                    inspect.signature(
                        attr
                    )
                )

                print(
                    f"  {name}"
                    f"{signature}"
                )

            except Exception:

                print(
                    f"  {name}"
                )

        else:

            print(
                f"  {name}"
            )


def main() -> None:

    print(
        "Portfolio Model Inspection"
    )

    show_class(
        "Portfolio",
        Portfolio,
    )

    show_class(
        "Position",
        Position,
    )

    print()
    print(
        "INSPECTION COMPLETE"
    )


if __name__ == "__main__":
    main()
import pytest

import runtime
from evaluation.benchmark import (
    BenchmarkDataError,
)


def test_runtime_benchmark_with_empty_history(
    tmp_path,
):

    db = (
        tmp_path
        / "benchmark-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    with pytest.raises(
        BenchmarkDataError
    ):

        live.get_benchmark_comparison()
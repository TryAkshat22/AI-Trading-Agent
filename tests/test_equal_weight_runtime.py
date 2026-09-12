import pytest

import runtime

from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkError,
)


def test_runtime_equal_weight_empty_history(
    tmp_path,
):

    db = (
        tmp_path
        / "equal-weight-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    with pytest.raises(
        EqualWeightBenchmarkError
    ):

        live.get_equal_weight_benchmark_comparison()
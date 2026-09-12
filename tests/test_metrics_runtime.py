import pytest

import runtime

from evaluation.performance_metrics import (
    PerformanceMetricError,
)


def test_runtime_metrics_empty_history(
    tmp_path,
):

    db = (
        tmp_path
        / "metrics-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    with pytest.raises(
        PerformanceMetricError
    ):

        live.get_performance_metrics()
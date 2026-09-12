import pytest

import runtime

from evaluation.evaluation_report import (
    EvaluationReportError,
)


def test_runtime_evaluation_empty_history(
    tmp_path,
):

    db = (
        tmp_path
        / "evaluation-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    with pytest.raises(
        EvaluationReportError
    ):

        live.get_evaluation_report()
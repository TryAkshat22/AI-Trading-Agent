import pytest

import runtime

from evaluation.evaluation_report import (
    EvaluationReportError,
)


def test_export_report_empty_history_fails_closed(
    tmp_path,
):

    db = (
        tmp_path
        / "report-bundle-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    with pytest.raises(
        EvaluationReportError
    ):

        live.export_report()
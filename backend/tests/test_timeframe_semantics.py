from __future__ import annotations

import os


def test_timeframe_analysis_uses_supported_rolling_month_labels():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    page_path = os.path.join(repo_root, "frontend", "components", "TimeframeAnalysis.tsx")

    with open(page_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Month-to-Date" not in content
    assert "MTD analysis" not in content
    assert "current,week,month,year" not in content
    assert "label: '1 Month'" in content
    assert "description: 'Rolling 1-month window'" in content
    assert "/api/v2/analyze/compare?timeframes=current,week,month" in content

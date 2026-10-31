"""体检引擎单元测试。"""

from __future__ import annotations

import pytest

from parquetscope import read_metadata
from parquetscope.analyzer import (
    SEVERITIES,
    audit,
    build_column_profiles,
    list_rules,
)

from .conftest import sample


def _codes(meta, **kwargs) -> set[str]:
    return {f.code for f in audit(meta, **kwargs).findings}


def test_list_rules_covers_all_segments():
    rules = list_rules()
    assert len(rules) == 22
    assert {r["code"][:2] for r in rules} <= {"PS"}
    assert rules[0]["code"] == "PS001"


def test_healthy_file_triggers_size_rules():
    meta = read_metadata(sample("healthy.parquet"))
    codes = _codes(meta)
    # 小样本文件必然触发体积类规则
    assert {"PS001", "PS003"} <= codes


def test_no_statistics_triggers_ps300():
    meta = read_metadata(sample("no_statistics.parquet"))
    codes = _codes(meta)
    assert "PS300" in codes
    report = audit(meta)
    finding = next(f for f in report.findings if f.code == "PS300")
    assert finding.severity == "error"


def test_uncompressed_triggers_ps201():
    meta = read_metadata(sample("uncompressed.parquet"))
    # 样本体积较小，这里覆盖默认阈值以验证规则本身
    assert "PS201" in _codes(meta, thresholds={"uncompressed_column_bytes": 100_000})
    assert "PS201" not in _codes(meta)


def test_wide_table_triggers_ps100():
    meta = read_metadata(sample("wide.parquet"))
    assert "PS100" in _codes(meta)
    assert meta.num_columns == 220


def test_nested_triggers_depth_rule():
    meta = read_metadata(sample("nested.parquet"))
    assert "PS101" in _codes(meta)


def test_int96_triggers_ps102_and_ps200():
    meta = read_metadata(sample("int96.parquet"))
    codes = _codes(meta)
    assert "PS102" in codes
    assert "PS200" in codes
    # INT96 不写统计属于规范预期，不应被判为缺失统计
    assert "PS300" not in codes


def test_wide_strings_triggers_ps402():
    meta = read_metadata(sample("wide_strings.parquet"))
    assert "PS402" in _codes(meta)


def test_sorted_column_detected():
    meta = read_metadata(sample("sorted.parquet"))
    profiles = {p.path: p for p in build_column_profiles(meta)}
    assert profiles["user_id"].global_sortedness == "ascending"
    assert profiles["event_id"].global_sortedness == "unsorted"


def test_single_row_group_sortedness_unknown():
    meta = read_metadata(sample("healthy.parquet"))
    profiles = build_column_profiles(meta)
    assert all(p.global_sortedness == "unknown" for p in profiles)


def test_score_bounds_and_severities():
    meta = read_metadata(sample("no_statistics.parquet"))
    report = audit(meta)
    assert 0 <= report.score <= 100
    assert set(report.severity_counts) == set(SEVERITIES)
    assert report.max_severity in SEVERITIES


def test_findings_sorted_error_first():
    meta = read_metadata(sample("no_statistics.parquet"))
    report = audit(meta)
    order = [{"info": 0, "warn": 1, "error": 2}[f.severity] for f in report.findings]
    assert order == sorted(order, reverse=True)


def test_threshold_override_disables_rule():
    meta = read_metadata(sample("healthy.parquet"))
    assert "PS001" in _codes(meta)
    assert "PS001" not in _codes(meta, thresholds={"min_file_bytes": 1})


def test_enabled_rules_filter():
    meta = read_metadata(sample("healthy.parquet"))
    codes = _codes(meta, enabled_rules=["PS003"])
    assert codes == {"PS003"}


def test_column_profile_aggregation():
    meta = read_metadata(sample("small_rowgroups.parquet"))
    profiles = build_column_profiles(meta)
    assert len(profiles) == 7
    for profile in profiles:
        assert profile.chunk_count == 10
        assert profile.stats_coverage == 1.0
        assert profile.compression_ratio > 0.9
    assert meta.overall_compression_ratio > 1.4


def test_report_to_dict_is_json_serializable():
    import json

    meta = read_metadata(sample("types.parquet"))
    report = audit(meta, path="types.parquet")
    payload = json.loads(json.dumps(report.to_dict(), default=str))
    assert payload["path"] == "types.parquet"
    assert payload["columns"]


def test_minimum_severity_filter():
    meta = read_metadata(sample("no_statistics.parquet"))
    report = audit(meta)
    assert len(report.findings_by_severity("error")) <= len(report.findings)

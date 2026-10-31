"""命令行与报告渲染单元测试。"""

from __future__ import annotations

import csv
import io
import json

import pytest

from parquetscope import read_metadata
from parquetscope.analyzer import audit, build_column_profiles
from parquetscope.cli import main
from parquetscope.report import (
    render_audit,
    render_columns,
    render_doctor,
    render_info,
    render_rowgroups,
    render_schema,
)

from .conftest import DATA_DIR, sample


# --------------------------------------------------------------------------- #
# 渲染层
# --------------------------------------------------------------------------- #
def test_render_info_all_formats():
    meta = read_metadata(sample("healthy.parquet"))
    text = render_info(meta, "text", path="healthy.parquet")
    assert "总行数" in text and "50,000" in text

    payload = json.loads(render_info(meta, "json", path="healthy.parquet"))
    assert payload["num_rows"] == 50_000
    assert payload["path"] == "healthy.parquet"

    md = render_info(meta, "markdown", path="healthy.parquet")
    assert md.startswith("###")

    cs_v = render_info(meta, "csv", path="healthy.parquet")
    assert "指标" in cs_v


def test_render_schema_contains_columns():
    meta = read_metadata(sample("types.parquet"))
    text = render_schema(meta)
    assert "string_col" in text and "STRING" in text
    payload = json.loads(render_schema(meta, "json"))
    assert "schema" in payload
    rows = list(csv.reader(io.StringIO(render_schema(meta, "csv"))))
    assert rows[0][0] == "path"


def test_render_rowgroups():
    meta = read_metadata(sample("small_rowgroups.parquet"))
    text = render_rowgroups(meta)
    assert "10" in text
    payload = json.loads(render_rowgroups(meta, "json"))
    assert len(payload) == 10


def test_render_columns_limit():
    meta = read_metadata(sample("wide.parquet"))
    profiles = build_column_profiles(meta)
    text = render_columns(profiles, "text", limit=5)
    assert "5/220" in text
    payload = json.loads(render_columns(profiles, "json", limit=3))
    assert payload["truncated"] is True and len(payload["columns"]) == 3


def test_render_audit_formats():
    meta = read_metadata(sample("no_statistics.parquet"))
    report = audit(meta, path="x.parquet")
    text = render_audit(report)
    assert "健康评分" in text and "PS300" in text
    md = render_audit(report, "markdown")
    assert "###" in md
    payload = json.loads(render_audit(report, "json"))
    assert payload["findings"]
    rows = list(csv.reader(io.StringIO(render_audit(report, "csv"))))
    assert rows[0][:2] == ["code", "severity"]


def test_render_doctor():
    summary = {
        "summary": {
            "num_files": 2,
            "num_rows": 100,
            "total_size": 2048,
            "total_compressed_size": 1024,
            "compression_ratio": 2.0,
            "avg_score": 88.0,
            "small_files": 2,
            "small_file_threshold": 8 * 1024 * 1024,
            "schema_variants": 1,
        },
        "files": [
            {
                "path": "a.parquet",
                "file_size": 1024,
                "num_rows": 50,
                "num_row_groups": 1,
                "compression_ratio": 2.0,
                "score": 88,
                "errors": 0,
                "warnings": 1,
                "schema_fingerprint": "abc",
            }
        ],
        "schema_drifts": [],
    }
    assert "文件数量" in render_doctor(summary)
    assert json.loads(render_doctor(summary, "json"))["summary"]["num_files"] == 2


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_info(capsys):
    code = main(["info", str(sample("healthy.parquet"))])
    assert code == 0
    assert "50,000" in capsys.readouterr().out


def test_cli_all_commands_exit_zero():
    path = str(sample("healthy.parquet"))
    for command in ("info", "schema", "rowgroups", "columns", "audit", "dump"):
        assert main([command, path]) == 0, command


def test_cli_audit_fail_on_error():
    path = str(sample("no_statistics.parquet"))
    assert main(["audit", path, "--fail-on", "error"]) == 1
    assert main(["audit", path, "--fail-on", "none"]) == 0


def test_cli_audit_fail_on_warn():
    assert main(["audit", str(sample("healthy.parquet")), "--fail-on", "warn"]) == 1


def test_cli_json_output():
    code = main(["audit", str(sample("healthy.parquet")), "--format", "json"])
    assert code == 0


def test_cli_dump_json(tmp_path, capsys):
    target = tmp_path / "meta.json"
    code = main(["dump", str(sample("types.parquet")), "-o", str(target)])
    assert code == 0
    payload = json.loads(target.read_text())
    assert payload["num_columns"] == 11
    assert payload["row_groups"]


def test_cli_output_file(tmp_path):
    target = tmp_path / "out.md"
    code = main(["schema", str(sample("nested.parquet")), "--format", "markdown", "-o", str(target)])
    assert code == 0 and target.exists() and "Schema" in target.read_text()


def test_cli_rules():
    assert main(["rules"]) == 0
    assert main(["rules", "--format", "json"]) == 0


def test_cli_missing_path():
    assert main(["info", "/no/such/file.parquet"]) == 1


def test_cli_directory_target():
    assert main(["info", str(DATA_DIR)]) == 0


def test_cli_glob_target():
    assert main(["audit", str(DATA_DIR / "*.parquet"), "--fail-on", "none"]) == 0


def test_cli_doctor():
    assert main(["doctor", str(DATA_DIR), "--fail-on", "none"]) == 0


def test_cli_doctor_schema_drift_reported(capsys):
    main(["doctor", str(DATA_DIR), "--fail-on", "none"])
    assert "Schema 漂移" in capsys.readouterr().out


def test_cli_threshold_override():
    path = str(sample("healthy.parquet"))
    # 默认阈值下 PS001（小文件）会触发 warning
    assert main(["audit", path, "--rule", "PS001", "--fail-on", "warn"]) == 1
    # 把小文件阈值降到接近 0 后不再触发
    assert main(["audit", path, "--rule", "PS001", "--min-file-mb", "0.000001",
                 "--fail-on", "warn"]) == 0


def test_cli_bad_file_reports_error(capsys):
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
        handle.write(b"NOTPARQUET" * 8)
        name = handle.name
    code = main(["info", name])
    assert code == 1
    assert "PAR1" in capsys.readouterr().out

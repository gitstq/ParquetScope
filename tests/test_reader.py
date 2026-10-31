"""文件读取器与样本解析单元测试。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from parquetscope import read_metadata, read_metadata_bytes
from parquetscope.errors import (
    EncryptedFileError,
    NotParquetError,
    ParquetScopeError,
    TruncatedFileError,
)
from parquetscope.reader import ParquetFile, iter_parquet_files, is_parquet_candidate

from .conftest import DATA_DIR, sample


# --------------------------------------------------------------------------- #
# 基础解析
# --------------------------------------------------------------------------- #
def test_read_healthy_metadata():
    meta = read_metadata(sample("healthy.parquet"))
    assert meta.num_rows == 50_000
    assert meta.num_columns == 7
    assert meta.num_row_groups == 1
    assert meta.created_by and "parquet-cpp-arrow" in meta.created_by
    assert meta.overall_compression_ratio > 1.5
    assert meta.encrypted is False


def test_leaf_paths_match_column_chunks():
    meta = read_metadata(sample("healthy.parquet"))
    leaf_paths = [leaf.path for leaf in meta.leaves]
    chunk_paths = [chunk.path_in_schema for chunk in meta.row_groups[0].columns]
    assert leaf_paths == chunk_paths


def test_statistics_decoded_for_all_columns():
    meta = read_metadata(sample("healthy.parquet"))
    for chunk in meta.row_groups[0].columns:
        assert chunk.statistics is not None
        assert chunk.statistics.min_value is not None


def test_no_statistics_sample():
    meta = read_metadata(sample("no_statistics.parquet"))
    with_stats = sum(
        1 for rg in meta.row_groups for c in rg.columns if c.statistics and c.statistics.present
    )
    assert with_stats == 0


def test_small_rowgroups_sample():
    meta = read_metadata(sample("small_rowgroups.parquet"))
    assert meta.num_row_groups == 10
    assert meta.avg_row_group_rows == 5_000


def test_decimal_and_timestamp_values():
    meta = read_metadata(sample("types.parquet"))
    by_path = {c.path_in_schema: c for c in meta.row_groups[0].columns}
    assert isinstance(by_path["decimal_col"].statistics.min_value, Decimal)
    assert isinstance(by_path["ts_us"].statistics.min_value, dt.datetime)
    assert isinstance(by_path["date_col"].statistics.min_value, dt.date)
    assert by_path["nullable_col"].statistics.null_count == 1_667


def test_uncompressed_sample_codec():
    meta = read_metadata(sample("uncompressed.parquet"))
    assert meta.row_groups[0].columns[0].codec_name == "UNCOMPRESSED"


def test_read_from_bytes():
    payload = sample("healthy.parquet").read_bytes()
    meta = read_metadata_bytes(payload, name="memory.parquet")
    assert meta.num_rows == 50_000


def test_context_manager():
    with ParquetFile(sample("healthy.parquet")) as handle:
        assert handle.metadata.num_rows == 50_000


# --------------------------------------------------------------------------- #
# 错误处理
# --------------------------------------------------------------------------- #
def test_not_parquet_error(tmp_path):
    bad = tmp_path / "bad.parquet"
    bad.write_bytes(b"NOTPARQUET" * 10)
    with pytest.raises(NotParquetError):
        read_metadata(bad)


def test_truncated_file_error(tmp_path):
    small = tmp_path / "tiny.parquet"
    small.write_bytes(b"PAR1" + b"\x00" * 4)
    with pytest.raises((TruncatedFileError, NotParquetError)):
        read_metadata(small)


def test_encrypted_footer_detected(tmp_path):
    path = tmp_path / "enc.parquet"
    path.write_bytes(b"PAR1" + b"\x00" * 16 + b"PARE")
    with pytest.raises(EncryptedFileError):
        read_metadata(path)


def test_corrupted_footer_length(tmp_path):
    path = tmp_path / "corrupt.parquet"
    payload = b"PAR1" + b"\x00" * 32
    path.write_bytes(payload + (10**9).to_bytes(4, "little") + b"PAR1")
    with pytest.raises(TruncatedFileError):
        read_metadata(path)


def test_missing_file():
    with pytest.raises(ParquetScopeError):
        read_metadata("/definitely/not/here.parquet")


# --------------------------------------------------------------------------- #
# 路径展开
# --------------------------------------------------------------------------- #
def test_is_parquet_candidate():
    assert is_parquet_candidate("a.parquet")
    assert is_parquet_candidate("a.PARQ")
    assert not is_parquet_candidate("a.csv")


def test_iter_parquet_files_directory():
    files = list(iter_parquet_files([DATA_DIR]))
    assert len(files) >= 8
    assert all(f.suffix == ".parquet" for f in files)


def test_iter_parquet_files_glob():
    files = list(iter_parquet_files([str(DATA_DIR / "heal*.parquet")]))
    assert len(files) == 1
    assert files[0].name == "healthy.parquet"


def test_iter_parquet_files_deduplicates():
    files = list(iter_parquet_files([DATA_DIR, DATA_DIR]))
    assert len(files) == len(set(files))

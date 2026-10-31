"""元数据模型与值解码单元测试。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from parquetscope import types as T
from parquetscope.metadata import (
    LogicalType,
    SchemaElement,
    build_schema_tree,
    decode_value,
    iter_leaves,
    schema_depth,
)
from parquetscope.errors import UnsupportedFeatureError

from .conftest import sample


# --------------------------------------------------------------------------- #
# LogicalType
# --------------------------------------------------------------------------- #
def test_logical_type_string():
    lt = LogicalType.from_thrift({1: {}})
    assert lt is not None and lt.name == "STRING"


def test_logical_type_decimal():
    lt = LogicalType.from_thrift({5: {1: 2, 2: 12}})
    assert lt is not None
    assert lt.name == "DECIMAL"
    assert lt.params == {"scale": 2, "precision": 12}
    assert str(lt) == "DECIMAL(scale=2,precision=12)"


def test_logical_type_timestamp_micros():
    # parquet 的 TimeUnit 是嵌套 union：{2: {}} 表示 MICROS
    lt = LogicalType.from_thrift({8: {1: True, 2: {2: {}}}})
    assert lt is not None
    assert lt.name == "TIMESTAMP"
    assert lt.params["unit"] == "MICROS"
    assert lt.params["is_adjusted_to_utc"] is True


def test_logical_type_timestamp_defaults_to_millis():
    lt = LogicalType.from_thrift({8: {1: False}})
    assert lt.params["unit"] == "MILLIS"


def test_logical_type_integer():
    lt = LogicalType.from_thrift({10: {1: 32, 2: True}})
    assert lt.name == "INTEGER"
    assert lt.params["bit_width"] == 32
    assert lt.params["is_signed"] is True


def test_logical_type_none():
    assert LogicalType.from_thrift(None) is None
    assert LogicalType.from_thrift({}) is None


# --------------------------------------------------------------------------- #
# schema 树
# --------------------------------------------------------------------------- #
def _group(name: str, children: int, repetition: int = T.REPETITION_OPTIONAL) -> SchemaElement:
    return SchemaElement(name=name, repetition=repetition, num_children=children)


def _leaf(name: str, ptype: int = T.TYPE_INT64) -> SchemaElement:
    return SchemaElement(
        name=name, physical_type=ptype, repetition=T.REPETITION_OPTIONAL, num_children=0
    )


def test_build_schema_tree_flat():
    root = build_schema_tree([_group("root", 2), _leaf("a"), _leaf("b")])
    assert root.name == "root"
    assert root.path == ""
    assert [leaf.path for leaf in iter_leaves(root)] == ["a", "b"]
    assert [leaf.leaf_index for leaf in iter_leaves(root)] == [0, 1]
    assert schema_depth(root) == 1


def test_build_schema_tree_nested():
    elements = [
        _group("root", 2),
        _group("outer", 2),
        _leaf("x"),
        _group("inner", 1),
        _leaf("y"),
        _leaf("z"),
    ]
    root = build_schema_tree(elements)
    assert [leaf.path for leaf in iter_leaves(root)] == ["outer.x", "outer.inner.y", "z"]
    assert schema_depth(root) == 3


def test_build_schema_tree_levels():
    root = build_schema_tree(
        [
            _group("root", 1, T.REPETITION_REQUIRED),
            _group("list", 1, T.REPETITION_REPEATED),
            _leaf("element", T.TYPE_BYTE_ARRAY),
        ]
    )
    # 标准 2 级 LIST：definition(max)=2, repetition(max)=1
    leaf = next(iter_leaves(root))
    assert leaf.max_repetition_level == 1
    assert leaf.max_definition_level == 2


def test_build_schema_tree_empty():
    with pytest.raises(UnsupportedFeatureError):
        build_schema_tree([])


# --------------------------------------------------------------------------- #
# 值解码
# --------------------------------------------------------------------------- #
def test_decode_int32_and_date():
    assert decode_value((42).to_bytes(4, "little", signed=True), T.TYPE_INT32) == 42
    value = decode_value(
        (20000).to_bytes(4, "little", signed=True), T.TYPE_INT32, converted_type=6
    )
    assert value == dt.date(2024, 10, 4)


def test_decode_int64_timestamp_micros():
    micros = 1_763_000_000_000_000
    value = decode_value(
        micros.to_bytes(8, "little", signed=True),
        T.TYPE_INT64,
        logical_type=LogicalType("TIMESTAMP", {"unit": "MICROS", "is_adjusted_to_utc": True}),
    )
    assert isinstance(value, dt.datetime)
    assert value.year == 2025
    assert value.tzinfo is not None


def test_decode_int64_timestamp_local_semantics():
    micros = 1_763_000_000_000_000
    value = decode_value(
        micros.to_bytes(8, "little", signed=True),
        T.TYPE_INT64,
        logical_type=LogicalType("TIMESTAMP", {"unit": "MICROS", "is_adjusted_to_utc": False}),
    )
    assert value.tzinfo is None


def test_decode_float_double_boolean():
    import struct

    assert decode_value(struct.pack("<f", 1.5), T.TYPE_FLOAT) == 1.5
    assert decode_value(struct.pack("<d", 2.25), T.TYPE_DOUBLE) == 2.25
    assert decode_value(b"\x01", T.TYPE_BOOLEAN) is True
    assert decode_value(b"\x00", T.TYPE_BOOLEAN) is False


def test_decode_byte_array_utf8():
    assert decode_value(b"hello", T.TYPE_BYTE_ARRAY, converted_type=0) == "hello"
    assert decode_value(b"hello", T.TYPE_BYTE_ARRAY, logical_type=LogicalType("STRING")) == "hello"


def test_decode_decimal_fixed_len():
    raw = (12345).to_bytes(8, "big", signed=True)
    value = decode_value(
        raw,
        T.TYPE_FIXED_LEN_BYTE_ARRAY,
        logical_type=LogicalType("DECIMAL", {"scale": 2, "precision": 12}),
    )
    assert value == Decimal("123.45")


def test_decode_uuid():
    raw = bytes(range(16))
    value = decode_value(raw, T.TYPE_FIXED_LEN_BYTE_ARRAY, logical_type=LogicalType("UUID"))
    assert value == "00010203-0405-0607-0809-0a0b0c0d0e0f"


def test_decode_float16():
    # 0x3C00 == 1.0
    assert decode_value(b"\x00\x3c", T.TYPE_FIXED_LEN_BYTE_ARRAY, logical_type=LogicalType("FLOAT16")) == 1.0


def test_decode_int96():
    julian_day = 2440588  # 1970-01-01
    raw = (0).to_bytes(8, "little") + julian_day.to_bytes(4, "little", signed=True)
    value = decode_value(raw, T.TYPE_INT96)
    assert isinstance(value, dt.datetime)
    assert value.date() == dt.date(1970, 1, 1)


def test_decode_unknown_bytes_fallback():
    raw = b"\xff\xfe"
    assert decode_value(raw, T.TYPE_BYTE_ARRAY) == raw


# --------------------------------------------------------------------------- #
# 真实样本上的 schema 结构
# --------------------------------------------------------------------------- #
def test_nested_sample_schema():
    from parquetscope import read_metadata

    meta = read_metadata(sample("nested.parquet"))
    paths = [leaf.path for leaf in meta.leaves]
    assert "payload.level1.level2.level3.level4.value" in paths
    assert "tags.list.element" in paths
    assert meta.depth >= 5


def test_types_sample_logical_types():
    from parquetscope import read_metadata

    meta = read_metadata(sample("types.parquet"))
    by_path = {leaf.path: leaf.element for leaf in meta.leaves}
    assert by_path["date_col"].logical_type.name == "DATE"
    assert by_path["decimal_col"].logical_type.params["scale"] == 2
    assert by_path["string_col"].logical_type.name == "STRING"
    assert by_path["ts_us"].logical_type.params["unit"] == "MICROS"


def test_schema_fingerprint_stable():
    from parquetscope import read_metadata

    meta = read_metadata(sample("healthy.parquet"))
    assert len(meta.schema_fingerprint()) == 16
    assert meta.schema_fingerprint() == read_metadata(sample("healthy.parquet")).schema_fingerprint()

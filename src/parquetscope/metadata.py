"""Parquet 元数据模型。

把 Thrift 解码后的裸字典转换为带有语义的对象模型：

* :class:`SchemaNode` —— 可嵌套的 schema 树
* :class:`ColumnStatistics` —— 列块级统计信息（含物理值解码）
* :class:`ColumnChunkInfo` / :class:`RowGroupInfo` —— 存储布局
* :class:`ParquetMetadata` —— 文件级元数据

所有解码逻辑均为自研实现，不依赖任何第三方 Parquet 库。
"""

from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

from . import types as T
from .errors import UnsupportedFeatureError

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
_I32 = struct.Struct("<i")
_I64 = struct.Struct("<q")
_F32 = struct.Struct("<f")
_F64 = struct.Struct("<d")
_F16_SIGN = 0x8000


# --------------------------------------------------------------------------- #
# 逻辑类型
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LogicalType:
    """Parquet ``LogicalType`` union 的解码结果。"""

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_thrift(cls, raw: dict[int, Any] | None) -> "LogicalType | None":
        if not raw:
            return None
        for fid, name in T.LOGICAL_TYPE_FIELDS.items():
            if fid not in raw:
                continue
            body = raw[fid]
            params: dict[str, Any] = {}
            if isinstance(body, dict):
                if fid == 5:
                    # DecimalType: 1=scale, 2=precision
                    params = {"scale": body.get(1, 0), "precision": body.get(2, 0)}
                elif fid in (7, 8):
                    # TimeType / TimestampType: 1=isAdjustedToUTC, 2=TimeUnit(union)
                    params["is_adjusted_to_utc"] = bool(body.get(1, False))
                    params["unit"] = _decode_time_unit(body.get(2))
                elif fid == 10:
                    # IntType: 1=bitWidth, 2=isSigned
                    params["bit_width"] = body.get(1)
                    params["is_signed"] = bool(body.get(2, True))
            return cls(name=name, params=params)
        return None

    def __str__(self) -> str:  # pragma: no cover - 展示用
        if not self.params:
            return self.name
        rendered = ",".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({rendered})"


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def _decode_name(value: Any) -> str:
    """Thrift 中 string 与 binary 同编码，这里统一转为 str。"""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _decode_time_unit(raw: Any) -> str:
    """解码 ``TimeUnit`` union（1=MILLIS, 2=MICROS, 3=NANOS，均为空结构体）。"""
    if isinstance(raw, dict):
        for code in (1, 2, 3):
            if code in raw:
                return T.TIME_UNITS[code]
        return "MILLIS"
    if isinstance(raw, int):
        return T.TIME_UNITS.get(raw, "MILLIS")
    return "MILLIS"


@dataclass
class SchemaElement:
    """``SchemaElement`` 的字段映射。"""

    name: str
    physical_type: int | None = None
    type_length: int | None = None
    repetition: int | None = None
    num_children: int = 0
    converted_type: int | None = None
    scale: int | None = None
    precision: int | None = None
    field_id: int | None = None
    logical_type: LogicalType | None = None

    @classmethod
    def from_thrift(cls, raw: dict[int, Any]) -> "SchemaElement":
        return cls(
            name=_decode_name(raw.get(T.SE_NAME, "")),
            physical_type=raw.get(T.SE_TYPE),
            type_length=raw.get(T.SE_TYPE_LENGTH),
            repetition=raw.get(T.SE_REPETITION),
            num_children=raw.get(T.SE_NUM_CHILDREN, 0) or 0,
            converted_type=raw.get(T.SE_CONVERTED_TYPE),
            scale=raw.get(T.SE_SCALE),
            precision=raw.get(T.SE_PRECISION),
            field_id=raw.get(T.SE_FIELD_ID),
            logical_type=LogicalType.from_thrift(raw.get(T.SE_LOGICAL_TYPE)),
        )

    @property
    def is_group(self) -> bool:
        return self.physical_type is None

    @property
    def is_leaf(self) -> bool:
        return not self.is_group

    @property
    def physical_name(self) -> str:
        if self.physical_type is None:
            return "GROUP"
        return T.PHYSICAL_TYPES.get(self.physical_type, f"UNKNOWN({self.physical_type})")

    @property
    def repetition_name(self) -> str:
        if self.repetition is None:
            return "-"
        return T.REPETITION_TYPES.get(self.repetition, f"UNKNOWN({self.repetition})")

    @property
    def converted_name(self) -> str | None:
        if self.converted_type is None:
            return None
        return T.CONVERTED_TYPES.get(self.converted_type)

    def annotate(self) -> str:
        """返回人类可读的类型标注，优先展示 LogicalType。"""
        if self.logical_type is not None:
            return str(self.logical_type)
        converted = self.converted_name
        base = self.physical_name
        if converted:
            return f"{converted} <{base}>"
        if self.physical_type == T.TYPE_FIXED_LEN_BYTE_ARRAY and self.type_length:
            return f"{base}[{self.type_length}]"
        return base


@dataclass
class SchemaNode:
    """schema 树节点。``leaf_index`` 仅在叶子节点上有意义。"""

    element: SchemaElement
    path: str
    depth: int
    children: list["SchemaNode"] = field(default_factory=list)
    leaf_index: int | None = None
    max_definition_level: int = 0
    max_repetition_level: int = 0

    @property
    def name(self) -> str:
        return self.element.name

    @property
    def is_leaf(self) -> bool:
        return self.element.is_leaf


def build_schema_tree(elements: Sequence[SchemaElement]) -> SchemaNode:
    """把扁平的 ``SchemaElement`` 列表还原为一棵树。

    Parquet 的 schema 列表是 **深度优先前序** 排列：遇到 group 时其子节点
    紧随其后。这里用显式栈完成重建，并对叶子列按顺序编号。
    """
    if not elements:
        raise UnsupportedFeatureError("空 schema：文件不含任何列定义")

    root_element = elements[0]
    # Parquet 的 path_in_schema 不含 root 名称，因此这里把 root 路径置空，
    # 使叶子节点的 path 与列块中的 path_in_schema 完全一致。
    root = SchemaNode(element=root_element, path="", depth=0)
    stack: list[SchemaNode] = [root]
    leaf_counter = 0
    def_level = 0
    rep_level = 0

    for element in elements[1:]:
        if not stack:
            raise UnsupportedFeatureError("schema 结构非法：节点栈提前耗尽")
        parent = stack[-1]
        node = SchemaNode(
            element=element,
            path=f"{parent.path}.{element.name}" if parent.path else element.name,
            depth=parent.depth + 1,
        )
        parent.children.append(node)

        if element.repetition == T.REPETITION_OPTIONAL:
            def_level += 1
        elif element.repetition == T.REPETITION_REPEATED:
            def_level += 1
            rep_level += 1
        node.max_definition_level = def_level
        node.max_repetition_level = rep_level

        if element.is_group:
            stack.append(node)
            continue

        node.leaf_index = leaf_counter
        leaf_counter += 1

        # 回溯：弹出所有子节点已填充完毕的 group
        while stack:
            top = stack[-1]
            expected = top.element.num_children
            if expected and len(top.children) < expected:
                break
            stack.pop()
            if top.element.repetition == T.REPETITION_OPTIONAL:
                def_level -= 1
            elif top.element.repetition == T.REPETITION_REPEATED:
                def_level -= 1
                rep_level -= 1
            if not stack:
                break

    return root


def iter_leaves(root: SchemaNode) -> Iterable[SchemaNode]:
    """按列顺序（深度优先）产出叶子节点。"""
    if root.is_leaf:
        yield root
        return
    for child in root.children:
        yield from iter_leaves(child)


def schema_depth(root: SchemaNode) -> int:
    """计算 schema 最大嵌套深度（root 深度为 0）。"""
    if not root.children:
        return 0
    return 1 + max((schema_depth(child) for child in root.children), default=0)


# --------------------------------------------------------------------------- #
# 统计信息
# --------------------------------------------------------------------------- #
def _decode_int96(raw: bytes) -> _dt.datetime | str:
    nanos = int.from_bytes(raw[:8], "little", signed=False)
    julian_day = _I32.unpack(raw[8:12])[0]
    try:
        unix_seconds = (julian_day - 2440588) * 86400 + nanos // 1_000_000_000
        micro = (nanos % 1_000_000_000) // 1000
        return _EPOCH + _dt.timedelta(seconds=unix_seconds, microseconds=micro)
    except (OverflowError, ValueError):
        return raw.hex()


def _decode_decimal(raw: bytes, scale: int) -> Decimal | str:
    try:
        unscaled = int.from_bytes(raw, "big", signed=True)
        return Decimal(unscaled).scaleb(-scale)
    except (InvalidOperation, ValueError):
        return raw.hex()


def _decode_float16(raw: bytes) -> float:
    if len(raw) != 2:
        return float("nan")
    bits = int.from_bytes(raw, "little")
    sign = (bits & _F16_SIGN) >> 15
    exp = (bits >> 10) & 0x1F
    frac = bits & 0x3FF
    if exp == 0:
        value = frac * (2**-24)
    elif exp == 31:
        return float("-inf") if sign else float("inf")
    else:
        value = (frac + 1024) * (2 ** (exp - 25))
    return -value if sign else value


def decode_value(
    raw: bytes,
    physical_type: int,
    *,
    converted_type: int | None = None,
    logical_type: LogicalType | None = None,
    type_length: int | None = None,
    scale: int = 0,
) -> Any:
    """把统计信息中的二进制值按物理/逻辑类型解码为 Python 值。"""
    if raw is None:
        return None
    if not isinstance(raw, (bytes, bytearray)):
        return raw

    logical_name = logical_type.name if logical_type else None
    converted_name = T.CONVERTED_TYPES.get(converted_type) if converted_type is not None else None

    try:
        if physical_type == T.TYPE_BOOLEAN:
            return bool(raw[0]) if raw else None
        if physical_type == T.TYPE_INT32:
            value = _I32.unpack(raw[:4])[0]
            if converted_name == "DATE" or logical_name == "DATE":
                return (_EPOCH + _dt.timedelta(days=value)).date()
            return value
        if physical_type == T.TYPE_INT64:
            value = _I64.unpack(raw[:8])[0]
            if logical_name == "TIMESTAMP":
                params = logical_type.params if logical_type else {}
                unit = params.get("unit") or "MILLIS"
                aware = bool(params.get("is_adjusted_to_utc", True))
                return _timestamp_from_int(value, unit, aware)
            if converted_name == "TIMESTAMP_MILLIS":
                return _timestamp_from_int(value, "MILLIS", True)
            if converted_name == "TIMESTAMP_MICROS":
                return _timestamp_from_int(value, "MICROS", True)
            # TIME_MILLIS / TIME_MICROS 表示一天内的时刻，不做日期换算
            return value
        if physical_type == T.TYPE_INT96:
            return _decode_int96(raw[:12])
        if physical_type == T.TYPE_FLOAT:
            return _F32.unpack(raw[:4])[0]
        if physical_type == T.TYPE_DOUBLE:
            return _F64.unpack(raw[:8])[0]
        if logical_name == "FLOAT16":
            return _decode_float16(raw)
        if physical_type in (T.TYPE_BYTE_ARRAY, T.TYPE_FIXED_LEN_BYTE_ARRAY):
            text_like = {"UTF8", "JSON", "BSON", "ENUM", "STRING"}
            if logical_name in text_like or converted_name in text_like:
                return raw.decode("utf-8", errors="replace")
            if logical_name == "DECIMAL" or converted_name == "DECIMAL":
                eff_scale = scale or (logical_type.params.get("scale", 0) if logical_type else 0)
                return _decode_decimal(raw, eff_scale)
            if logical_name == "UUID" and len(raw) == 16:
                hexed = raw.hex()
                return f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"
            return raw
    except (struct.error, ValueError, OverflowError):
        return raw.hex()
    return raw


def _timestamp_from_int(value: int, unit: str, aware: bool) -> _dt.datetime | int:
    divisors = {"MILLIS": 1_000, "MICROS": 1_000_000, "NANOS": 1_000_000_000}
    divisor = divisors.get(unit, 1_000)
    try:
        seconds, remainder = divmod(value, divisor)
        micro = remainder * 1_000_000 // divisor
        moment = _EPOCH + _dt.timedelta(seconds=seconds, microseconds=micro)
        return moment if aware else moment.replace(tzinfo=None)
    except (OverflowError, ValueError):
        return value


@dataclass
class ColumnStatistics:
    """单个列块的统计信息。"""

    min_value: Any = None
    max_value: Any = None
    null_count: int | None = None
    distinct_count: int | None = None
    is_min_exact: bool = True
    is_max_exact: bool = True
    has_deprecated_only: bool = False

    @property
    def present(self) -> bool:
        return any(
            value is not None
            for value in (
                self.min_value,
                self.max_value,
                self.null_count,
                self.distinct_count,
            )
        )

    @classmethod
    def from_thrift(
        cls,
        raw: dict[int, Any] | None,
        *,
        physical_type: int,
        converted_type: int | None = None,
        logical_type: LogicalType | None = None,
        type_length: int | None = None,
        scale: int = 0,
    ) -> "ColumnStatistics | None":
        if not raw:
            return None

        decode = lambda payload: decode_value(  # noqa: E731 - 局部闭包提高可读性
            payload,
            physical_type,
            converted_type=converted_type,
            logical_type=logical_type,
            type_length=type_length,
            scale=scale,
        )

        has_new = T.ST_MIN_VALUE in raw or T.ST_MAX_VALUE in raw
        min_raw = raw.get(T.ST_MIN_VALUE, raw.get(T.ST_MIN))
        max_raw = raw.get(T.ST_MAX_VALUE, raw.get(T.ST_MAX))
        return cls(
            min_value=decode(min_raw) if min_raw is not None else None,
            max_value=decode(max_raw) if max_raw is not None else None,
            null_count=raw.get(T.ST_NULL_COUNT),
            distinct_count=raw.get(T.ST_DISTINCT_COUNT),
            is_min_exact=bool(raw.get(T.ST_IS_MIN_VALUE_EXACT, True)),
            is_max_exact=bool(raw.get(T.ST_IS_MAX_VALUE_EXACT, True)),
            has_deprecated_only=not has_new,
        )


# --------------------------------------------------------------------------- #
# 列块 / Row Group / 文件元数据
# --------------------------------------------------------------------------- #
@dataclass
class ColumnChunkInfo:
    """列块（Column Chunk）信息。"""

    path_in_schema: str
    physical_type: int
    codec: int
    encodings: list[str]
    num_values: int
    total_uncompressed_size: int
    total_compressed_size: int
    data_page_offset: int | None = None
    dictionary_page_offset: int | None = None
    index_page_offset: int | None = None
    statistics: ColumnStatistics | None = None
    has_offset_index: bool = False
    has_column_index: bool = False
    has_bloom_filter: bool = False
    encoding_stats: list[dict[str, Any]] = field(default_factory=list)
    key_value_metadata: dict[str, str] = field(default_factory=dict)
    file_path: str | None = None
    file_offset: int | None = None

    @property
    def codec_name(self) -> str:
        return T.CODECS.get(self.codec, f"UNKNOWN({self.codec})")

    @property
    def physical_name(self) -> str:
        return T.PHYSICAL_TYPES.get(self.physical_type, f"UNKNOWN({self.physical_type})")

    @property
    def compression_ratio(self) -> float:
        if self.total_compressed_size <= 0:
            return 0.0
        return self.total_uncompressed_size / self.total_compressed_size

    @property
    def has_dictionary(self) -> bool:
        return bool(T.DICTIONARY_ENCODINGS.intersection(self.encodings))


@dataclass
class SortingColumn:
    """``SortingColumn``：row group 内的排序列声明。"""

    column_index: int
    descending: bool = False
    nulls_first: bool = False

    @classmethod
    def from_thrift(cls, raw: dict[int, Any]) -> "SortingColumn":
        return cls(
            column_index=raw.get(T.SC_COLUMN_IDX, -1),
            descending=bool(raw.get(T.SC_DESCENDING, False)),
            nulls_first=bool(raw.get(T.SC_NULLS_FIRST, False)),
        )


@dataclass
class RowGroupInfo:
    """Row Group 信息。"""

    ordinal: int
    num_rows: int
    total_byte_size: int
    total_compressed_size: int
    columns: list[ColumnChunkInfo]
    file_offset: int | None = None
    sorting_columns: list[SortingColumn] = field(default_factory=list)

    @property
    def compression_ratio(self) -> float:
        if self.total_compressed_size <= 0:
            return 0.0
        return self.total_byte_size / self.total_compressed_size

    @property
    def num_columns(self) -> int:
        return len(self.columns)


@dataclass
class ParquetMetadata:
    """文件级元数据。"""

    version: int | None
    num_rows: int
    num_row_groups: int
    created_by: str | None
    schema_root: SchemaNode
    schema_elements: list[SchemaElement]
    row_groups: list[RowGroupInfo]
    key_value_metadata: dict[str, str]
    file_size: int
    footer_length: int
    encrypted: bool = False

    # ---------------------------------------------------------------- #
    @property
    def leaves(self) -> list[SchemaNode]:
        return list(iter_leaves(self.schema_root))

    @property
    def num_columns(self) -> int:
        return len(self.leaves)

    @property
    def depth(self) -> int:
        return schema_depth(self.schema_root)

    @property
    def total_compressed_size(self) -> int:
        return sum(rg.total_compressed_size or _rg_bytes(rg) for rg in self.row_groups)

    @property
    def total_uncompressed_size(self) -> int:
        return sum(rg.total_byte_size for rg in self.row_groups)

    @property
    def overall_compression_ratio(self) -> float:
        compressed = self.total_compressed_size
        if compressed <= 0:
            return 0.0
        return self.total_uncompressed_size / compressed

    @property
    def avg_row_group_rows(self) -> float:
        if not self.row_groups:
            return 0.0
        return self.num_rows / len(self.row_groups)

    def schema_fingerprint(self) -> str:
        """计算 schema 指纹（列名 + 类型 + 可空性），用于跨文件 schema 漂移检测。"""
        import hashlib

        payload = []
        for leaf in self.leaves:
            payload.append(
                "|".join(
                    (
                        leaf.path,
                        leaf.element.physical_name,
                        leaf.element.repetition_name,
                        leaf.element.annotate(),
                    )
                )
            )
        return hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()[:16]

    def to_dict(self, *, include_statistics: bool = True) -> dict[str, Any]:
        """序列化为可 JSON 化的字典（供 ``dump`` 命令与 API 使用）。"""
        return {
            "version": self.version,
            "num_rows": self.num_rows,
            "num_row_groups": self.num_row_groups,
            "num_columns": self.num_columns,
            "schema_depth": self.depth,
            "created_by": self.created_by,
            "schema_fingerprint": self.schema_fingerprint(),
            "file_size": self.file_size,
            "footer_length": self.footer_length,
            "encrypted": self.encrypted,
            "total_uncompressed_size": self.total_uncompressed_size,
            "total_compressed_size": self.total_compressed_size,
            "compression_ratio": round(self.overall_compression_ratio, 4),
            "key_value_metadata": self.key_value_metadata,
            "schema": _node_to_dict(self.schema_root),
            "row_groups": [_rowgroup_to_dict(rg, include_statistics) for rg in self.row_groups],
        }


def _rg_bytes(rg: RowGroupInfo) -> int:
    return sum(col.total_compressed_size for col in rg.columns)


def _node_to_dict(node: SchemaNode) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": node.name,
        "path": node.path or node.name,
        "depth": node.depth,
        "repetition": node.element.repetition_name,
        "physical_type": node.element.physical_name,
        "annotated_type": node.element.annotate(),
        "converted_type": node.element.converted_name,
        "logical_type": str(node.element.logical_type) if node.element.logical_type else None,
        "max_definition_level": node.max_definition_level,
        "max_repetition_level": node.max_repetition_level,
    }
    if node.is_leaf:
        item["leaf_index"] = node.leaf_index
        item["type_length"] = node.element.type_length
    else:
        item["num_children"] = len(node.children)
        item["children"] = [_node_to_dict(child) for child in node.children]
    return item


def _rowgroup_to_dict(rg: RowGroupInfo, include_statistics: bool) -> dict[str, Any]:
    return {
        "ordinal": rg.ordinal,
        "num_rows": rg.num_rows,
        "total_byte_size": rg.total_byte_size,
        "total_compressed_size": rg.total_compressed_size,
        "compression_ratio": round(rg.compression_ratio, 4),
        "file_offset": rg.file_offset,
        "sorting_columns": [
            {
                "column_index": sc.column_index,
                "descending": sc.descending,
                "nulls_first": sc.nulls_first,
            }
            for sc in rg.sorting_columns
        ],
        "columns": [_column_to_dict(col, include_statistics) for col in rg.columns],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"0x{bytes(value).hex()}"[:66]
    return value


def _column_to_dict(col: ColumnChunkInfo, include_statistics: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": col.path_in_schema,
        "physical_type": col.physical_name,
        "codec": col.codec_name,
        "encodings": col.encodings,
        "num_values": col.num_values,
        "total_uncompressed_size": col.total_uncompressed_size,
        "total_compressed_size": col.total_compressed_size,
        "compression_ratio": round(col.compression_ratio, 4),
        "data_page_offset": col.data_page_offset,
        "dictionary_page_offset": col.dictionary_page_offset,
        "has_dictionary": col.has_dictionary,
        "has_offset_index": col.has_offset_index,
        "has_column_index": col.has_column_index,
        "has_bloom_filter": col.has_bloom_filter,
    }
    if include_statistics and col.statistics is not None:
        stats = col.statistics
        item["statistics"] = {
            "min": _jsonable(stats.min_value),
            "max": _jsonable(stats.max_value),
            "null_count": stats.null_count,
            "distinct_count": stats.distinct_count,
            "is_min_exact": stats.is_min_exact,
            "is_max_exact": stats.is_max_exact,
        }
    else:
        item["statistics"] = None
    return item


__all__ = [
    "LogicalType",
    "SchemaElement",
    "SchemaNode",
    "ColumnStatistics",
    "ColumnChunkInfo",
    "SortingColumn",
    "RowGroupInfo",
    "ParquetMetadata",
    "build_schema_tree",
    "iter_leaves",
    "schema_depth",
    "decode_value",
]

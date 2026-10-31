"""Parquet 文件读取器：定位 footer、解码元数据、构建对象模型。

典型用法::

    from parquetscope import ParquetFile

    with ParquetFile("data.parquet") as pf:
        meta = pf.metadata
        print(meta.num_rows, meta.num_columns, meta.overall_compression_ratio)

也可以直接读取字节::

    meta = read_metadata_bytes(payload, name="memory.parquet")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import types as T
from .errors import (
    EncryptedFileError,
    NotParquetError,
    ParquetScopeError,
    ThriftDecodeError,
    TruncatedFileError,
)
from .metadata import (
    ColumnChunkInfo,
    ColumnStatistics,
    ParquetMetadata,
    RowGroupInfo,
    SchemaElement,
    SortingColumn,
    build_schema_tree,
    iter_leaves,
)
from .thrift import CompactProtocolReader

_PARQUET_SUFFIXES = (".parquet", ".parq", ".pq")


class ParquetFile:
    """单个 Parquet 文件的句柄，支持上下文管理器。"""

    def __init__(self, source: str | os.PathLike[str] | bytes, *, name: str | None = None) -> None:
        if isinstance(source, (bytes, bytearray, memoryview)):
            self._data = bytes(source)
            self.path = name or "<memory>"
            self._owned = True
        else:
            self.path = str(source)
            self._data = None  # type: ignore[assignment]
            self._owned = False
        self._metadata: ParquetMetadata | None = None

    # ------------------------------------------------------------------ #
    def __enter__(self) -> "ParquetFile":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._data = None  # type: ignore[assignment]
        self._metadata = None

    # ------------------------------------------------------------------ #
    @property
    def _buffer(self) -> bytes:
        if self._data is None:
            try:
                with open(self.path, "rb") as handle:
                    self._data = handle.read()
            except FileNotFoundError as exc:
                raise ParquetScopeError("文件不存在", path=self.path) from exc
            except IsADirectoryError as exc:
                raise ParquetScopeError("目标是目录而非文件", path=self.path) from exc
            except OSError as exc:
                raise ParquetScopeError(f"读取失败: {exc}", path=self.path) from exc
        return self._data

    @property
    def metadata(self) -> ParquetMetadata:
        if self._metadata is None:
            self._metadata = self._parse()
        return self._metadata

    # ------------------------------------------------------------------ #
    def _parse(self) -> ParquetMetadata:
        data = self._buffer
        size = len(data)

        if size < 12:
            raise TruncatedFileError(
                f"文件过小（{size} 字节），不足以容纳 Parquet 魔数与 footer", path=self.path
            )
        if data[:4] != T.MAGIC:
            raise NotParquetError("文件头魔数不是 PAR1", path=self.path)

        tail_magic = data[-4:]
        if tail_magic == T.MAGIC_ENCRYPTED_FOOTER:
            raise EncryptedFileError(
                "检测到加密 footer（PARE），ParquetScope 不解析加密元数据", path=self.path
            )
        if tail_magic != T.MAGIC:
            raise NotParquetError("文件尾魔数不是 PAR1（文件可能损坏）", path=self.path)

        footer_length = int.from_bytes(data[-8:-4], "little", signed=False)
        if footer_length <= 0 or footer_length + 12 > size:
            raise TruncatedFileError(
                f"footer 长度非法：{footer_length} 字节（文件大小 {size} 字节）", path=self.path
            )

        footer_start = size - 8 - footer_length
        reader = CompactProtocolReader(data, pos=footer_start, limit=size - 8)
        try:
            raw = reader.read_struct()
        except ThriftDecodeError as exc:
            raise ThriftDecodeError(f"footer 解码失败: {exc}", path=self.path) from exc

        return _build_metadata(raw, file_size=size, footer_length=footer_length, path=self.path)


# --------------------------------------------------------------------------- #
# 元数据构建
# --------------------------------------------------------------------------- #
def _text(value: Any) -> str:
    """Thrift 不区分 string 与 binary，这里把已知的文本字段统一转为 str。"""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value) if value is not None else ""


def _build_metadata(
    raw: dict[int, Any],
    *,
    file_size: int,
    footer_length: int,
    path: str,
) -> ParquetMetadata:
    schema_raw = raw.get(T.FMD_SCHEMA) or []
    elements = [
        SchemaElement.from_thrift(item) if isinstance(item, dict) else item for item in schema_raw
    ]
    if not elements:
        raise ParquetScopeError("footer 中缺少 schema 定义", path=path)
    root = build_schema_tree(elements)
    leaves = list(iter_leaves(root))
    leaf_by_path = {leaf.path: leaf for leaf in leaves}

    row_groups: list[RowGroupInfo] = []
    for index, rg_raw in enumerate(raw.get(T.FMD_ROW_GROUPS) or []):
        chunks: list[ColumnChunkInfo] = []
        for cc_raw in rg_raw.get(T.RG_COLUMNS) or []:
            cmd = cc_raw.get(T.CC_META_DATA) or {}
            if cc_raw.get(T.CC_ENCRYPTED_COLUMN_METADATA):
                # 列级加密：元数据不可读，仅保留占位信息
                chunks.append(
                    ColumnChunkInfo(
                        path_in_schema=".",
                        physical_type=-1,
                        codec=0,
                        encodings=[],
                        num_values=0,
                        total_uncompressed_size=0,
                        total_compressed_size=0,
                    )
                )
                continue
            path_in_schema = ".".join(_text(part) for part in cmd.get(T.CMD_PATH_IN_SCHEMA) or [])
            leaf = leaf_by_path.get(path_in_schema)
            physical_type = cmd.get(T.CMD_TYPE)
            stat_raw = cmd.get(T.CMD_STATISTICS)
            statistics = None
            if stat_raw and leaf is not None:
                statistics = ColumnStatistics.from_thrift(
                    stat_raw,
                    physical_type=physical_type,
                    converted_type=leaf.element.converted_type,
                    logical_type=leaf.element.logical_type,
                    type_length=leaf.element.type_length,
                    scale=leaf.element.scale or 0,
                )
            encodings = [
                T.ENCODINGS.get(code, f"UNKNOWN({code})") for code in cmd.get(T.CMD_ENCODINGS) or []
            ]
            encoding_stats = []
            for entry in cmd.get(T.CMD_ENCODING_STATS) or []:
                if not isinstance(entry, dict):
                    continue
                encoding_stats.append(
                    {
                        "page_type": T.PAGE_TYPES.get(entry.get(1), "UNKNOWN"),
                        "encoding": T.ENCODINGS.get(entry.get(2), f"UNKNOWN({entry.get(2)})"),
                        "count": entry.get(3, 0),
                    }
                )
            chunks.append(
                ColumnChunkInfo(
                    path_in_schema=path_in_schema,
                    physical_type=physical_type if physical_type is not None else -1,
                    codec=cmd.get(T.CMD_CODEC, 0),
                    encodings=encodings,
                    num_values=cmd.get(T.CMD_NUM_VALUES, 0),
                    total_uncompressed_size=cmd.get(T.CMD_TOTAL_UNCOMPRESSED_SIZE, 0),
                    total_compressed_size=cmd.get(T.CMD_TOTAL_COMPRESSED_SIZE, 0),
                    data_page_offset=cmd.get(T.CMD_DATA_PAGE_OFFSET),
                    dictionary_page_offset=cmd.get(T.CMD_DICTIONARY_PAGE_OFFSET),
                    index_page_offset=cmd.get(T.CMD_INDEX_PAGE_OFFSET),
                    statistics=statistics,
                    has_offset_index=bool(cc_raw.get(T.CC_OFFSET_INDEX_OFFSET)),
                    has_column_index=bool(cc_raw.get(T.CC_COLUMN_INDEX_OFFSET)),
                    has_bloom_filter=bool(cmd.get(T.CMD_BLOOM_FILTER_OFFSET)),
                    encoding_stats=encoding_stats,
                    key_value_metadata=_kv_to_dict(cmd.get(T.CMD_KEY_VALUE_METADATA)),
                    file_path=_text(cc_raw[T.CC_FILE_PATH]) if cc_raw.get(T.CC_FILE_PATH) else None,
                    file_offset=cc_raw.get(T.CC_FILE_OFFSET),
                )
            )
        row_groups.append(
            RowGroupInfo(
                ordinal=rg_raw.get(T.RG_ORDINAL, index),
                num_rows=rg_raw.get(T.RG_NUM_ROWS, 0),
                total_byte_size=rg_raw.get(T.RG_TOTAL_BYTE_SIZE, 0)
                or sum(c.total_uncompressed_size for c in chunks),
                total_compressed_size=rg_raw.get(T.RG_TOTAL_COMPRESSED_SIZE, 0)
                or sum(c.total_compressed_size for c in chunks),
                columns=chunks,
                file_offset=rg_raw.get(T.RG_FILE_OFFSET),
                sorting_columns=[
                    SortingColumn.from_thrift(sc)
                    for sc in rg_raw.get(T.RG_SORTING_COLUMNS) or []
                    if isinstance(sc, dict)
                ],
            )
        )

    return ParquetMetadata(
        version=raw.get(T.FMD_VERSION),
        num_rows=raw.get(T.FMD_NUM_ROWS, 0),
        num_row_groups=len(row_groups),
        created_by=_text(raw[T.FMD_CREATED_BY]) if raw.get(T.FMD_CREATED_BY) is not None else None,
        schema_root=root,
        schema_elements=elements,
        row_groups=row_groups,
        key_value_metadata=_kv_to_dict(raw.get(T.FMD_KEY_VALUE_METADATA)),
        file_size=file_size,
        footer_length=footer_length,
        encrypted=bool(raw.get(T.FMD_ENCRYPTION_ALGORITHM)),
    )


def _kv_to_dict(raw: Any) -> dict[str, str]:
    if not raw:
        return {}
    result: dict[str, str] = {}
    for item in raw:
        if isinstance(item, dict):
            key = item.get(T.KV_KEY)
            value = item.get(T.KV_VALUE)
            if key is not None:
                result[_text(key)] = _text(value)
    return result


# --------------------------------------------------------------------------- #
# 便捷函数
# --------------------------------------------------------------------------- #
def read_metadata(source: str | os.PathLike[str] | bytes, *, name: str | None = None) -> ParquetMetadata:
    """一步到位读取元数据（推荐在只需要元数据的场景使用）。"""
    with ParquetFile(source, name=name) as pf:
        return pf.metadata


def read_metadata_bytes(data: bytes, *, name: str = "<memory>") -> ParquetMetadata:
    """从字节内容读取元数据（便于测试与网络场景）。"""
    return read_metadata(data, name=name)


def is_parquet_candidate(path: str | os.PathLike[str]) -> bool:
    """按扩展名快速判断是否为候选 Parquet 文件。"""
    return str(path).lower().endswith(_PARQUET_SUFFIXES)


def iter_parquet_files(
    targets: Iterable[str | os.PathLike[str]],
    *,
    recursive: bool = True,
) -> Iterator[Path]:
    """把文件/目录/通配符展开为 Parquet 文件路径序列（按路径排序）。"""
    seen: set[Path] = set()
    for target in targets:
        text = str(target)
        if any(ch in text for ch in ("*", "?", "[")):
            from glob import glob

            for match in sorted(glob(text, recursive=recursive)):
                path = Path(match)
                if path.is_file() and is_parquet_candidate(path) and path not in seen:
                    seen.add(path)
                    yield path
            continue
        path = Path(text)
        if path.is_dir():
            walker = path.rglob("*") if recursive else path.glob("*")
            for child in sorted(walker):
                if child.is_file() and is_parquet_candidate(child) and child not in seen:
                    seen.add(child)
                    yield child
        elif path.is_file():
            resolved = path
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


__all__ = [
    "ParquetFile",
    "read_metadata",
    "read_metadata_bytes",
    "iter_parquet_files",
    "is_parquet_candidate",
]

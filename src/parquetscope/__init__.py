"""ParquetScope — 零依赖、离线优先的 Parquet 列式文件体检与审计引擎。

核心能力
--------
* 自研 Thrift Compact Protocol 解码器，纯标准库解析 Parquet footer
* 完整的 schema 树、row group 布局、列块统计信息还原
* 22 条可解释的体检规则，输出健康评分与 CI 门禁退出码
* 目录级 schema 漂移检测与小文件问题诊断
* 库 + CLI 双形态，支持 text / markdown / json / csv 四种输出

快速上手::

    from parquetscope import read_metadata, audit

    meta = read_metadata("data.parquet")
    report = audit(meta, path="data.parquet")
    print(report.score, report.severity_counts)

命令行::

    parquetscope info data.parquet
    parquetscope audit "./warehouse/**/*.parquet" --fail-on error
"""

from __future__ import annotations

from .analyzer import (
    ColumnProfile,
    Finding,
    AuditReport,
    audit,
    build_column_profiles,
    list_rules,
)
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
    SchemaNode,
)
from .reader import (
    ParquetFile,
    iter_parquet_files,
    read_metadata,
    read_metadata_bytes,
)
from .thrift import CompactProtocolReader, decode_compact

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # 高层 API
    "read_metadata",
    "read_metadata_bytes",
    "ParquetFile",
    "iter_parquet_files",
    "audit",
    "build_column_profiles",
    "list_rules",
    # 模型
    "ParquetMetadata",
    "RowGroupInfo",
    "ColumnChunkInfo",
    "ColumnStatistics",
    "SchemaNode",
    "ColumnProfile",
    "Finding",
    "AuditReport",
    # 协议层
    "CompactProtocolReader",
    "decode_compact",
    # 异常
    "ParquetScopeError",
    "NotParquetError",
    "TruncatedFileError",
    "ThriftDecodeError",
    "EncryptedFileError",
]

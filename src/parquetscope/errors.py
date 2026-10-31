"""异常类型定义。

所有异常均继承自 :class:`ParquetScopeError`，方便调用方统一捕获。
"""

from __future__ import annotations


class ParquetScopeError(Exception):
    """ParquetScope 的基础异常类型。"""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        if path:
            message = f"{message} (文件: {path})"
        super().__init__(message)


class NotParquetError(ParquetScopeError):
    """目标文件不是合法的 Parquet 文件（魔数校验失败）。"""


class TruncatedFileError(ParquetScopeError):
    """文件被截断或 footer 长度非法。"""


class ThriftDecodeError(ParquetScopeError):
    """Thrift Compact Protocol 解码失败。"""


class EncryptedFileError(ParquetScopeError):
    """文件使用了 Parquet 列加密特性，元数据无法直接解析。"""


class UnsupportedFeatureError(ParquetScopeError):
    """遇到了当前版本尚未支持的 Parquet 特性。"""


__all__ = [
    "ParquetScopeError",
    "NotParquetError",
    "TruncatedFileError",
    "ThriftDecodeError",
    "EncryptedFileError",
    "UnsupportedFeatureError",
]

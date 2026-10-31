"""自研 Thrift Compact Protocol 解码器（纯标准库，零第三方依赖）。

Parquet 的 footer 元数据采用 **Thrift Compact Protocol** 序列化。为了做到真正的
零依赖，这里从协议字节层完整实现了该编码的读取逻辑，而不是引入 ``thrift`` 或
``fastparquet`` 之类的第三方库。

协议要点
--------
字段头（field header）编码方式::

    byte 0:  [ delta_field_id (4 bits) | compact_type (4 bits) ]
    delta_field_id == 0  ->  紧随一个 zigzag varint 表示真实 field id
    delta_field_id != 0  ->  field_id = last_field_id + delta_field_id
    compact_type == 0    ->  STOP，结构体结束

类型编号::

    1  BOOLEAN_TRUE    2  BOOLEAN_FALSE   3  BYTE      4  I16
    5  I32             6  I64             7  DOUBLE    8  BINARY
    9  LIST           10  SET            11  MAP      12  STRUCT

解码结果使用 ``dict[int, Any]`` 表达结构体（键为 field id），这样既保留了
Parquet 格式的向前/向后兼容语义，也让上层可以按字段号精确取值。
"""

from __future__ import annotations

import struct
from typing import Any

from .errors import ThriftDecodeError

# --------------------------------------------------------------------------- #
# 类型常量
# --------------------------------------------------------------------------- #
T_STOP = 0x00
T_BOOLEAN_TRUE = 0x01
T_BOOLEAN_FALSE = 0x02
T_BYTE = 0x03
T_I16 = 0x04
T_I32 = 0x05
T_I64 = 0x06
T_DOUBLE = 0x07
T_BINARY = 0x08
T_LIST = 0x09
T_SET = 0x0A
T_MAP = 0x0B
T_STRUCT = 0x0C

_DOUBLE_STRUCT = struct.Struct("<d")
_UINT32_STRUCT = struct.Struct("<I")


class CompactProtocolReader:
    """Thrift Compact Protocol 的流式读取器。"""

    __slots__ = ("buf", "pos", "limit")

    def __init__(self, buf: bytes | memoryview, pos: int = 0, limit: int | None = None) -> None:
        self.buf = memoryview(buf) if not isinstance(buf, memoryview) else buf
        self.pos = pos
        self.limit = len(self.buf) if limit is None else limit

    # ------------------------------------------------------------------ #
    # 基础原语
    # ------------------------------------------------------------------ #
    def _need(self, n: int) -> None:
        if self.pos + n > self.limit:
            raise ThriftDecodeError(
                f"缓冲区不足：需要 {n} 字节，仅剩 {max(0, self.limit - self.pos)} 字节"
            )

    def read_byte(self) -> int:
        self._need(1)
        value = self.buf[self.pos]
        self.pos += 1
        return value

    def read_bytes(self, n: int) -> bytes:
        self._need(n)
        value = bytes(self.buf[self.pos : self.pos + n])
        self.pos += n
        return value

    def read_varint(self) -> int:
        """读取 unsigned LEB128 变长整数。"""
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
            if shift > 63:
                raise ThriftDecodeError("varint 过长（超过 10 字节）")

    def read_zigzag(self) -> int:
        """读取 zigzag 编码的有符号变长整数。"""
        n = self.read_varint()
        return (n >> 1) ^ -(n & 1)

    def read_double(self) -> float:
        return _DOUBLE_STRUCT.unpack(self.read_bytes(8))[0]

    def read_binary(self) -> bytes:
        return self.read_bytes(self.read_varint())

    def read_string(self) -> str:
        return self.read_binary().decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ #
    # 复合类型
    # ------------------------------------------------------------------ #
    def read_struct(self) -> dict[int, Any]:
        """读取一个 STRUCT，返回 ``{field_id: value}``。"""
        result: dict[int, Any] = {}
        last_fid = 0
        while True:
            header = self.read_byte()
            compact_type = header & 0x0F
            if compact_type == T_STOP:
                return result
            delta = (header & 0xF0) >> 4
            if delta == 0:
                fid = self.read_zigzag()
            else:
                fid = last_fid + delta
            last_fid = fid
            result[fid] = self.read_value(compact_type)

    def read_collection_header(self) -> tuple[int, int]:
        """读取 LIST/SET/MAP 的头信息，返回 ``(size, element_type)``。"""
        head = self.read_byte()
        size = (head & 0xF0) >> 4
        elem_type = head & 0x0F
        if size == 15:
            size = self.read_varint()
        return size, elem_type

    def read_list(self) -> list[Any]:
        """读取 LIST/SET：先读集合头（size + 元素类型），再逐项读取。"""
        size, elem_type = self.read_collection_header()
        if elem_type == 0 or size == 0:
            return []
        return [self.read_value(elem_type) for _ in range(size)]

    def read_map(self) -> dict[Any, Any]:
        size = self.read_varint()
        if size == 0:
            return {}
        kv = self.read_byte()
        if kv == 0:
            return {}
        key_type = (kv & 0xF0) >> 4
        val_type = kv & 0x0F
        return {self.read_value(key_type): self.read_value(val_type) for _ in range(size)}

    def read_value(self, compact_type: int) -> Any:
        if compact_type == T_BOOLEAN_TRUE:
            return True
        if compact_type == T_BOOLEAN_FALSE:
            return False
        if compact_type == T_BYTE:
            raw = self.read_byte()
            return raw - 256 if raw > 127 else raw
        if compact_type in (T_I16, T_I32, T_I64):
            return self.read_zigzag()
        if compact_type == T_DOUBLE:
            return self.read_double()
        if compact_type == T_BINARY:
            return self.read_binary()
        if compact_type == T_LIST:
            return self.read_list()
        if compact_type == T_SET:
            return self.read_list()
        if compact_type == T_MAP:
            return self.read_map()
        if compact_type == T_STRUCT:
            return self.read_struct()
        raise ThriftDecodeError(f"未知的 Thrift compact 类型: {compact_type}")

    # ------------------------------------------------------------------ #
    # 便捷入口
    # ------------------------------------------------------------------ #
    def remaining(self) -> int:
        return self.limit - self.pos


def decode_compact(data: bytes | memoryview, pos: int = 0, limit: int | None = None) -> dict[int, Any]:
    """把一段 Thrift Compact 字节流解码为结构体字典。"""
    reader = CompactProtocolReader(data, pos=pos, limit=limit)
    return reader.read_struct()


def zigzag_decode(n: int) -> int:
    """zigzag 解码（供测试与外部复用）。"""
    return (n >> 1) ^ -(n & 1)


def varint_size(n: int) -> int:
    """计算 unsigned varint 编码 ``n`` 所需的字节数。"""
    size = 0
    while True:
        size += 1
        n >>= 7
        if n == 0:
            return size


__all__ = [
    "CompactProtocolReader",
    "decode_compact",
    "zigzag_decode",
    "varint_size",
]

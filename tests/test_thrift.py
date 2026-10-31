"""Thrift Compact Protocol 解码器单元测试（纯字节级，不依赖任何样本）。"""

from __future__ import annotations

import struct

import pytest

from parquetscope.errors import ThriftDecodeError
from parquetscope.thrift import (
    CompactProtocolReader,
    decode_compact,
    varint_size,
    zigzag_decode,
)

from .conftest import _encode_varint, encode_zigzag


# --------------------------------------------------------------------------- #
# 原语
# --------------------------------------------------------------------------- #
def test_varint_single_and_multi_byte():
    for value in (0, 1, 63, 64, 127, 128, 300, 16383, 16384, 2**28):
        payload = _encode_varint(value)
        reader = CompactProtocolReader(payload)
        assert reader.read_varint() == value
        assert varint_size(value) == len(payload)


def test_zigzag_roundtrip():
    for value in (0, -1, 1, -2, 2, 63, -64, 1000, -1000, 2**31 - 1, -(2**31)):
        payload = encode_zigzag(value)
        reader = CompactProtocolReader(payload)
        assert reader.read_zigzag() == value
        assert zigzag_decode(int.from_bytes(payload, "little")) != None  # noqa: E711


def test_zigzag_decode_known_values():
    assert zigzag_decode(0) == 0
    assert zigzag_decode(1) == -1
    assert zigzag_decode(2) == 1
    assert zigzag_decode(3) == -2
    assert zigzag_decode(4) == 2


# --------------------------------------------------------------------------- #
# 字段头与基础类型
# --------------------------------------------------------------------------- #
def test_struct_with_i32_and_stop():
    payload = bytes([0x15]) + encode_zigzag(42) + b"\x00"
    assert decode_compact(payload) == {1: 42}


def test_field_id_delta_encoding():
    # field 1 = 10（delta=1），field 3 = 20（delta=2）
    payload = bytes([0x15]) + encode_zigzag(10) + bytes([0x25]) + encode_zigzag(20) + b"\x00"
    assert decode_compact(payload) == {1: 10, 3: 20}


def test_boolean_true_and_false():
    payload = bytes([0x11, 0x12, 0x00])  # field1=True, field2=False（delta=1）
    assert decode_compact(payload) == {1: True, 2: False}


def test_binary_and_string():
    payload = bytes([0x18]) + _encode_varint(3) + b"abc" + b"\x00"
    assert decode_compact(payload) == {1: b"abc"}


def test_byte_and_double():
    payload = bytes([0x13, 0xFF, 0x00])
    assert decode_compact(payload) == {1: -1}

    payload = bytes([0x17]) + struct.pack("<d", 3.5) + b"\x00"
    assert decode_compact(payload) == {1: 3.5}


def test_i16_i32_i64_all_use_zigzag():
    payload = (
        bytes([0x14]) + encode_zigzag(-7)  # i16
        + bytes([0x15]) + encode_zigzag(100000)  # i32, field 2
        + bytes([0x16]) + encode_zigzag(-(2**40))  # i64, field 3
        + b"\x00"
    )
    assert decode_compact(payload) == {1: -7, 2: 100000, 3: -(2**40)}


# --------------------------------------------------------------------------- #
# 集合类型
# --------------------------------------------------------------------------- #
def test_list_of_i32():
    payload = bytes([0x19, 0x25]) + encode_zigzag(1) + encode_zigzag(2) + b"\x00"
    assert decode_compact(payload) == {1: [1, 2]}


def test_list_of_strings():
    # 集合元素为裸值，不含字段头
    body = _encode_varint(2) + b"hi" + _encode_varint(3) + b"abc"
    payload = bytes([0x19, 0x28]) + body + b"\x00"
    assert decode_compact(payload) == {1: [b"hi", b"abc"]}


def test_list_with_long_size():
    values = list(range(20))
    body = b"".join(encode_zigzag(v) for v in values)
    payload = bytes([0x19, 0xF5]) + _encode_varint(20) + body + b"\x00"
    assert decode_compact(payload) == {1: values}


def test_empty_list():
    payload = bytes([0x19, 0x00, 0x00])
    assert decode_compact(payload) == {1: []}


def test_map():
    # map<i32, binary>，1 个键值对
    payload = (
        bytes([0x1B])  # field1, MAP
        + _encode_varint(1)
        + bytes([0x58])  # key=i32(5), value=binary(8)
        + encode_zigzag(7)
        + _encode_varint(2)
        + b"ok"
        + b"\x00"
    )
    assert decode_compact(payload) == {1: {7: b"ok"}}


def test_empty_map():
    payload = bytes([0x1B]) + _encode_varint(0) + b"\x00"
    assert decode_compact(payload) == {1: {}}


def test_nested_struct():
    inner = bytes([0x15]) + encode_zigzag(5) + b"\x00"
    payload = bytes([0x1C]) + inner + b"\x00"
    assert decode_compact(payload) == {1: {1: 5}}


def test_list_of_structs():
    inner = bytes([0x15]) + encode_zigzag(9) + b"\x00"
    payload = bytes([0x19, 0x2C]) + inner + inner + b"\x00"
    assert decode_compact(payload) == {1: [{1: 9}, {1: 9}]}


# --------------------------------------------------------------------------- #
# 错误处理
# --------------------------------------------------------------------------- #
def test_buffer_underflow_raises():
    with pytest.raises(ThriftDecodeError):
        decode_compact(bytes([0x15, 0x80]))  # varint 未终止


def test_unknown_type_raises():
    with pytest.raises(ThriftDecodeError):
        decode_compact(bytes([0x1F, 0x00]))  # type 15 未定义


def test_remaining_bytes_reported():
    reader = CompactProtocolReader(b"\x00\x00\x00")
    reader.read_byte()
    assert reader.remaining() == 2

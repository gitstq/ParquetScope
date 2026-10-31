"""pytest 公共夹具。

测试全部基于仓库内已提交的样本文件（``tests/data/*.parquet``），
运行时不需要 pyarrow 或任何第三方依赖。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DATA_DIR = Path(__file__).resolve().parent / "data"


def sample(name: str) -> Path:
    """返回样本文件路径；文件不存在时跳过用例。"""
    path = DATA_DIR / name
    if not path.exists():
        pytest.skip(f"缺少测试样本 {name}，请先运行 scripts/generate_fixtures.py")
    return path


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def healthy_path() -> Path:
    return sample("healthy.parquet")


@pytest.fixture(scope="session")
def types_path() -> Path:
    return sample("types.parquet")


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_zigzag(value: int) -> bytes:
    """zigzag + varint 编码（测试内辅助函数，用于构造 Thrift 字节）。"""
    return _encode_varint((value << 1) ^ (value >> 63) if value >= 0 else ((value << 1) ^ ~0))


@pytest.fixture(scope="session")
def thrift_encoder() -> dict:
    return {"varint": _encode_varint, "zigzag": encode_zigzag}

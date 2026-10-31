#!/usr/bin/env python3
"""生成测试用的 Parquet 样本文件。

注意：本脚本 **仅用于生成测试夹具**，需要本机安装 pyarrow；
ParquetScope 自身运行时零依赖，不需要 pyarrow。

用法::

    python scripts/generate_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "data"
RNG = np.random.default_rng(20261031)


def _write(table: pa.Table, name: str, **kwargs) -> Path:
    path = OUT_DIR / name
    pq.write_table(table, path, **kwargs)
    print(f"  {name:<28} {path.stat().st_size:>10,} bytes  rows={table.num_rows}")
    return path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("生成测试样本 ->", OUT_DIR)

    # 1) 健康文件：单 row group、zstd 压缩、完整统计
    rows = 50_000
    healthy = pa.table(
        {
            "event_id": pa.array(np.arange(rows, dtype=np.int64)),
            "user_id": pa.array(RNG.integers(0, 50_000, rows, dtype=np.int64)),
            "event_type": pa.array(RNG.choice(["click", "view", "purchase", "share"], rows)),
            "country": pa.array(RNG.choice(["CN", "US", "JP", "DE", "BR"], rows)),
            "amount": pa.array(np.round(RNG.random(rows) * 1000, 4)),
            "is_active": pa.array(RNG.random(rows) > 0.3),
            "event_time": pa.array(
                np.array("2026-01-01T00:00:00", dtype="datetime64[us]")
                + np.arange(rows).astype("timedelta64[us]")
            ),
        }
    )
    _write(healthy, "healthy.parquet", compression="zstd", row_group_size=rows, version="2.6")

    # 2) 小 row group：5000 行一个 row group，触发 PS003/PS004
    _write(healthy, "small_rowgroups.parquet", compression="snappy", row_group_size=5_000, version="2.6")

    # 3) 未压缩：触发 PS201
    _write(healthy, "uncompressed.parquet", compression="none", row_group_size=rows, version="2.6")

    # 4) 关闭统计信息：触发 PS300
    _write(healthy, "no_statistics.parquet", compression="snappy", write_statistics=False, version="2.6")

    # 5) 嵌套 schema：struct + list + map，触发 PS101
    nested = pa.table(
        {
            "id": pa.array(np.arange(10_000, dtype=np.int64)),
            "payload": pa.array(
                [
                    {
                        "level1": {
                            "level2": {
                                "level3": {"level4": {"value": float(i), "tag": f"t{i}"}}
                            }
                        }
                    }
                    for i in range(10_000)
                ]
            ),
            "tags": pa.array([[f"tag{i % 7}", "common"] for i in range(10_000)]),
        }
    )
    _write(nested, "nested.parquet", compression="zstd", version="2.6")

    # 6) 超宽表：220 列，触发 PS100
    wide_cols = {f"col_{i:03d}": pa.array(RNG.integers(0, 1000, 2_000, dtype=np.int32)) for i in range(220)}
    _write(pa.table(wide_cols), "wide.parquet", compression="snappy", version="2.6")

    # 7) 多种物理/逻辑类型：decimal、date、uuid 风格字符串、float16 等
    types_table = pa.table(
        {
            "int32_col": pa.array(RNG.integers(-2**31, 2**31 - 1, 5_000, dtype=np.int32)),
            "int64_col": pa.array(RNG.integers(0, 10**12, 5_000, dtype=np.int64)),
            "float_col": pa.array(RNG.random(5_000, dtype=np.float32)),
            "double_col": pa.array(RNG.random(5_000)),
            "bool_col": pa.array(RNG.random(5_000) > 0.5),
            "string_col": pa.array([f"row-{i}-value" for i in range(5_000)]),
            "date_col": pa.array(np.array("2026-01-01", dtype="datetime64[D]") + np.arange(5_000).astype("timedelta64[D]")),
            "ts_ms": pa.array(np.array("2026-05-01", dtype="datetime64[ms]") + np.arange(5_000).astype("timedelta64[ms]")),
            "ts_us": pa.array(np.array("2026-05-01", dtype="datetime64[us]") + np.arange(5_000).astype("timedelta64[us]")),
            "decimal_col": pa.array(
                [__import__("decimal").Decimal(f"{i}.{(i % 100):02d}") for i in range(5_000)],
                type=pa.decimal128(12, 2),
            ),
            "nullable_col": pa.array([None if i % 3 == 0 else i for i in range(5_000)], type=pa.int64()),
        }
    )
    _write(types_table, "types.parquet", compression="zstd", version="2.6")

    # 8) INT96 时间戳（已废弃类型），触发 PS102
    int96 = pa.table(
        {
            "legacy_ts": pa.array(
                np.array("2026-07-01T00:00:00", dtype="datetime64[ns]")
                + np.arange(5_000).astype("timedelta64[ns]")
            ),
            "value": pa.array(RNG.integers(0, 100, 5_000, dtype=np.int32)),
        }
    )
    try:
        _write(
            int96,
            "int96.parquet",
            compression="snappy",
            version="1.0",
            use_deprecated_int96_timestamps=True,
            coerce_timestamps=None,
        )
    except Exception as exc:  # pragma: no cover - 取决于 pyarrow 版本
        print(f"  跳过 int96.parquet（{exc}）")

    # 9) 排序文件：按 user_id 排序，用于有序性检测
    sorted_table = healthy.sort_by([("user_id", "ascending")])
    _write(sorted_table, "sorted.parquet", compression="zstd", row_group_size=25_000, version="2.6")

    # 10) 平均长度偏大的字符串列（随机内容，避免被字典编码压缩），触发 PS402
    alphabet = np.array(list("abcdefghijklmnopqrstuvwxyz0123456789"))
    docs = [
        "".join(alphabet[RNG.integers(0, len(alphabet), 2_000)]) for _ in range(1_500)
    ]
    big_strings = pa.table(
        {
            "id": pa.array(np.arange(1_500, dtype=np.int64)),
            "document": pa.array(docs),
        }
    )
    _write(big_strings, "wide_strings.parquet", compression="snappy", version="2.6")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

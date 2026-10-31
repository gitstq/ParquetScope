"""Parquet 格式常量与枚举映射。

对照 Parquet 官方 ``parquet.thrift`` 定义整理，字段编号与枚举值保持一致，
确保解析结果与 ``pyarrow`` / ``parquet-cli`` 等工具语义对齐。
"""

from __future__ import annotations

MAGIC = b"PAR1"
MAGIC_ENCRYPTED_FOOTER = b"PARE"
FOOTER_LENGTH_SIZE = 4

# --------------------------------------------------------------------------- #
# Type（物理类型）
# --------------------------------------------------------------------------- #
TYPE_BOOLEAN = 0
TYPE_INT32 = 1
TYPE_INT64 = 2
TYPE_INT96 = 3
TYPE_FLOAT = 4
TYPE_DOUBLE = 5
TYPE_BYTE_ARRAY = 6
TYPE_FIXED_LEN_BYTE_ARRAY = 7

PHYSICAL_TYPES: dict[int, str] = {
    TYPE_BOOLEAN: "BOOLEAN",
    TYPE_INT32: "INT32",
    TYPE_INT64: "INT64",
    TYPE_INT96: "INT96",
    TYPE_FLOAT: "FLOAT",
    TYPE_DOUBLE: "DOUBLE",
    TYPE_BYTE_ARRAY: "BYTE_ARRAY",
    TYPE_FIXED_LEN_BYTE_ARRAY: "FIXED_LEN_BYTE_ARRAY",
}

# --------------------------------------------------------------------------- #
# ConvertedType（旧式逻辑类型）
# --------------------------------------------------------------------------- #
CONVERTED_TYPES: dict[int, str] = {
    0: "UTF8",
    1: "MAP",
    2: "MAP_KEY_VALUE",
    3: "LIST",
    4: "ENUM",
    5: "DECIMAL",
    6: "DATE",
    7: "TIME_MILLIS",
    8: "TIME_MICROS",
    9: "TIMESTAMP_MILLIS",
    10: "TIMESTAMP_MICROS",
    11: "UINT_8",
    12: "UINT_16",
    13: "UINT_32",
    14: "UINT_64",
    15: "INT_8",
    16: "INT_16",
    17: "INT_32",
    18: "INT_64",
    19: "JSON",
    20: "BSON",
    21: "INTERVAL",
}

# --------------------------------------------------------------------------- #
# FieldRepetitionType
# --------------------------------------------------------------------------- #
REPETITION_REQUIRED = 0
REPETITION_OPTIONAL = 1
REPETITION_REPEATED = 2

REPETITION_TYPES: dict[int, str] = {
    REPETITION_REQUIRED: "REQUIRED",
    REPETITION_OPTIONAL: "OPTIONAL",
    REPETITION_REPEATED: "REPEATED",
}

# --------------------------------------------------------------------------- #
# CompressionCodec
# --------------------------------------------------------------------------- #
CODEC_UNCOMPRESSED = 0
CODEC_SNAPPY = 1
CODEC_GZIP = 2
CODEC_LZO = 3
CODEC_BROTLI = 4
CODEC_LZ4 = 5
CODEC_ZSTD = 6
CODEC_LZ4_RAW = 7

CODECS: dict[int, str] = {
    CODEC_UNCOMPRESSED: "UNCOMPRESSED",
    CODEC_SNAPPY: "SNAPPY",
    CODEC_GZIP: "GZIP",
    CODEC_LZO: "LZO",
    CODEC_BROTLI: "BROTLI",
    CODEC_LZ4: "LZ4",
    CODEC_ZSTD: "ZSTD",
    CODEC_LZ4_RAW: "LZ4_RAW",
}

# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #
ENCODINGS: dict[int, str] = {
    0: "PLAIN",
    2: "PLAIN_DICTIONARY",
    3: "RLE",
    4: "BIT_PACKED",
    5: "DELTA_BINARY_PACKED",
    6: "DELTA_LENGTH_BYTE_ARRAY",
    7: "DELTA_BYTE_ARRAY",
    8: "RLE_DICTIONARY",
    9: "BYTE_STREAM_SPLIT",
}

#: 已废弃或不建议继续使用的编码方式
DEPRECATED_ENCODINGS: dict[int, str] = {
    ENCODINGS[2]: "已在 Parquet 2.0 被 RLE_DICTIONARY 取代，建议改用 RLE_DICTIONARY",
    ENCODINGS[4]: "BIT_PACKED 仅用于 definition/repetition level，不建议用于数据页",
}

#: 对字符串/字节列收益明显的字典类编码
DICTIONARY_ENCODINGS = {"PLAIN_DICTIONARY", "RLE_DICTIONARY"}

# --------------------------------------------------------------------------- #
# LogicalType（union 字段号 -> 名称）
# --------------------------------------------------------------------------- #
LOGICAL_TYPE_FIELDS: dict[int, str] = {
    1: "STRING",
    2: "MAP",
    3: "LIST",
    4: "ENUM",
    5: "DECIMAL",
    6: "DATE",
    7: "TIME",
    8: "TIMESTAMP",
    # 9 保留
    10: "INTEGER",
    11: "UNKNOWN",
    12: "JSON",
    13: "BSON",
    14: "UUID",
    15: "FLOAT16",
}

TIME_UNITS: dict[int, str] = {1: "MILLIS", 2: "MICROS", 3: "NANOS"}

# --------------------------------------------------------------------------- #
# PageType
# --------------------------------------------------------------------------- #
PAGE_TYPES: dict[int, str] = {
    0: "DATA_PAGE",
    1: "INDEX_PAGE",
    2: "DICTIONARY_PAGE",
    3: "DATA_PAGE_V2",
}

# --------------------------------------------------------------------------- #
# FileMetaData / SchemaElement / ColumnChunk / Statistics 字段号
# --------------------------------------------------------------------------- #
FMD_VERSION = 1
FMD_SCHEMA = 2
FMD_NUM_ROWS = 3
FMD_ROW_GROUPS = 4
FMD_KEY_VALUE_METADATA = 5
FMD_CREATED_BY = 6
FMD_COLUMN_ORDERS = 7
FMD_ENCRYPTION_ALGORITHM = 8
FMD_FOOTER_SIGNING_KEY_METADATA = 9

SE_TYPE = 1
SE_TYPE_LENGTH = 2
SE_REPETITION = 3
SE_NAME = 4
SE_NUM_CHILDREN = 5
SE_CONVERTED_TYPE = 6
SE_SCALE = 7
SE_PRECISION = 8
SE_FIELD_ID = 9
SE_LOGICAL_TYPE = 10

RG_COLUMNS = 1
RG_TOTAL_BYTE_SIZE = 2
RG_NUM_ROWS = 3
RG_SORTING_COLUMNS = 4
RG_FILE_OFFSET = 5
RG_TOTAL_COMPRESSED_SIZE = 6
RG_ORDINAL = 7

CC_FILE_PATH = 1
CC_FILE_OFFSET = 2
CC_META_DATA = 3
CC_OFFSET_INDEX_OFFSET = 4
CC_OFFSET_INDEX_LENGTH = 5
CC_COLUMN_INDEX_OFFSET = 6
CC_COLUMN_INDEX_LENGTH = 7
CC_CRYPTO_METADATA = 8
CC_ENCRYPTED_COLUMN_METADATA = 9

CMD_TYPE = 1
CMD_ENCODINGS = 2
CMD_PATH_IN_SCHEMA = 3
CMD_CODEC = 4
CMD_NUM_VALUES = 5
CMD_TOTAL_UNCOMPRESSED_SIZE = 6
CMD_TOTAL_COMPRESSED_SIZE = 7
CMD_KEY_VALUE_METADATA = 8
CMD_DATA_PAGE_OFFSET = 9
CMD_INDEX_PAGE_OFFSET = 10
CMD_DICTIONARY_PAGE_OFFSET = 11
CMD_STATISTICS = 12
CMD_ENCODING_STATS = 13
CMD_BLOOM_FILTER_OFFSET = 14
CMD_BLOOM_FILTER_LENGTH = 15
CMD_SIZE_STATISTICS = 16

ST_MAX = 1
ST_MIN = 2
ST_NULL_COUNT = 3
ST_DISTINCT_COUNT = 4
ST_MAX_VALUE = 5
ST_MIN_VALUE = 6
ST_IS_MAX_VALUE_EXACT = 7
ST_IS_MIN_VALUE_EXACT = 8

SC_COLUMN_IDX = 1
SC_DESCENDING = 2
SC_NULLS_FIRST = 3

KV_KEY = 1
KV_VALUE = 2

# --------------------------------------------------------------------------- #
# 体检阈值（默认值，可通过 CLI 覆盖）
# --------------------------------------------------------------------------- #
DEFAULT_THRESHOLDS: dict[str, float] = {
    "target_row_group_bytes": 128 * 1024 * 1024,  # 推荐的 row group 未压缩大小
    "min_row_group_bytes": 32 * 1024 * 1024,  # 低于该值视为过小
    "target_row_group_rows": 1_000_000,  # 推荐的单 row group 行数
    "min_row_group_rows": 100_000,  # 低于该值视为行数偏少
    "min_file_bytes": 8 * 1024 * 1024,  # 小于该值属于“小文件”
    "min_compression_ratio": 1.2,  # 启用压缩后至少应达到的压缩比
    "max_columns": 200,  # 列数超过该值视为超宽表
    "max_schema_depth": 5,  # schema 嵌套深度上限
    "max_row_group_skew": 3.0,  # 最大/最小 row group 体积比
    "high_null_ratio": 0.5,  # 空值率告警阈值
    "low_cardinality_ratio": 0.05,  # distinct/rows 低于该值视为低基数列
    "low_cardinality_min_rows": 10_000,  # 低基数判定所需的最小行数
    "large_string_avg_bytes": 512,  # 字符串列平均长度告警阈值
    "large_column_bytes": 64 * 1024 * 1024,  # 单列未压缩体积告警阈值
    "uncompressed_column_bytes": 16 * 1024 * 1024,  # 未压缩大列告警阈值
}


__all__ = [
    "MAGIC",
    "MAGIC_ENCRYPTED_FOOTER",
    "PHYSICAL_TYPES",
    "CONVERTED_TYPES",
    "REPETITION_TYPES",
    "CODECS",
    "ENCODINGS",
    "LOGICAL_TYPE_FIELDS",
    "DEFAULT_THRESHOLDS",
]

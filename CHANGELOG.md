# 更新日志 / Changelog

本项目的所有重要变更都会记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [Semantic Versioning](https://semver.org/)。

## [1.0.0] - 2026-10-31

首个正式版本发布。

### ✨ 新增（Added）

- **零依赖 Parquet Footer 解析器**
  - 自研 Thrift Compact Protocol 解码器（`thrift.py`），支持变长整型、zigzag、嵌套结构体、list / map、布尔打包等全部类型。
  - 完整解析 `FileMetaData` / `SchemaElement` / `RowGroup` / `ColumnChunk` / `ColumnMetaData` / `Statistics` / `SortingColumn` / `KeyValue`。
- **Schema 还原能力**
  - 扁平与嵌套 schema 还原为树形结构，输出 `path_in_schema`、最大 definition / repetition level、物理类型、逻辑类型、ConvertedType。
  - Schema 指纹（SHA-256）用于目录级 schema 漂移检测。
- **统计信息解码**
  - min / max / null_count / distinct_count / min_value / max_value，按逻辑类型还原为原生 Python 值。
  - 支持 INT96 时间戳、Decimal（INT32 / INT64 / FIXED_LEN_BYTE_ARRAY / BYTE_ARRAY）、UUID、Float16、Date、Time、Timestamp（毫秒 / 微秒 / 纳秒，含 `isAdjustedToUTC` 时区语义）。
- **22 条审计规则**（`PS001`–`PS402`）
  - 文件布局（小文件、row group 过大 / 过小、行数过少、文件数量）
  - Schema 结构（嵌套过深、列数过宽、重复命名、全 optional 列）
  - 编码与压缩（无压缩、压缩收益低、字典编码不适用、PLAIN 编码大列）
  - 统计信息与索引（缺失统计、缺失排序键、统计信息过宽、null 占比过高、INT96 时间戳）
  - 列特征（高基数字典、宽字符串、常量列）
- **健康评分与 CI 门禁**
  - 0–100 健康分（info 扣 1、warn 扣 6、error 扣 15），A/B/C/D 评级。
  - `--fail-on {error,warn,none}` 让体检结果直接进入 CI 流水线。
- **8 个 CLI 子命令**：`info` / `schema` / `rowgroups` / `columns` / `audit` / `doctor` / `dump` / `rules`。
- **4 种输出格式**：`text`（CJK 宽度对齐）、`json`、`markdown`、`csv`。
- **目录级扫描**：`doctor` 支持目标目录递归扫描、聚合评分、schema 漂移报告。
- **Python API**：`ParquetFile` / `read_metadata` / `audit` / `iter_parquet_files` 均可作为库调用。
- **完整测试套件**：99 个单元测试，覆盖字节级 Thrift 解码、元数据解析、规则触发、CLI 退出码与输出格式。
- **三语文档**：简体中文 / English / 繁體中文 README，含可点击语言切换。

### 🔒 兼容性

- 需要 Python 3.9+，仅使用标准库。
- 支持未加密 Parquet 文件；遇到加密 footer（`PARE`）会给出明确报错。
- 支持 parquet-mr、parquet-cpp / Arrow、DuckDB、Spark 等主流写入器产出的文件。

### ⚠️ 已知限制（Known Limitations）

- 仅解析 footer 元数据，**不读取数据页**，因此不做数据正确性校验、不计算真实压缩后的 page 级指标。
- 暂不解析 Page Index（Offset Index / Column Index）与 Bloom Filter 的实际内容，仅探测是否存在。
- 暂不支持加密文件的 footer 解密。
- 暂不提供 V2 数据页的 DataPageHeaderV2 深度分析。

## 规划中（Planned）

- `v1.1`：Page Index（Column Index / Offset Index）可视化、Bloom Filter 命中率预估、HTML 报告导出。
- `v1.2`：多文件 schema 演进 diff、自定义规则插件（YAML / Python entry point）、Glob 排除语法。
- `v2.0`：可选的数据页采样扫描（需 pyarrow，作为可选依赖）、Parquet 写入建议自动生成（`suggest` 命令）。

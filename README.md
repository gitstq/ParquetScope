<div align="center">

# 🔭 ParquetScope

**零依赖 · 离线优先的 Parquet 列式文件体检与存储布局审计引擎**

[English](./README.en.md) · 简体中文 · [繁體中文](./README.zh-TW.md)

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](./pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

</div>

---

## 🎉 项目介绍

**ParquetScope** 是一个面向数据工程师、平台工程师与数据分析师的 **Parquet 文件"体检仪"**。

它只读取 Parquet 的 **footer 元数据**（不解压、不扫描数据页），就能在毫秒级回答这些关键问题：

- 这个文件的 row group 切分合理吗？会不会拖慢查询？
- 哪些列没有统计信息，导致谓词下推失效？
- 压缩算法选对了吗？压缩收益是多少？
- schema 有没有嵌套过深、列数过宽？
- 一整个数据目录里，有多少小文件？schema 是否发生了漂移？

### 为什么需要它

Parquet 是数据湖的事实标准格式，但**绝大多数性能问题都源于"写的时候没写对"**：row group 太小、统计信息缺失、排序键没设置、小文件泛滥。这些问题往往要等到查询变慢后才被发现，而排查成本极高。

传统排查方式需要启动 Spark / DuckDB / pyarrow 读取整个文件；ParquetScope 只需要**标准库 + 文件的最后几 KB**：

| 对比项 | 传统方式 | ParquetScope |
| --- | --- | --- |
| 依赖 | Spark / DuckDB / pyarrow（数百 MB） | **零第三方依赖** |
| 读取量 | 整个文件（可能数 GB） | **仅 footer（通常几 KB）** |
| 启动耗时 | 秒级 ~ 分钟级 | **毫秒级** |
| 运行环境 | 需要 JVM / 本地库 | **纯 Python，跨平台** |
| CI 集成 | 重 | **一条命令，退出码门禁** |

### 自研差异化亮点

- 🧬 **自研 Thrift Compact Protocol 解码器**：从字节层完整实现 Parquet footer 的序列化协议，不引入 `thrift` / `fastparquet` / `pyarrow` 任何依赖。
- 🧠 **可解释的规则引擎**：22 条规则每条都带编号、严重级别、证据指标和可执行建议，而不是一个黑盒分数。
- 🔀 **目录级 schema 漂移检测**：自动比对多个文件的 schema 指纹，定位新增/缺失/类型变化的列。
- 🚦 **CI 门禁就绪**：`--fail-on error` 直接产出非零退出码，可作为数据质量流水线的一环。
- 🧭 **有序性推断**：基于各 row group 的 min/max 区间推断列是否全局有序，量化"能否被 row group 剪枝"。

> 灵感来源：社区对"本地优先、零依赖诊断工具"的持续需求（`parquet-cli`、`parquet-tools` 等），以及近期 GitHub Trending 上开发者工具向 **离线、可解释、可嵌入 CI** 演进的趋势。ParquetScope 在能力边界上做了重新设计：只做元数据层诊断，换取极致的轻量与速度。

---

## ✨ 核心特性

- 🔍 **零依赖**：仅使用 Python 标准库，`pip install` 后无任何传递依赖
- ⚡ **毫秒级**：只读 footer，TB 级文件也能秒开
- 🌳 **完整 schema 还原**：嵌套 STRUCT / LIST / MAP、LogicalType、definition & repetition level
- 📊 **列级画像**：行数、空值率、去重数、压缩比、min/max、字典编码使用情况
- 🗂️ **row group 布局**：体积分布、倾斜度、排序列声明、压缩比
- 🩺 **22 条体检规则**：布局 / Schema / 编码压缩 / 统计索引 / 列特征五大类
- 🔀 **schema 漂移检测**：跨文件比对，定位新增列、缺失列、类型变化
- 🚦 **健康评分 + CI 门禁**：0~100 评分，`--fail-on` 控制退出码
- 📤 **四种输出格式**：`text` / `markdown` / `json` / `csv`，可直接喂给下游系统
- 🐍 **库 + CLI 双形态**：既可命令行使用，也可 `from parquetscope import read_metadata`
- 🖥️ **跨平台**：Windows / macOS / Linux 全支持，纯 Python 无本地扩展
- 🔒 **只读安全**：全程只读，绝不修改或写入目标文件

---

## 🚀 快速开始

### 环境要求

- **Python 3.9+**（仅标准库，无第三方依赖）
- 操作系统：Windows / macOS / Linux 任意

### 安装

```bash
# 方式一：从源码安装（推荐）
git clone https://github.com/gitstq/ParquetScope.git
cd ParquetScope
pip install .

# 方式二：开发模式
pip install -e ".[dev]"

# 方式三：免安装，直接运行
PYTHONPATH=src python3 -m parquetscope info data.parquet
```

### 30 秒上手

```bash
# 1. 看一眼文件概览
parquetscope info data.parquet

# 2. 查看 schema 结构
parquetscope schema data.parquet

# 3. 做一次完整体检
parquetscope audit data.parquet

# 4. 整个目录一起体检（小文件 + schema 漂移）
parquetscope doctor ./warehouse

# 5. 在 CI 中拦截有严重问题的文件
parquetscope audit "./warehouse/**/*.parquet" --fail-on error
```

### Python API

```python
from parquetscope import read_metadata, audit

meta = read_metadata("data.parquet")
print(meta.num_rows, meta.num_columns, meta.overall_compression_ratio)

report = audit(meta, path="data.parquet")
print(report.score)                    # 健康评分 0~100
print(report.severity_counts)          # {'info': 2, 'warn': 3, 'error': 0}
for finding in report.findings:
    print(finding.code, finding.severity, finding.title, finding.advice)
```

---

## 📖 详细使用指南

### 命令一览

| 命令 | 作用 | 常用参数 |
| --- | --- | --- |
| `info` | 文件概览（行数、列数、体积、压缩比） | `--format` |
| `schema` | schema 结构树 | `--max-depth` |
| `rowgroups` | row group 布局明细 | `--format` |
| `columns` | 列级画像 | `--limit` |
| `audit` | 单/多文件体检 | `--fail-on`、`--rule`、阈值参数 |
| `doctor` | 目录级数据集体检 | `--format json` |
| `dump` | 导出完整元数据 JSON | `--no-statistics` |
| `rules` | 列出全部体检规则 | `--format json` |

### 全局参数

| 参数 | 说明 |
| --- | --- |
| `-f, --format` | 输出格式：`text`（默认）/ `markdown` / `json` / `csv` |
| `-o, --output` | 写入文件而非标准输出 |
| `paths` | 支持文件路径、目录、glob 通配符，可同时传多个 |

### 输出格式示例

```bash
# 机器可读，便于二次处理
parquetscope audit data.parquet --format json | jq '.score'

# 生成可直接粘到 PR 里的 Markdown 报告
parquetscope audit data.parquet --format markdown -o report.md

# 列级画像导出 CSV，用 Excel 继续分析
parquetscope columns data.parquet --format csv -o columns.csv
```

### 阈值自定义

体检规则的所有阈值都可以按项目实际情况覆盖：

```bash
parquetscope audit data.parquet \
  --target-row-group-mb 256 \     # row group 推荐体积
  --min-row-group-mb 64 \         # row group 最小体积
  --min-compression-ratio 1.5 \   # 最低可接受压缩比
  --max-columns 300 \             # 列数上限
  --max-null-ratio 0.8 \          # 空值率告警阈值
  --min-file-mb 64                # 小文件判定阈值
```

也可以只运行关心的规则：

```bash
parquetscope audit data.parquet --rule PS300 --rule PS003
```

### CI 集成示例（GitHub Actions）

```yaml
- name: Parquet 文件体检
  run: |
    pip install parquetscope
    parquetscope audit "./data/**/*.parquet" --fail-on error --format markdown -o audit.md
```

### 体检规则全表

| 编号 | 级别 | 规则 | 说明 |
| --- | --- | --- | --- |
| PS001 | ⚠️ | 文件体积过小 | 触发经典的"小文件问题" |
| PS002 | ❌ | 无 row group | 文件不含可读数据块 |
| PS003 | ❌/⚠️ | row group 体积偏小 | 低于 128MB 推荐值 |
| PS004 | ⚠️ | row group 行数偏少 | 少于 100 万行 |
| PS005 | ⚠️ | row group 体积倾斜 | 最大/最小比超过 3 倍 |
| PS006 | ℹ️ | 超大 row group | 超过 512MB，影响并行度 |
| PS100 | ⚠️ | 超宽表 | 列数超过 200 |
| PS101 | ⚠️ | schema 嵌套过深 | 深度超过 5 层 |
| PS102 | ⚠️ | INT96 时间戳 | 已废弃类型，兼容性风险 |
| PS103 | ℹ️ | 缺少 created_by | 无法追溯写入器 |
| PS200 | ⚠️ | 废弃编码 | PLAIN_DICTIONARY 等 |
| PS201 | ⚠️ | 大列未压缩 | 大体积列使用 UNCOMPRESSED |
| PS202 | ℹ️ | 压缩收益偏低 | 整体压缩比低于 1.2x |
| PS203 | ℹ️ | 低基数列未用字典编码 | 单值/低基数列的压缩机会 |
| PS300 | ❌/⚠️ | 缺少统计信息 | 谓词下推失效 |
| PS301 | ⚠️ | 统计值非精确 | min/max 被标记为近似 |
| PS302 | ℹ️ | 仅旧版统计字段 | 未写入 min_value/max_value |
| PS303 | ℹ️ | 缺少 Page Index | 无法页级剪枝 |
| PS304 | ℹ️ | 区间重叠严重 | 排序键缺失，剪枝率低 |
| PS400 | ℹ️ | 高空值率列 | 空值率超过 50% |
| PS401 | ℹ️ | 超大列 | 单列未压缩超过 64MB |
| PS402 | ℹ️ | 长字符串列 | 平均行长度超过 512 字节 |

### 支持的 Parquet 特性

- ✅ Parquet v1 / v2（含 DataPageV2 的元数据字段）
- ✅ 全部物理类型：BOOLEAN / INT32 / INT64 / INT96 / FLOAT / DOUBLE / BYTE_ARRAY / FIXED_LEN_BYTE_ARRAY
- ✅ LogicalType：STRING、DATE、TIME、TIMESTAMP（MILLIS/MICROS/NANOS）、DECIMAL、UUID、JSON、BSON、ENUM、INTEGER、FLOAT16、UNKNOWN
- ✅ ConvertedType 全量映射（旧式逻辑类型）
- ✅ 压缩编解码标识：UNCOMPRESSED / SNAPPY / GZIP / LZO / BROTLI / LZ4 / ZSTD / LZ4_RAW
- ✅ 嵌套结构：STRUCT / LIST / MAP，含 max definition & repetition level
- ✅ 列块统计：min/max、null_count、distinct_count、精确性标记
- ✅ Page Index / Bloom Filter 存在性标记
- ⚠️ 列加密文件（PARE）：**明确拒绝解析**并给出清晰报错（不做任何解密尝试）

### 退出码约定

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部通过 |
| `1` | 命中 `--fail-on` 指定级别的问题，或输入路径无效 |
| `2` | 运行期错误（如文件损坏、权限不足） |

---

## 💡 设计思路与迭代规划

### 技术选型

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 语言 | Python | Parquet 生态的事实通用语言，运维/数据团队接受度最高 |
| 依赖 | **零** | 可嵌入任何环境（含受限生产容器），安装不可能失败 |
| 协议层 | 自研 Thrift Compact 解码 | 避免引入 thrift/pyarrow；协议本身仅约 200 行 |
| 解析范围 | 仅 footer | 保证毫秒级；数据页解码交由专业引擎，不做重复造轮子 |
| 输出 | text / markdown / json / csv | 覆盖人读、文档、程序、表格四类场景 |
| 规则组织 | 编号 + 级别 + 建议 | 可解释、可裁剪、可演进，便于团队定制基线 |

### 架构分层

```
┌─────────────────────────────────────────┐
│  CLI (cli.py)        参数解析 · 退出码   │
├─────────────────────────────────────────┤
│  Report (report.py)  text/md/json/csv   │
├─────────────────────────────────────────┤
│  Analyzer (analyzer.py) 列画像 · 规则引擎│
├─────────────────────────────────────────┤
│  Metadata (metadata.py) schema 树 · 解码 │
├─────────────────────────────────────────┤
│  Reader (reader.py)  footer 定位         │
├─────────────────────────────────────────┤
│  Thrift (thrift.py)  Compact Protocol    │
└─────────────────────────────────────────┘
```

### 迭代规划

- **v1.1**：支持 Parquet Page Index（ColumnIndex/OffsetIndex）解析，输出页级 min/max 分布
- **v1.2**：支持 Bloom Filter 命中率评估与列级索引建议
- **v1.3**：增加 SARIF 输出，直接接入 GitHub Code Scanning
- **v1.4**：支持 ORC / Arrow IPC 的同类体检能力
- **v2.0**：提供可插拔规则 SDK，支持团队自定义规则包

---

## 🧪 测试

```bash
pip install -e ".[dev]"
pytest
```

测试覆盖 Thrift 协议字节级解码、元数据模型、值解码、规则引擎、CLI 与四种渲染格式，共 **99 个用例**，全部基于仓库内已提交的样本文件，运行不依赖 pyarrow。

重新生成样本（仅在需要新夹具时才执行，**运行时不需要**）：

```bash
pip install pyarrow numpy
python scripts/generate_fixtures.py
```

---

## 📄 许可证

[MIT License](./LICENSE) — 免费用于个人与商业项目。

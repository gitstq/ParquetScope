<div align="center">

# 🔭 ParquetScope

**Zero-dependency, offline-first Parquet health check & columnar storage layout audit engine**

English · [简体中文](./README.md) · [繁體中文](./README.zh-TW.md)

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](./pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

</div>

---

## 🎉 Project Introduction

**ParquetScope** is a *health checker* for Parquet files, built for data engineers, platform engineers, and analysts.

It reads **only the Parquet footer metadata** — no decompression, no data-page scanning — and answers, in milliseconds:

- Are the row groups sized sensibly, or are they quietly slowing every query down?
- Which columns lack statistics, silently disabling predicate pushdown?
- Is the right compression codec in use, and what is the actual compression gain?
- Is the schema too wide, or nested too deeply?
- Across an entire dataset directory: how many small files, and has the schema drifted?

### Why it exists

Parquet is the de facto standard for data lakes, yet **most performance problems come from how files were written**: tiny row groups, missing statistics, no sort keys, and small-file sprawl. These issues usually surface only after queries get slow, and diagnosing them is expensive.

The traditional route means spinning up Spark, DuckDB, or pyarrow and reading whole files. ParquetScope needs **nothing but the standard library and the last few KB of a file**:

| | Traditional tooling | ParquetScope |
| --- | --- | --- |
| Dependencies | Spark / DuckDB / pyarrow (hundreds of MB) | **Zero third-party deps** |
| Bytes read | Entire file (possibly GBs) | **Footer only (usually a few KB)** |
| Startup | Seconds to minutes | **Milliseconds** |
| Runtime | JVM / native libraries | **Pure Python, cross-platform** |
| CI integration | Heavy | **One command, exit-code gate** |

### What makes it original

- 🧬 **Hand-written Thrift Compact Protocol decoder** — Parquet footers are decoded at the byte level, with no `thrift`, `fastparquet`, or `pyarrow` dependency.
- 🧠 **Explainable rule engine** — 22 rules, each with an ID, severity, evidence metrics, and an actionable fix. No black-box score.
- 🔀 **Directory-level schema drift detection** — compares schema fingerprints across files and pinpoints added, missing, or retyped columns.
- 🚦 **CI-ready** — `--fail-on error` produces a non-zero exit code for data-quality pipelines.
- 🧭 **Sortedness inference** — uses per-row-group min/max ranges to infer whether a column is globally sorted, quantifying how well row-group pruning can work.

> Inspiration: the community's long-standing need for local-first, dependency-free diagnostic tooling (`parquet-cli`, `parquet-tools`), plus the recent GitHub Trending shift of developer tools toward **offline, explainable, CI-embeddable** designs. ParquetScope redraws the boundary: metadata-layer diagnostics only, in exchange for extreme lightness and speed.

---

## ✨ Key Features

- 🔍 **Zero dependencies** — standard library only; nothing else is pulled in on install
- ⚡ **Millisecond latency** — footer-only reads, even on TB-scale files
- 🌳 **Full schema reconstruction** — nested STRUCT / LIST / MAP, logical types, max definition & repetition levels
- 📊 **Column profiles** — row counts, null ratios, distinct counts, compression ratios, min/max, dictionary usage
- 🗂️ **Row group layout** — size distribution, skew, declared sort columns, compression ratios
- 🩺 **22 audit rules** — layout / schema / encoding / statistics / column characteristics
- 🔀 **Schema drift detection** — cross-file comparison of added, missing, and retyped columns
- 🚦 **Health score + CI gate** — 0–100 score with `--fail-on` exit-code control
- 📤 **Four output formats** — `text` / `markdown` / `json` / `csv`, ready for downstream systems
- 🐍 **Library + CLI** — use the CLI, or `from parquetscope import read_metadata`
- 🖥️ **Cross-platform** — Windows / macOS / Linux, pure Python with no native extensions
- 🔒 **Read-only by design** — never modifies or writes to the target file

---

## 🚀 Quick Start

### Requirements

- **Python 3.9+** (standard library only, no third-party packages)
- Any of Windows / macOS / Linux

### Installation

```bash
# Option 1: install from source (recommended)
git clone https://github.com/gitstq/ParquetScope.git
cd ParquetScope
pip install .

# Option 2: editable / development install
pip install -e ".[dev]"

# Option 3: run without installing
PYTHONPATH=src python3 -m parquetscope info data.parquet
```

### Up and running in 30 seconds

```bash
# 1. File overview
parquetscope info data.parquet

# 2. Inspect the schema
parquetscope schema data.parquet

# 3. Run a full health check
parquetscope audit data.parquet

# 4. Audit a whole directory (small files + schema drift)
parquetscope doctor ./warehouse

# 5. Block files with severe issues in CI
parquetscope audit "./warehouse/**/*.parquet" --fail-on error
```

### Python API

```python
from parquetscope import read_metadata, audit

meta = read_metadata("data.parquet")
print(meta.num_rows, meta.num_columns, meta.overall_compression_ratio)

report = audit(meta, path="data.parquet")
print(report.score)                    # health score, 0-100
print(report.severity_counts)          # {'info': 2, 'warn': 3, 'error': 0}
for finding in report.findings:
    print(finding.code, finding.severity, finding.title, finding.advice)
```

---

## 📖 Usage Guide

### Command reference

| Command | Purpose | Notable flags |
| --- | --- | --- |
| `info` | File overview (rows, columns, sizes, ratio) | `--format` |
| `schema` | Schema tree | `--max-depth` |
| `rowgroups` | Row group layout detail | `--format` |
| `columns` | Column profiles | `--limit` |
| `audit` | Single/multi-file health check | `--fail-on`, `--rule`, thresholds |
| `doctor` | Directory-level dataset audit | `--format json` |
| `dump` | Export full metadata as JSON | `--no-statistics` |
| `rules` | List every audit rule | `--format json` |

### Global flags

| Flag | Description |
| --- | --- |
| `-f, --format` | Output format: `text` (default) / `markdown` / `json` / `csv` |
| `-o, --output` | Write to a file instead of stdout |
| `paths` | File paths, directories, or glob patterns — multiple allowed |

### Output format examples

```bash
# Machine-readable, easy to post-process
parquetscope audit data.parquet --format json | jq '.score'

# Markdown report you can paste straight into a PR
parquetscope audit data.parquet --format markdown -o report.md

# Column profiles as CSV for spreadsheet analysis
parquetscope columns data.parquet --format csv -o columns.csv
```

### Custom thresholds

Every audit threshold can be tuned to your project:

```bash
parquetscope audit data.parquet \
  --target-row-group-mb 256 \     # recommended row group size
  --min-row-group-mb 64 \         # minimum row group size
  --min-compression-ratio 1.5 \   # minimum acceptable compression ratio
  --max-columns 300 \             # column count ceiling
  --max-null-ratio 0.8 \          # null ratio warning threshold
  --min-file-mb 64                # small-file threshold
```

Run only the rules you care about:

```bash
parquetscope audit data.parquet --rule PS300 --rule PS003
```

### CI integration (GitHub Actions)

```yaml
- name: Parquet health check
  run: |
    pip install parquetscope
    parquetscope audit "./data/**/*.parquet" --fail-on error --format markdown -o audit.md
```

### Full rule catalog

| ID | Severity | Rule | Description |
| --- | --- | --- | --- |
| PS001 | ⚠️ | File too small | Classic small-file problem |
| PS002 | ❌ | No row groups | File contains no readable data blocks |
| PS003 | ❌/⚠️ | Row groups too small | Below the 128 MB recommendation |
| PS004 | ⚠️ | Too few rows per row group | Fewer than 1M rows |
| PS005 | ⚠️ | Row group size skew | Max/min ratio above 3x |
| PS006 | ℹ️ | Oversized row group | Above 512 MB, hurts parallelism |
| PS100 | ⚠️ | Over-wide table | More than 200 columns |
| PS101 | ⚠️ | Schema nested too deeply | Depth above 5 |
| PS102 | ⚠️ | INT96 timestamps | Deprecated type, compatibility risk |
| PS103 | ℹ️ | Missing created_by | Writer cannot be traced |
| PS200 | ⚠️ | Deprecated encodings | PLAIN_DICTIONARY and friends |
| PS201 | ⚠️ | Large column uncompressed | Big column stored as UNCOMPRESSED |
| PS202 | ℹ️ | Low compression gain | Overall ratio below 1.2x |
| PS203 | ℹ️ | Low-cardinality column without dictionary | Missed compression opportunity |
| PS300 | ❌/⚠️ | Missing statistics | Predicate pushdown disabled |
| PS301 | ⚠️ | Inexact statistics | min/max flagged as approximate |
| PS302 | ℹ️ | Legacy statistics fields only | No min_value/max_value written |
| PS303 | ℹ️ | Missing page index | No page-level pruning |
| PS304 | ℹ️ | Heavily overlapping ranges | No sort key, low pruning rate |
| PS400 | ℹ️ | High null ratio | Above 50% nulls |
| PS401 | ℹ️ | Oversized column | Uncompressed size above 64 MB |
| PS402 | ℹ️ | Long string column | Average row length above 512 bytes |

### Parquet feature support

- ✅ Parquet v1 / v2 (including DataPageV2 metadata fields)
- ✅ All physical types: BOOLEAN / INT32 / INT64 / INT96 / FLOAT / DOUBLE / BYTE_ARRAY / FIXED_LEN_BYTE_ARRAY
- ✅ Logical types: STRING, DATE, TIME, TIMESTAMP (MILLIS/MICROS/NANOS), DECIMAL, UUID, JSON, BSON, ENUM, INTEGER, FLOAT16, UNKNOWN
- ✅ Full ConvertedType mapping (legacy logical types)
- ✅ Codec identifiers: UNCOMPRESSED / SNAPPY / GZIP / LZO / BROTLI / LZ4 / ZSTD / LZ4_RAW
- ✅ Nested structures: STRUCT / LIST / MAP with max definition & repetition levels
- ✅ Column chunk statistics: min/max, null_count, distinct_count, exactness flags
- ✅ Page index / bloom filter presence detection
- ⚠️ Encrypted files (PARE): **explicitly refused** with a clear error (no decryption attempted)

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Everything passed |
| `1` | A finding matched `--fail-on`, or an input path was invalid |
| `2` | Runtime error (corrupt file, permission denied, etc.) |

---

## 💡 Design Notes & Roadmap

### Technology choices

| Decision | Choice | Rationale |
| --- | --- | --- |
| Language | Python | The lingua franca of the Parquet ecosystem |
| Dependencies | **None** | Embeddable anywhere, including locked-down production containers |
| Protocol layer | Hand-written Thrift Compact decoder | Avoids thrift/pyarrow; the protocol is only ~200 lines |
| Parse scope | Footer only | Guarantees millisecond latency; page decoding belongs to query engines |
| Output | text / markdown / json / csv | Covers human, docs, program, and spreadsheet needs |
| Rule layout | ID + severity + advice | Explainable, selectable, evolvable — easy to set a team baseline |

### Architecture

```
┌─────────────────────────────────────────┐
│  CLI (cli.py)        args · exit codes  │
├─────────────────────────────────────────┤
│  Report (report.py)  text/md/json/csv   │
├─────────────────────────────────────────┤
│  Analyzer (analyzer.py) profiles · rules│
├─────────────────────────────────────────┤
│  Metadata (metadata.py) schema · decode │
├─────────────────────────────────────────┤
│  Reader (reader.py)  footer location    │
├─────────────────────────────────────────┤
│  Thrift (thrift.py)  Compact Protocol   │
└─────────────────────────────────────────┘
```

### Roadmap

- **v1.1** — Parse the Parquet page index (ColumnIndex/OffsetIndex) and report page-level min/max distribution
- **v1.2** — Bloom filter hit-rate estimation and per-column index recommendations
- **v1.3** — SARIF output for GitHub Code Scanning
- **v1.4** — Equivalent auditing for ORC and Arrow IPC
- **v2.0** — Pluggable rule SDK for team-specific rule packs

---

## 🧪 Tests

```bash
pip install -e ".[dev]"
pytest
```

Coverage spans byte-level Thrift decoding, the metadata model, value decoding, the rule engine, the CLI, and all four renderers — **99 test cases** built on sample files committed to the repo, with no pyarrow requirement at test time.

Regenerating samples (only needed when new fixtures are required — **not** needed at runtime):

```bash
pip install pyarrow numpy
python scripts/generate_fixtures.py
```

---

## 📄 License

[MIT License](./LICENSE) — free for personal and commercial use.

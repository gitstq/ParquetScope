<div align="center">

# 🔭 ParquetScope

**零依賴 · 離線優先的 Parquet 列式檔案健檢與儲存佈局稽核引擎**

[English](./README.en.md) · [简体中文](./README.md) · 繁體中文

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](./pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

</div>

---

## 🎉 專案介紹

**ParquetScope** 是一套為資料工程師、平台工程師與資料分析師打造的 **Parquet 檔案「健康檢查儀」**。

它只讀取 Parquet 的 **footer 中繼資料**（不解壓縮、不掃描資料頁），就能在毫秒等級回答這些關鍵問題：

- 這個檔案的 row group 切分合理嗎？會不會拖慢每一次查詢？
- 哪些欄位缺少統計資訊，導致謂詞下推失效？
- 壓縮演算法選對了嗎？實際壓縮收益是多少？
- schema 是否過寬、巢狀過深？
- 整個資料目錄裡有多少小檔案？schema 是否已經發生漂移？

### 為什麼需要它

Parquet 是資料湖的事實標準格式，但**絕大多數效能問題都源自「寫入時沒寫對」**：row group 太小、統計資訊缺失、沒設排序鍵、小檔案氾濫。這些問題往往要等到查詢變慢才被發現，而排查成本極高。

傳統排查方式需要啟動 Spark / DuckDB / pyarrow 讀取整份檔案；ParquetScope 只需要**標準函式庫加上檔案最後幾 KB**：

| 對比項 | 傳統方式 | ParquetScope |
| --- | --- | --- |
| 依賴 | Spark / DuckDB / pyarrow（數百 MB） | **零第三方依賴** |
| 讀取量 | 整份檔案（可能數 GB） | **僅 footer（通常幾 KB）** |
| 啟動耗時 | 秒級 ~ 分鐘級 | **毫秒級** |
| 執行環境 | 需要 JVM / 原生函式庫 | **純 Python，跨平台** |
| CI 整合 | 沉重 | **一條指令，退出碼閘門** |

### 自研差異化亮點

- 🧬 **自研 Thrift Compact Protocol 解碼器**：從位元組層完整實作 Parquet footer 的序列化協定，不引入 `thrift` / `fastparquet` / `pyarrow` 任何依賴。
- 🧠 **可解釋的規則引擎**：22 條規則每條都帶編號、嚴重度、證據指標與可執行建議，而不是黑盒分數。
- 🔀 **目錄級 schema 漂移偵測**：自動比對多個檔案的 schema 指紋，定位新增／缺失／型別變化的欄位。
- 🚦 **CI 閘門就緒**：`--fail-on error` 直接產出非零退出碼，可作為資料品質流水線的一環。
- 🧭 **有序性推斷**：依據各 row group 的 min/max 區間推斷欄位是否全域有序，量化「能否被 row group 剪枝」。

> 靈感來源：社群對「本地優先、零依賴診斷工具」的長期需求（`parquet-cli`、`parquet-tools` 等），以及近期 GitHub Trending 上開發者工具朝 **離線、可解釋、可嵌入 CI** 演進的趨勢。ParquetScope 重新劃定了能力邊界：只做中繼資料層診斷，換取極致的輕量與速度。

---

## ✨ 核心特色

- 🔍 **零依賴**：僅使用 Python 標準函式庫，`pip install` 後不會帶入任何傳遞依賴
- ⚡ **毫秒級**：只讀 footer，TB 級檔案也能秒開
- 🌳 **完整 schema 還原**：巢狀 STRUCT / LIST / MAP、LogicalType、definition & repetition level
- 📊 **欄位級畫像**：列數、空值率、去重數、壓縮比、min/max、字典編碼使用情況
- 🗂️ **row group 佈局**：體積分佈、傾斜度、排序欄位宣告、壓縮比
- 🩺 **22 條健檢規則**：佈局 / Schema / 編碼壓縮 / 統計索引 / 欄位特徵五大類
- 🔀 **schema 漂移偵測**：跨檔案比對，定位新增欄位、缺失欄位、型別變化
- 🚦 **健康評分 + CI 閘門**：0~100 評分，`--fail-on` 控制退出碼
- 📤 **四種輸出格式**：`text` / `markdown` / `json` / `csv`，可直接餵給下游系統
- 🐍 **函式庫 + CLI 雙形態**：可用指令操作，也可 `from parquetscope import read_metadata`
- 🖥️ **跨平台**：Windows / macOS / Linux 全支援，純 Python 無原生擴充
- 🔒 **唯讀安全**：全程唯讀，絕不修改或寫入目標檔案

---

## 🚀 快速開始

### 環境需求

- **Python 3.9+**（僅標準函式庫，無第三方依賴）
- 作業系統：Windows / macOS / Linux 皆可

### 安裝

```bash
# 方式一：從原始碼安裝（推薦）
git clone https://github.com/gitstq/ParquetScope.git
cd ParquetScope
pip install .

# 方式二：開發模式
pip install -e ".[dev]"

# 方式三：免安裝，直接執行
PYTHONPATH=src python3 -m parquetscope info data.parquet
```

### 30 秒上手

```bash
# 1. 看一眼檔案概覽
parquetscope info data.parquet

# 2. 檢視 schema 結構
parquetscope schema data.parquet

# 3. 做一次完整健檢
parquetscope audit data.parquet

# 4. 整個目錄一起健檢（小檔案 + schema 漂移）
parquetscope doctor ./warehouse

# 5. 在 CI 中攔截有嚴重問題的檔案
parquetscope audit "./warehouse/**/*.parquet" --fail-on error
```

### Python API

```python
from parquetscope import read_metadata, audit

meta = read_metadata("data.parquet")
print(meta.num_rows, meta.num_columns, meta.overall_compression_ratio)

report = audit(meta, path="data.parquet")
print(report.score)                    # 健康評分 0~100
print(report.severity_counts)          # {'info': 2, 'warn': 3, 'error': 0}
for finding in report.findings:
    print(finding.code, finding.severity, finding.title, finding.advice)
```

---

## 📖 詳細使用指南

### 指令一覽

| 指令 | 作用 | 常用參數 |
| --- | --- | --- |
| `info` | 檔案概覽（列數、欄位數、體積、壓縮比） | `--format` |
| `schema` | schema 結構樹 | `--max-depth` |
| `rowgroups` | row group 佈局明細 | `--format` |
| `columns` | 欄位級畫像 | `--limit` |
| `audit` | 單／多檔案健檢 | `--fail-on`、`--rule`、閾值參數 |
| `doctor` | 目錄級資料集健檢 | `--format json` |
| `dump` | 匯出完整中繼資料 JSON | `--no-statistics` |
| `rules` | 列出全部健檢規則 | `--format json` |

### 全域參數

| 參數 | 說明 |
| --- | --- |
| `-f, --format` | 輸出格式：`text`（預設）/ `markdown` / `json` / `csv` |
| `-o, --output` | 寫入檔案而非標準輸出 |
| `paths` | 支援檔案路徑、目錄、glob 萬用字元，可同時傳多個 |

### 輸出格式範例

```bash
# 機器可讀，便於二次處理
parquetscope audit data.parquet --format json | jq '.score'

# 產生可直接貼到 PR 的 Markdown 報告
parquetscope audit data.parquet --format markdown -o report.md

# 欄位級畫像匯出 CSV，用試算表繼續分析
parquetscope columns data.parquet --format csv -o columns.csv
```

### 閾值自訂

健檢規則的所有閾值都能依專案實際情況覆寫：

```bash
parquetscope audit data.parquet \
  --target-row-group-mb 256 \     # row group 建議體積
  --min-row-group-mb 64 \         # row group 最小體積
  --min-compression-ratio 1.5 \   # 最低可接受壓縮比
  --max-columns 300 \             # 欄位數上限
  --max-null-ratio 0.8 \          # 空值率告警閾值
  --min-file-mb 64                # 小檔案判定閾值
```

也可以只執行關心的規則：

```bash
parquetscope audit data.parquet --rule PS300 --rule PS003
```

### CI 整合範例（GitHub Actions）

```yaml
- name: Parquet 檔案健檢
  run: |
    pip install parquetscope
    parquetscope audit "./data/**/*.parquet" --fail-on error --format markdown -o audit.md
```

### 健檢規則全表

| 編號 | 嚴重度 | 規則 | 說明 |
| --- | --- | --- | --- |
| PS001 | ⚠️ | 檔案體積過小 | 觸發經典的「小檔案問題」 |
| PS002 | ❌ | 無 row group | 檔案不含可讀資料區塊 |
| PS003 | ❌/⚠️ | row group 體積偏小 | 低於 128MB 建議值 |
| PS004 | ⚠️ | row group 列數偏少 | 少於 100 萬列 |
| PS005 | ⚠️ | row group 體積傾斜 | 最大／最小比超過 3 倍 |
| PS006 | ℹ️ | 超大 row group | 超過 512MB，影響平行度 |
| PS100 | ⚠️ | 超寬表 | 欄位數超過 200 |
| PS101 | ⚠️ | schema 巢狀過深 | 深度超過 5 層 |
| PS102 | ⚠️ | INT96 時間戳 | 已廢棄型別，相容性風險 |
| PS103 | ℹ️ | 缺少 created_by | 無法追溯寫入器 |
| PS200 | ⚠️ | 廢棄編碼 | PLAIN_DICTIONARY 等 |
| PS201 | ⚠️ | 大欄位未壓縮 | 大體積欄位使用 UNCOMPRESSED |
| PS202 | ℹ️ | 壓縮收益偏低 | 整體壓縮比低於 1.2x |
| PS203 | ℹ️ | 低基數欄位未用字典編碼 | 單值／低基數欄位的壓縮機會 |
| PS300 | ❌/⚠️ | 缺少統計資訊 | 謂詞下推失效 |
| PS301 | ⚠️ | 統計值非精確 | min/max 被標記為近似 |
| PS302 | ℹ️ | 僅舊版統計欄位 | 未寫入 min_value/max_value |
| PS303 | ℹ️ | 缺少 Page Index | 無法頁級剪枝 |
| PS304 | ℹ️ | 區間重疊嚴重 | 排序鍵缺失，剪枝率低 |
| PS400 | ℹ️ | 高空值率欄位 | 空值率超過 50% |
| PS401 | ℹ️ | 超大欄位 | 單欄位未壓縮超過 64MB |
| PS402 | ℹ️ | 長字串欄位 | 平均列長度超過 512 位元組 |

### 支援的 Parquet 特性

- ✅ Parquet v1 / v2（含 DataPageV2 的中繼資料欄位）
- ✅ 全部物理型別：BOOLEAN / INT32 / INT64 / INT96 / FLOAT / DOUBLE / BYTE_ARRAY / FIXED_LEN_BYTE_ARRAY
- ✅ LogicalType：STRING、DATE、TIME、TIMESTAMP（MILLIS/MICROS/NANOS）、DECIMAL、UUID、JSON、BSON、ENUM、INTEGER、FLOAT16、UNKNOWN
- ✅ ConvertedType 全量對應（舊式邏輯型別）
- ✅ 壓縮編解碼標識：UNCOMPRESSED / SNAPPY / GZIP / LZO / BROTLI / LZ4 / ZSTD / LZ4_RAW
- ✅ 巢狀結構：STRUCT / LIST / MAP，含 max definition & repetition level
- ✅ 欄位區塊統計：min/max、null_count、distinct_count、精確性標記
- ✅ Page Index / Bloom Filter 存在性標記
- ⚠️ 欄位加密檔案（PARE）：**明確拒絕解析**並給出清晰錯誤（不做任何解密嘗試）

### 退出碼約定

| 退出碼 | 含義 |
| --- | --- |
| `0` | 全部通過 |
| `1` | 命中 `--fail-on` 指定嚴重度，或輸入路徑無效 |
| `2` | 執行期錯誤（如檔案損毀、權限不足） |

---

## 💡 設計思路與迭代規劃

### 技術選型

| 決策 | 選擇 | 原因 |
| --- | --- | --- |
| 語言 | Python | Parquet 生態的事實通用語言，維運／資料團隊接受度最高 |
| 依賴 | **零** | 可嵌入任何環境（含受限的生產容器），安裝不可能失敗 |
| 協定層 | 自研 Thrift Compact 解碼 | 避免引入 thrift/pyarrow；協定本身僅約 200 行 |
| 解析範圍 | 僅 footer | 保證毫秒級；資料頁解碼交由專業引擎，不重複造輪子 |
| 輸出 | text / markdown / json / csv | 覆蓋人讀、文件、程式、試算表四類場景 |
| 規則組織 | 編號 + 嚴重度 + 建議 | 可解釋、可裁剪、可演進，便於團隊自訂基線 |

### 架構分層

```
┌─────────────────────────────────────────┐
│  CLI (cli.py)        參數解析 · 退出碼   │
├─────────────────────────────────────────┤
│  Report (report.py)  text/md/json/csv   │
├─────────────────────────────────────────┤
│  Analyzer (analyzer.py) 欄位畫像 · 規則  │
├─────────────────────────────────────────┤
│  Metadata (metadata.py) schema 樹 · 解碼 │
├─────────────────────────────────────────┤
│  Reader (reader.py)  footer 定位         │
├─────────────────────────────────────────┤
│  Thrift (thrift.py)  Compact Protocol    │
└─────────────────────────────────────────┘
```

### 迭代規劃

- **v1.1**：支援 Parquet Page Index（ColumnIndex/OffsetIndex）解析，輸出頁級 min/max 分佈
- **v1.2**：支援 Bloom Filter 命中率評估與欄位級索引建議
- **v1.3**：增加 SARIF 輸出，直接接入 GitHub Code Scanning
- **v1.4**：支援 ORC / Arrow IPC 的同類健檢能力
- **v2.0**：提供可插拔規則 SDK，支援團隊自訂規則包

---

## 🧪 測試

```bash
pip install -e ".[dev]"
pytest
```

測試覆蓋 Thrift 協定位元組級解碼、中繼資料模型、值解碼、規則引擎、CLI 與四種渲染格式，共 **99 個案例**，全部基於倉庫內已提交的樣本檔案，執行時不依賴 pyarrow。

重新產生樣本（僅在需要新夾具時才執行，**執行期不需要**）：

```bash
pip install pyarrow numpy
python scripts/generate_fixtures.py
```

---

## 📄 授權條款

[MIT License](./LICENSE) — 可自由用於個人與商業專案。

# 贡献指南 / Contributing / 貢獻指南

感谢你愿意为 **ParquetScope** 贡献代码！🎉

本项目为 **零第三方依赖** 的纯标准库实现，因此在接受任何 Pull Request 之前，请务必阅读以下约定。

---

## 🌍 语言

- Issue / PR 描述：中文、英文均可。
- 代码注释与文档字符串：英文优先，中文亦可。
- **README 必须同步更新三语版本**：`README.md`（简体中文）、`README.en.md`（English）、`README.zh-TW.md`（繁體中文）。

## 🚫 硬性红线（Hard Rules）

以下三条是本项目存在的意义，违反任意一条的 PR 将直接被关闭：

1. **不得引入任何第三方运行时依赖** — `src/parquetscope/**` 中只允许 `import` Python 标准库。
   `pyarrow` 等仅可在 `scripts/`（生成测试样本）与 `tests/`（交叉校验）中使用，且必须放在 `dev` 可选依赖内。
2. **不得复制任何既有项目的实现代码** — 所有解析逻辑需为独立实现（可参考公开的 Parquet 格式规范文档，但不得照抄 parquet-mr / Arrow / fastparquet 的源码）。
3. **不得提交未经测试的代码** — 新增规则、新增解码能力必须配套单元测试。

## 🛠 本地开发

```bash
git clone https://github.com/gitstq/ParquetScope.git
cd ParquetScope

# 安装（可编辑模式，仅开发用）
python3 -m pip install -e ".[dev]"

# 生成测试样本（需要 pyarrow，仅在缺样本或需要更新样本时执行）
python3 scripts/generate_fixtures.py

# 运行全部测试
python3 -m pytest tests -q
```

> 若你的环境无法安装 `pyarrow`，可以跳过 `generate_fixtures.py`——仓库已内置 `tests/data/*.parquet` 样本，
> `pytest` 本身不需要 `pyarrow`。

## 🧪 测试要求

| 变更类型 | 必须新增的测试 |
| --- | --- |
| 新增审计规则 | `tests/test_analyzer.py` 中新增触发用例 + 健康文件不触发用例 |
| 新增 Thrift / 类型解码能力 | `tests/test_thrift.py` 或 `tests/test_metadata.py` 的字节级用例 |
| 新增 CLI 命令或参数 | `tests/test_cli.py` 中的退出码 / 输出断言 |
| 修复缺陷 | 先写一个能复现该缺陷的失败测试，再修复 |

执行命令：

```bash
python3 -m pytest tests -q
```

CI（`.github/workflows/ci.yml`）会在 Python 3.9 / 3.10 / 3.11 / 3.12 / 3.13 上运行同一套测试。

## 📝 提交信息规范（Angular 风格）

```
feat: 新增 XXX 规则
fix: 修复 XXX 在 YYY 场景下的崩溃
docs: 补充 XXX 的三语说明
refactor: 重构 XXX 的解码流程
test: 补充 XXX 的边界用例
chore: 调整 XXX 配置
perf: 优化 XXX 的解析性能
```

规则 ID 命名规范：`PS{类别}{序号}`

| 类别前缀 | 含义 |
| --- | --- |
| `PS0xx` | 文件布局（小文件 / row group 切分） |
| `PS1xx` | Schema 结构（嵌套深度 / 列宽 / 命名） |
| `PS2xx` | 编码与压缩 |
| `PS3xx` | 统计信息与索引 |
| `PS4xx` | 列特征（高基数字典 / 宽字符串 / 常量列） |

## 🔍 新增一条审计规则的步骤

1. 在 `src/parquetscope/analyzer.py` 中新增 `_rule_xxx()` 函数，返回 `list[Finding]`。
2. 定义规则 ID、名称、严重级别（info / warn / error）、说明与建议文案。
3. 将函数注册进 `_RULES` 元组。
4. 若需要阈值，在 `src/parquetscope/types.py` 的 `DEFAULT_THRESHOLDS` 中登记默认值。
5. 在 `src/parquetscope/cli.py` 中登记对应的命令行覆盖参数（如需要）。
6. 补充测试 + 更新三语 README 的规则表。

## 📄 许可证

提交 PR 即表示你同意你的贡献以 **MIT License** 授权。

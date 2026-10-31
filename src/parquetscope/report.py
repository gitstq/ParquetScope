"""报告渲染层：把结构化结果渲染为 text / markdown / json / csv。

所有渲染函数均为纯函数，返回字符串，便于测试与二次集成。
"""

from __future__ import annotations

import csv
import io
import json
import unicodedata
from typing import Any, Iterable, Sequence

from .analyzer import AuditReport, ColumnProfile, Finding, format_bytes
from .metadata import ParquetMetadata, SchemaNode, iter_leaves

SEVERITY_ICON = {"info": "ℹ️", "warn": "⚠️", "error": "❌"}
SEVERITY_LABEL = {"info": "提示", "warn": "警告", "error": "严重"}


# --------------------------------------------------------------------------- #
# 对齐工具（支持中日韩宽字符）
# --------------------------------------------------------------------------- #
def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad(text: str, width: int, *, align: str = "left") -> str:
    space = max(0, width - _display_width(text))
    if align == "right":
        return " " * space + text
    return text + " " * space


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], aligns: str = "") -> str:
    """渲染等宽文本表格（单线框风格）。"""
    all_rows = [list(headers)] + [list(row) for row in rows]
    widths = [
        max(_display_width(str(row[index])) for row in all_rows) for index in range(len(headers))
    ]
    aligns = aligns or "l" * len(headers)

    def line(row: Sequence[str]) -> str:
        cells = [
            _pad(str(row[index]), widths[index], align="right" if aligns[index] == "r" else "left")
            for index in range(len(headers))
        ]
        return "  ".join(cells).rstrip()

    separator = "  ".join("-" * width for width in widths)
    out = [line(headers), separator]
    out.extend(line(row) for row in rows)
    return "\n".join(out)


def _fmt_int(value: float) -> str:
    return f"{int(value):,}"


def _fmt_ratio(value: float) -> str:
    return f"{value:.2f}x" if value else "-"


def _short(value: Any, limit: int = 28) -> str:
    if value is None:
        return "-"
    text = str(value)
    text = text.replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


# --------------------------------------------------------------------------- #
# info
# --------------------------------------------------------------------------- #
def render_info(meta: ParquetMetadata, fmt: str = "text", *, path: str = "") -> str:
    """渲染文件概览。"""
    if fmt == "json":
        payload = meta.to_dict(include_statistics=False)
        payload["path"] = path
        return _dumps(payload)

    rows: list[tuple[str, str]] = [
        ("文件路径", path or "-"),
        ("文件大小", format_bytes(meta.file_size)),
        ("Parquet 版本", str(meta.version) if meta.version is not None else "-"),
        ("写入器 (created_by)", meta.created_by or "-"),
        ("总行数", _fmt_int(meta.num_rows)),
        ("叶子列数", _fmt_int(meta.num_columns)),
        ("Row group 数", _fmt_int(meta.num_row_groups)),
        ("平均 row group 行数", _fmt_int(meta.avg_row_group_rows)),
        ("Schema 嵌套深度", str(meta.depth)),
        ("Schema 指纹", meta.schema_fingerprint()),
        ("未压缩体积", format_bytes(meta.total_uncompressed_size)),
        ("压缩后体积", format_bytes(meta.total_compressed_size)),
        ("整体压缩比", _fmt_ratio(meta.overall_compression_ratio)),
        ("Footer 长度", format_bytes(meta.footer_length)),
        ("加密文件", "是" if meta.encrypted else "否"),
    ]
    if meta.key_value_metadata:
        rows.append(("元数据键值项", ", ".join(sorted(meta.key_value_metadata)[:5])))

    if fmt == "markdown":
        return _md_kv("Parquet 文件概览", rows)
    if fmt == "csv":
        return _csv_rows(["指标", "取值"], [[k, v] for k, v in rows])

    width = max(_display_width(k) for k, _ in rows)
    lines = ["📦 Parquet 文件概览", ""]
    lines.extend(f"  {_pad(key, width)} : {value}" for key, value in rows)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def render_schema(meta: ParquetMetadata, fmt: str = "text", *, max_depth: int | None = None) -> str:
    """渲染 schema 树。"""
    if fmt == "json":
        return _dumps({"schema": meta.to_dict(include_statistics=False)["schema"]})

    lines: list[str] = []

    def walk(node: SchemaNode, prefix: str = "", is_last: bool = True, depth: int = 0) -> None:
        if max_depth is not None and depth > max_depth:
            return
        connector = "" if depth == 0 else ("└── " if is_last else "├── ")
        tag = "📁" if not node.is_leaf else "🔹"
        rep = node.element.repetition_name
        lines.append(f"{prefix}{connector}{tag} {node.name}  ({rep}) {node.element.annotate()}")
        child_prefix = prefix + ("" if depth == 0 else ("    " if is_last else "│   "))
        children = node.children
        for index, child in enumerate(children):
            walk(child, child_prefix, index == len(children) - 1, depth + 1)

    walk(meta.schema_root)

    header = [f"🌳 Schema 结构（{meta.num_columns} 个叶子列，深度 {meta.depth}）", ""]
    if fmt == "markdown":
        return "\n".join(
            [
                "### Schema 结构",
                "",
                "```",
                *lines,
                "```",
                "",
            ]
        )
    if fmt == "csv":
        rows = []
        for leaf in iter_leaves(meta.schema_root):
            rows.append(
                [
                    leaf.path,
                    leaf.element.repetition_name,
                    leaf.element.physical_name,
                    leaf.element.annotate(),
                    str(leaf.max_definition_level),
                    str(leaf.max_repetition_level),
                ]
            )
        return _csv_rows(["path", "repetition", "physical_type", "logical_type", "max_def", "max_rep"], rows)
    return "\n".join(header + lines)


# --------------------------------------------------------------------------- #
# rowgroups
# --------------------------------------------------------------------------- #
def render_rowgroups(meta: ParquetMetadata, fmt: str = "text") -> str:
    """渲染 row group 布局表。"""
    rows: list[list[str]] = []
    for rg in meta.row_groups:
        compressed = rg.total_compressed_size or sum(c.total_compressed_size for c in rg.columns)
        rows.append(
            [
                str(rg.ordinal),
                _fmt_int(rg.num_rows),
                format_bytes(rg.total_byte_size),
                format_bytes(compressed),
                _fmt_ratio(rg.compression_ratio),
                str(len(rg.sorting_columns)),
                _short(",".join(str(sc.column_index) for sc in rg.sorting_columns) or "-", 18),
            ]
        )
    headers = ["#", "行数", "未压缩", "压缩后", "压缩比", "排序列数", "排序列"]
    if fmt == "json":
        return _dumps(
            [
                {
                    "ordinal": rg.ordinal,
                    "num_rows": rg.num_rows,
                    "uncompressed_size": rg.total_byte_size,
                    "compressed_size": rg.total_compressed_size,
                    "compression_ratio": round(rg.compression_ratio, 4),
                    "sorting_columns": [
                        {
                            "column_index": sc.column_index,
                            "descending": sc.descending,
                            "nulls_first": sc.nulls_first,
                        }
                        for sc in rg.sorting_columns
                    ],
                }
                for rg in meta.row_groups
            ]
        )
    if fmt == "markdown":
        return _md_table(f"Row Group 布局（共 {len(rows)} 个）", headers, rows)
    if fmt == "csv":
        return _csv_rows(headers, rows)
    title = f"🗂️  Row Group 布局（共 {len(rows)} 个）"
    return "\n".join([title, "", _render_table(headers, rows, aligns="rrrrrrl")])


# --------------------------------------------------------------------------- #
# columns
# --------------------------------------------------------------------------- #
def render_columns(columns: Sequence[ColumnProfile], fmt: str = "text", *, limit: int = 0) -> str:
    """渲染列级画像表。"""
    selected = list(columns)
    truncated = False
    if limit and len(selected) > limit:
        selected = selected[:limit]
        truncated = True

    rows: list[list[str]] = []
    for col in selected:
        rows.append(
            [
                _short(col.path, 38),
                _short(col.annotated_type, 22),
                _short(col.codec, 12),
                _fmt_int(col.num_values),
                _fmt_int(col.null_count),
                f"{col.null_ratio:.1%}",
                _fmt_int(col.distinct_count) if col.distinct_count is not None else "-",
                format_bytes(col.total_uncompressed_size),
                format_bytes(col.total_compressed_size),
                _fmt_ratio(col.compression_ratio),
            ]
        )
    headers = ["列路径", "类型", "压缩", "行数", "空值数", "空值率", "去重数", "未压缩", "压缩后", "压缩比"]
    aligns = "llrrrrrrrr"

    if fmt == "json":
        payload = [col.to_dict() for col in selected]
        return _dumps({"columns": payload, "truncated": truncated})
    if fmt == "markdown":
        return _md_table(f"列级画像（{len(selected)}/{len(columns)} 列）", headers, rows)
    if fmt == "csv":
        return _csv_rows(headers, rows)

    title = f"📊 列级画像（{len(selected)}/{len(columns)} 列）"
    body = [title, "", _render_table(headers, rows, aligns=aligns)]
    if truncated:
        body.append("")
        body.append(f"（仅显示前 {limit} 列，使用 --limit 调整）")
    return "\n".join(body)


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #
def render_audit(report: AuditReport, fmt: str = "text", *, minimum: str = "info") -> str:
    """渲染体检报告。"""
    findings = report.findings_by_severity(minimum)
    if fmt == "json":
        return _dumps(report.to_dict(minimum_severity=minimum))

    counts = report.severity_counts
    rows: list[list[str]] = []
    for finding in findings:
        rows.append(
            [
                finding.code,
                f"{SEVERITY_ICON.get(finding.severity, '')} {SEVERITY_LABEL.get(finding.severity, finding.severity)}",
                finding.title,
                _short(finding.detail, 70),
            ]
        )
    headers = ["编号", "级别", "问题", "证据"]

    if fmt == "markdown":
        parts = [
            f"### 体检报告：`{report.path}`",
            "",
            f"- 健康评分：**{report.score}/100**",
            f"- 严重 {counts.get('error', 0)} / 警告 {counts.get('warn', 0)} / 提示 {counts.get('info', 0)}",
            "",
            _md_table("诊断项", headers, rows) if rows else "_未发现任何问题 ✅_",
            "",
        ]
        if rows:
            parts.append("#### 修复建议")
            parts.append("")
            for finding in findings:
                parts.append(f"- **{finding.code}** {finding.advice}")
            parts.append("")
        return "\n".join(parts)

    if fmt == "csv":
        return _csv_rows(["code", "severity", "title", "detail", "advice"],
                         [[f.code, f.severity, f.title, f.detail, f.advice] for f in findings])

    grade = _grade(report.score)
    lines = [
        f"🩺 体检报告：{report.path}",
        "",
        f"  健康评分 : {report.score}/100  {grade}",
        f"  诊断结论 : ❌ 严重 {counts.get('error', 0)}   ⚠️ 警告 {counts.get('warn', 0)}   ℹ️ 提示 {counts.get('info', 0)}",
        "",
    ]
    if rows:
        lines.append(_render_table(headers, rows))
        lines.append("")
        lines.append("💡 修复建议")
        for finding in findings:
            lines.append(f"  • [{finding.code}] {finding.advice}")
    else:
        lines.append("✅ 未发现任何问题，该文件布局健康。")
    return "\n".join(lines)


def _grade(score: int) -> str:
    if score >= 90:
        return "（优秀）"
    if score >= 75:
        return "（良好）"
    if score >= 60:
        return "（一般）"
    return "（需优化）"


# --------------------------------------------------------------------------- #
# doctor（目录级）
# --------------------------------------------------------------------------- #
def render_doctor(summary: dict[str, Any], fmt: str = "text") -> str:
    """渲染目录级体检汇总。"""
    if fmt == "json":
        return _dumps(summary)
    files: list[dict[str, Any]] = summary["files"]
    rows = [
        [
            _short(item["path"], 46),
            format_bytes(item["file_size"]),
            _fmt_int(item["num_rows"]),
            str(item["num_row_groups"]),
            _fmt_ratio(item["compression_ratio"]),
            str(item["score"]),
            str(item["errors"]),
            str(item["warnings"]),
        ]
        for item in files
    ]
    headers = ["文件", "大小", "行数", "RG 数", "压缩比", "评分", "严重", "警告"]
    stats = summary["summary"]
    head = [
        "🏥 数据集体检汇总",
        "",
        f"  文件数量 : {stats['num_files']}",
        f"  总行数   : {_fmt_int(stats['num_rows'])}",
        f"  总体积   : {format_bytes(stats['total_size'])}（压缩后 {format_bytes(stats['total_compressed_size'])}）",
        f"  整体压缩比: {_fmt_ratio(stats['compression_ratio'])}",
        f"  平均评分 : {stats['avg_score']}",
        f"  小文件数 : {stats['small_files']}（< {format_bytes(stats['small_file_threshold'])}）",
        f"  Schema 版本数 : {stats['schema_variants']}",
        "",
    ]
    if fmt == "markdown":
        parts = ["### 数据集体检汇总", ""]
        parts.extend(f"- {line.strip()}" for line in head[2:] if line.strip())
        parts.append("")
        parts.append(_md_table("文件明细", headers, rows))
        return "\n".join(parts)
    if fmt == "csv":
        return _csv_rows(headers, rows)
    lines = list(head)
    if rows:
        lines.append(_render_table(headers, rows, aligns="lrrrrrrr"))
    for drift in summary.get("schema_drifts", []):
        lines.append("")
        lines.append(f"🔀 Schema 漂移：{drift['fingerprint']} 出现在 {drift['count']} 个文件")
        for diff in drift["differences"][:8]:
            lines.append(f"    - {diff}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 通用序列化
# --------------------------------------------------------------------------- #
def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _csv_rows(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue().rstrip("\r\n")


def _md_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [f"**{title}**", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def _md_kv(title: str, rows: Sequence[tuple[str, str]]) -> str:
    lines = [f"### {title}", "", "| 指标 | 取值 |", "|---|---|"]
    for key, value in rows:
        escaped = str(value).replace("|", "\\|")
        lines.append(f"| {key} | {escaped} |")
    return "\n".join(lines)


__all__ = [
    "render_info",
    "render_schema",
    "render_rowgroups",
    "render_columns",
    "render_audit",
    "render_doctor",
]

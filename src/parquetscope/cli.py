"""命令行入口。

子命令::

    parquetscope info      文件概览
    parquetscope schema    schema 树
    parquetscope rowgroups row group 布局
    parquetscope columns   列级画像
    parquetscope audit     单文件/多文件体检（可 CI 门禁）
    parquetscope doctor    目录级数据集体检（小文件 + schema 漂移）
    parquetscope dump      导出完整元数据 JSON
    parquetscope rules     列出全部体检规则
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from . import types as T
from .analyzer import audit, build_column_profiles, list_rules
from .errors import ParquetScopeError
from .metadata import iter_leaves
from .reader import ParquetFile, iter_parquet_files, read_metadata
from .report import (
    render_audit,
    render_columns,
    render_doctor,
    render_info,
    render_rowgroups,
    render_schema,
)

FORMATS = ("text", "markdown", "json", "csv")
SEVERITY_CHOICES = ("info", "warn", "error", "none")


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parquetscope",
        description="ParquetScope — 零依赖的 Parquet 文件体检与列式存储审计引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  parquetscope info data.parquet\n"
            "  parquetscope schema data.parquet --format markdown\n"
            "  parquetscope columns data.parquet --format csv -o cols.csv\n"
            "  parquetscope audit 'warehouse/**/*.parquet' --fail-on error\n"
            "  parquetscope doctor ./warehouse --format json\n"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"parquetscope {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("paths", nargs="+", help="Parquet 文件、目录或通配符")
        sp.add_argument("-f", "--format", choices=FORMATS, default="text", help="输出格式")
        sp.add_argument("-o", "--output", help="写入文件（默认输出到标准输出）")

    # info ------------------------------------------------------------
    sp_info = sub.add_parser("info", help="文件概览")
    add_common(sp_info)

    # schema ----------------------------------------------------------
    sp_schema = sub.add_parser("schema", help="schema 结构树")
    add_common(sp_schema)
    sp_schema.add_argument("--max-depth", type=int, help="只输出到指定嵌套深度")

    # rowgroups -------------------------------------------------------
    sp_rg = sub.add_parser("rowgroups", help="row group 布局")
    add_common(sp_rg)

    # columns ---------------------------------------------------------
    sp_cols = sub.add_parser("columns", help="列级画像")
    add_common(sp_cols)
    sp_cols.add_argument("--limit", type=int, default=0, help="最多显示 N 列（0 表示全部）")

    # audit -----------------------------------------------------------
    sp_audit = sub.add_parser("audit", help="体检并给出诊断结论")
    add_common(sp_audit)
    sp_audit.add_argument("--min-severity", choices=("info", "warn", "error"), default="info",
                          help="报告中展示的最低级别")
    sp_audit.add_argument("--fail-on", choices=SEVERITY_CHOICES, default="none",
                          help="出现该级别及以上问题时返回非零退出码（CI 门禁）")
    sp_audit.add_argument("--rule", action="append", dest="rules",
                          help="只运行指定规则（可重复，如 --rule PS001）")
    sp_audit.add_argument("--target-row-group-mb", type=float, help="row group 推荐体积（MB）")
    sp_audit.add_argument("--min-row-group-mb", type=float, help="row group 最小体积（MB）")
    sp_audit.add_argument("--min-compression-ratio", type=float, help="最低可接受压缩比")
    sp_audit.add_argument("--max-columns", type=float, help="列数上限")
    sp_audit.add_argument("--max-null-ratio", type=float, help="空值率告警阈值（0~1）")
    sp_audit.add_argument("--min-file-mb", type=float, help="小文件判定阈值（MB）")

    # doctor ----------------------------------------------------------
    sp_doc = sub.add_parser("doctor", help="目录级数据集体检")
    add_common(sp_doc)
    sp_doc.add_argument("--min-severity", choices=("info", "warn", "error"), default="info")
    sp_doc.add_argument("--fail-on", choices=SEVERITY_CHOICES, default="none")
    sp_doc.add_argument("--rule", action="append", dest="rules")
    sp_doc.add_argument("--min-file-mb", type=float, help="小文件判定阈值（MB）")

    # dump ------------------------------------------------------------
    sp_dump = sub.add_parser("dump", help="导出完整元数据 JSON")
    add_common(sp_dump)
    sp_dump.add_argument("--no-statistics", action="store_true", help="不导出统计信息")

    # rules -----------------------------------------------------------
    sp_rules = sub.add_parser("rules", help="列出全部体检规则")
    sp_rules.add_argument("-f", "--format", choices=("text", "json"), default="text",
                          help="输出格式")
    sp_rules.add_argument("-o", "--output", help="写入文件（默认输出到标准输出）")

    return parser


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, float]:
    th: dict[str, float] = {}
    mapping = {
        "target_row_group_mb": ("target_row_group_bytes", 1024 * 1024),
        "min_row_group_mb": ("min_row_group_bytes", 1024 * 1024),
        "min_file_mb": ("min_file_bytes", 1024 * 1024),
        "min_compression_ratio": ("min_compression_ratio", 1),
        "max_columns": ("max_columns", 1),
        "max_null_ratio": ("high_null_ratio", 1),
    }
    for arg_name, (key, factor) in mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            th[key] = value * factor
    return th


# --------------------------------------------------------------------------- #
# 命令实现
# --------------------------------------------------------------------------- #
def _emit(text: str, output: str | None) -> None:
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {output}")
    else:
        print(text)


def _load(paths: Sequence[str]) -> list[tuple[str, Any]]:
    """加载元数据，返回 ``(路径, 元数据或异常)`` 列表。"""
    loaded: list[tuple[str, Any]] = []
    for file_path in iter_parquet_files(paths):
        try:
            with ParquetFile(file_path) as handle:
                loaded.append((str(file_path), handle.metadata))
        except ParquetScopeError as exc:
            loaded.append((str(file_path), exc))
    return loaded


def cmd_info(args: argparse.Namespace) -> int:
    blocks = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            blocks.append(f"❌ {path}: {item}")
            continue
        blocks.append(render_info(item, args.format, path=path))
    _emit("\n\n".join(blocks), args.output)
    return 1 if failures else 0


def cmd_schema(args: argparse.Namespace) -> int:
    blocks = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            blocks.append(f"❌ {path}: {item}")
            continue
        blocks.append(render_schema(item, args.format, max_depth=args.max_depth))
    _emit("\n\n".join(blocks), args.output)
    return 1 if failures else 0


def cmd_rowgroups(args: argparse.Namespace) -> int:
    blocks = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            blocks.append(f"❌ {path}: {item}")
            continue
        blocks.append(render_rowgroups(item, args.format))
    _emit("\n\n".join(blocks), args.output)
    return 1 if failures else 0


def cmd_columns(args: argparse.Namespace) -> int:
    blocks = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            blocks.append(f"❌ {path}: {item}")
            continue
        blocks.append(render_columns(build_column_profiles(item), args.format, limit=args.limit))
    _emit("\n\n".join(blocks), args.output)
    return 1 if failures else 0


def cmd_audit(args: argparse.Namespace) -> int:
    thresholds = _thresholds_from_args(args)
    reports = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            reports.append(f"❌ {path}: {item}")
            continue
        report = audit(item, path=path, thresholds=thresholds, enabled_rules=args.rules)
        reports.append(render_audit(report, args.format, minimum=args.min_severity))
        if _should_fail(report.max_severity, args.fail_on):
            failures += 1
    _emit("\n\n".join(reports), args.output)
    return 1 if failures else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    thresholds = _thresholds_from_args(args)
    files: list[dict[str, Any]] = []
    errors = 0
    reports: list[Any] = []
    schema_maps: dict[str, dict[str, str]] = {}

    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            errors += 1
            continue
        report = audit(item, path=path, thresholds=thresholds, enabled_rules=args.rules)
        reports.append(report)
        files.append(
            {
                "path": path,
                "file_size": item.file_size,
                "num_rows": item.num_rows,
                "num_row_groups": item.num_row_groups,
                "compression_ratio": round(item.overall_compression_ratio, 4),
                "score": report.score,
                "errors": report.severity_counts.get("error", 0),
                "warnings": report.severity_counts.get("warn", 0),
                "schema_fingerprint": item.schema_fingerprint(),
            }
        )
        schema_maps[item.schema_fingerprint()] = {
            leaf.path: leaf.element.annotate() for leaf in iter_leaves(item.schema_root)
        }
        if _should_fail(report.max_severity, args.fail_on):
            errors += 1

    if not files:
        _emit("未找到任何 Parquet 文件。", args.output)
        return 1

    small_threshold = thresholds.get("min_file_bytes", T.DEFAULT_THRESHOLDS["min_file_bytes"])
    total_size = sum(f["file_size"] for f in files)
    total_compressed = sum(r.metadata.total_compressed_size for r in reports)
    total_uncompressed = sum(r.metadata.total_uncompressed_size for r in reports)

    # schema 漂移分析
    drifts = _analyze_schema_drift(schema_maps, files)

    summary: dict[str, Any] = {
        "summary": {
            "num_files": len(files),
            "num_rows": sum(f["num_rows"] for f in files),
            "total_size": total_size,
            "total_compressed_size": total_compressed,
            "compression_ratio": round(
                (total_uncompressed / total_compressed) if total_compressed else 0.0, 4
            ),
            "avg_score": round(sum(f["score"] for f in files) / len(files), 1),
            "small_files": sum(1 for f in files if f["file_size"] < small_threshold),
            "small_file_threshold": small_threshold,
            "schema_variants": len(schema_maps),
        },
        "files": files,
        "schema_drifts": drifts,
    }
    _emit(render_doctor(summary, args.format), args.output)
    return 1 if errors else 0


def _analyze_schema_drift(
    schema_maps: dict[str, dict[str, str]], files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(schema_maps) <= 1:
        return []
    counts: dict[str, int] = {}
    for item in files:
        counts[item["schema_fingerprint"]] = counts.get(item["schema_fingerprint"], 0) + 1
    baseline_fp = max(counts, key=lambda fp: counts[fp])
    baseline = schema_maps[baseline_fp]

    drifts: list[dict[str, Any]] = []
    for fingerprint, schema_map in schema_maps.items():
        if fingerprint == baseline_fp:
            continue
        differences: list[str] = []
        for path, annotated in schema_map.items():
            if path not in baseline:
                differences.append(f"新增列 {path}（{annotated}）")
            elif baseline[path] != annotated:
                differences.append(f"类型变化 {path}：{baseline[path]} → {annotated}")
        for path, annotated in baseline.items():
            if path not in schema_map:
                differences.append(f"缺少列 {path}（{annotated}）")
        drifts.append(
            {
                "fingerprint": fingerprint,
                "count": counts[fingerprint],
                "baseline": baseline_fp,
                "differences": differences[:50],
            }
        )
    return drifts


def cmd_dump(args: argparse.Namespace) -> int:
    blocks: list[Any] = []
    failures = 0
    for path, item in _load(args.paths):
        if isinstance(item, Exception):
            failures += 1
            blocks.append({"path": path, "error": str(item)})
            continue
        payload = item.to_dict(include_statistics=not args.no_statistics)
        payload["path"] = path
        blocks.append(payload)
    _emit(_json_dumps(blocks if len(blocks) != 1 else blocks[0]), args.output)
    return 1 if failures else 0


def _json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def cmd_rules(args: argparse.Namespace) -> int:
    rows = list_rules()
    if args.format == "json":
        _emit(_json_dumps(rows), args.output)
        return 0
    lines = [f"{item['code']}  {item['title']}" for item in rows]
    _emit("\n".join(lines), args.output)
    return 0


def _should_fail(max_severity: str | None, fail_on: str) -> bool:
    if fail_on == "none" or max_severity is None:
        return False
    order = {"info": 0, "warn": 1, "error": 2}
    return order[max_severity] >= order[fail_on]


_HANDLERS = {
    "info": cmd_info,
    "schema": cmd_schema,
    "rowgroups": cmd_rowgroups,
    "columns": cmd_columns,
    "audit": cmd_audit,
    "doctor": cmd_doctor,
    "dump": cmd_dump,
    "rules": cmd_rules,
}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口，返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "rules":
        return cmd_rules(args)

    missing = [
        str(target)
        for target in args.paths
        if not any(ch in str(target) for ch in ("*", "?", "[")) and not Path(target).exists()
    ]
    if missing:
        print(f"路径不存在: {', '.join(missing)}", file=sys.stderr)
        return 1
    if not any(True for _ in iter_parquet_files(args.paths)):
        print(f"未找到匹配的 Parquet 文件: {' '.join(map(str, args.paths))}", file=sys.stderr)
        return 1
    try:
        return _HANDLERS[args.command](args)
    except ParquetScopeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("已中断", file=sys.stderr)
        return 130


__all__ = ["main", "build_parser"]

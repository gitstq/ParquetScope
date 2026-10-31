"""体检（audit）引擎：列级画像 + 规则诊断 + 健康评分。

设计目标
--------
1. **只读元数据**：不做数据页解码，因此可以在毫秒级完成 TB 级文件的体检。
2. **可解释**：每条规则产出编号、严重级别、证据指标与可执行建议。
3. **可门禁**：支持按严重级别返回非零退出码，直接接入 CI。

规则编号段::

    PS0xx  文件级布局与体积
    PS1xx  Schema 设计
    PS2xx  编码与压缩
    PS3xx  统计信息与索引（影响谓词下推）
    PS4xx  列级数据特征
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import types as T
from .metadata import ColumnChunkInfo, ParquetMetadata, RowGroupInfo, iter_leaves

SEVERITIES = ("info", "warn", "error")
_SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}
_SEVERITY_PENALTY = {"info": 1, "warn": 6, "error": 15}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class ColumnProfile:
    """跨 row group 聚合后的列画像。"""

    path: str
    annotated_type: str
    physical_type: str
    repetition: str
    codec: str
    encodings: list[str]
    num_values: int = 0
    null_count: int = 0
    distinct_count: int | None = None
    total_uncompressed_size: int = 0
    total_compressed_size: int = 0
    chunk_count: int = 0
    chunks_with_stats: int = 0
    chunks_with_index: int = 0
    chunks_with_bloom: int = 0
    min_value: Any = None
    max_value: Any = None
    global_sortedness: str = "unknown"
    deprecated_encoding: bool = False
    has_dictionary: bool = False
    is_int96: bool = False

    @property
    def compression_ratio(self) -> float:
        if self.total_compressed_size <= 0:
            return 0.0
        return self.total_uncompressed_size / self.total_compressed_size

    @property
    def null_ratio(self) -> float:
        if self.num_values <= 0:
            return 0.0
        return self.null_count / self.num_values

    @property
    def distinct_ratio(self) -> float | None:
        if self.distinct_count is None or self.num_values <= 0:
            return None
        return self.distinct_count / self.num_values

    @property
    def stats_coverage(self) -> float:
        if self.chunk_count == 0:
            return 0.0
        return self.chunks_with_stats / self.chunk_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "annotated_type": self.annotated_type,
            "physical_type": self.physical_type,
            "repetition": self.repetition,
            "codec": self.codec,
            "encodings": self.encodings,
            "num_values": self.num_values,
            "null_count": self.null_count,
            "null_ratio": round(self.null_ratio, 6),
            "distinct_count": self.distinct_count,
            "distinct_ratio": (
                round(self.distinct_ratio, 6) if self.distinct_ratio is not None else None
            ),
            "uncompressed_size": self.total_uncompressed_size,
            "compressed_size": self.total_compressed_size,
            "compression_ratio": round(self.compression_ratio, 4),
            "chunk_count": self.chunk_count,
            "stats_coverage": round(self.stats_coverage, 4),
            "has_page_index": self.chunks_with_index > 0,
            "has_bloom_filter": self.chunks_with_bloom > 0,
            "has_dictionary": self.has_dictionary,
            "min": _scalar(self.min_value),
            "max": _scalar(self.max_value),
            "global_sortedness": self.global_sortedness,
        }


@dataclass
class Finding:
    """一条诊断结论。"""

    code: str
    severity: str
    title: str
    detail: str
    advice: str
    subject: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "advice": self.advice,
            "subject": self.subject,
            "metrics": {key: _scalar(value) for key, value in self.metrics.items()},
        }


@dataclass
class AuditReport:
    """单文件体检报告。"""

    path: str
    metadata: ParquetMetadata
    columns: list[ColumnProfile]
    findings: list[Finding]
    thresholds: dict[str, float]
    score: int = 100

    # ------------------------------------------------------------------ #
    @property
    def severity_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in SEVERITIES}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    @property
    def max_severity(self) -> str | None:
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: _SEVERITY_ORDER[f.severity]).severity

    def findings_by_severity(self, minimum: str = "info") -> list[Finding]:
        floor = _SEVERITY_ORDER.get(minimum, 0)
        return [f for f in self.findings if _SEVERITY_ORDER[f.severity] >= floor]

    def to_dict(self, *, minimum_severity: str = "info") -> dict[str, Any]:
        return {
            "path": self.path,
            "score": self.score,
            "severity_counts": self.severity_counts,
            "thresholds": self.thresholds,
            "summary": {
                "file_size": self.metadata.file_size,
                "num_rows": self.metadata.num_rows,
                "num_columns": self.metadata.num_columns,
                "num_row_groups": self.metadata.num_row_groups,
                "schema_depth": self.metadata.depth,
                "created_by": self.metadata.created_by,
                "schema_fingerprint": self.metadata.schema_fingerprint(),
                "uncompressed_size": self.metadata.total_uncompressed_size,
                "compressed_size": self.metadata.total_compressed_size,
                "compression_ratio": round(self.metadata.overall_compression_ratio, 4),
                "avg_row_group_rows": int(self.metadata.avg_row_group_rows),
            },
            "columns": [col.to_dict() for col in self.columns],
            "findings": [f.to_dict() for f in self.findings_by_severity(minimum_severity)],
        }


def _scalar(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"0x{bytes(value).hex()}"[:66]
    return value


# --------------------------------------------------------------------------- #
# 列画像构建
# --------------------------------------------------------------------------- #
def build_column_profiles(meta: ParquetMetadata) -> list[ColumnProfile]:
    """把所有 row group 的列块聚合为列级画像。"""
    leaves = list(iter_leaves(meta.schema_root))
    leaf_by_path = {leaf.path: leaf for leaf in leaves}

    profiles: dict[str, ColumnProfile] = {}
    order: list[str] = []

    for rg in meta.row_groups:
        for chunk in rg.columns:
            path = chunk.path_in_schema
            leaf = leaf_by_path.get(path)
            if path not in profiles:
                annotated = leaf.element.annotate() if leaf else chunk.physical_name
                repetition = leaf.element.repetition_name if leaf else "-"
                profiles[path] = ColumnProfile(
                    path=path,
                    annotated_type=annotated,
                    physical_type=chunk.physical_name,
                    repetition=repetition,
                    codec=chunk.codec_name,
                    encodings=sorted(set(chunk.encodings)),
                )
                order.append(path)
            profile = profiles[path]

            profile.chunk_count += 1
            profile.num_values += chunk.num_values
            profile.total_uncompressed_size += chunk.total_uncompressed_size
            profile.total_compressed_size += chunk.total_compressed_size
            if chunk.has_offset_index or chunk.has_column_index:
                profile.chunks_with_index += 1
            if chunk.has_bloom_filter:
                profile.chunks_with_bloom += 1
            if chunk.has_dictionary:
                profile.has_dictionary = True
            if chunk.physical_type == T.TYPE_INT96:
                profile.is_int96 = True
            if any(enc in T.DEPRECATED_ENCODINGS for enc in chunk.encodings):
                profile.deprecated_encoding = True

            stats = chunk.statistics
            if stats is not None and stats.present:
                profile.chunks_with_stats += 1
                if stats.null_count:
                    profile.null_count += stats.null_count
                if stats.distinct_count is not None:
                    profile.distinct_count = (profile.distinct_count or 0) + stats.distinct_count
                if stats.min_value is not None:
                    profile.min_value = (
                        stats.min_value
                        if profile.min_value is None
                        else _safe_min(profile.min_value, stats.min_value)
                    )
                if stats.max_value is not None:
                    profile.max_value = (
                        stats.max_value
                        if profile.max_value is None
                        else _safe_max(profile.max_value, stats.max_value)
                    )

    result = [profiles[path] for path in order]
    for profile in result:
        profile.global_sortedness = _detect_sortedness(meta, profile.path)
    return result


def _safe_min(current: Any, candidate: Any) -> Any:
    try:
        return candidate if candidate < current else current
    except TypeError:
        return current


def _safe_max(current: Any, candidate: Any) -> Any:
    try:
        return candidate if candidate > current else current
    except TypeError:
        return current


def _detect_sortedness(meta: ParquetMetadata, path: str) -> str:
    """基于各 row group 的 min/max 推断列的全局有序性。"""
    mins: list[Any] = []
    maxs: list[Any] = []
    for rg in meta.row_groups:
        chunk = _find_chunk(rg, path)
        if chunk is None or chunk.statistics is None:
            continue
        if chunk.statistics.min_value is not None:
            mins.append(chunk.statistics.min_value)
        if chunk.statistics.max_value is not None:
            maxs.append(chunk.statistics.max_value)
    if len(mins) < 2 or len(mins) != len(maxs):
        return "unknown"
    return _sortedness_from_ranges(list(zip(mins, maxs)))


def _sortedness_from_ranges(ranges: Sequence[tuple[Any, Any]]) -> str:
    ascending = True
    descending = True
    comparable = 0
    for index in range(1, len(ranges)):
        prev_min, prev_max = ranges[index - 1]
        cur_min, cur_max = ranges[index]
        try:
            if cur_min < prev_max:
                ascending = False
            if cur_max > prev_min:
                descending = False
            comparable += 1
        except TypeError:
            return "unknown"
    if comparable == 0:
        return "unknown"
    if ascending and not descending:
        return "ascending"
    if descending and not ascending:
        return "descending"
    return "unsorted"


def _is_constant_column(col: ColumnProfile) -> bool:
    """基于 min/max 判断是否为单值列（所有 row group 取值区间退化为一点）。"""
    if col.min_value is None or col.max_value is None:
        return False
    try:
        return col.min_value == col.max_value
    except Exception:  # pragma: no cover - 不可比较类型
        return False


def _find_chunk(rg: RowGroupInfo, path: str) -> ColumnChunkInfo | None:
    for chunk in rg.columns:
        if chunk.path_in_schema == path:
            return chunk
    return None


# --------------------------------------------------------------------------- #
# 规则引擎
# --------------------------------------------------------------------------- #
def audit(
    meta: ParquetMetadata,
    *,
    path: str = "<memory>",
    thresholds: dict[str, float] | None = None,
    enabled_rules: Iterable[str] | None = None,
) -> AuditReport:
    """对单个文件的元数据执行全量体检。"""
    th = dict(T.DEFAULT_THRESHOLDS)
    if thresholds:
        th.update(thresholds)

    columns = build_column_profiles(meta)
    findings: list[Finding] = []

    for rule in _RULES:
        if enabled_rules is not None and rule.code not in enabled_rules:
            continue
        result = rule.check(meta, columns, th)
        if result is None:
            continue
        if isinstance(result, Finding):
            findings.append(result)
        else:
            findings.extend(result)

    findings.sort(key=lambda f: (-_SEVERITY_ORDER[f.severity], f.code))
    score = max(0, 100 - sum(_SEVERITY_PENALTY[f.severity] for f in findings))
    return AuditReport(
        path=path,
        metadata=meta,
        columns=columns,
        findings=findings,
        thresholds=th,
        score=score,
    )


@dataclass(frozen=True)
class _Rule:
    code: str
    check: Any  # (meta, columns, thresholds) -> Finding | list[Finding] | None


def _fmt_bytes(value: float) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < step or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} TB"  # pragma: no cover


def _fmt_int(value: float) -> str:
    return f"{int(value):,}"


def _rule_layout_small_file(meta, columns, th) -> Finding | None:
    if meta.file_size >= th["min_file_bytes"]:
        return None
    return Finding(
        code="PS001",
        severity="warn",
        title="文件体积过小（小文件问题）",
        detail=(
            f"文件大小 {_fmt_bytes(meta.file_size)}，低于推荐的 {_fmt_bytes(th['min_file_bytes'])}。"
        ),
        advice="批量合并为更大的文件（目标 128MB~1GB），可显著降低 NameNode/对象存储元数据压力与扫描开销。",
        metrics={"file_size": meta.file_size},
    )


def _rule_layout_no_row_groups(meta, columns, th) -> Finding | None:
    if meta.num_row_groups > 0:
        return None
    return Finding(
        code="PS002",
        severity="error",
        title="文件没有任何 row group",
        detail="footer 中 row_groups 为空，文件不含可读数据块。",
        advice="重新生成文件；若使用自研写入器，请确认已正确 flush 至少一个 row group。",
    )


def _rule_layout_tiny_row_groups(meta, columns, th) -> Finding | None:
    if not meta.row_groups:
        return None
    avg_bytes = meta.total_uncompressed_size / len(meta.row_groups)
    if avg_bytes >= th["target_row_group_bytes"]:
        return None
    severity = "warn" if avg_bytes >= th["min_row_group_bytes"] else "error"
    return Finding(
        code="PS003",
        severity=severity,
        title="row group 体积偏小",
        detail=(
            f"{len(meta.row_groups)} 个 row group，平均未压缩 {_fmt_bytes(avg_bytes)}，"
            f"低于推荐的 {_fmt_bytes(th['target_row_group_bytes'])}。"
        ),
        advice="增大写入端 row group 大小（如 pyarrow 的 row_group_size），使单个 row group 达到 128MB~1GB。",
        metrics={"avg_row_group_bytes": int(avg_bytes), "num_row_groups": meta.num_row_groups},
    )


def _rule_layout_few_rows_per_group(meta, columns, th) -> Finding | None:
    if not meta.row_groups:
        return None
    avg_rows = meta.avg_row_group_rows
    if avg_rows >= th["target_row_group_rows"]:
        return None
    if avg_rows >= th["min_row_group_rows"]:
        return None
    return Finding(
        code="PS004",
        severity="warn",
        title="row group 行数偏少",
        detail=(
            f"平均每个 row group 仅 {_fmt_int(avg_rows)} 行，"
            f"低于推荐的 {_fmt_int(th['target_row_group_rows'])} 行。"
        ),
        advice="按行数切分 row group（100 万行以上），可减少元数据总量并提升顺序扫描吞吐。",
        metrics={"avg_row_group_rows": int(avg_rows)},
    )


def _rule_layout_skew(meta, columns, th) -> Finding | None:
    if len(meta.row_groups) < 2:
        return None
    sizes = [rg.total_byte_size or sum(c.total_uncompressed_size for c in rg.columns) for rg in meta.row_groups]
    smallest = min(sizes)
    largest = max(sizes)
    if smallest <= 0:
        return None
    skew = largest / smallest
    if skew <= th["max_row_group_skew"]:
        return None
    return Finding(
        code="PS005",
        severity="warn",
        title="row group 体积分布不均",
        detail=(
            f"最大/最小 row group 体积比为 {skew:.1f}x"
            f"（{_fmt_bytes(largest)} vs {_fmt_bytes(smallest)}）。"
        ),
        advice="写入时固定 row group 目标体积，或对历史文件执行 compaction 重写。",
        metrics={"skew": round(skew, 2), "max_bytes": largest, "min_bytes": smallest},
    )


def _rule_layout_huge_row_group(meta, columns, th) -> Finding | None:
    limit = 512 * 1024 * 1024
    oversized = [
        rg.ordinal for rg in meta.row_groups if (rg.total_byte_size or 0) > limit
    ]
    if not oversized:
        return None
    return Finding(
        code="PS006",
        severity="info",
        title="存在超大 row group",
        detail=f"row group {', '.join(map(str, oversized[:5]))} 未压缩体积超过 {_fmt_bytes(limit)}。",
        advice="超大 row group 会降低并行度并抬高读取端内存峰值，建议控制在 1GB 以内。",
        metrics={"oversized_row_groups": oversized[:10]},
    )


def _rule_schema_wide(meta, columns, th) -> Finding | None:
    if meta.num_columns <= th["max_columns"]:
        return None
    return Finding(
        code="PS100",
        severity="warn",
        title="超宽表：列数过多",
        detail=f"共 {meta.num_columns} 个叶子列，超过建议上限 {int(th['max_columns'])}。",
        advice="考虑垂直拆分冷热列，或把稀疏字段收敛为 MAP/STRUCT，降低元数据与 IO 放大。",
        metrics={"num_columns": meta.num_columns},
    )


def _rule_schema_deep(meta, columns, th) -> Finding | None:
    if meta.depth <= th["max_schema_depth"]:
        return None
    return Finding(
        code="PS101",
        severity="warn",
        title="schema 嵌套过深",
        detail=f"最大嵌套深度 {meta.depth} 层，超过建议上限 {int(th['max_schema_depth'])}。",
        advice="扁平化高频访问字段；深层嵌套会抬高 definition/repetition level 的编解码成本。",
        metrics={"depth": meta.depth},
    )


def _rule_schema_int96(meta, columns, th) -> Finding | None:
    hits = [col.path for col in columns if col.is_int96]
    if not hits:
        return None
    return Finding(
        code="PS102",
        severity="warn",
        title="使用了已废弃的 INT96 时间戳",
        detail=f"列 {', '.join(hits[:5])} 使用 INT96 存储时间戳（Parquet 已废弃该类型）。",
        advice="改用 INT64 + TIMESTAMP(MICROS/MILLIS) 逻辑类型，避免跨引擎兼容问题（部分引擎已不再支持 INT96）。",
        metrics={"columns": hits[:10]},
    )


def _rule_schema_no_writer(meta, columns, th) -> Finding | None:
    if meta.created_by:
        return None
    return Finding(
        code="PS103",
        severity="info",
        title="缺少 created_by 写入器标识",
        detail="footer 未记录写入器信息，排查跨引擎兼容性问题时缺少线索。",
        advice="使用主流写入器（pyarrow / parquet-mr / duckdb 等），或在自研写入器中写入 created_by。",
    )


def _rule_encoding_deprecated(meta, columns, th) -> Finding | None:
    hits: list[str] = []
    for col in columns:
        for enc in col.encodings:
            if enc in T.DEPRECATED_ENCODINGS and enc != "BIT_PACKED":
                hits.append(f"{col.path}:{enc}")
    if not hits:
        return None
    return Finding(
        code="PS200",
        severity="warn",
        title="使用了已废弃的编码方式",
        detail="、".join(hits[:5]),
        advice="升级写入器并使用 RLE_DICTIONARY / DELTA_BINARY_PACKED 等现代编码。",
        metrics={"encodings": hits[:10]},
    )


def _rule_encoding_uncompressed(meta, columns, th) -> Finding | None:
    big = [
        col
        for col in columns
        if col.codec == "UNCOMPRESSED"
        and col.total_uncompressed_size > th["uncompressed_column_bytes"]
    ]
    if not big:
        return None
    total = sum(col.total_uncompressed_size for col in big)
    return Finding(
        code="PS201",
        severity="warn",
        title="大列未启用压缩",
        detail=(
            f"{len(big)} 个列使用 UNCOMPRESSED，累计未压缩体积 {_fmt_bytes(total)}"
            f"（例如 {big[0].path}）。"
        ),
        advice="为字符串/数值列启用 ZSTD 或 SNAPPY；ZSTD 通常在压缩率与解压速度上更均衡。",
        metrics={"columns": [col.path for col in big[:10]], "uncompressed_bytes": total},
    )


def _rule_encoding_low_ratio(meta, columns, th) -> Finding | None:
    ratio = meta.overall_compression_ratio
    if ratio == 0 or ratio >= th["min_compression_ratio"]:
        return None
    compressed_any = any(rg.total_compressed_size > 0 for rg in meta.row_groups)
    if not compressed_any:
        return None
    return Finding(
        code="PS202",
        severity="info",
        title="整体压缩收益偏低",
        detail=f"整体压缩比为 {ratio:.2f}x，低于参考值 {th['min_compression_ratio']}x。",
        advice="若数据本身随机性高（如已加密/哈希值）可忽略；否则尝试 ZSTD 或对字符串列先做字典编码。",
        metrics={"compression_ratio": round(ratio, 3)},
    )


def _rule_encoding_dictionary_missed(meta, columns, th) -> Finding | None:
    """低基数列未使用字典编码。

    优先使用 distinct_count；多数写入器不落盘该字段时，退化为「min == max 的单值列」
    启发式判定，仍能发现最典型的字典编码漏用场景。
    """
    candidates: list[tuple[str, Any]] = []
    for col in columns:
        if col.has_dictionary:
            continue
        if col.num_values < th["low_cardinality_min_rows"]:
            continue
        if col.distinct_count is not None:
            ratio = col.distinct_count / max(1, col.num_values)
            if ratio <= th["low_cardinality_ratio"]:
                candidates.append((col.path, round(ratio, 4)))
            continue
        if _is_constant_column(col):
            candidates.append((col.path, "single-value"))
    if not candidates:
        return None
    return Finding(
        code="PS203",
        severity="info",
        title="低基数列未使用字典编码",
        detail=(
            f"{len(candidates)} 个低基数列未启用字典编码，例如 "
            + "、".join(f"{path}({ratio})" for path, ratio in candidates[:3])
        ),
        advice="对枚举/状态码/地区等低基数列启用字典编码，可显著压缩体积并加速过滤。",
        metrics={"columns": [path for path, _ in candidates[:10]]},
    )


def _rule_stats_missing(meta, columns, th) -> Finding | None:
    # INT96 的排序顺序在规范中未定义，主流写入器不为其生成统计，属于预期行为
    scored = [col for col in columns if not col.is_int96]
    missing = [col.path for col in scored if col.chunks_with_stats < col.chunk_count]
    if not missing:
        return None
    total_chunks = sum(col.chunk_count for col in scored)
    missing_chunks = sum(col.chunk_count - col.chunks_with_stats for col in scored)
    ratio = missing_chunks / max(1, total_chunks)
    severity = "error" if ratio >= 0.5 else "warn"
    return Finding(
        code="PS300",
        severity=severity,
        title="列块缺少统计信息",
        detail=(
            f"{missing_chunks}/{total_chunks} 个列块没有 statistics（涉及 {len(missing)} 列），"
            "谓词下推与 row group 剪枝将失效。"
        ),
        advice="写入时开启统计信息采集（多数引擎默认开启，关闭常见于手工构造的元数据或超长字符串列被截断）。",
        metrics={"missing_chunks": missing_chunks, "total_chunks": total_chunks},
    )


def _rule_stats_inexact(meta, columns, th) -> Finding | None:
    hits: list[str] = []
    for rg in meta.row_groups:
        for chunk in rg.columns:
            stats = chunk.statistics
            if stats and (not stats.is_min_exact or not stats.is_max_exact):
                hits.append(chunk.path_in_schema)
    if not hits:
        return None
    return Finding(
        code="PS301",
        severity="warn",
        title="统计信息被标记为非精确值",
        detail=f"{len(hits)} 个列块的 min/max 被标记为 is_*_value_exact=false，例如 {hits[0]}。",
        advice="截断/近似统计会让查询引擎误判数据范围，必要时重写文件以生成精确统计。",
        metrics={"columns": sorted(set(hits))[:10]},
    )


def _rule_stats_deprecated_fields(meta, columns, th) -> Finding | None:
    hits: list[str] = []
    for rg in meta.row_groups:
        for chunk in rg.columns:
            stats = chunk.statistics
            if stats is not None and stats.has_deprecated_only:
                hits.append(chunk.path_in_schema)
    if not hits:
        return None
    return Finding(
        code="PS302",
        severity="info",
        title="仅使用旧版 min/max 统计字段",
        detail=f"{len(hits)} 个列块只写入了 deprecated 的 min/max，未写入 min_value/max_value。",
        advice="新版读取器优先读取 min_value/max_value；建议升级写入器以输出新字段。",
        metrics={"columns": sorted(set(hits))[:10]},
    )


def _rule_stats_no_page_index(meta, columns, th) -> Finding | None:
    if meta.file_size < 64 * 1024 * 1024:
        return None
    total_chunks = sum(col.chunk_count for col in columns)
    if total_chunks == 0:
        return None
    with_index = sum(col.chunks_with_index for col in columns)
    if with_index >= total_chunks:
        return None
    return Finding(
        code="PS303",
        severity="info",
        title="缺少 Page Index（offset/column index）",
        detail=f"{total_chunks - with_index}/{total_chunks} 个列块没有 page index。",
        advice="开启 page index 写入，可让查询引擎在页级剪枝，点查场景收益明显。",
        metrics={"missing": total_chunks - with_index, "total": total_chunks},
    )


def _rule_stats_overlap(meta, columns, th) -> Finding | None:
    if len(meta.row_groups) < 4:
        return None
    unsorted = [col.path for col in columns if col.global_sortedness == "unsorted"]
    if len(unsorted) < max(1, len(columns) // 2):
        return None
    return Finding(
        code="PS304",
        severity="info",
        title="多数列的 row group 取值区间相互重叠",
        detail=f"{len(unsorted)}/{len(columns)} 列的 row group 区间无序，范围查询将命中更多 row group。",
        advice="按高频过滤列排序后再写入（如 ORDER BY 时间列），可显著提升 row group 剪枝率。",
        metrics={"unsorted_columns": unsorted[:10]},
    )


def _rule_column_high_null(meta, columns, th) -> Finding | None:
    hits = [(col.path, col.null_ratio) for col in columns if col.null_ratio > th["high_null_ratio"]]
    if not hits:
        return None
    hits.sort(key=lambda item: item[1], reverse=True)
    return Finding(
        code="PS400",
        severity="info",
        title="存在高空值率列",
        detail=(
            f"{len(hits)} 个列空值率超过 {th['high_null_ratio']:.0%}，"
            f"最高为 {hits[0][0]}（{hits[0][1]:.1%}）。"
        ),
        advice="空值率极高的列可考虑拆表或使用稀疏结构；同时确认上游数据质量。",
        metrics={"columns": [path for path, _ in hits[:10]]},
    )


def _rule_column_huge(meta, columns, th) -> Finding | None:
    hits = [
        col
        for col in columns
        if col.total_uncompressed_size > th["large_column_bytes"]
    ]
    if not hits:
        return None
    hits.sort(key=lambda col: col.total_uncompressed_size, reverse=True)
    return Finding(
        code="PS401",
        severity="info",
        title="存在超大列",
        detail=(
            f"{hits[0].path} 未压缩体积 {_fmt_bytes(hits[0].total_uncompressed_size)}，"
            f"超过 {_fmt_bytes(th['large_column_bytes'])}。"
        ),
        advice="检查是否存在超长文本/二进制字段，必要时拆分存储或开启更强的压缩。",
        metrics={"columns": [col.path for col in hits[:5]]},
    )


def _rule_column_wide_strings(meta, columns, th) -> Finding | None:
    hits: list[tuple[str, float]] = []
    for col in columns:
        if col.physical_type not in ("BYTE_ARRAY", "FIXED_LEN_BYTE_ARRAY"):
            continue
        if col.num_values <= 0:
            continue
        avg = col.total_uncompressed_size / col.num_values
        if avg > th["large_string_avg_bytes"]:
            hits.append((col.path, avg))
    if not hits:
        return None
    hits.sort(key=lambda item: item[1], reverse=True)
    return Finding(
        code="PS402",
        severity="info",
        title="存在平均长度偏大的字符串列",
        detail=(
            f"{hits[0][0]} 平均每行 {_fmt_bytes(hits[0][1])}，"
            f"超过参考阈值 {int(th['large_string_avg_bytes'])} 字节。"
        ),
        advice="长文本建议外置存储或开启 ZSTD；同时确认是否需要对该列建立 bloom filter。",
        metrics={"columns": [path for path, _ in hits[:5]]},
    )


_RULES: tuple[_Rule, ...] = (
    _Rule("PS001", _rule_layout_small_file),
    _Rule("PS002", _rule_layout_no_row_groups),
    _Rule("PS003", _rule_layout_tiny_row_groups),
    _Rule("PS004", _rule_layout_few_rows_per_group),
    _Rule("PS005", _rule_layout_skew),
    _Rule("PS006", _rule_layout_huge_row_group),
    _Rule("PS100", _rule_schema_wide),
    _Rule("PS101", _rule_schema_deep),
    _Rule("PS102", _rule_schema_int96),
    _Rule("PS103", _rule_schema_no_writer),
    _Rule("PS200", _rule_encoding_deprecated),
    _Rule("PS201", _rule_encoding_uncompressed),
    _Rule("PS202", _rule_encoding_low_ratio),
    _Rule("PS203", _rule_encoding_dictionary_missed),
    _Rule("PS300", _rule_stats_missing),
    _Rule("PS301", _rule_stats_inexact),
    _Rule("PS302", _rule_stats_deprecated_fields),
    _Rule("PS303", _rule_stats_no_page_index),
    _Rule("PS304", _rule_stats_overlap),
    _Rule("PS400", _rule_column_high_null),
    _Rule("PS401", _rule_column_huge),
    _Rule("PS402", _rule_column_wide_strings),
)


def list_rules() -> list[dict[str, str]]:
    """列出全部规则（供 ``rules`` 命令与文档生成使用）。"""
    descriptions = {
        "PS001": "文件体积过小（小文件问题）",
        "PS002": "文件没有任何 row group",
        "PS003": "row group 体积偏小",
        "PS004": "row group 行数偏少",
        "PS005": "row group 体积分布不均",
        "PS006": "存在超大 row group",
        "PS100": "超宽表：列数过多",
        "PS101": "schema 嵌套过深",
        "PS102": "使用了已废弃的 INT96 时间戳",
        "PS103": "缺少 created_by 写入器标识",
        "PS200": "使用了已废弃的编码方式",
        "PS201": "大列未启用压缩",
        "PS202": "整体压缩收益偏低",
        "PS203": "低基数列未使用字典编码",
        "PS300": "列块缺少统计信息",
        "PS301": "统计信息被标记为非精确值",
        "PS302": "仅使用旧版 min/max 统计字段",
        "PS303": "缺少 Page Index",
        "PS304": "row group 取值区间重叠，剪枝效率低",
        "PS400": "存在高空值率列",
        "PS401": "存在超大列",
        "PS402": "存在平均长度偏大的字符串列",
    }
    return [
        {"code": rule.code, "title": descriptions.get(rule.code, rule.code)} for rule in _RULES
    ]


__all__ = [
    "audit",
    "build_column_profiles",
    "list_rules",
    "ColumnProfile",
    "Finding",
    "AuditReport",
    "SEVERITIES",
    "format_bytes",
]

format_bytes = _fmt_bytes

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = (PROJECT_ROOT / "data" / "qlib").resolve()
FROZEN_ROOT = Path(r"C:\Users\HYSHEN\AlphaCouncil2-AI").resolve()
LEGACY_ROOTS = (
    Path(r"C:\XuanJiQuant-QlibData").resolve(),
    Path(r"C:\AlphaCouncil-QlibData").resolve(),
)


@dataclass(frozen=True)
class PathResolution:
    recorded_path: str
    resolved_path: str
    path_state: str
    resolution_reason: str


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validated_active_root(candidate: Path) -> Path:
    resolved = candidate.resolve()
    if _inside(resolved, FROZEN_ROOT) or any(
        _inside(resolved, root) for root in LEGACY_ROOTS
    ):
        raise ValueError(f"活动 Qlib 数据根禁止使用旧路径或冻结备份: {resolved}")
    return resolved


def data_root() -> Path:
    configured = os.environ.get("QLIB_DATA_ROOT", "").strip()
    return _validated_active_root(
        Path(configured) if configured else DEFAULT_DATA_ROOT
    )


def resolve_recorded_path(value: str | Path | None) -> PathResolution:
    recorded = str(value or "")
    if not recorded:
        return PathResolution(
            recorded_path="",
            resolved_path="",
            path_state="missing_historical",
            resolution_reason="历史记录没有路径",
        )

    path = Path(recorded).resolve()
    active = data_root()
    if _inside(path, FROZEN_ROOT):
        return PathResolution(
            recorded_path=recorded,
            resolved_path="",
            path_state="rejected_frozen",
            resolution_reason="冻结备份路径只供审计展示",
        )
    if _inside(path, active):
        exists = path.exists()
        return PathResolution(
            recorded_path=recorded,
            resolved_path=str(path) if exists else "",
            path_state="active" if exists else "missing_historical",
            resolution_reason="当前活动路径" if exists else "当前记录指向的文件不存在",
        )
    for legacy in LEGACY_ROOTS:
        if _inside(path, legacy):
            mapped = active.joinpath(path.relative_to(legacy)).resolve()
            exists = mapped.exists()
            return PathResolution(
                recorded_path=recorded,
                resolved_path=str(mapped) if exists else "",
                path_state="mapped_legacy" if exists else "missing_historical",
                resolution_reason=(
                    "旧外部数据根已映射到当前活动数据根"
                    if exists
                    else "旧路径对应的当前文件不存在"
                ),
            )
    return PathResolution(
        recorded_path=recorded,
        resolved_path="",
        path_state="missing_historical",
        resolution_reason="路径不属于活动数据根",
    )


def resolve_data_path(*parts: str) -> Path:
    root = data_root()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path is outside Qlib data root: {target}")
    return target

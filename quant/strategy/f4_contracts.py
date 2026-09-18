"""Stable contracts for research-only F4 portfolio validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

F4_BUILDING = "f4_building"
F4_BLOCKED = "f4_blocked"
F4_REJECTED = "f4_rejected"
F4_RESEARCH_CANDIDATE = "f4_research_candidate"


def authority_fields() -> dict[str, object]:
    return {"promotion_state": "research_only", "execution_authority": False}


class F4Blocked(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(
            f"{self.reason_code}: {self.detail}" if self.detail else self.reason_code
        )


@dataclass(frozen=True, slots=True)
class F4ValidationIdentity:
    market_date: str
    factor_snapshot_id: str
    factor_data_version: str
    factor_universe_version: str
    pit_dataset_version: str
    pit_manifest_hash: str
    pit_quality_report_id: str
    industry_version: str
    benchmark_version: str
    pipeline_version: str
    candidate_spec_version: str
    portfolio_policy_version: str
    cost_model_version: str
    gate_version: str

    @property
    def validation_id(self) -> str:
        payload = json.dumps(
            asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "validation_id": self.validation_id, **authority_fields()}

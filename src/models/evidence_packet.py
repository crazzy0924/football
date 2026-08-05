"""
单场赛前证据包系统

核心转变: 从"覆盖所有联赛"收缩为"深度研究单场未来比赛"
不再追求数据库无限扩张, 而是为每一场比赛建立不可篡改的时间戳证据链。

证据包结构:
  MatchIdentity     — 比赛是谁 vs 谁, 何时何地
  TeamPublicInfo    — 球队公开信息 (带来源+抓取时间)
  MarketEnvironment — 赔率环境 (早盘/午盘/终盘, 含盘口变化轨迹)
  Snapshots         — 多时间节点快照 (T-24h, T-6h, lineup, pre-kickoff)
  PredictionFreeze  — 开球前冻结预测 (不可修改)
  PostMatchAudit    — 赛后审计 (只追加, 不修改)

规则:
  1. 所有数据保留来源、观察时间和抓取时间
  2. 无明确时间的内容不精确化 → 标注 "时间: 未知"
  3. 同一来源重复信息去重 → 不重复计数为多份证据
  4. 缺失数据明确标注 → 将不确定性保留在结果中
  5. 开球后不能回溯修改任何预测
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# ============================================================
# 数据结构
# ============================================================

@dataclass
class EvidenceItem:
    """单条证据"""
    key: str                          # e.g. "team_form_last5"
    value: Any                        # 证据内容
    source: str                       # 来源, e.g. "API-Football /fixtures"
    observed_at: str                  # 观察时间 ISO8601
    retrieved_at: str = ""            # 实际抓取时间
    confidence: str = "confirmed"     # confirmed / uncertain / disputed
    notes: str = ""                   # 附加说明


@dataclass
class MatchIdentity:
    """比赛身份 —— 不可变标识"""
    home_team_id: str                 # 统一球队ID, 如 CLQ_OLY
    away_team_id: str
    home_team_display: str            # 显示名, 如 "奥林匹亚科斯"
    away_team_display: str
    competition: str                  # CLQ / EL / ECL / PL / ...
    kickoff_time: str                 # ISO8601
    venue: str = ""                   # 球场
    is_neutral_venue: bool = False    # 中立场地?
    match_api_id: str = ""            # 外部API的比赛ID

    def match_label(self) -> str:
        return f"{self.home_team_display} vs {self.away_team_display} ({self.competition})"


@dataclass
class Snapshot:
    """单次快照 —— 不可变时间节点

    每个快照是一个完整的时间切面, 包含当时所有可用证据。
    新信息创建新快照, 不修改旧快照。
    """
    snapshot_id: str                  # e.g. "T-24h", "T-6h", "lineup", "freeze"
    label: str                        # 人类可读, e.g. "赛前24小时"
    created_at: str                   # ISO8601
    evidence: list[EvidenceItem] = field(default_factory=list)

    # 不确定性标记
    missing_data: list[str] = field(default_factory=list)  # 哪些数据缺失
    uncertainty_level: str = "low"    # low / medium / high / extreme

    # 内容哈希 (防篡改)
    content_hash: str = ""


@dataclass
class FrozenPrediction:
    """开球前冻结预测 —— 不可修改

    一旦冻结, 即使后来发现输入错误, 也只能新增更正记录,
    不能修改此对象。
    """
    match: MatchIdentity
    frozen_at: str                    # 冻结时间
    cutoff: str                       # 预设截止时间

    # 完整比分分布 (必须输出, 即使证据不足)
    score_distribution: dict[str, float] = field(default_factory=dict)
    # {"1-0": 0.12, "2-0": 0.09, "1-1": 0.08, ...}

    # 胜平负
    home_win_prob: float = 0.0
    draw_prob: float = 0.0
    away_win_prob: float = 0.0

    # 市场
    over_25_prob: float = 0.0
    btts_prob: float = 0.0

    # 不确定性声明
    uncertainty_note: str = ""
    evidence_gaps: list[str] = field(default_factory=list)

    # 防篡改哈希
    prediction_hash: str = ""


@dataclass
class PostMatchAudit:
    """赛后审计 —— 只追加, 不修改

    比赛结束后追加赛果和复盘, 但绝不修改冻结预测。
    如果发现输入错误, 只能新增更正记录, 不能改原始文件。
    """
    match: MatchIdentity
    actual_score: str = ""            # e.g. "2-1"
    actual_result: str = ""           # "H" / "D" / "A"
    audit_added_at: str = ""

    # 对照
    prediction_correct_direction: bool = False
    brier_score: float = 0.0
    log_loss: float = 0.0

    # 复盘笔记 (追加, 不修改)
    review_notes: list[str] = field(default_factory=list)

    # 错误更正 (如果赛后发现输入错误)
    corrections: list[dict] = field(default_factory=list)


# ============================================================
# 证据包构建器
# ============================================================

class EvidencePacketBuilder:
    """为单场比赛构建完整证据包

    流程:
      1. 确认比赛身份 MatchIdentity
      2. 收集 T-24h 快照 (球队信息+初盘赔率)
      3. 收集 T-6h 快照 (更新赔率+阵容信息)
      4. 收集 lineup 快照 (确认首发)
      5. 开球前 freeze → 输出 FrozenPrediction
      6. 赛后追加 PostMatchAudit
    """

    def __init__(self, storage_dir: str | Path = ""):
        base = Path(storage_dir or Path(__file__).resolve().parents[2] / "data" / "evidence_packets")
        self._dir = base
        self._dir.mkdir(parents=True, exist_ok=True)

        self._match: MatchIdentity | None = None
        self._snapshots: list[Snapshot] = []
        self._frozen: FrozenPrediction | None = None
        self._audit: PostMatchAudit | None = None

    # ---- Step 1: 确认比赛身份 ----

    def identify_match(self, home_id: str, away_id: str, competition: str,
                       kickoff: str, venue: str = "", neutral: bool = False,
                       home_display: str = "", away_display: str = "",
                       api_id: str = "") -> MatchIdentity:
        """建立比赛身份 —— 整个证据链的根"""
        from src.data.team_registry import resolve_team

        h = resolve_team(home_id)
        a = resolve_team(away_id)

        self._match = MatchIdentity(
            home_team_id=h.team_id if h else home_id,
            away_team_id=a.team_id if a else away_id,
            home_team_display=home_display or (h.primary_name if h else home_id),
            away_team_display=away_display or (a.primary_name if a else away_id),
            competition=competition,
            kickoff_time=kickoff,
            venue=venue,
            is_neutral_venue=neutral,
            match_api_id=api_id,
        )
        logger.info(f"证据包初始化: {self._match.match_label()}")
        return self._match

    # ---- Step 2-4: 收集快照 ----

    def create_snapshot(self, snapshot_id: str, label: str,
                        evidence_list: list[EvidenceItem],
                        missing: list[str] | None = None) -> Snapshot:
        """创建新快照 —— 不可变时间切面

        新信息创建新快照, 不修改旧快照。
        """
        if self._match is None:
            raise RuntimeError("请先调用 identify_match() 建立比赛身份")

        snap = Snapshot(
            snapshot_id=snapshot_id,
            label=label,
            created_at=datetime.now().isoformat(),
            evidence=evidence_list,
            missing_data=missing or [],
            uncertainty_level=self._assess_uncertainty(evidence_list, missing or []),
        )
        snap.content_hash = self._hash_snapshot(snap)
        self._snapshots.append(snap)

        logger.info(f"快照 [{snapshot_id}] 创建: {len(evidence_list)} 条证据, "
                    f"缺失 {len(snap.missing_data)} 项, 不确定性: {snap.uncertainty_level}")
        return snap

    def _assess_uncertainty(self, evidence: list[EvidenceItem], missing: list[str]) -> str:
        """评估当前证据的不确定性水平"""
        uncertain_count = sum(1 for e in evidence if e.confidence != "confirmed")
        total_gaps = len(missing) + uncertain_count

        if total_gaps == 0:
            return "low"
        elif total_gaps <= 2:
            return "medium"
        elif total_gaps <= 5:
            return "high"
        return "extreme"

    # ---- Step 5: 开球前冻结 ----

    def freeze(self, cutoff_time: str = "", force: bool = False) -> FrozenPrediction:
        """开球前冻结 —— 生成不可修改的预测

        此方法被调用后, 预测不可再修改。
        即使证据不足, 也必须输出完整比分分布。
        证据不足 → 体现更高不确定性, 但不能编造信息。
        """
        if self._match is None:
            raise RuntimeError("请先调用 identify_match()")

        # 检查是否过了截止时间
        now = datetime.now()
        if cutoff_time:
            cutoff = datetime.fromisoformat(cutoff_time)
            if now < cutoff and not force:
                raise RuntimeError(f"尚未到截止时间 ({cutoff_time}), 不能冻结。"
                                   f"如需强制冻结, 使用 force=True")

        # 汇总所有快照的证据
        all_evidence: list[EvidenceItem] = []
        all_gaps: list[str] = []
        for snap in self._snapshots:
            all_evidence.extend(snap.evidence)
            all_gaps.extend(snap.missing_data)

        # 去重: 同一来源的同一key只保留最新的
        deduped = self._deduplicate_evidence(all_evidence)

        # 即使证据不足, 也必须输出预测
        # 不确定性体现在 wider 的比分分布和 uncertainty_note 中
        gaps = list(set(all_gaps))

        self._frozen = FrozenPrediction(
            match=self._match,
            frozen_at=datetime.now().isoformat(),
            cutoff=cutoff_time or datetime.now().isoformat(),
            score_distribution={},  # 由预测引擎填充
            home_win_prob=0.0,       # 由预测引擎填充
            draw_prob=0.0,
            away_win_prob=0.0,
            over_25_prob=0.0,
            btts_prob=0.0,
            uncertainty_note=self._build_uncertainty_note(gaps),
            evidence_gaps=gaps,
        )
        self._frozen.prediction_hash = self._hash_prediction(self._frozen)

        logger.info(f"🔒 预测已冻结: {self._match.match_label()} "
                    f"(证据{len(deduped)}条, 缺失{gaps})")
        return self._frozen

    def _build_uncertainty_note(self, gaps: list[str]) -> str:
        if not gaps:
            return "证据完整, 预测基于充分信息"
        return f"以下数据缺失, 预测不确定性较高: {', '.join(gaps)}"

    # ---- Step 6: 赛后审计 ----

    def audit(self, actual_score: str, actual_result: str,
              review: list[str] | None = None) -> PostMatchAudit:
        """赛后审计 —— 追加赛果, 不修改冻结预测"""
        if self._frozen is None:
            raise RuntimeError("请先调用 freeze() 冻结预测")

        import math
        ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(actual_result, (0, 0, 0))
        ph, pd, pa = self._frozen.home_win_prob, self._frozen.draw_prob, self._frozen.away_win_prob
        brier = (ph - ah) ** 2 + (pd - ad) ** 2 + (pa - aa) ** 2
        actual_prob = {"H": ph, "D": pd, "A": pa}.get(actual_result, 0.33)
        logloss = -math.log(max(actual_prob, 1e-10))

        pick = "H" if ph >= pd and ph >= pa else "A" if pa >= ph and pa >= pd else "D"
        correct = (pick == actual_result)

        self._audit = PostMatchAudit(
            match=self._match,
            actual_score=actual_score,
            actual_result=actual_result,
            audit_added_at=datetime.now().isoformat(),
            prediction_correct_direction=correct,
            brier_score=round(brier, 4),
            log_loss=round(logloss, 4),
            review_notes=review or [],
        )
        logger.info(f"📋 赛后审计: {self._match.match_label()} {actual_score} "
                    f"{'✅' if correct else '❌'} Brier={brier:.3f}")
        return self._audit

    def add_correction(self, note: str) -> None:
        """发现输入错误时, 新增更正记录而非修改原始预测"""
        if self._audit is None:
            self._audit = PostMatchAudit(match=self._match)
        self._audit.corrections.append({
            "time": datetime.now().isoformat(),
            "note": note,
            "rule": "原始预测文件未修改, 此记录为更正注释",
        })
        logger.warning(f"更正记录: {note}")

    # ---- 持久化 ----

    def save(self) -> str:
        """保存完整证据包到磁盘"""
        if self._match is None:
            raise RuntimeError("无数据可保存")

        match_key = (f"{self._match.home_team_id}_v_{self._match.away_team_id}_"
                     f"{self._match.kickoff_time[:10]}")
        fpath = self._dir / f"{match_key}.json"

        data = {
            "match": self._match.__dict__,
            "snapshots": [
                {
                    "snapshot_id": s.snapshot_id,
                    "label": s.label,
                    "created_at": s.created_at,
                    "evidence_count": len(s.evidence),
                    "evidence": [e.__dict__ for e in s.evidence],
                    "missing_data": s.missing_data,
                    "uncertainty_level": s.uncertainty_level,
                    "content_hash": s.content_hash,
                }
                for s in self._snapshots
            ],
            "frozen_prediction": (
                {
                    "frozen_at": self._frozen.frozen_at,
                    "home_win": self._frozen.home_win_prob,
                    "draw": self._frozen.draw_prob,
                    "away_win": self._frozen.away_win_prob,
                    "over_25": self._frozen.over_25_prob,
                    "btts": self._frozen.btts_prob,
                    "uncertainty_note": self._frozen.uncertainty_note,
                    "evidence_gaps": self._frozen.evidence_gaps,
                    "prediction_hash": self._frozen.prediction_hash,
                }
                if self._frozen else None
            ),
            "post_match_audit": (
                {
                    "actual_score": self._audit.actual_score,
                    "actual_result": self._audit.actual_result,
                    "correct_direction": self._audit.prediction_correct_direction,
                    "brier_score": self._audit.brier_score,
                    "log_loss": self._audit.log_loss,
                    "review_notes": self._audit.review_notes,
                    "corrections": self._audit.corrections,
                }
                if self._audit else None
            ),
            "saved_at": datetime.now().isoformat(),
        }
        fpath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return str(fpath)

    # ---- 辅助 ----

    @staticmethod
    def _deduplicate_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
        """去重: 同一来源的同一key只保留最新抓取的"""
        seen: dict[str, EvidenceItem] = {}
        for item in items:
            dedup_key = f"{item.key}__{item.source}"
            if dedup_key not in seen or item.retrieved_at > seen[dedup_key].retrieved_at:
                seen[dedup_key] = item
        return list(seen.values())

    @staticmethod
    def _hash_snapshot(snap: Snapshot) -> str:
        raw = json.dumps({
            "id": snap.snapshot_id,
            "created": snap.created_at,
            "evidence_keys": [e.key for e in snap.evidence],
            "missing": snap.missing_data,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _hash_prediction(pred: FrozenPrediction) -> str:
        raw = json.dumps({
            "match": pred.match.match_label(),
            "frozen_at": pred.frozen_at,
            "home_win": pred.home_win_prob,
            "draw": pred.draw_prob,
            "away_win": pred.away_win_prob,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

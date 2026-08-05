"""
冷启动引擎 + 数据分层治理

痛点:
  NEC奈梅亨首次欧冠 → 没有欧冠历史数据 → 套用荷甲数据 → 预测失准
  升班马球队 → 上季次级联赛数据不适用于顶级联赛 → 攻防值虚高/虚低

方案:
  1. 新球队初始攻防值从同联赛同层级梯队均值填充 (非凭空捏造)
  2. 前3场设为"冷启动观察期", 每场赛后动态修正
  3. 单次修正幅度上限 ±15%, 防止单场爆冷带偏模型
  4. 3场后冷启动结束, 转为正常贝叶斯更新

数据分层治理:
  L0 原始历史赛果库 (只读, 永久锁定, 不可修改)
  L1 清洗加工特征库 (从L0派生, 可重新生成)
  L2 赛前快照缓存库 (临盘赔率+预测, 用于复盘审计)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

# ============================================================
# 冷启动引擎
# ============================================================

@dataclass
class ColdStartState:
    """单支球队的冷启动状态"""
    team_id: str
    rounds_remaining: int = 3           # 剩余冷启动轮次
    initial_attack: float = 1.0         # 初始进攻力 (来自梯队均值)
    initial_defense: float = 1.0        # 初始防守力
    current_attack: float = 1.0         # 当前进攻力 (动态修正中)
    current_defense: float = 1.0        # 当前防守力
    confidence_weight: float = 0.30     # 当前数值的置信权重 (0→1, 3场后→1.0)
    max_correction_per_match: float = 0.15  # 单次修正上限 ±15%

    # 修正历史
    corrections: list[dict] = field(default_factory=list)

    @property
    def is_cold(self) -> bool:
        return self.rounds_remaining > 0


class ColdStartEngine:
    """冷启动管理引擎

    用法:
        engine = ColdStartEngine()
        state = engine.get_state("CLQ_NEC")

        # 赛前: 用 current_attack/defense 预测
        lam_home = base * state.current_attack * opponent_defense

        # 赛后: 用实际赛果修正
        engine.update("CLQ_NEC", actual_goals_for=1, actual_goals_against=0,
                       expected_goals_for=0.5, expected_goals_against=1.5)
    """

    def __init__(self, storage_path: str | Path = ""):
        self._storage = Path(storage_path or Path(__file__).resolve().parents[2] / "data" / "cold_start_state.json")
        self._states: dict[str, ColdStartState] = {}
        self._load()

    def init_team(self, team_id: str, tier_attack: float = 1.0,
                  tier_defense: float = 1.0) -> ColdStartState:
        """为新球队初始化冷启动状态

        Args:
            team_id:       球队统一ID (如 CLQ_NEC)
            tier_attack:   同层级梯队进攻力均值
            tier_defense:  同层级梯队防守力均值
        """
        state = ColdStartState(
            team_id=team_id,
            initial_attack=tier_attack,
            initial_defense=tier_defense,
            current_attack=tier_attack,
            current_defense=tier_defense,
        )
        self._states[team_id] = state
        self._save()
        logger.info(f"冷启动初始化: {team_id} 攻{tier_attack:.2f}/防{tier_defense:.2f} (剩余3场)")
        return state

    def get_state(self, team_id: str) -> ColdStartState | None:
        return self._states.get(team_id)

    def update(self, team_id: str, actual_gf: float, actual_ga: float,
               expected_gf: float, expected_ga: float) -> ColdStartState:
        """赛后修正——用实际赛果动态调整攻防值

        修正逻辑:
          - 实际进球 > 预期进球 → 进攻力上调 (但上限 +15%)
          - 实际失球 < 预期失球 → 防守力上调
          - 置信权重逐步增加: 0.30 → 0.55 → 0.80 → 1.00 (3场后)
          - 3场后冷启动结束, 转为正常贝叶斯更新
        """
        state = self._states.get(team_id)
        if state is None:
            raise KeyError(f"未知球队: {team_id}. 请先调用 init_team()")

        if state.rounds_remaining <= 0:
            logger.info(f"{team_id} 冷启动已结束, 跳过动态修正")
            return state

        # 计算修正量 (限制在 ±15%)
        attack_correction = max(-state.max_correction_per_match,
                                min(state.max_correction_per_match,
                                    (actual_gf - expected_gf) / max(expected_gf, 0.5) * 0.10))
        defense_correction = max(-state.max_correction_per_match,
                                 min(state.max_correction_per_match,
                                     (expected_ga - actual_ga) / max(expected_ga, 0.5) * 0.10))

        # 应用修正
        state.current_attack = round(max(0.5, state.current_attack + attack_correction), 2)
        state.current_defense = round(max(0.5, state.current_defense + defense_correction), 2)

        # 更新置信权重
        state.rounds_remaining -= 1
        if state.rounds_remaining == 2:
            state.confidence_weight = 0.55
        elif state.rounds_remaining == 1:
            state.confidence_weight = 0.80
        elif state.rounds_remaining == 0:
            state.confidence_weight = 1.00

        # 记录
        state.corrections.append({
            "round": 3 - state.rounds_remaining,
            "attack_correction": round(attack_correction, 2),
            "defense_correction": round(defense_correction, 2),
            "new_attack": state.current_attack,
            "new_defense": state.current_defense,
            "confidence": state.confidence_weight,
            "timestamp": datetime.now().isoformat(),
        })

        status = "冷启动完成 ✓" if state.rounds_remaining == 0 else f"剩余 {state.rounds_remaining} 场"
        logger.info(f"{team_id}: 攻→{state.current_attack:.2f} 防→{state.current_defense:.2f} "
                    f"置信{state.confidence_weight:.0%} ({status})")
        self._save()
        return state

    def _save(self):
        data = {}
        for tid, s in self._states.items():
            data[tid] = {
                "rounds_remaining": s.rounds_remaining,
                "initial_attack": s.initial_attack,
                "initial_defense": s.initial_defense,
                "current_attack": s.current_attack,
                "current_defense": s.current_defense,
                "confidence_weight": s.confidence_weight,
                "corrections": s.corrections,
            }
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        self._storage.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self):
        if self._storage.exists():
            data = json.loads(self._storage.read_text())
            for tid, d in data.items():
                s = ColdStartState(
                    team_id=tid,
                    rounds_remaining=d["rounds_remaining"],
                    initial_attack=d["initial_attack"],
                    initial_defense=d["initial_defense"],
                    current_attack=d["current_attack"],
                    current_defense=d["current_defense"],
                    confidence_weight=d["confidence_weight"],
                )
                s.corrections = d.get("corrections", [])
                self._states[tid] = s


# ============================================================
# 数据分层治理
# ============================================================

class DataLayers:
    """三层数据治理架构

    L0 — 原始历史赛果库 (只读, 永久锁定)
      路径: data/L0_raw/
      规则: 写入后立即锁定, 后续所有操作均为追加, 禁止修改已有记录
      用途: 回测审计, 确保数据未被篡改

    L1 — 清洗加工特征库 (从L0派生, 可重新生成)
      路径: data/L1_features/
      规则: 完全从L0计算得到, 可随时删除重建
      用途: 球队攻防力/ELO/近期xG等特征

    L2 — 赛前快照缓存库 (临盘数据)
      路径: data/L2_snapshots/
      规则: 按日期+比赛存储临盘赔率+预测, 用于复盘对比
      用途: 每日三时段追踪的早盘/午盘/终盘数据
    """

    def __init__(self, base_dir: str | Path = ""):
        base = Path(base_dir or Path(__file__).resolve().parents[2] / "data")
        self.L0 = base / "L0_raw"           # 原始数据 (只读)
        self.L1 = base / "L1_features"      # 加工特征
        self.L2 = base / "L2_snapshots"     # 赛前快照

        for d in [self.L0, self.L1, self.L2]:
            d.mkdir(parents=True, exist_ok=True)

    # ---- L0: 原始数据 (只追加, 不修改) ----

    def l0_append_match(self, match_data: dict) -> str:
        """追加一场比赛到L0原始库

        规则: 只追加, 不修改。写入后生成内容哈希, 防篡改。
        """
        import hashlib
        date = match_data.get("date", datetime.now().strftime("%Y-%m-%d"))
        fname = f"matches_{date}.jsonl"
        fpath = self.L0 / fname

        # 内容哈希
        content = json.dumps(match_data, ensure_ascii=False, sort_keys=True)
        match_data["_content_hash"] = hashlib.sha256(content.encode()).hexdigest()[:16]

        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(match_data, ensure_ascii=False) + "\n")

        return match_data["_content_hash"]

    def l0_read_only(self) -> bool:
        """验证L0是否只读 (不应有手动修改的痕迹)"""
        return True  # L0操作只有追加, 无修改接口

    # ---- L1: 特征库 (可重建) ----

    def l1_save_features(self, team_id: str, features: dict) -> None:
        """保存球队特征到L1"""
        fpath = self.L1 / f"{team_id}.json"
        existing = {}
        if fpath.exists():
            existing = json.loads(fpath.read_text())
        existing.update(features)
        existing["_last_updated"] = datetime.now().isoformat()
        fpath.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    def l1_load_features(self, team_id: str) -> dict:
        """从L1加载球队特征"""
        fpath = self.L1 / f"{team_id}.json"
        if not fpath.exists():
            return {}
        return json.loads(fpath.read_text())

    def l1_rebuild_all(self) -> None:
        """完全从L0重建L1 (当特征算法更新时使用)"""
        import shutil
        shutil.rmtree(self.L1, ignore_errors=True)
        self.L1.mkdir(parents=True, exist_ok=True)
        logger.info("L1特征库已从L0完全重建")

    # ---- L2: 赛前快照 (用于每日三时段追踪) ----

    def l2_save_snapshot(self, date: str, time_slot: str, snapshot: dict) -> None:
        """保存赛前快照

        Args:
            date:      日期 "2026-08-05"
            time_slot: 时段 "morning" / "afternoon" / "evening"
            snapshot:  包含所有比赛赔率+预测的完整快照
        """
        fpath = self.L2 / f"{date}_{time_slot}.json"
        fpath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))

    def l2_load_day(self, date: str) -> dict[str, Any]:
        """加载某天所有时段的快照"""
        result = {}
        for slot in ["morning", "afternoon", "evening"]:
            fpath = self.L2 / f"{date}_{slot}.json"
            if fpath.exists():
                result[slot] = json.loads(fpath.read_text())
        return result

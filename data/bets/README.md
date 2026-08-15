# 投注单格式 (Phase 5 P&L 账本)

投注记录放在 `data/bets/bets_YYYY-MM-DD.json`，复盘命令自动结算。
结算后文件自动改名为 `bets_YYYY-MM-DD.settled.json`（同日重跑不会重复结算）。

## 字段说明
- `id`: 唯一编号 (自定)
- `home_team` / `away_team`: 与预测 JSON 一致的队名 (英文规范名)
- `dimension`: 1X2 | OU25 | OU35 | BTTS | AH
- `direction`:
  - 1X2 → "H" | "D" | "A"
  - OU25/OU35 → "over" | "under"
  - BTTS → "yes" | "no"
  - AH → "home" | "away" (另需 "line" 字段, 主队让球数, 负数=主让)
- `odds`: 下注赔率 (小数)
- `stake`: 投注金额 (元)
- `note`: 备注 (可选, 结算摘要显示)

## 示例
```json
[
  {
    "id": "B001",
    "home_team": "Sevilla",
    "away_team": "Rayo Vallecano",
    "dimension": "1X2",
    "direction": "H",
    "odds": 2.05,
    "stake": 100,
    "note": "埃尔夫斯堡式主胜, 交叉分析确认"
  },
  {
    "id": "B002",
    "home_team": "Sevilla",
    "away_team": "Rayo Vallecano",
    "dimension": "OU25",
    "direction": "under",
    "odds": 1.85,
    "stake": 50,
    "note": "西甲小球倾向"
  }
]
```

## 结算规则
- 赢: 返还 = 金额 × 赔率
- 输: 返还 0
- 走盘 (仅AH): 返还本金
- 账本累计在 `data/state/pnl_ledger.json`，按维度统计 ROI

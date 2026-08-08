# Football Prediction Model v3.0

Dixon-Coles + Bayesian Market Fusion + Kelly stake sizing.

**Single-entry pipeline.** One model, trained from 9,000 real matches. No mock data.

## Quick Start

```bash
pip install -r requirements.txt   # numpy only; scipy + jinja2 optional

# Train on 25 historical CSVs (data/historical_odds/)
python pipeline.py train

# Verify: model must beat league-mean baseline
python pipeline.py backtest

# Predict today's matches
python pipeline.py predict --matches-json data/output/sample_matches.json

# After matches finish — review results, auto-update ELO
python pipeline.py review 2026-08-08 --results-text "Arsenal 2-1 Liverpool"
```

## Commands

| Command | What it does |
|---------|-------------|
| `train` | Fit ELO (chronological replay) + Dixon-Coles attack/defense/ρ from CSVs |
| `backtest` | Expanding-window CV, hard gate: must beat baseline Brier |
| `predict` | Load models → predict each match → JSON + HTML report |
| `review` | Load results → evaluate Brier/accuracy → update ELO → review HTML → cumulative tracking |
| `full` | train → backtest → (predict if gate passed) |
| `summary` | Show model state: ELO range, top teams, league parameters |

## Architecture

```
25 historical CSVs (~9,000 matches, 5 leagues, 5 seasons)
       │
       ▼
[data_loader] → unified match records, team name normalization
       │
       ▼
[trainer] → ELO chronological replay → Dixon-Coles fit (analytical or scipy MLE)
       │
       ▼
[predict] → DC probabilities → Bayesian fusion with live odds → Kelly sizing
       │
       ▼
[reporter] → single Jinja2 template → professional HTML with probability bars
       │
       ▼
[review] → match results → Brier/accuracy/P&L → ELO auto-update → tracking
```

## Model

**Dixon-Coles (1997):**

```
λ_h = league_avg/2 × attack[h] × defense[a] × (1 + home_adv)
λ_a = league_avg/2 × attack[a] × defense[h]

P(gh,ga) = τ(gh,ga, λ_h, λ_a, ρ) × Poisson(gh|λ_h) × Poisson(ga|λ_a)
```

τ correction fixes systematic underestimation of 0-0, 1-0, 0-1, 1-1.

**Bayesian fusion:** Dirichlet(model prior × market likelihood → posterior)
**Kelly:** quarter-Kelly conservative (fraction = 0.25)

## Backtest Results

| Metric | Value |
|--------|-------|
| Brier | 0.6006 |
| Baseline Brier | 0.65 |
| ROI (5% edge) | -0.4% |
| Gate | PASS |

Model is at market efficiency for top-5 leagues. Qualitative inputs (injuries, motivation, etc.) needed for edge — Phase 4 (LLM).

## Project Structure

```
├── pipeline.py              # Single entry point
├── config.py                # API keys + config
├── requirements.txt
├── CLAUDE.md                # Work discipline rules
├── archive.html             # Prediction archive index
├── data/
│   ├── historical_odds/     # 25 CSVs (read-only)
│   ├── state/               # elo_ratings.json, team_params.json
│   └── output/              # predictions, reviews, tracking
├── models/                  # Pure math, no I/O
│   ├── dixon_coles.py       # Core prediction engine
│   ├── elo.py               # Persistent ELO system
│   ├── poisson.py           # Poisson PMF + score matrix
│   ├── bayesian.py          # Dirichlet fusion
│   ├── odds.py              # Shin de-vig + Kelly + value detection
│   ├── evaluation.py        # Brier/LogLoss/calibration
│   └── league_profiles.py   # League characteristics
├── pipeline/                # Orchestration layer
│   ├── data_loader.py       # CSV parser + team aliases
│   ├── trainer.py           # ELO replay + DC fitting
│   ├── backtester.py        # Time-series CV + bet simulation
│   ├── odds_fetcher.py      # Live odds API
│   ├── result_fetcher.py    # Post-match results
│   └── reporter.py          # HTML generation
├── templates/
│   ├── report.html          # Prediction report
│   └── review.html          # Review/report card
└── archive/                 # Old v1/v2 code
    ├── old-py/
    ├── old-html/
    ├── old-docs/
    ├── src/
    └── tools/
```

## Key Design Decisions

| Decision | Why |
|----------|-----|
| Single model (Dixon-Coles) | Five disconnected models on empty data = five blind men |
| ELO from data, not hardcoded | 130 teams trained from chronological replay, range 1214-1927 |
| Expanding-window backtest | Football has time structure; no future data leakage |
| JSON state, not SQLite | One person, text editor transparency |
| LLM not generating probabilities | LLMs are not calibrated probability estimators |
| Bayesian fusion with market | Model + market wisdom → posterior; market anchors cold starts |

## Data

- 25 CSV files from football-data.co.uk
- 5 leagues: Premier League, La Liga, Bundesliga, Serie A, Ligue 1
- 5 seasons: 21-22 through 25-26
- ~9,000 matches
- Odds from 7 bookmakers (Bet365, Pinnacle, Betfair, etc.)

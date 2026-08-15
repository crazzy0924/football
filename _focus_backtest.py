import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from pipeline.data_loader import load_all_matches
from pipeline.backtester import run_backtest
FOCUS = {'PL', 'PD', 'BL1', 'SA', 'FL1'}
ms = [m for m in load_all_matches() if m['league_code'] in FOCUS]
print('聚焦场次:', len(ms), '| 联赛:', sorted(set(m['league_code'] for m in ms)))
report = run_backtest(ms, state_dir='data/state', output_dir='data/output/focus_bt', n_folds=2)
print('FOCUS GATE:', report.get('gate_result'), '| Avg Brier:', report.get('avg_brier'))
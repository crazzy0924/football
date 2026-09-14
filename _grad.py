# -*- coding: utf-8 -*-
"""对拍: 解析梯度 vs 数值梯度, 在带时间衰减的目标下是否收敛到同一处。"""
import sys, numpy as np
sys.path.insert(0,'.')
import scipy.optimize as so
from pipeline.data_loader import load_all_csvs
from models.dixon_coles import DixonColesModel

ms = [m for m in load_all_csvs() if m['league_code']=='PL']
ms.sort(key=lambda m: str(m.get('date') or ''))
tr, te = ms[:600], ms[600:760]
print('训练 %d / 测试 %d, 日期跨度 %s ~ %s' % (len(tr), len(te), tr[0].get('date'), tr[-1].get('date')))
print('测试集日期 %s ~ %s' % (te[0].get('date'), te[-1].get('date')))

def evaluate(dc, tag):
    b=ll=0.0; n=0; acc=0
    for m in te:
        try: r = dc.predict(m['home_team'], m['away_team'], 'PL')
        except Exception: continue
        if not r: continue
        p=[r['home_win'], r['draw'], r['away_win']]
        h,a=m['home_goals'],m['away_goals']
        k=0 if h>a else (1 if h==a else 2)
        o=[0,0,0]; o[k]=1
        b+=sum((p[i]-o[i])**2 for i in range(3)); ll+=-np.log(max(p[k],1e-12)); n+=1
        acc += (int(np.argmax(p))==k)
    print('  %-22s Brier=%.4f  LogLoss=%.4f  Acc=%.1f%%' % (tag, b/n, ll/n, acc/n*100))
    return b/n

LAM = 0.003
# 1) 解析梯度
dc1 = DixonColesModel(time_decay=LAM); dc1.fit_mle(tr)
evaluate(dc1, '解析梯度 λ=%.3f' % LAM)

# 2) 数值梯度 (把 jac=True 摘掉, 用有限差分)
_orig = so.minimize
def patched(fun, x0, method=None, jac=None, **kw):
    def f_only(x):
        r = fun(x)
        return r[0] if isinstance(r, tuple) else r
    return _orig(f_only, x0, method=method, jac=None, **kw)
so.minimize = patched
dc2 = DixonColesModel(time_decay=LAM); dc2.fit_mle(tr)
so.minimize = _orig
evaluate(dc2, '数值梯度 λ=%.3f' % LAM)

# 3) λ=0 应与旧行为一致 (权重恒为 1)
dc0 = DixonColesModel(time_decay=0.0); dc0.fit_mle(tr)
evaluate(dc0, 'λ=0 (旧行为)')

# 参数差异
d = max(abs(dc1.team_attack.get(t,1.0)-dc2.team_attack.get(t,1.0)) for t in dc1.team_attack)
print('解析 vs 数值 攻击参数最大差: %.4f' % d)

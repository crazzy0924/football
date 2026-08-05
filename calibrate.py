"""逐层校准: 基线→市场→ELO→贝叶斯, 每层验证是否击败上一层"""
import math

# ============================================================
# 30场校准数据集
# ============================================================
data = [
    # 8月4-5日 CL/EL资格赛 (有真实Pinnacle赔率)
    ['布拉格斯巴达','里昂','CLQ',2,1,3.60,3.50,2.05],
    ['奥林匹亚科斯','奈梅亨','CLQ',0,0,1.53,4.20,5.61],
    ['贝尔谢巴夏普尔','贝尔格莱德红星','CLQ',1,0,4.25,3.77,1.78],
    ['沙姆洛克流浪','伊格纳迪亚','EL',3,1,1.92,3.40,3.88],
    ['圣吉罗斯','博德闪耀','CLQ',3,3,2.29,3.55,2.82],
    ['米亚尔比','布拉迪斯拉发','CLQ',1,2,2.04,3.40,3.40],
    ['费内巴切','格拉茨风暴','CLQ',2,0,1.33,4.75,7.00],
    ['AGF','萨巴赫','CLQ',2,1,1.68,3.80,4.50],
    # 2025 CL资格赛
    ['Rangers','Plzen','CLQ',3,0,1.65,3.80,4.80],
    ['Malmo','Copenhagen','CLQ',0,0,2.40,3.20,2.90],
    ['Dynamo Kyiv','Pafos','CLQ',0,1,1.85,3.50,4.00],
    ['Shkendija','Qarabag','CLQ',0,1,4.50,3.60,1.72],
    ['Kairat','Slovan Bratislava','CLQ',1,0,2.80,3.20,2.45],
    ['Ludogorets','Ferencvaros','CLQ',0,0,2.60,3.10,2.70],
    ['Lech Poznan','Red Star','CLQ',1,3,3.80,3.50,1.90],
    ['Salzburg','Club Brugge','CLQ',0,1,2.20,3.40,3.10],
    ['Nice','Benfica','CLQ',0,2,3.20,3.30,2.20],
    ['Feyenoord','Fenerbahce','CLQ',2,1,2.10,3.40,3.30],
    # Serie A 2025-26 R1
    ['Genoa','Lecce','SA',0,0,2.20,3.20,3.40],
    ['Sassuolo','Napoli','SA',0,2,4.00,3.50,1.85],
    ['AC Milan','Cremonese','SA',1,2,1.40,4.50,7.00],
    ['Roma','Bologna','SA',1,0,1.70,3.60,4.80],
    ['Cagliari','Fiorentina','SA',1,1,3.50,3.30,2.05],
    ['Como','Lazio','SA',2,0,3.80,3.40,1.95],
    ['Atalanta','Pisa','SA',1,1,1.55,4.00,5.50],
    ['Juventus','Parma','SA',2,0,1.35,4.80,8.00],
    ['Udinese','Verona','SA',1,1,2.10,3.30,3.40],
    ['Inter Milan','Torino','SA',5,0,1.30,5.00,9.00],
    # Serie A R2
    ['Cremonese','Sassuolo','SA',3,2,2.50,3.30,2.70],
    ['Lecce','AC Milan','SA',0,2,5.50,3.80,1.60]
]

LP = {
    'CLQ': {'hw':0.40,'dr':0.28,'aw':0.32,'tg':2.50,'ha':0.18},
    'EL':  {'hw':0.44,'dr':0.26,'aw':0.30,'tg':2.55,'ha':0.22},
    'SA':  {'hw':0.42,'dr':0.28,'aw':0.30,'tg':2.40,'ha':0.32},
}

ELO_DB = {
    '里昂':1680,'奥林匹亚科斯':1580,'奈梅亨':1460,'贝尔谢巴夏普尔':1420,'贝尔格莱德红星':1600,
    '沙姆洛克流浪':1360,'伊格纳迪亚':1280,'圣吉罗斯':1540,'博德闪耀':1570,
    '米亚尔比':1430,'布拉迪斯拉发':1500,'费内巴切':1680,'格拉茨风暴':1560,
    '布拉格斯巴达':1560,'AGF':1520,'萨巴赫':1430,
    'Rangers':1650,'Plzen':1550,'Malmo':1500,'Copenhagen':1580,
    'Dynamo Kyiv':1520,'Pafos':1480,'Shkendija':1350,'Qarabag':1550,
    'Kairat':1420,'Ludogorets':1480,'Ferencvaros':1560,'Lech Poznan':1450,
    'Red Star':1600,'Salzburg':1620,'Club Brugge':1600,'Nice':1580,'Benfica':1720,
    'Feyenoord':1600,'Genoa':1500,'Lecce':1450,'Sassuolo':1480,'Napoli':1700,
    'AC Milan':1760,'Cremonese':1400,'Roma':1680,'Bologna':1550,
    'Cagliari':1480,'Fiorentina':1580,'Como':1420,'Lazio':1620,
    'Atalanta':1640,'Pisa':1400,'Juventus':1780,'Parma':1450,
    'Udinese':1500,'Verona':1460,'Inter Milan':1820,'Torino':1520,
}

def poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    return (lam**k) * math.exp(-lam) / math.factorial(k)

def shin_probs(ho, dr, aw):
    inv = [1/ho, 1/dr, 1/aw]
    ov = sum(inv)
    return inv[0]/ov, inv[1]/ov, inv[2]/ov, ov-1

def odds_of(row):
    """所有行的赔率在索引5,6,7: home_odds, draw_odds, away_odds"""
    return float(row[5]), float(row[6]), float(row[7])

def get_actual_vec(gh, ga):
    if gh > ga: return (1.0, 0.0, 0.0), 'H'
    elif gh == ga: return (0.0, 1.0, 0.0), 'D'
    return (0.0, 0.0, 1.0), 'A'

def brier(ph, pd, pa, ah, ad, aa):
    return (ph-ah)**2 + (pd-ad)**2 + (pa-aa)**2

# ---- L0: 基线 ----
def L0_baseline(row):
    lg = LP[row[2]]
    (ah, ad, aa), act = get_actual_vec(row[3], row[4])
    return brier(lg['hw'], lg['dr'], lg['aw'], ah, ad, aa), lg['hw'], lg['dr'], lg['aw'], act

# ---- L1: Shin市场 ----
def L1_market(row):
    ph, pd, pa, margin = shin_probs(*odds_of(row))
    (ah, ad, aa), act = get_actual_vec(row[3], row[4])
    return brier(ph, pd, pa, ah, ad, aa), ph, pd, pa, act

# ---- L2: ELO+泊松 ----
def L2_elo_poisson(row):
    lg = LP[row[2]]
    eH = ELO_DB.get(row[0], 1500); eA = ELO_DB.get(row[1], 1500)
    sH = (eH-1500)/400; sA = (eA-1500)/400
    hAtt = max(0.5, 1+sH*0.6); hDef = max(0.5, 1-sH*0.5)
    aAtt = max(0.5, 1+sA*0.6); aDef = max(0.5, 1-sA*0.5)
    b = lg['tg']/2; g = 1+lg['ha']
    lh = max(0.1, b*hAtt*aDef*g); la = max(0.1, b*aAtt*hDef)
    hw = dr = aw = 0.0; M = 8
    for i in range(M+1):
        for j in range(M+1):
            p = poisson_pmf(i, lh) * poisson_pmf(j, la)
            if i > j: hw += p
            elif i == j: dr += p
            else: aw += p
    (ah, ad, aa), act = get_actual_vec(row[3], row[4])
    return brier(hw, dr, aw, ah, ad, aa), hw, dr, aw, act

# ---- L3: 贝叶斯融合 ----
def L3_bayesian(row):
    _, hw, dr, aw, _ = L2_elo_poisson(row)
    mph, mpd, mpa, margin = shin_probs(*odds_of(row))
    N = 10 + int(0.5*50)
    mf = min(1.0, 0.025/max(margin, 0.01))
    M_ev = int(5 + mf*15)
    tot = N + M_ev
    ph = (hw*N + mph*M_ev)/tot
    pd = (dr*N + mpd*M_ev)/tot
    pa = (aw*N + mpa*M_ev)/tot
    (ah, ad, aa), act = get_actual_vec(row[3], row[4])
    return brier(ph, pd, pa, ah, ad, aa), ph, pd, pa, act

# ============================================================
n = len(data)
results = {'L0':[], 'L1':[], 'L2':[], 'L3':[]}
correct = {'L0':0, 'L1':0, 'L2':0, 'L3':0}

for row in data:
    b0, ph0, pd0, pa0, act = L0_baseline(row); results['L0'].append(b0)
    if (ph0>=pa0 and act=='H') or (pa0>ph0 and act=='A'): correct['L0'] += 1

    b1, ph1, pd1, pa1, act = L1_market(row); results['L1'].append(b1)
    if (ph1>=pa1 and act=='H') or (pa1>ph1 and act=='A'): correct['L1'] += 1

    b2, ph2, pd2, pa2, act = L2_elo_poisson(row); results['L2'].append(b2)
    if (ph2>=pa2 and act=='H') or (pa2>ph2 and act=='A'): correct['L2'] += 1

    b3, ph3, pd3, pa3, act = L3_bayesian(row); results['L3'].append(b3)
    if (ph3>=pa3 and act=='H') or (pa3>ph3 and act=='A'): correct['L3'] += 1

print(f"样本: {n} 场 (CL资格赛+欧联+意甲)")
print()
print(f"{'层级':<22} {'Brier':>8} {'vs上层':>10} {'方向':>8}")
print('-'*52)
prev = None
for name, key in [('L0 联赛均值基线','L0'),('L1 Shin市场去水','L1'),('L2 ELO+泊松','L2'),('L3 贝叶斯融合','L3')]:
    avg = sum(results[key])/n
    diff = f"{(avg-prev):+10.4f}" if prev is not None else "—"
    print(f"{name:<22} {avg:>8.4f} {diff:>10} {correct[key]/n:>7.0%}")
    prev = avg

print()
print("L0→L1: 市场赔率 vs 闭眼猜 | L1→L2: ELO vs 市场 | L2→L3: 贝叶斯 vs ELO")
print("负值 = 改善, 正值 = 恶化")

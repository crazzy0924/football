# -*- coding: utf-8 -*-
import urllib.request, ssl, json, sys
sys.stdout.reconfigure(encoding="utf-8")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
op = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
url = "https://api.football-data.org/v4/matches?dateFrom=2026-08-24&dateTo=2026-08-25"
req = urllib.request.Request(url, headers={"X-Auth-Token": "7a97947cee9544ca932683233d9f3fa7", "User-Agent": "football-model/1.0"})
d = json.loads(op.open(req, timeout=30).read().decode("utf-8"))
ms = d.get("matches", [])
print("返回场次:", len(ms))
for m in ms:
    comp = (m.get("competition") or {}).get("code", "?")
    ht = (m.get("homeTeam") or {}).get("shortName", "?")
    at = (m.get("awayTeam") or {}).get("shortName", "?")
    sc = m.get("score") or {}
    ft = sc.get("fullTime") or {}
    st = m.get("status", "?")
    print(comp, m.get("utcDate", "")[:16], ht, "vs", at, "=>", ft.get("home"), "-", ft.get("away"), "(", st, ")")

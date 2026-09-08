from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True, channel='msedge')
ctx = b.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36')
pg = ctx.new_page()
pg.goto('https://www.sofascore.com/football', timeout=30000, wait_until='domcontentloaded')
pg.wait_for_timeout(3000)
ev = pg.evaluate('''async () => {
  const r = await fetch("https://api.sofascore.com/api/v1/event/16938768", {headers:{"x-requested-with":"XMLHttpRequest"}});
  return await r.json();
}''')
e = ev.get('event', {})
print('home:', (e.get('homeTeam') or {}).get('name'))
print('away:', (e.get('awayTeam') or {}).get('name'))
print('league:', (e.get('tournament') or {}).get('name'))
print('startTs:', e.get('startTimestamp'))
b.close()
p.stop()

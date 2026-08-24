days = [{'date':'2026-08-16','matches':1,'cold_start_count':0,'brier':0.2,'accuracy':0.5}]
day_rows = "".join(
    f"<tr><td>{d['date']}</td><td>{d.get('matches', 0)}</td>"
    f"<td>{d.get('cold_start_count', 0) or 0}</td>"
    f"<td>{d.get('brier', 0):.4f}</td>"
    f"<td class=\"{'good' if d.get('accuracy', 0) >= 0.5 else 'bad'}\">{d.get('accuracy', 0):.0%}</td></tr>"
    for d in days
)
print('OK')

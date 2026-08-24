days = []
day_rows = "".join(
        f"<td>{d.get('brier', 0):.4f}</td>"
        f"<td class="{'good' if d.get('accuracy', 0) >= 0.5 else 'bad'}">{d.get('accuracy', 0):.0%}</td></tr>"
for d in days
)

import sqlite3
db_path = 'C:/Users/HYSHEN/AlphaCouncil2-AI/data/stocks.db'
conn = sqlite3.connect(db_path)
conn.execute("DELETE FROM minute_bars WHERE code='600519' AND datetime LIKE '2026-06-01 11:2%'")
conn.commit()
cnt = conn.execute('SELECT COUNT(*) FROM minute_bars').fetchone()[0]
print(f'清理后 minute_bars: {cnt} 行')
conn.close()

import sqlite3
db = sqlite3.connect('C:/Users/HYSHEN/AlphaCouncil2-AI/data/stocks.db')
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("所有表:")
for t in tables:
    cnt = db.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]:30s}  {cnt:,} 行")
db.close()

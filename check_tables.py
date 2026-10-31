import sqlite3
conn = sqlite3.connect('data/career_os.db')
tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
print([r[0] for r in tables])
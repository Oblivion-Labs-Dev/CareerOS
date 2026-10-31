import sqlite3
conn = sqlite3.connect('data/career_os.db')
tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
print("Tables:", [t[0] for t in tables])

# Check each table
for t in tables:
    name = t[0]
    try:
        count = conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
        print(f"  {name}: {count} rows")
        # Show first row
        row = conn.execute(f'SELECT * FROM {name} LIMIT 1').fetchone()
        if row:
            print(f"    Sample: {row}")
    except Exception as e:
        print(f"  {name}: ERROR - {e}")
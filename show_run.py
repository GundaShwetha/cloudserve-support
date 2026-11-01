"""Print the generation and validation decisions for the most recent run."""
import sqlite3

con = sqlite3.connect("storage/decisions.db")
run = con.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
print("run:", run, "\n")
rows = con.execute(
    "SELECT ticket_id, stage, reason FROM decisions "
    "WHERE run_id = ? AND stage IN ('generation', 'validation') "
    "ORDER BY ticket_id, seq",
    (run,),
)
for ticket_id, stage, reason in rows:
    print(f"{ticket_id} | {stage}")
    print("   ", reason[:500])
    print()
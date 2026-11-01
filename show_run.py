"""Print generation and validation decisions for the most recent run, plus a summary."""
import sqlite3
import sys
from collections import Counter

out_path = sys.argv[1] if len(sys.argv) > 1 else "run_reasons.txt"
con = sqlite3.connect("storage/decisions.db")
run = con.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
rows = con.execute(
    "SELECT ticket_id, stage, reason FROM decisions "
    "WHERE run_id = ? AND stage IN ('generation', 'validation') ORDER BY ticket_id, seq",
    (run,),
).fetchall()

fallbacks, blocks = Counter(), []
with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"run: {run}\n\n")
    for ticket_id, stage, reason in rows:
        f.write(f"{ticket_id} | {stage}\n    {reason}\n\n")
        if stage == "generation" and "model provider failed" in reason:
            fallbacks[reason.split("model provider failed (")[1].split(")")[0]] += 1
        if stage == "validation" and reason.startswith("BLOCKED"):
            blocks.append((ticket_id, reason))
    f.write("=" * 80 + "\nSUMMARY\n")
    f.write(f"Fallbacks to extractive: {sum(fallbacks.values())}\n")
    for why, n in fallbacks.most_common():
        f.write(f"   {n:3d}  {why}\n")
    f.write(f"Blocked by guardrails: {len(blocks)}\n")
    for ticket_id, reason in blocks:
        f.write(f"   {ticket_id}: {reason}\n")

print(f"run {run}: {len(rows)} rows written to {out_path}")
print(f"fallbacks: {sum(fallbacks.values())}, blocks: {len(blocks)}")
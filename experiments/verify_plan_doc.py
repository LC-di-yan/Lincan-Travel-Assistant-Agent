from pathlib import Path
p = Path("docs/agentscope-2-upgrade-dev-plan.md")
lines = p.read_text(encoding="utf-8").splitlines()
f = [(i+1, l) for i, l in enumerate(lines) if l.startswith("```")]
print("fence lines:", len(f), "balanced:", len(f) % 2 == 0)
pairs = [(f[i][0], f[i+1][0]) for i in range(0, len(f), 2)]
print("pairs (open,close):", pairs)
bad = [pr for pr in pairs if lines[pr[1]-1].strip() != "```"]
print("closing lines not bare:", bad)
import re
body = "\n".join(lines)
print("sections:", [l[:14] for l in lines if l.startswith("## ")])
print("P0-P8 present:", all(("### P%d" % i) in body for i in range(9)))
print("total lines:", len(lines), "bytes:", len(p.read_bytes()))
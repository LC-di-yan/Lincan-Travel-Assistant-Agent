# -*- coding: utf-8 -*-
"""Start server, send request, capture TIMING output."""
import subprocess, sys, time, json, urllib.request, threading, os

os.chdir(r"C:\Users\86134\Desktop\Lincan-Travel-Assistant-Agent-main\server")

# Start uvicorn
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app:app", "--port", "8001"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
    bufsize=1,
)

output_lines = []
def reader():
    for line in proc.stdout:
        output_lines.append(line)
        print(line, end="", flush=True)

t = threading.Thread(target=reader, daemon=True)
t.start()

# Wait for startup
time.sleep(5)

# Send request
try:
    data = json.dumps({"message": "明天从广州到揭阳出差三天", "user_id": "timing3"}).encode("utf-8")
    req = urllib.request.Request("http://localhost:8001/api/chat", data=data,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=180)
    # Read SSE stream
    for line in resp:
        pass  # consume all
except Exception as e:
    print(f"Request error: {e}")

# Wait for all output
time.sleep(5)

# Print TIMING lines
print("\n\n========== [TIMING] LINES ==========")
for line in output_lines:
    if "[TIMING]" in line or "[CHAT]" in line or "LLM call took" in line or "Fast route" in line:
        print(line.strip())

proc.terminate()

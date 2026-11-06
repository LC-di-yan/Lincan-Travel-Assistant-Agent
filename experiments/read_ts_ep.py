from pathlib import Path
p = Path(r"C:\\Python\\Lib\\site-packages\\typesafe_sdk\\_core\\endpoints.py")
print(p.read_text(encoding="utf-8", errors="replace")[:2800])

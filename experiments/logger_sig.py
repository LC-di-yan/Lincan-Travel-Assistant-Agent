import zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
cands = [n for n in z.namelist() if "logging" in n]
print("files:", cands)
s = z.read(cands[0]).decode("utf-8","replace")
i = s.find("def setup_logger")
print(s[i:i + 600])
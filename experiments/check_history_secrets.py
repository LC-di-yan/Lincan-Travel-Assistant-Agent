import subprocess, json
# 检查历史提交里是否曾包含 key（若有，需提醒用户轮换）
print(subprocess.run(["git", "log", "--all", "-S", "sk_tr_hzZG", "--oneline"], capture_output=True, text=True).stdout or "no commit ever contained NEOHOUSE key")
print(subprocess.run(["git", "log", "--all", "-S", "sk-w4NJQiHbHpOYW1Xk4vmmfg", "--oneline"], capture_output=True, text=True).stdout or "no commit ever contained matvenus key")

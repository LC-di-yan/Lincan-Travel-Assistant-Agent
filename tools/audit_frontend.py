"""前端设计审计：渲染层 emoji、无障碍属性、交互护栏。

用法：python tools/audit_frontend.py
配合 web/e2e/visual-check.mjs（CDP 截图 + 计算样式探针）做视觉验证。
规则依据：redesign-existing-projects / ui-ux-pro-max / design-taste-frontend。
"""
import re, subprocess, collections
from pathlib import Path
emoji = re.compile('[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U0000FE0F\U0001F1E6-\U0001F1FF\U00002300-\U000023FF]')
print('=== emoji in rendered component files (.tsx) ===')
tot = 0
for p in sorted(Path('web/src').rglob('*.tsx')):
    t = p.read_text(encoding='utf-8')
    n = len(emoji.findall(t))
    if n: print(f'  {p.name}: {n}'); tot += n
print('  TOTAL tsx:', tot)
print()
print('=== a11y / interaction attribute counts ===')
files = list(Path('web/src').rglob('*.tsx'))
all_text = '\n'.join(p.read_text(encoding='utf-8') for p in files)
for label, pat in [('aria-label','aria-label'),('aria-live','aria-live'),('aria-busy','aria-busy'),('role=','role='),('role="alert"','role="alert"'),('role="log"','role="log"'),('strokeWidth={1.5}','strokeWidth=\\{1\\.5\\}')]:
    print(f'  {label}: {len(re.findall(re.escape(pat) if chr(92) not in pat else pat, all_text))}')
css = Path('web/src/styles/globals.css').read_text(encoding='utf-8')
print()
print('=== CSS interaction guards ===')
for label, pat in [('press scale', r'scale\(0\.97\)'),('coarse pointer 44px', r'pointer: coarse'),('reduced-motion', r'prefers-reduced-motion'),('focus-visible', r':focus-visible')]:
    print(f'  {label}: {len(re.findall(pat, css))}')
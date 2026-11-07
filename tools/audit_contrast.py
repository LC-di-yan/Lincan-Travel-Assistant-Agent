"""WCAG 对比度实测：暖纸/墨色 palette 的正文与次要文本是否达 4.5:1。"""

def lum(hexc):
    hexc = hexc.lstrip('#')
    r, g, b = (int(hexc[i:i+2], 16)/255 for i in (0, 2, 4))
    def f(c): return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
    return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b)

def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

LIGHT = {'paper':'#f7f3ec','paper-raised':'#fffdf8','paper-sunken':'#efe9de',
         'ink':'#171a1f','ink-2':'#4a4f57','ink-3':'#62676f','accent':'#b83c22',
         'route':'#1f4e6b','ok':'#2f6b4f','warn':'#8a5a00','err':'#a3302a'}
DARK = {'paper':'#101418','paper-raised':'#1c222a','paper-sunken':'#171c22',
        'ink':'#f2ede4','ink-2':'#c9c3b8','ink-3':'#9a948a','accent':'#e06a4f',
        'route':'#7fb3d5','ok':'#6fbf9a','warn':'#e0b45c','err':'#e58a80'}

pairs = [('ink','paper'),('ink','paper-raised'),('ink-2','paper'),('ink-2','paper-raised'),
         ('ink-3','paper'),('ink-3','paper-raised'),('ink-3','paper-sunken'),
         ('accent','paper'),('accent','paper-raised'),('route','paper'),
         ('ok','paper'),('warn','paper'),('err','paper')]

for name, pal in (('LIGHT', LIGHT), ('DARK', DARK)):
    print('===', name, '===')
    fails = []
    for fg, bg in pairs:
        r = ratio(pal[fg], pal[bg])
        flag = 'OK' if r >= 4.5 else ('AA-large-only' if r >= 3 else 'FAIL')
        print('  %-12s on %-14s %5.2f  %s' % (fg, bg, r, flag))
        if r < 4.5: fails.append((fg, bg, round(r, 2)))
    print('  below 4.5:', fails)
    print()
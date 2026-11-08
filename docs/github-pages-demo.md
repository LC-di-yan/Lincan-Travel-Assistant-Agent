# GitHub Pages 演示（可交互对话）

## 地址

- 演示：**<https://lc-di-yan.github.io/Lincan-Travel-Assistant-Agent/demo/>**
- 落地页：<https://lc-di-yan.github.io/Lincan-Travel-Assistant-Agent/>

打开即可直接提问，**不需要后端**——因为它跑的是真实前端 + 浏览器内 mock 后端。

## 它是怎么做到的

三部分组成，都在 `docs/demo/`：

| 文件/目录 | 作用 |
|---|---|
| `index.html` + `assets/` | **真实的 React 前端构建产物**（`vite build --base=./`），与本地生产构建同一份代码 |
| `mock-backend.js` | 在页面加载前拦截 `window.fetch`，把 `/api/*` 接管掉 |
| `data/*.json` | 7 组**真实运行录制**的交互数据（意图识别 + 各技能返回） |

`mock-backend.js` 收到 `/api/chat` 后：

1. 关键词匹配到 7 个场景之一（行程/车票/知识库/天气/记账/汇率/偏好）；
2. 按真实 SSE 协议逐步吐事件：`thinking → intention → dispatching → agent_start → agent_result → complete`，
   每步之间有延迟，所以进度条、意图面板、结果卡片都会像真实运行时一样动起来；
3. 匹配不到时返回一条提示，说明演示覆盖范围。

因此用户体验与真实运行几乎一致：输入问题、看到处理链路、拿到结构化卡片、
右侧意图/实体/调度/推理面板同步更新。

## 与真实运行的区别

- 回答来自录制快照，不会再有新的推理（汇率、余票是录制时点的值）；
- 朗读 / TTS 不可用（依赖后端音频接口）；
- 覆盖 7 个场景，超出范围的输入会提示演示边界。

## 重新构建与更新

```powershell
# 1) 重新录制数据（需本地后端在跑）
python server/app.py
python tools/record_demo_data.py      # 写入 docs/demo/data/

# 2) 重新构建并部署前端
cd web; npx vite build --base=./ --outDir=dist-pages --emptyOutDir; cd ..
Get-ChildItem docs/demo -Force | Where-Object { $_.Name -notin @('data','mock-backend.js') } | Remove-Item -Recurse -Force
Copy-Item web/dist-pages/* docs/demo -Recurse -Force

# 3) 注入 mock（每次构建后都要，产物 index.html 会被覆盖）
$idx = Get-Content docs/demo/index.html -Raw
$idx = $idx -replace '<script type="module"', '<script src="mock-backend.js"></script><script type="module"'
Set-Content docs/demo/index.html -Value $idx -Encoding utf8 -NoNewline

# 4) 推送 → Pages 自动重建
git add docs/demo; git commit -m 'demo: update'; git push
```

## 发布机制

仓库的 Pages **已启用**，source 为 `main` 分支的 **`/docs`** 目录。
所以只要把文件放进 `docs/` 并 push，Pages 会自动重建——不需要改任何设置。

### 本机推送受阻时的绕行

`github.com` / `api.github.com` 被本机 hosts 指向 `127.0.0.1`（Steam++ 残留），
但真实 IP 可达。git 2.44+ 支持指定解析：

```powershell
git -c http.curloptResolve=github.com:443:140.82.114.3 push https://github.com/<owner>/<repo>.git main
```

调 GitHub API 同理：`curl --resolve api.github.com:443:140.82.112.5 ...`。
IP 可能轮换，`140.82.112.3` / `.113.3` / `.114.3` 可依次重试。

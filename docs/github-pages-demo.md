# GitHub Pages 静态演示

## 已上线

**<https://lc-di-yan.github.io/Lincan-Travel-Assistant-Agent/demo/>**

落地页（根路径）：<https://lc-di-yan.github.io/Lincan-Travel-Assistant-Agent/>

浏览器实测：7 个场景可切换、汇率卡渲染 `USD → CNY 667.13`、与主站同一套暖纸墨色视觉。

## 页面

`web/demo/` 是一个**零依赖的自包含静态页**（`index.html` + `app.js` + `data/*.json`），
内容是把项目**真实运行**产生的 7 组交互录下来回放：行程规划、火车票、知识库问答、
天气、费用记录、汇率、偏好记忆。

页面本身不含任何密钥，不发起网络请求（只读取同目录 JSON），因此可以安全地公开托管。

## 为什么是「录制回放」而不是「在线对话」

在线对话需要 Python 后端持有模型密钥。静态托管做不到这一点，也不应该把密钥打进前端。
所以这里用「真实数据 + 静态回放」：画面里的每一条回答都是真实调用大模型与技能产生的，
只是被录成了 JSON。需要实时对话请用 README 里的在线实例（隧道）。

## 重新录制数据

```powershell
python server/app.py            # 先启动后端
python tools/record_demo_data.py  # 逐场景真实请求，写入 web/demo/data/
```

> 行程规划偶发「模型返回格式有误」，脚本会记录失败态；重跑一次通常即可。

## 本地预览

```powershell
cd web/demo; python -m http.server 8099
# 打开 http://127.0.0.1:8099/
```

## 发布方式（已验证生效）

仓库的 Pages **本来就已启用**，source 为 `main` 分支的 **`/docs`** 目录。
所以只要把页面放进 `docs/demo/`、push 到 main，Pages 就会自动重建并发布——
**不需要改任何 Pages 设置**。

```
push main → Pages(main /docs) 自动构建 → /Lincan-Travel-Assistant-Agent/demo/
```

落地页 `docs/index.html` 提供根路径入口，指向 `/demo/`。

### 走过的弯路（记录以免重犯）

1. 一开始误判「GitHub Pages 不可用」——实际是本机 hosts 把 `github.com` 指向 `127.0.0.1`，
   但 `*.github.io` **不受影响**，Pages 站点一直可访问。
2. 试过用 Actions + `GITHUB_TOKEN` 改 Pages source，被拒：
   `{"message":"Resource not accessible by integration","status":403}`
   ——修改 Pages 配置需要仓库 admin 权限。
3. 最终发现 source 已是 `main /docs`，**根本不需要改配置**，放对目录即可。

### 推送受阻时的绕行（本机环境特有）

`github.com` 与 `api.github.com` 被 hosts 屏蔽，但真实 IP 可达。git 2.44+ 支持：

```powershell
git -c http.curloptResolve=github.com:443:140.82.112.3 push https://github.com/<owner>/<repo>.git main
```

调用 GitHub API 同理：`curl --resolve api.github.com:443:140.82.112.5 ...`。


## 已知限制

- 回放数据是录制时点的快照（汇率、余票会随时间变化）；
- 页面不联网，所以「朗读」等需要后端的按钮无效；
- 行程规划那条录制自第 2 次成功尝试（首轮遇到模型输出格式问题）。
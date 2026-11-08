# GitHub Pages 静态演示

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

## 发布到 GitHub Pages

`web/demo/` 的内容已推送到本仓库的 **`gh-pages` 分支**。启用只需一步（网页操作）：

1. 打开 <https://github.com/LC-di-yan/Lincan-Travel-Assistant-Agent/settings/pages>
2. **Source** 选 `Deploy from a branch`
3. **Branch** 选 `gh-pages`，目录选 `/ (root)`，点 **Save**
4. 等 1–2 分钟，访问 <https://lc-di-yan.github.io/Lincan-Travel-Assistant-Agent/>

### 为什么必须手动点

试过用 GitHub Actions 自动启用（内置 `GITHUB_TOKEN` + `permissions: pages: write`），
实测被拒：

```
gh api -X PUT repos/{owner}/{repo}/pages -f 'source[branch]=gh-pages'
→ {"message":"Resource not accessible by integration","status":403}
```

`GET /pages` 能读（说明站点已存在），但 **修改 Pages 配置需要仓库 admin 权限**，
`GITHUB_TOKEN` 不具备。因此自动化止步于此，最后一步需在网页点一下。

## 已知限制

- 回放数据是录制时点的快照（汇率、余票会随时间变化）；
- 页面不联网，所以「朗读」等需要后端的按钮无效；
- 行程规划那条录制自第 2 次成功尝试（首轮遇到模型输出格式问题）。

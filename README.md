# ALIGO 智能差旅助手

基于 Python、FastAPI、AgentScope 和 React 的多智能体差旅助手。按意图协作处理差旅规划、交通和天气查询、住宿、差旅资料检索以及费用记账。聊天记录按会话区分，个人中心、账本和偏好按浏览器身份共享。

## 快速开始

需要 Python 3.12 和 Node.js 22.13+（推荐 Node.js 24）。建议使用虚拟环境：

```bash
python -m venv .venv
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
# Linux/macOS：source .venv/bin/activate
python -m pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env`，按需填写自己的 `ALIGO_API_KEY`、`ALIGO_BASE_URL` 和 `ALIGO_MODEL_NAME`。天气、地图、语音及其他供应商使用各自的可选配置。不要提交真实 `.env`。

```bash
npm --prefix web ci
npm --prefix web run build
python scripts/build_rag_index.py
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

打开 [本机差旅助手](http://127.0.0.1:8000/)。开发前端可使用 `npm --prefix web run dev`，默认将接口转发给本机 8000 端口。

## 目录

| 目录 | 用途 |
| --- | --- |
| `agents/`、`.claude/skills/` | 意图路由、编排和专业技能 |
| `server/` | 聊天流、历史记录、个人中心和 Web 接口 |
| `context/`、`db/`、`cache/` | 持久化、可选 PostgreSQL 和 Redis |
| `rag_core/`、`scripts/` | 文档检索与离线索引构建 |
| `web/` | React 前端、资源源码和测试 |
| `tests/`、`tools/` | 回归测试、维护及静态检查 |
| `docs/`、`.github/` | 使用说明和 GitHub Actions |

## 数据与测试

- 默认使用本地 JSON，首次运行生成数据；此副本不带任何旧账号、聊天、行程、费用、认证文件或部署配置。
- 知识库仅含标注为虚构的演示样文，不是企业差旅制度或真实签证政策。使用自己的资料时，将有权使用的文本放到对应技能的 `data/documents/`，再运行索引构建命令。不要公开未授权资料。
- 交通、价格和供应情况应核对实际来源；查看历史结果不会重新查价或执行预订。费用操作须由用户确认。
- [聊天记录](docs/CONVERSATION_HISTORY.md) · [个人中心与存储](docs/PERSONAL_CENTER_RUNBOOK.md)
- 浏览器验收为可选项：安装 Playwright 和 Chromium 后，按聊天记录文档运行隔离流程。
- 测试：先使用 python -m pip install -r requirements-dev.txt 安装开发依赖，再运行`python -m pytest -m "not integration" -q` 与 `npm --prefix web test`。需要真实上游或单独服务的测试，请先按测试注释配置；对比原始知识库的历史评测不适用于本副本的虚构样文。

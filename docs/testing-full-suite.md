# 全量测试「零跳过」复跑指南

> 2026-11-07 实测：把全部前置条件补齐后，此前 7 个 skipped 用例全部可执行并通过。
> 默认 `pytest` 只跑离线用例（web 契约与决策金标准会跳过），本文说明如何解锁。

## 7 个 skipped 的来源与解锁条件

| 用例 | 跳过原因 | 解锁条件 |
|---|---|---|
| `test_health_and_static_index` | 服务未运行；且 `/` 需 `web/dist` | 启动服务 + 构建前端 |
| `test_session_and_read_endpoints` | 服务未运行 | 启动服务 |
| `test_plugin_and_persona_contracts` | 服务未运行 | 启动服务 |
| `test_history_newest_first_contract` | 服务未运行 | 启动服务 |
| `test_tts_stream_contract` | `ALIGO_AUDIO_BASE_URL` 未设 | 指向「已接 mock 上游的服务」 |
| `test_narrate_stream_contract` | 同上 | 同上 |
| `test_golden_set_accuracy` | 缺 `NEOHOUSE_API_KEY` + `ALIGO_DECISION_EVAL=1` | 配置真实 key |

## 关键语义澄清（容易踩）

`ALIGO_AUDIO_BASE_URL` **不是 mock 上游地址**，而是「已经接了 mock 上游的 Aligo 服务地址」。
测试打的是 `/api/tts` 与 `/api/narrate`（Aligo 自己的路由），并会先探它的 `/api/health`。
若误填 mock 端口（3015），会因为 mock 只有 `/health` 而报 `HTTP 404` 跳过。

正确拓扑：

```
pytest ──> Aligo 服务 :3003 ──> mock 上游 :3015
           (ALIGO_AUDIO_BASE_URL 指这里)   (MIMO_BASE_URL / NARRATION_BASE_URL 指这里)
```

## 复跑步骤（PowerShell）

```powershell
# 1) 构建前端（web/dist 与 node_modules 均已 gitignore）
cd web; npm install --no-audit --no-fund; npm run build; cd ..

# 2) 启动音频 mock（tests 不是 package，必须用 --app-dir）
python -m uvicorn mock_audio_provider:app --app-dir tests --port 3015 --log-level warning

# 3) 启动 Aligo 服务，TTS/朗读上游指向 mock
$env:MIMO_BASE_URL='http://127.0.0.1:3015/v1';      $env:MIMO_API_KEY='mock-key'
$env:NARRATION_BASE_URL='http://127.0.0.1:3015/v1'; $env:NARRATION_API_KEY='mock-key'
python server/app.py

# 4) 另开终端跑全量（服务端 env 与测试端 env 是两套，别混）
$env:ALIGO_AUDIO_BASE_URL='http://127.0.0.1:3003'   # 指服务，不是 mock
$env:ALIGO_DECISION_EVAL='1'
$env:ALIGO_DECISION_BACKEND='jev'
$env:NEOHOUSE_API_KEY='<sk_tr_...>'
python -m pytest -q -rs

# 5) 收尾：停掉服务与 mock（两个进程）
```

## 注意事项

- `server/app.py` 的静态挂载是**启动时**判定 `if dist_path.exists()`；
  先启动服务再构建前端不会生效，必须**先 build 再启动**（或重启）。
- `MIMO_BASE_URL` / `NARRATION_BASE_URL` 要带 `/v1`：路由内部拼 `{base_url}/chat/completions`。
- shell 里设的 env 优先于 `.env`（`load_dotenv()` 默认不覆盖已有变量），所以 mock 配置不会写进 `.env`。

## 实测结果（2026-11-07）

| 跑法 | 结果 |
|---|---|
| 默认 `pytest -q`（离线，无服务/无音频/无决策 key） | 196 passed · 7 skipped · 0 failed |
| 本文全部前置条件齐备 | **203 passed · 0 skipped · 0 failed**（387s） |
| 仅 web 契约（服务 + dist + mock） | 6 passed（含 TTS / 朗读 SSE 流） |

结论：AgentScope 2.0.11 升级后 **web 层契约完好** —— 健康检查与静态首页、会话与读取端点、
插件与人格契约、历史倒序、TTS 流式音频分片、朗读流式文本，全部通过。

收尾提醒：跑完记得停掉 **:3003 服务** 与 **:3015 mock** 两个进程，否则端口占用会影响下次启动。

# 个人中心：本地验证与发布前核对

个人中心在同一个 Web 应用中运行，默认关闭。支持聊天结果保存、历史版本、安排与冲突确认、关联原账本费用、出行偏好授权和收藏。它不代订票、代订房或代写消费；已安排不等于预订，「已完成」需要本人标记。

## 本地启用

在现有配置里启用 `ALIGO_PERSONAL_CENTER_ENABLED=1`，按项目原有方式构建并启动 Web。打开同源站点，点右上角「个人中心」，或访问 `/#/personal`。本地回环地址允许 HTTP；其他站点使用 HTTPS。浏览器身份保存在现有签名 Cookie 中，清理身份、换浏览器或更换服务端签名密钥后不会自动找回旧资料。

- **当前 JSON 存储**：不用执行数据库迁移；用户随后保存时，新资料与现有记忆、费用写到同一用户文件，仍使用原锁和原子写入。
- **PostgreSQL 存储**：在授权的数据库上先确认已有 `db/schema.sql`，做好备份，再按序用 `psql -v ON_ERROR_STOP=1 -f <迁移文件>` 运行 [001 行程](../db/migrations/001_personal_trips.sql)、[002 日历](../db/migrations/002_personal_schedule.sql)、[003 费用关联](../db/migrations/003_personal_expenses.sql)、[004 收藏](../db/migrations/004_personal_favorites.sql)。第三步只补旧费用的稳定引用，不修改账本金额、币种或旧 ID；可能取得表锁，应先以真实数据量演练。迁移要求 PostgreSQL 13 或以上，测试使用临时 PostgreSQL 17。应用启动不会自动执行迁移。
- 未保存的候选引用现在保留 30 分钟、受容量限制，绑定用户和会话，进程重启可能失效；保存成功的资料不受影响。要在多进程部署使用个人中心，应先验证请求亲和性；不建议在没有共享候选存储或路由亲和的情况下启用。

## 最小验证

- `python -m pytest -q tests/test_personal_trips.py tests/test_personal_conflicts.py tests/test_personal_finance.py tests/test_personal_profile.py`：JSON 和 API。PostgreSQL 集成测试只接受独立回环测试库 `aligo_personal_dev_test`，通过 `ALIGO_TEST_PERSONAL_PG_DSN` 注入。
- 在 `web` 运行 `npm run build`，以及 `node --test tests/*.mjs`，确认聊天卡片、流式输出和旧交互仍兼容。可把构建输出放到临时目录。
- `python tests/run_isolated_browser_audit.py --assets <本地构建目录> --output <新临时目录> --personal`：现有 FastAPI + Chromium + 回环模拟铁路、酒店和天气 API 的端到端流程。模拟价格和余票只是测试夹具，不能用于用户决策。若使用已有 Edge/Chromium，额外传 `--chromium-exe <路径>`。

## 启用前检查

1. 核对部署产物的前后端版本、真实同源 HTTPS、反向代理传递正确协议、持久身份密钥与存储权限；不是只检查首页能打开。
2. 用同一浏览器跨会话、刷新及重启读出已保存草稿；独立浏览器不可读。再次确认过期预检、并发安排只允许一方提交；初次启用不自动把旧摘要排到日历。
3. 用隔离测试资料确认关联费用前后原币金额相同，旧账本入口仍可用；灰度期逐步观察预检冲突率、失败率、锁等待和首个有效聊天事件。
4. 对真实铁路、酒店等供应接口仅做授权范围内的只读验证。规划中缺失或过期的证据必须继续明确提示，不用合成数据冒充。
5. 回退时先关功能开关，保留新表、已安排投影、版本和费用归属；不要用旧快照覆盖正式数据。

当前仍是同一浏览器身份，不包含跨设备账号找回、外部日历双向写入或自动预订。

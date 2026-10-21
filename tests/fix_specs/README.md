# Bug 修复文档索引

本目录包含 6 份修复文档，按"文件 + 函数区域"切分，**支持多窗口并行执行**。所有修复均针对 `tests/logic_audit/BUG_REPORT.md` 中的 33 个 bug。

## 文档总览

| 文档 | 修改文件 | 修改区域 | 负责 Bug | 预计减少 |
|------|---------|---------|---------|---------|
| [fix_01_fast_route_trip_signal.md](./fix_01_fast_route_trip_signal.md) | `agents/intention_agent.py` | `_fast_match` 顶部 + 新增 `_TRIP_SIGNAL_PATTERNS` | BUG-001~007, 013~017 (12 条) | -12 |
| [fix_02_intention_keyword_patterns.md](./fix_02_intention_keyword_patterns.md) | `agents/intention_agent.py` | `_HOTEL/RESTAURANT/SCENIC_PATTERNS`, `_TRANSLATION_PATTERNS`, `_MEMORY_PATTERNS`, `_TRAIN_PATTERNS` 日期 | BUG-008~011, 018~024, 031 (12 条) | -12 |
| [fix_03_elliptical_resolution.md](./fix_03_elliptical_resolution.md) | `agents/intention_agent.py` | `_CITY_KEYWORDS`, `_resolve_elliptical` | BUG-012 (1 条) | -1 |
| [fix_04_multi_intent_weather.md](./fix_04_multi_intent_weather.md) | `agents/intention_agent.py` | `_fast_match` 天气分支 | BUG-028, 030 (2 条) | -2 |
| [fix_05_place_search_location.md](./fix_05_place_search_location.md) | `.claude/skills/place-search/script/agent.py` | `_extract_city`, `_extract_location_context` + 新增 `_UNIVERSITY_CITY_MAP` | BUG-025~027 (3 条) | -3 |
| [fix_06_place_search_type_detection.md](./fix_06_place_search_type_detection.md) | `.claude/skills/place-search/script/agent.py` | `_is_restaurant_query`, `_is_scenic_query`, `_NON_*_KEYWORDS` | BUG-032~033 (2 条) | -2 |

合计 32 条（BUG-029 由文档 04 在备注中说明，需文档 02 配合或后续单独处理）。

## 并行安全矩阵

### `agents/intention_agent.py` 的分区（4 个窗口同时改）

```
行号范围          区域                          负责文档
─────────────────────────────────────────────────────────
185-189          _TRANSLATION_PATTERNS         文档 02
191-199          _TRAIN_PATTERNS (日期)         文档 02
201-207          _MEMORY_PATTERNS              文档 02
209-214          _CITY_KEYWORDS                文档 03
215-265          _resolve_elliptical           文档 03
267-282          _fast_match 顶部               文档 01
317-348          _fast_match 天气分支           文档 04
其他 *_PATTERNS  模块级正则                     文档 02
```

### `.claude/skills/place-search/script/agent.py` 的分区（2 个窗口同时改）

```
行号范围          区域                          负责文档
─────────────────────────────────────────────────────────
75-97            _NON_RESTAURANT/SCENIC_KW     文档 06
205-224          _is_restaurant_query          文档 06
349-364          _is_scenic_query              文档 06
471-477          _extract_city                 文档 05
481-526          _extract_location_context     文档 05
新增 ~62         _UNIVERSITY_CITY_MAP          文档 05
```

### 冲突点与协调

| 协调点 | 涉及文档 | 协调方式 |
|--------|---------|---------|
| "旅游" 关键词 | 文档 02（从 `_SCENIC_KEYWORDS` 移除）+ 文档 01（`_TRIP_SIGNAL_PATTERNS` 加"旅游"） | 文档 02 删词，文档 01 加信号，两边不冲突，合并后整体跑审计验证 |
| `_CITY_KEYWORDS` 移除火车站名 | 文档 03 | 文档 03 单独负责，CE-006 用例期望可能需同步更新 |
| 天气分支多意图附加 | 文档 04（天气分支）+ 文档 02（`_RESTAURANT_KEYWORDS` 变化） | 文档 04 建议复用 `_RESTAURANT_KEYWORDS` 而非手写列表，与文档 02 同步 |
| 高校映射 | 文档 05（新增 `_UNIVERSITY_CITY_MAP`） | 独立新增，无冲突 |

## 执行流程

每个窗口的执行步骤：

1. **认领文档**：选择一份 fix_*.md，明确自己的修改区域
2. **阅读 BUG_REPORT.md**：了解所负责 bug 的完整上下文
3. **按文档步骤修改代码**：严格遵守"修改区域"与"禁止修改"声明
4. **本地验证**：
   ```bash
   python tests/logic_audit/runner.py
   ```
   确认自己负责的 bug 转为通过，且不引入新 bug
5. **提交**：commit message 建议含 `fix(audit): N 条 bug（文档 0X）`

## 全量验证

所有窗口完成后，在主分支合并后执行：

```bash
python tests/logic_audit/runner.py
```

期望：
- 总 bug 数从 33 降至 0~1（BUG-029 可能仍残留，需单独处理）
- 附录"通过用例"含全部 79 条

若仍有残留 bug，按类别分派新一轮修复文档。

## 已知未覆盖项

- **BUG-029**（"北京景点和酒店" → 应 scenic_search + hotel_search）：文档 04 不覆盖（命中酒店分支非天气分支）。需在 `_HOTEL_PATTERNS` / `_SCENIC_PATTERNS` 分支也加多意图附加，建议后续补 `fix_07_place_search_multi_intent.md`。
- **WM-001/002/004 双城市错配**：当前是用例期望设计为通过，但实际行为是城市错配。若要严格修复，需重构 `_fast_match` 城市提取为列表，影响范围大，建议单独评估。
- **LLM 路径 bug**：本审计不覆盖，需另建 LLM 行为测试套件。

## 用例期望同步调整

部分修复会让原"通过用例"的行为变化，需同步更新用例 JSON（不是代码 bug，是用例期望收紧）：

| 用例 | 文档 | 调整内容 |
|------|------|---------|
| EL-001~005 | 文档 03 | `expected.elliptical_resolved` 从 `false` 改为 `true` |
| CE-006 | 文档 03 | 若 `_CITY_KEYWORDS` 移除"虹桥"，`expected.key_entities_destination` 可能需调整 |
| WM-001~004 | — | 若启用双城市严格校验，需新增 `expected.agents_contains` 字段 |

用例调整由各文档在"验证"章节单独说明，不阻塞代码修复。

# 凭条卡片暖色渐变方案

## 1. 动机

当前 CompactReceipt 卡片背景为 `accentColor` 的 6% 透明度叠加 `var(--bg-elevated)`：

```
linear-gradient(135deg, #f9731606 0%, var(--bg-elevated) 40%)
```

不同 Agent 的 accent 色各不相同（橙、粉、青、蓝），导致凭条风格不统一，且冷色调缺乏"旅行票据"的温度感。改为浅棕色→白色渐变，营造纸质凭条的暖调质感。

## 2. 色值体系

### 2.1 主色盘

| 角色 | 色值 | 说明 |
|------|------|------|
| 卡片渐变起点 | `#f3e8db` | 暖浅棕，模拟牛皮纸/茶渍底色 |
| 卡片渐变终点 | `#ffffff` | 纯白收尾，干净利落 |
| 暗色模式起点 | `#3d342b` | 深棕，适配暗色背景 |
| 暗色模式终点 | `var(--bg-elevated)` | 与页面暗色背景自然融合 |

### 2.2 视觉层次

```
┌─────────────────────────────────────┐
│  #f3e8db (top-left, 0%)             │  ← 暖浅棕起点
│          ↘                          │
│            ↘                        │
│              ↘  #ffffff (60%)       │  ← 纯白收尾
│                 ↘                   │
│                    #ffffff (100%)   │
└─────────────────────────────────────┘
```

渐变角度保持 135deg（左上→右下），只改色值，不改结构。

### 2.3 辅助色

| 元素 | 当前 | 改为 | 理由 |
|------|------|------|------|
| 卡片边框 | `var(--border-light)` | `rgba(180, 150, 120, 0.25)` | 暖调边框，与渐变呼应 |
| Badge 背景 | `${accentColor}15` | `${accentColor}18` | 略微增强，在暖色背景上保持辨识度 |
| 虚线分隔 | `${accentColor}30` | `rgba(180, 150, 120, 0.3)` | 统一暖调 |
| Exchange from 行 | `var(--bg-secondary)` | `rgba(243, 232, 219, 0.4)` | 半透明暖棕底 |
| Exchange to 行 | `var(--accent-light)` | 保持 `var(--accent-light)` | 保留高亮效果 |

## 3. 暗色模式

使用 CSS 媒体查询或主题变量自动切换：

```css
/* 亮色模式 */
background: linear-gradient(135deg, #f3e8db 0%, #ffffff 40%);

/* 暗色模式 */
@media (prefers-color-scheme: dark) {
  background: linear-gradient(135deg, #3d342b 0%, var(--bg-elevated) 40%);
}
```

项目已有 `var(--bg-elevated)` 等主题变量，暗色模式切换无需额外逻辑。

## 4. 改动范围

只改 **1 个文件**：`CompactReceipt.tsx`，共 **4 处** 修改：

| # | 位置 | 改动 | 影响 |
|---|------|------|------|
| 1 | `CompactReceipt` 背景渐变 | `accentColor` tint → 固定暖棕渐变 | 所有凭条卡片 |
| 2 | `CompactReceipt` 边框 | `var(--border-light)` → 暖调 rgba | 所有凭条卡片 |
| 3 | `CompactReceipt` 虚线分隔 | `${accentColor}30` → 暖调 rgba | 所有含 footer 的凭条 |
| 4 | `CompactReceiptExchange` from 行背景 | `var(--bg-secondary)` → 暖棕半透明 | 汇率/翻译卡片 |

**不改动** 的文件：

| 文件 | 为什么不改 |
|------|-----------|
| `ExpenseCard.tsx` | 只传参，不从 CompactReceipt 读颜色 |
| `PreferenceCard.tsx` | 同上 |
| `CurrencyCard.tsx` | 同上 |
| `TranslationCard.tsx` | 同上 |
| `AnimatedValue` | 大数值的渐变色保留 agent accent，与暖色背景不冲突 |

## 5. 各卡片效果预览

### 费用记录（橙色 accent `#f97316`）

```
暖棕渐变底 + 橙色 Badge「✓ 已记录」 + 橙色大字 ¥50.00
```

### 偏好管理（粉色 accent `#ec4899`）

```
暖棕渐变底 + 粉色 Badge「✓ 已记住」 + 粉色大字偏好值
```

### 汇率换算（青色 accent `#14b8a6`）

```
暖棕渐变底 + from/to 行 + 青色箭头 + 青色大字结果
```

### 翻译（蓝色 accent `#0ea5e9`）

```
暖棕渐变底 + from/to 行 + 蓝色箭头 + 蓝色大字译文 + 复制按钮
```

## 6. 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| 暗色模式下暖棕过亮 | 低 | 起点用 `#3d342b` 深棕，已在其他项目验证 |
| accent 大字在暖色底上对比度不足 | 极低 | accent 色饱和度高（橙/粉/青/蓝），与暖棕底色不冲突 |
| Exchange from 行半透明叠加在渐变上层次不清 | 中 | 用 40% 透明度，且 from 行有 `rounded-xl` 独立背景块 |

## 7. 实施

- 改动量：1 个文件，4 处修改，约 10 行
- 测试范围：费用记录、偏好、汇率、翻译 4 类卡片，亮/暗模式各测一次
- 回滚：改回 `accentColor` tint 渐变即可，零风险

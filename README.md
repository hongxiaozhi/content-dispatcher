# Content Dispatcher

独立的内容分发工具仓库。内容 Markdown 留在 `content` 工作区；本仓库保存 Python 组稿与调度脚本及公开示例配置。

## Markdown 图文编译

`scripts/compile_markdown.py` 只读取新版双正文 Markdown：顶层元数据、`full`/`short` 正文标记及平台媒体配置。它会将 SVG 转为 PNG，保持完整正文图片的原始插入位置，并输出审核结果、素材清单、可直接在浏览器打开的 `preview.html` 和平台 payload。

### 一篇 Markdown，多个平台

Markdown 是唯一内容源：顶层保存完整主标题、共享摘要、关键词和话题；正文只有 `full` 与由其忠实浓缩的 `short` 两个版本。`platforms` 只保存封面、卡片、裁切、通知等媒体配置。小红书可显式配置同主题的精简标题；标题超出平台限制时脚本会报错，绝不截断。

```yaml
---
title: "完整主标题不受小红书长度限制"
summary: "唯一的共享摘要来源。"
keywords:
  - 计算化学
hashtags:
  - 分子对接

platforms:
  wechat:
    notify_subscribers: false
    cover: "assets/03-wechat-cover.svg"
  xiaohongshu:
    title: "小红书短标题"
    cover: "assets/03-xhs-cover.svg"
    images:
      - assets/03-xhs-cover.svg
      - assets/03-xhs-card-01.svg
---

<!-- content:full:start -->

公众号使用的完整技术教程。

<!-- content:full:end -->

<!-- content:short:start -->

小红书使用的忠实简化正文。

<!-- content:short:end -->
```

微信公众号使用顶层 `title`、`summary` 和 `full`；小红书使用 `short`、顶层 `hashtags`，以及 `xiaohongshu.title`（如配置，否则使用顶层 `title`）。当小红书声明 `images` 时，编译器只使用这组卡片，不会把完整正文插图混入图文列表。旧 Markdown 格式会被正式解析器拒绝；一次性迁移请使用 `scripts/migrate_dual_content.py --write <文章路径>`。

预览结构由脚本统一生成，避免不同平台或文章漏图；颜色、品牌名、字体色和内容区宽度则放在 [`themes/default.json`](themes/default.json)。复制并修改该 JSON 后，可通过 `--theme <文件路径>` 切换预览风格，内容与发布逻辑不会受到影响。

默认只生成 `review.json`、`manifest.json` 与转换后的图片，不上传、不发布：

```powershell
python scripts/compile_markdown.py "../content/chemistry/计算化学入门/01-分子对接到底在回答什么.md" --target wechat --output-dir build/post-01
```

加上 `--upload` 后，脚本会逐张通过 `yxer upload` 上传图片，并生成可供后续校验的 payload。`--account-id` 必须来自 `yxer accounts list` 的真实结果：

```powershell
python scripts/compile_markdown.py "../content/chemistry/计算化学入门/01-分子对接到底在回答什么.md" --target wechat --account-id <公众号账号ID> --upload --output-dir build/post-01
python scripts/compile_markdown.py "../content/chemistry/计算化学入门/01-分子对接到底在回答什么.md" --target xiaohongshu --account-id <小红书账号ID> --upload --output-dir build/post-01-xhs
```

SVG 转换优先使用 macOS 自带的 `sips`；Linux 会自动尝试 `rsvg-convert` 或 ImageMagick。找不到转换器时会终止，不会悄悄忽略图片。

`scripts/yxer_publish.py` 使用 Python 标准库包装蚁小二的 `yxer` CLI，可从 TOML 选择平台、内容类型、payload 路径和 `cloud` / `local` 通道。

## 安全流程

`release` 固定使用同一份 payload 和同一套通道参数执行：

`validate → dry-run → 输入 PUBLISH 确认 → publish`

脚本不读取或显示 Cookie、二维码、API Key、登录态或 payload 正文。真实账号、素材上传、动态字段查询和 payload 组装仍应通过 `yxer` 完成。

## 使用

```powershell
Copy-Item config.example.toml config.toml
python scripts/yxer_publish.py --config config.toml doctor
python scripts/yxer_publish.py --config config.toml accounts
python scripts/yxer_publish.py --config config.toml validate
python scripts/yxer_publish.py --config config.toml dry-run
python scripts/yxer_publish.py --config config.toml release
```

正式发布只会在交互终端中输入 `PUBLISH` 后继续。`config.toml`、payload 和 `.state` 已由 Git 忽略。

## GitHub

```powershell
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

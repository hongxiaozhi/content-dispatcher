# Content Dispatcher

独立的内容分发工具仓库。内容 Markdown 留在 `content` 工作区；本仓库只保存 Python 调度脚本与公开示例配置。

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

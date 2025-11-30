# Render 部署指南

## 问题解决

如果遇到 "Port scan timeout" 错误，原因是应用没有正确绑定到 `0.0.0.0` 或没有使用环境变量 `PORT`。

## 已修复的问题

1. ✅ 应用现在会从环境变量 `PORT` 读取端口（Render 自动提供）
2. ✅ 应用绑定到 `0.0.0.0` 以允许外部访问
3. ✅ 添加了 `gunicorn` 作为生产服务器
4. ✅ 创建了 `Procfile` 用于 Render 部署
5. ✅ 创建了 `render.yaml` 配置文件（可选）

## 部署步骤

### 方法 1: 使用 Procfile（推荐）

1. 在 Render 上创建新的 Web Service
2. 连接你的 GitHub 仓库
3. Render 会自动检测 `Procfile` 并使用 `gunicorn` 启动应用
4. 确保设置以下环境变量：
   - `OPENAI_API_KEY`: 你的 OpenAI API 密钥
   - `SECRET_KEY`: Flask 会话密钥（随机字符串）
   - `FLASK_DEBUG`: 设置为 `False`（生产环境）

### 方法 2: 使用 render.yaml

1. 在 Render Dashboard 中选择 "New" -> "Blueprint"
2. 连接你的 GitHub 仓库
3. Render 会自动读取 `render.yaml` 配置

## 环境变量

在 Render Dashboard 的 Environment 部分添加：

```
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_random_secret_key_here
FLASK_DEBUG=False
```

## 注意事项

1. **数据库**: 当前使用 SQLite，在 Render 上文件系统是临时的。如果需要持久化数据，建议使用 PostgreSQL（Render 提供免费 PostgreSQL 数据库）。

2. **静态文件**: 确保前端构建文件在 `docs/` 目录中。如果使用 `frontend/build/`，需要修改 `app.py` 中的 `static_folder` 参数。

3. **端口**: Render 会自动通过环境变量 `PORT` 提供端口，应用会自动使用。

4. **日志**: 在 Render Dashboard 的 Logs 部分可以查看应用日志。

## 故障排除

如果仍然遇到端口问题：

1. 检查 Render 日志，确认应用是否正常启动
2. 确认 `Procfile` 中的命令正确：`web: gunicorn app:app`
3. 确认 `gunicorn` 已添加到 `requirements.txt`
4. 检查环境变量 `PORT` 是否被正确读取


# 环境变量配置说明

## 创建 .env 文件

在项目根目录创建 `.env` 文件，内容如下：

```
OPENAI_API_KEY=your-openai-api-key-here
SECRET_KEY=your-secret-key-here
```

## 获取 OpenAI API Key

1. 访问 [OpenAI Platform](https://platform.openai.com/)
2. 注册或登录账户
3. 进入 API Keys 页面
4. 创建新的 API Key
5. 将 API Key 复制到 `.env` 文件中的 `OPENAI_API_KEY`

## SECRET_KEY

`SECRET_KEY` 用于 Flask 会话加密，可以生成一个随机字符串：

```python
import secrets
print(secrets.token_hex(32))
```

将生成的字符串填入 `.env` 文件中的 `SECRET_KEY`。

## 注意事项

- `.env` 文件已添加到 `.gitignore`，不会被提交到版本控制
- 不要将 API Key 分享给他人
- 如果 API Key 泄露，请立即在 OpenAI 平台撤销并重新生成



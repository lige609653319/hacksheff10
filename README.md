# AA 账单助手

一个基于 React 和 Flask 的智能 AA 账单提取应用，使用 LangChain 和 OpenAI 从自然语言描述中提取结构化的账单信息。

## 功能特性

- ✅ 使用 LangChain 框架
- ✅ HTTP 流式响应（Server-Sent Events）
- ✅ 从自然语言提取结构化账单信息
- ✅ 美观的账单卡片展示
- ✅ 现代化的用户界面
- ✅ 响应式设计，支持移动端
- ✅ 连接状态显示
- ✅ 支持取消正在进行的请求

## 项目结构

```
FlaskProject/
├── app.py                 # Flask 后端主文件
├── requirements.txt       # Python 依赖
├── .env.example          # 环境变量示例
├── frontend/             # React 前端项目
│   ├── src/
│   │   ├── App.js        # 主应用组件
│   │   └── App.css       # 样式文件
│   └── package.json
└── README.md
```

## 安装和运行

### 1. 后端设置

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 创建 .env 文件（复制 .env.example）
cp .env.example .env

# 编辑 .env 文件，填入你的 OpenAI API Key
# OPENAI_API_KEY=your-api-key-here
# SECRET_KEY=your-secret-key-here

# 运行 Flask 服务器
python app.py
```

后端将在 `http://localhost:5000` 启动。

### 2. 前端设置

```bash
# 进入前端目录
cd frontend

# 安装依赖（如果还没有安装）
npm install

# 启动开发服务器
npm start
```

前端将在 `http://localhost:3000` 启动。

## 使用说明

1. 确保后端和前端都已启动
2. 在浏览器中打开前端应用（通常是 `http://localhost:3000`）
3. 等待连接状态显示"已连接"
4. 输入账单描述，例如：
   - "张三、李四、王五一起吃了晚餐，张三付了200元"
   - "我和小明打车花了50块，我付的钱"
   - "Alice 和 Bob 在咖啡店消费了 30 美元，Alice 付款"
5. AI 将实时流式返回解析后的账单信息
6. 账单信息将以卡片形式美观展示

## 技术栈

### 后端
- Flask - Python Web 框架
- LangChain - LLM 应用框架
- LangChain OpenAI - OpenAI 集成
- OpenAI API - AI 模型
- python-dotenv - 环境变量管理
- Server-Sent Events (SSE) - 流式响应

### 前端
- React - UI 框架
- Fetch API - HTTP 请求和流式读取
- CSS3 - 样式和动画

## API 接口

### POST /api/chat
发送账单描述，返回流式响应（Server-Sent Events）

**请求体：**
```json
{
  "message": "张三、李四一起吃了晚餐，张三付了200元"
}
```

**响应格式（SSE）：**
```
data: {"type": "start"}
data: {"type": "chunk", "content": "..."}
data: {"type": "json", "data": [{"topic": "晚餐", "payer": "张三", ...}]}
data: {"type": "complete"}
```

### GET /api/health
健康检查接口

**响应：**
```json
{
  "status": "ok",
  "client_configured": true
}
```

## 账单信息字段

提取的账单信息包含以下字段：

- **topic**: 消费主题/用途（例如：晚餐、打车、旅馆、咖啡等）
- **payer**: 实际付款的人（字符串）
- **participants**: 所有关联的人名列表（字符串数组）
- **amount**: 此笔消费总金额（数字）
- **currency**: 货币（如 "CNY", "GBP", "USD"），默认为 "CNY"
- **note**: 其他补充信息（可选）

## 解析规则

- 若用户提供的语句中包含多笔消费，会分成多条 JSON 记录
- 若未提及 participants，则默认 participants 为包含 payer 在内的所有出现的人名
- 若用户未提及货币，默认 currency="CNY"
- 若出现模糊金额（如"差不多 100 块"），按数字部分提取 amount=100
- 若无法解析，返回一个空数组 []

## 注意事项

1. **API Key**: 需要有效的 OpenAI API Key 才能使用 AI 功能
2. **CORS**: 后端已配置允许所有来源的 CORS，生产环境请修改
3. **端口**: 确保端口 5000（后端）和 3000（前端）未被占用
4. **流式响应**: 使用 Server-Sent Events (SSE) 实现，浏览器原生支持

## 开发建议

- 生产环境部署时，建议使用 Nginx 作为反向代理
- 可以考虑添加账单历史记录功能
- 可以添加账单导出功能（JSON/CSV）
- 建议添加错误重试机制
- 可以考虑添加请求超时处理

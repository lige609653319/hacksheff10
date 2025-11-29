# Smart Assistant - AI Chat & TripWise Pro

一个基于 React 和 Flask 的智能助手应用，包含 AI 聊天功能和 AA 账单管理功能。使用 LangChain 和 OpenAI 进行智能对话和账单信息提取。

## 功能特性

### 💬 AI 聊天助手
- ✅ 使用 LangChain 框架
- ✅ HTTP 流式响应（Server-Sent Events）
- ✅ 智能路由：自动识别旅行相关或账单相关问题
- ✅ 旅行助手：提供旅行建议、行程规划等
- ✅ 账单助手：从自然语言提取结构化账单信息
- ✅ 账单查询：支持按 ID、付款人、参与者查询
- ✅ 数据库存储：SQLite 存储账单记录
- ✅ 现代化的用户界面
- ✅ 响应式设计，支持移动端
- ✅ 连接状态显示
- ✅ 支持取消正在进行的请求

### 🌍 TripWise Pro - AA 账单管理
- ✅ 费用记录：添加、删除费用记录
- ✅ 参与者管理：添加、删除参与者
- ✅ 自动结算：智能计算最优结算方案
- ✅ 数据同步：从后端加载已保存的账单
- ✅ 美观的结算支票展示
- ✅ 使用 Tailwind CSS 构建的现代化界面

## 项目结构

```
FlaskProject/
├── app.py                      # Flask 后端主文件
├── requirements.txt            # Python 依赖
├── .env                        # 环境变量（不提交到 git）
├── instance/                   # SQLite 数据库目录
│   └── bills.db               # 账单数据库
├── frontend/                   # React 前端项目
│   ├── src/
│   │   ├── App.js             # 路由入口
│   │   ├── ChatApp.js          # 聊天应用组件
│   │   ├── pages/
│   │   │   └── TripWisePro.js  # TripWise Pro 页面
│   │   ├── components/
│   │   │   ├── JsonImport.js   # 数据导入组件
│   │   │   └── SettlementCheque.js  # 结算支票组件
│   │   ├── types.js            # 类型定义
│   │   └── App.css             # 样式文件
│   ├── package.json
│   ├── tailwind.config.js      # Tailwind CSS 配置
│   └── postcss.config.js       # PostCSS 配置
└── README.md
```

## 安装和运行

### 1. 克隆仓库

```bash
git clone <repository-url>
cd FlaskProject
```

### 2. 后端设置

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 创建 .env 文件
cp .env.example .env  # 如果存在
# 或手动创建 .env 文件

# 编辑 .env 文件，填入你的 OpenAI API Key
# OPENAI_API_KEY=your-api-key-here
# SECRET_KEY=your-secret-key-here

# 运行 Flask 服务器
python app.py
```

后端将在 `http://localhost:5000` 启动。

### 3. 前端设置

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm start
```

前端将在 `http://localhost:3000` 启动。

## 使用说明

### AI 聊天助手

1. 访问 `http://localhost:3000/` 进入聊天页面
2. 等待连接状态显示"Connected"
3. 可以询问：
   - **旅行相关问题**：例如 "I want to travel to Beijing"
   - **账单记录**：例如 "Alice and Bob had dinner together, Alice paid $50"
   - **账单查询**：例如 "Query bill ID 1" 或 "What bills did Alice pay?"

### TripWise Pro

1. 访问 `http://localhost:3000/tripwise` 进入账单管理页面
2. 添加参与者
3. 添加费用记录
4. 切换到 "Settlements" 标签查看自动计算的结算方案
5. 点击 "Load Expenses from Server" 从后端加载已保存的账单

## 技术栈

### 后端
- Flask - Python Web 框架
- LangChain - LLM 应用框架
- LangChain OpenAI - OpenAI 集成
- OpenAI API - AI 模型
- Flask-SQLAlchemy - ORM 数据库操作
- SQLite - 数据库
- python-dotenv - 环境变量管理
- Server-Sent Events (SSE) - 流式响应

### 前端
- React - UI 框架
- React Router - 路由管理
- Tailwind CSS - 样式框架
- Fetch API - HTTP 请求和流式读取

## API 接口

### POST /api/chat
发送消息，返回流式响应（Server-Sent Events）

**请求体：**
```json
{
  "message": "Alice and Bob had dinner, Alice paid $50"
}
```

**响应格式（SSE）：**
```
data: {"type": "start"}
data: {"type": "agent", "agent": "bill"}
data: {"type": "chunk", "content": "Bill successfully recorded! Bill ID: 1"}
data: {"type": "complete"}
```

### GET /api/health
健康检查接口

### GET /api/bills
查询账单列表

**查询参数：**
- `page`: 页码（默认 1）
- `per_page`: 每页数量（默认 20）
- `payer`: 按付款人筛选（可选）

### POST /api/bills
创建新账单

### GET /api/bills/<id>
根据 ID 查询单个账单

## 账单信息字段

提取的账单信息包含以下字段：

- **topic**: 消费主题/用途（例如：晚餐、打车、旅馆、咖啡等）
- **payer**: 实际付款的人（字符串）
- **participants**: 所有关联的人名列表（字符串数组）
- **amount**: 此笔消费总金额（数字）
- **currency**: 货币（如 "CNY", "GBP", "USD"），默认为 "CNY"
- **note**: 其他补充信息（可选）

## 开发

### Git 工作流

项目使用单一 Git 仓库管理前后端代码：

```bash
# 查看状态
git status

# 添加文件
git add .

# 提交
git commit -m "your message"

# 推送到远程
git push
```

### 环境变量

创建 `.env` 文件（不会被提交到 git）：

```
OPENAI_API_KEY=your-api-key-here
SECRET_KEY=your-secret-key-here
```

## 注意事项

1. **API Key**: 需要有效的 OpenAI API Key 才能使用 AI 功能
2. **CORS**: 后端已配置允许所有来源的 CORS，生产环境请修改
3. **端口**: 确保端口 5000（后端）和 3000（前端）未被占用
4. **数据库**: SQLite 数据库文件存储在 `instance/` 目录，不会被提交到 git

## 许可证

MIT License

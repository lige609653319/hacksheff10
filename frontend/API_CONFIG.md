# API 配置说明

## 概述

前端应用现在使用统一的 API 配置，支持通过环境变量或自动检测来设置后端 API 地址。

## 配置方式

### 方式 1: 使用环境变量（推荐）

在项目根目录创建 `.env` 文件（开发环境）或 `.env.production` 文件（生产环境）：

**开发环境 (.env):**
```
REACT_APP_API_URL=http://127.0.0.1:5000
```

**生产环境 (.env.production):**
```
REACT_APP_API_URL=https://hacksheff10.onrender.com
```

### 方式 2: 自动检测（默认）

如果不设置环境变量，系统会根据 `NODE_ENV` 自动选择：
- **生产环境** (`NODE_ENV=production`): 使用 `https://hacksheff10.onrender.com`
- **开发环境**: 使用 `http://127.0.0.1:5000`

## 当前配置

- **生产环境后端**: `https://hacksheff10.onrender.com`
- **开发环境后端**: `http://127.0.0.1:5000`

## 修改配置

所有 API 调用现在都通过 `src/config.js` 统一管理。如果需要修改后端地址：

1. 修改 `src/config.js` 中的默认值
2. 或设置环境变量 `REACT_APP_API_URL`

## 使用示例

```javascript
import { API_URL } from './config';

// 使用 API_URL 进行 API 调用
fetch(`${API_URL}/api/endpoint`)
```

## 注意事项

- React 环境变量必须以 `REACT_APP_` 开头才能在前端代码中访问
- 修改环境变量后需要重启开发服务器
- 生产构建时，环境变量会被编译到代码中


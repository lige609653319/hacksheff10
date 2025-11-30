// API 配置
// 优先使用环境变量，如果没有则根据当前环境自动选择
const getApiUrl = () => {
  // 如果设置了环境变量，优先使用
  if (process.env.REACT_APP_API_URL) {
    return process.env.REACT_APP_API_URL;
  }
  
  // 生产环境使用 Render 部署的地址
  if (process.env.NODE_ENV === 'production') {
    return 'https://hacksheff10.onrender.com';
  }
  
  // 开发环境使用本地地址
  return 'http://127.0.0.1:5000';
};

export const API_URL = getApiUrl();


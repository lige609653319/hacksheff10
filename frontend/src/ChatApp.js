import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

const API_URL = 'http://127.0.0.1:5000';

function ChatApp() {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentAgent, setCurrentAgent] = useState(null);
  const [userId, setUserId] = useState(null);
  const [username, setUsername] = useState(null);
  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);
  const messageIdCounter = useRef(0);
  const eventSourceRef = useRef(null);
  
  // 获取或创建user_id和username
  useEffect(() => {
    const initUser = async () => {
      let storedUserId = localStorage.getItem('chat_user_id');
      let storedUsername = localStorage.getItem('chat_username');
      
      if (storedUserId && storedUsername) {
        // 验证用户是否存在
        try {
          const response = await fetch(`${API_URL}/api/user?user_id=${storedUserId}`);
          if (response.ok) {
            const data = await response.json();
            setUserId(data.user_id);
            setUsername(data.username);
            return;
          }
        } catch (error) {
          console.error('验证用户失败:', error);
        }
      }
      
      // 创建新用户
      try {
        const response = await fetch(`${API_URL}/api/user`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        });
        if (response.ok) {
          const data = await response.json();
          localStorage.setItem('chat_user_id', data.user_id);
          localStorage.setItem('chat_username', data.username);
          setUserId(data.user_id);
          setUsername(data.username);
        }
      } catch (error) {
        console.error('创建用户失败:', error);
      }
    };
    
    initUser();
  }, []);
  
  // 连接到SSE事件流
  useEffect(() => {
    if (!userId) return;
    
    const connectEvents = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      
      const eventSource = new EventSource(`${API_URL}/api/events?user_id=${userId}`);
      eventSourceRef.current = eventSource;
      
      eventSource.onmessage = (event) => {
        if (event.data === 'heartbeat') return;
        
        try {
          const message = JSON.parse(event.data);
          
          // 检查消息是否已存在（用于实时更新）
          setMessages(prev => {
            const existingIndex = prev.findIndex(msg => msg.id === message.id);
            
            if (existingIndex >= 0) {
              // 如果消息已存在，更新它（用于流式更新）
              const updated = [...prev];
              updated[existingIndex] = {
                ...updated[existingIndex],
                content: message.content !== undefined ? message.content : updated[existingIndex].content,
                agent: message.agent !== undefined ? message.agent : updated[existingIndex].agent,
                planner: message.planner !== undefined ? message.planner : updated[existingIndex].planner,
                isStreaming: message.isStreaming !== undefined ? message.isStreaming : (message.type === 'planner' || message.type === 'ai')
              };
              return updated;
            }
            
            // 添加新消息
            return [...prev, {
              id: message.id || messageIdCounter.current++,
              type: message.type,
              user_id: message.user_id,
              username: message.username,
              content: message.content || '',
              agent: message.agent,
              planner: message.planner,
              timestamp: message.timestamp,
              isOwnMessage: message.user_id === userId,
              isStreaming: message.isStreaming !== undefined ? message.isStreaming : (message.type === 'planner' || message.type === 'ai')
            }];
          });
          
          // 更新currentAgent
          if (message.agent) {
            setCurrentAgent(message.agent);
          }
        } catch (error) {
          console.error('解析SSE消息失败:', error, event.data);
        }
      };
      
      eventSource.onerror = (error) => {
        console.error('SSE连接错误:', error);
        // 尝试重连
        setTimeout(connectEvents, 3000);
      };
    };
    
    connectEvents();
    
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [userId]);
  
  // 获取或创建session_id（使用localStorage持久化）
  const getSessionId = () => {
    let sessionId = localStorage.getItem('travel_session_id');
    if (!sessionId) {
      // 生成新的UUID格式的session_id
      sessionId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
      });
      localStorage.setItem('travel_session_id', sessionId);
    }
    return sessionId;
  };

  // Check connection status
  useEffect(() => {
    const checkConnection = async () => {
      try {
        const response = await fetch(`${API_URL}/api/health`);
        if (response.ok) {
          setIsConnected(true);
        } else {
          setIsConnected(false);
        }
      } catch (error) {
        setIsConnected(false);
      }
    };

    checkConnection();
    const interval = setInterval(checkConnection, 5000); // Check every 5 seconds

    return () => clearInterval(interval);
  }, []);

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading || !userId) return;

    // 用户消息会通过SSE广播接收，这里不需要手动添加
    const messageToSend = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    // Create AbortController for canceling requests
    abortControllerRef.current = new AbortController();

    // Save user input for future bill saving
    const currentUserInput = messageToSend;

    try {
      // 获取session_id
      const sessionId = getSessionId();
      
      const response = await fetch(`${API_URL}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId,  // 在请求头中发送session_id
          'X-User-ID': userId,  // 在请求头中发送user_id
        },
        body: JSON.stringify({ 
          message: messageToSend,
          session_id: sessionId,  // 也在请求体中发送（双重保险）
          user_id: userId  // 也在请求体中发送user_id
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // 消息会通过SSE广播接收，这里只需要等待响应完成
      const reader = response.body.getReader();
      while (true) {
        const { done } = await reader.read();
        if (done) {
          setIsLoading(false);
          break;
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Request cancelled');
      } else {
        console.error('Send message error:', error);
        console.error('Error details:', {
          name: error.name,
          message: error.message,
          stack: error.stack
        });
        setIsLoading(false);
        setMessages(prev => {
          const newMessages = [...prev];
          const lastIndex = newMessages.length - 1;
          if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
            // Update error message instead of removing
            let errorMessage = `Error sending message: ${error.message}`;
            if (error.message === 'Failed to fetch') {
              errorMessage += '\n\nPossible causes:\n- Server is not running\n- CORS configuration issue\n- Network connection problem\n\nPlease check:\n1. Is the Flask server running on http://127.0.0.1:5000?\n2. Check browser console for more details';
            }
            newMessages[lastIndex] = {
              ...newMessages[lastIndex],
              content: errorMessage,
              isStreaming: false
            };
          }
          return [...newMessages, { 
            id: messageIdCounter.current++, 
            type: 'error', 
            content: `Error sending message: ${error.message}` 
          }];
        });
      }
    }
  };

  // Query bill data (kept for future possible direct query functionality)
  const fetchBills = async (page = 1, payer = null) => {
    try {
      let url = `${API_URL}/api/bills?page=${page}&per_page=20`;
      if (payer) {
        url += `&payer=${encodeURIComponent(payer)}`;
      }
      
      const response = await fetch(url);
      if (response.ok) {
        const result = await response.json();
        return result;
      } else {
        console.error('Query bills failed:', await response.text());
        return null;
      }
    } catch (error) {
      console.error('Query bills error:', error);
      return null;
    }
  };

  // Cancel request
  const cancelRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsLoading(false);
    }
  };

  return (
    <div className="App">
      <div className="chat-container">
        <div className="chat-header">
          <h1>💬 Multi-User Chat Room</h1>
          <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
            {username && (
              <div className="user-badge" style={{padding: '5px 10px', background: '#4CAF50', color: 'white', borderRadius: '15px', fontSize: '14px'}}>
                👤 {username}
              </div>
            )}
            {currentAgent && (
              <div className="agent-badge">
                {currentAgent === 'travel' && '✈️ Travel Assistant'}
                {currentAgent === 'bill' && '💰 Bill Assistant'}
                {currentAgent === 'unknown' && '❓ Unknown'}
              </div>
            )}
            <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
              {isConnected ? '● Connected' : '○ Disconnected'}
            </div>
          </div>
        </div>
        
        <div className="messages-container">
          {messages.length === 0 && (
            <div className="welcome-message">
              <p>👋 Welcome to Smart Assistant!</p>
              <p>I can help you with the following:</p>
              <ul style={{textAlign: 'left', marginTop: '10px', fontSize: '14px', color: '#666'}}>
                <li>✈️ Travel-related questions (trip planning, attraction recommendations, etc.)</li>
                <li>💰 Bill-related questions:</li>
                <li style={{marginLeft: '20px'}}>- Record bills: "Alice and Bob had dinner together, Alice paid $50"</li>
                <li style={{marginLeft: '20px'}}>- Query bills: "Query bill ID 1" or "What bills did Alice pay?" or "Bills involving Bob"</li>
              </ul>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`message ${msg.type} ${msg.isOwnMessage ? 'own-message' : ''}`}>
              <div className="message-content">
                {msg.type === 'user' && (
                  <span className="message-label">
                    {msg.isOwnMessage ? 'You' : (msg.username || 'User')}:
                  </span>
                )}
                {msg.type === 'ai' && (
                  <span className="message-label">
                    {msg.username && !msg.isOwnMessage && `${msg.username} - `}
                    {msg.agent === 'travel' && '✈️ Travel Assistant:'}
                    {msg.agent === 'bill' && '💰 Bill Assistant:'}
                    {(!msg.agent || msg.agent === 'unknown') && '🤖 Assistant:'}
                  </span>
                )}
                {msg.type === 'planner' && (
                  <span className="message-label">
                    {msg.username && !msg.isOwnMessage && `${msg.username} - `}
                    {msg.planner}:
                  </span>
                )}
                {msg.type === 'error' && (
                  <span className="message-label">
                    {msg.username && !msg.isOwnMessage && `${msg.username} - `}
                    Error:
                  </span>
                )}
                <div className="message-text">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
                {msg.isStreaming && <span className="cursor">▋</span>}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <form className="input-container" onSubmit={sendMessage}>
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder="Enter your question, e.g.: I want to travel to Beijing / Alice and Bob had dinner, Alice paid $50 / Query bill ID 1"
            disabled={isLoading}
            className="message-input"
          />
          {isLoading ? (
            <button
              type="button"
              onClick={cancelRequest}
              className="send-button cancel-button"
            >
              Cancel
            </button>
          ) : (
            <button
              type="submit"
              disabled={!inputMessage.trim()}
              className="send-button"
            >
              Send
            </button>
          )}
        </form>
      </div>
    </div>
  );
}

export default ChatApp;



import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const API_URL = 'http://127.0.0.1:5000';

function ChatApp() {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentAgent, setCurrentAgent] = useState(null);
  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);
  const messageIdCounter = useRef(0);

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
    if (!inputMessage.trim() || isLoading) return;

    const userMessage = { 
      id: messageIdCounter.current++, 
      type: 'user', 
      content: inputMessage 
    };
    setMessages(prev => [...prev, userMessage]);
    const messageToSend = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    // Create new AI message placeholder
    const aiMessage = { 
      id: messageIdCounter.current++, 
      type: 'ai', 
      content: '', 
      isStreaming: true 
    };
    setMessages(prev => [...prev, aiMessage]);

    // Create AbortController for canceling requests
    abortControllerRef.current = new AbortController();

    // Save user input for future bill saving
    const currentUserInput = messageToSend;

    try {
      const response = await fetch(`${API_URL}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: messageToSend }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep the last incomplete line

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.type === 'start') {
                // Start receiving data, reset content
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastIndex = newMessages.length - 1;
                  if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
                    // Create new object instead of modifying existing one
                    newMessages[lastIndex] = {
                      ...newMessages[lastIndex],
                      content: ''
                    };
                  }
                  return newMessages;
                });
              } else if (data.type === 'agent') {
                // Receive agent type
                setCurrentAgent(data.agent);
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastIndex = newMessages.length - 1;
                  if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
                    // Update message's agent type
                    newMessages[lastIndex] = {
                      ...newMessages[lastIndex],
                      agent: data.agent
                    };
                  }
                  return newMessages;
                });
              } else if (data.type === 'chunk') {
                // Receive data chunk
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastIndex = newMessages.length - 1;
                  if (lastIndex >= 0 && 
                      newMessages[lastIndex].type === 'ai' && 
                      newMessages[lastIndex].isStreaming) {
                    // Create new object, append content
                    newMessages[lastIndex] = {
                      ...newMessages[lastIndex],
                      content: newMessages[lastIndex].content + data.content
                    };
                  }
                  return newMessages;
                });
              } else if (data.type === 'bill_ids') {
                // Receive bill ID information (already saved to database)
                // Bill ID information is already displayed in chunk, can do additional processing here
                console.log('Bills saved, IDs:', data.ids);
              } else if (data.type === 'complete') {
                // Complete
                setIsLoading(false);
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastIndex = newMessages.length - 1;
                  if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
                    // Create new object, stop streaming
                    newMessages[lastIndex] = {
                      ...newMessages[lastIndex],
                      isStreaming: false
                    };
                  }
                  return newMessages;
                });
              } else if (data.type === 'error') {
                // Error
                setIsLoading(false);
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastIndex = newMessages.length - 1;
                  if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
                    // Remove streaming message, add error message
                    newMessages.pop();
                  }
                  return [...newMessages, { 
                    id: messageIdCounter.current++, 
                    type: 'error', 
                    content: data.content 
                  }];
                });
              }
            } catch (parseError) {
              console.error('Parse data error:', parseError);
            }
          }
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Request cancelled');
      } else {
        console.error('Send message error:', error);
        setIsLoading(false);
        setMessages(prev => {
          const newMessages = [...prev];
          const lastIndex = newMessages.length - 1;
          if (lastIndex >= 0 && newMessages[lastIndex].type === 'ai') {
            // Remove incomplete AI message
            newMessages.pop();
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
          <h1>🤖 Smart Assistant</h1>
          <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
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
            <div key={msg.id} className={`message ${msg.type}`}>
              <div className="message-content">
                {msg.type === 'user' && <span className="message-label">You:</span>}
                {msg.type === 'ai' && (
                  <span className="message-label">
                    {msg.agent === 'travel' && '✈️ Travel Assistant:'}
                    {msg.agent === 'bill' && '💰 Bill Assistant:'}
                    {(!msg.agent || msg.agent === 'unknown') && '🤖 Assistant:'}
                  </span>
                )}
                {msg.type === 'error' && <span className="message-label">Error:</span>}
                <span className="message-text">{msg.content}</span>
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



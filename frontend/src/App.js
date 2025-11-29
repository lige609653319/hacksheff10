import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import ChatApp from './ChatApp';
import TripWisePro from './pages/TripWisePro';

const Navigation = () => {
  const location = useLocation();
  
  return (
    <nav style={{
      backgroundColor: '#f8f9fa',
      padding: '10px 20px',
      borderBottom: '1px solid #dee2e6',
      display: 'flex',
      gap: '20px',
      alignItems: 'center'
    }}>
      <Link 
        to="/" 
        style={{
          textDecoration: 'none',
          color: location.pathname === '/' ? '#4f46e5' : '#6c757d',
          fontWeight: location.pathname === '/' ? 'bold' : 'normal',
          padding: '8px 16px',
          borderRadius: '4px',
          backgroundColor: location.pathname === '/' ? '#eef2ff' : 'transparent'
        }}
      >
        💬 Chat Assistant
      </Link>
      <Link 
        to="/tripwise" 
        style={{
          textDecoration: 'none',
          color: location.pathname === '/tripwise' ? '#4f46e5' : '#6c757d',
          fontWeight: location.pathname === '/tripwise' ? 'bold' : 'normal',
          padding: '8px 16px',
          borderRadius: '4px',
          backgroundColor: location.pathname === '/tripwise' ? '#eef2ff' : 'transparent'
        }}
      >
        🌍 TripWise Pro
      </Link>
    </nav>
  );
};

function App() {
  return (
    <Router>
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Navigation />
        <Routes>
          <Route path="/" element={<ChatApp />} />
          <Route path="/tripwise" element={<TripWisePro />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;

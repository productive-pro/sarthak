import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.jsx';

// Inject Inter font (variable weight, no-flash)
const link = document.createElement('link');
link.rel = 'preconnect';
link.href = 'https://fonts.googleapis.com';
document.head.appendChild(link);
const link2 = document.createElement('link');
link2.rel = 'stylesheet';
link2.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
document.head.appendChild(link2);

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>
);

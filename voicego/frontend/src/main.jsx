import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import './styles/tokens.css';
import './styles/global.css';

// NOTE: no React.StrictMode — its double-invoke of mount effects (in dev) was
// cancelling the greeting/auto-listen init before it could run.
ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);

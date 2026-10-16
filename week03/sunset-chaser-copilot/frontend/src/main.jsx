import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App.jsx';
import './styles.css';
import 'leaflet/dist/leaflet.css';

// StrictMode is on deliberately: it double-invokes effects in development, which
// is exactly the fault mode that breaks an imperatively-mounted Leaflet map.
// Leaving it on means that guard is exercised on every run rather than only in
// the case someone remembers to test.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);

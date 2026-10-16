import { Link, Route, Routes } from 'react-router-dom';

import { CameraPage } from './pages/CameraPage.jsx';
import { ChasePage } from './pages/ChasePage.jsx';
import { EmptyState } from './components/EmptyState.jsx';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link className="app-brand" to="/">
          <span className="app-brand-mark" aria-hidden="true" />
          <span>
            <strong>Sunset Chaser</strong>
            <small>Webcams on the day/night line</small>
          </span>
        </Link>
        <nav className="app-nav">
          <Link to="/">Chase</Link>
        </nav>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<ChasePage />} />
          <Route path="/camera/:webcamId" element={<CameraPage />} />
          {/* A real 404 rather than a silent redirect, so a typo is visible. */}
          <Route
            path="*"
            element={
              <EmptyState
                title="No such page"
                detail="That address does not match anything in this app."
                hints={['Try the main chase view at /']}
              />
            }
          />
        </Routes>
      </main>

      <footer className="app-footer">
        <p>
          Sun position computed locally with{' '}
          <a href="https://github.com/cosinekitty/astronomy" target="_blank" rel="noreferrer noopener">
            astronomy-engine
          </a>
          . Camera data from{' '}
          <a href="https://www.windy.com/" target="_blank" rel="noreferrer noopener">
            Windy.com
          </a>
          , whose free tier requires this link back.
        </p>
      </footer>
    </div>
  );
}

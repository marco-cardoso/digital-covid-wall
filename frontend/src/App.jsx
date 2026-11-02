import { useState } from 'react'
import WallPanorama from './components/WallPanorama'
import Victims from './components/Victims'
import Dashboard from './components/Dashboard'
import './App.css'

const VIEWS = [
  { id: 'wall', label: 'The wall' },
  { id: 'victims', label: 'The names' },
  { id: 'dashboard', label: 'Dashboard' },
]

function App() {
  const [view, setView] = useState('wall')

  return (
    <div className="app">
      <header className="site-header">
        <div className="site-header-inner">
          <div className="wordmark">
            <span className="wordmark-heart" aria-hidden="true" />
            <div>
              <h1>The Memorial Wall</h1>
              <p className="wordmark-tagline">
                Remembering those we lost to COVID-19
              </p>
            </div>
          </div>

          <nav className="nav" aria-label="Primary">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`nav-link${view === item.id ? ' nav-link-active' : ''}`}
                aria-current={view === item.id ? 'page' : undefined}
                onClick={() => setView(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="site-main">
        {view === 'wall' && <WallPanorama />}
        {view === 'victims' && <Victims />}
        {view === 'dashboard' && <Dashboard />}
      </main>

      <footer className="footer">
        <span className="footer-heart" aria-hidden="true" />
        <p>Built in remembrance. Be gentle with one another.</p>
      </footer>
    </div>
  )
}

export default App

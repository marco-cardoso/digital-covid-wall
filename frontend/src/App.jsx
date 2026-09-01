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
      <header className="hero">
        <h1>The Memorial Wall</h1>
        <p className="hero-subtitle">
          The National Covid Memorial Wall in London, photo by photo —
          remembering those we lost to COVID-19.
        </p>
      </header>

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

      {view === 'wall' && <WallPanorama />}
      {view === 'victims' && <Victims />}
      {view === 'dashboard' && <Dashboard />}

      <footer className="footer">
        <p>Built in remembrance. Be gentle with one another.</p>
      </footer>
    </div>
  )
}

export default App

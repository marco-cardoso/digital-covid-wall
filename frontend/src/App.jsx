import { useState } from 'react'
import WallPanorama from './components/WallPanorama'
import Victims from './components/Victims'
import Dashboard from './components/Dashboard'
import Contact from './components/Contact'
import './App.css'

const VIEWS = [
  { id: 'wall', label: 'The wall' },
  { id: 'victims', label: 'Honors' },
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'contact', label: 'Contact' },
]

function App() {
  const [view, setView] = useState('wall')

  const goTo = (id) => {
    setView(id)
    window.scrollTo(0, 0)
  }

  return (
    <div className={`app${view === 'wall' ? ' app-wall' : ''}`}>
      <header className="site-header">
        <div className="site-header-inner">
          <div className="wordmark">
            <span className="wordmark-heart" aria-hidden="true" />
            <div>
              <div className="wordmark-title">
                <h1>The Memorial Wall</h1>
                <button
                  type="button"
                  className="beta-pill"
                  aria-label="In development: tell us what we’ve got wrong"
                  title="This site is under development. Tell us what we’ve got wrong."
                  onClick={() => goTo('contact')}
                >
                  In development
                </button>
              </div>
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
                onClick={() => goTo(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="site-main">
        {view === 'wall' && <WallPanorama />}
        {view === 'victims' && <Victims onContact={() => goTo('contact')} />}
        {view === 'dashboard' && <Dashboard />}
        {view === 'contact' && <Contact />}
      </main>

      {view !== 'wall' && (
        <footer className="footer">
          <span className="footer-heart" aria-hidden="true" />
          <p>Built in remembrance. Be gentle with one another.</p>
        </footer>
      )}
    </div>
  )
}

export default App

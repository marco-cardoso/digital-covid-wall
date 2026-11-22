// Says plainly that the site is still being built and the names are not all there yet.
function DevNotice({ onContact, children }) {
  return (
    <aside className="dev-notice" aria-label="This site is under development">
      <span className="dev-notice-badge">In development</span>
      <p>
        {children ?? (
          <>
            Not every name has been detected yet, and some of those that have may
            contain typos. We are working to make this as accurate as we can.
          </>
        )}
      </p>
      {onContact && (
        <button type="button" className="dev-notice-link" onClick={onContact}>
          Report a typo or a missing name →
        </button>
      )}
    </aside>
  )
}

export default DevNotice

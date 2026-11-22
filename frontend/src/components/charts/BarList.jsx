import { useId } from 'react'

/**
 * Ranked horizontal bars: a name, a thin bar and the value at its tip, one row per item, all on one baseline.
 * items: [{ label, value, note?, color?, tip? }]; `max` is the value a full bar stands for (default: the biggest).
 * Each row is focusable and shows a small readout on hover or focus; the same numbers sit in the row itself.
 */
function BarList({ items, max, color = 'var(--viz-accent)' }) {
  const id = useId()
  const top = max ?? Math.max(1, ...items.map((item) => item.value))

  return (
    <ol className="bar-list">
      {items.map((item, i) => {
        const tipId = `${id}-${i}`
        return (
          <li key={item.label} className="bar-row" tabIndex={0} aria-describedby={tipId}>
            <span className="bar-label">
              {item.label}
              {item.note && <small>{item.note}</small>}
            </span>
            <span className="bar-track">
              <span
                className="bar-fill"
                style={{ '--ratio': Math.min(1, item.value / top), background: item.color ?? color }}
              />
              <span className="bar-value">{item.value.toLocaleString()}</span>
            </span>
            <span role="tooltip" id={tipId} className="viz-tip bar-tip">
              <span className="viz-tip-title">{item.label}</span>
              <span className="viz-tip-value">{item.value.toLocaleString()}</span>
              {item.tip && <span className="viz-tip-row">{item.tip}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export default BarList

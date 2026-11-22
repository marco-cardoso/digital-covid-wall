import { useId, useState } from 'react'

/**
 * A titled card around one chart, with the chart's table view one button away: every value the chart
 * draws is also readable as plain rows, so nothing depends on hover or colour.
 * `table` is { columns: ['Photos', ...], rows: [['1–40', 9,402, ...]] } (first column is the row header).
 */
function ChartCard({ title, subtitle, table, wide = false, children }) {
  const [asTable, setAsTable] = useState(false)
  const headingId = useId()

  return (
    <figure className={`chart-card${wide ? ' chart-card-wide' : ''}`} aria-labelledby={headingId}>
      <div className="chart-head">
        <div>
          <h3 id={headingId}>{title}</h3>
          {subtitle && <p className="chart-subtitle">{subtitle}</p>}
        </div>
        {table && (
          <button
            type="button"
            className="chart-toggle"
            aria-pressed={asTable}
            onClick={() => setAsTable((on) => !on)}
          >
            {asTable ? 'View as chart' : 'View as table'}
          </button>
        )}
      </div>

      {asTable && table ? (
        <div className="chart-table-wrap" tabIndex={0} role="region" aria-label={`${title}, as a table`}>
          <table className="chart-table">
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, i) =>
                    i === 0 ? (
                      <th key={i} scope="row">
                        {cell}
                      </th>
                    ) : (
                      <td key={i}>{typeof cell === 'number' ? cell.toLocaleString() : cell}</td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </figure>
  )
}

export default ChartCard

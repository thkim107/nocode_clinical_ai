interface Props {
  columns: string[];
  rows: (string | number)[][];
  totalHint: string;
}

export default function CsvViewer({ columns, rows, totalHint }: Props) {
  return (
    <div className="csv-viewer">
      <div className="csv-info">
        Showing {rows.length} rows {totalHint === "500+" ? "(truncated)" : `of ${totalHint}`} | {columns.length} columns
      </div>
      <div className="csv-table-wrapper">
        <table className="csv-table">
          <thead>
            <tr>
              <th className="row-num">#</th>
              {columns.map((col, i) => (
                <th key={i}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                <td className="row-num">{ri + 1}</td>
                {row.map((cell, ci) => (
                  <td key={ci}>{String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

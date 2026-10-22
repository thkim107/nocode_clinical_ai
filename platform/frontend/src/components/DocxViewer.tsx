import type { DocxElement } from "../types";

interface Props {
  elements: DocxElement[];
}

export default function DocxViewer({ elements }: Props) {
  return (
    <div className="docx-viewer">
      {elements.map((el, i) => {
        if (el.kind === "heading") {
          const Tag = `h${Math.min(el.level || 1, 6)}` as keyof JSX.IntrinsicElements;
          return <Tag key={i}>{el.text}</Tag>;
        }
        if (el.kind === "table" && el.rows) {
          return (
            <table key={i} className="docx-table">
              <tbody>
                {el.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      ri === 0 ? <th key={ci}>{cell}</th> : <td key={ci}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        return <p key={i}>{el.text}</p>;
      })}
    </div>
  );
}

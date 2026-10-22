interface Props {
  code: string;
  language: string;
}

export default function CodeViewer({ code, language }: Props) {
  return (
    <div className="code-viewer">
      <div className="code-lang">{language}</div>
      <pre className="code-block">
        <code>{code}</code>
      </pre>
    </div>
  );
}

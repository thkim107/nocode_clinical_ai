interface Props {
  path: string;
  onNavigate: (path: string) => void;
}

export default function Breadcrumb({ path, onNavigate }: Props) {
  const parts = path ? path.split("/").filter(Boolean) : [];

  return (
    <nav className="breadcrumb">
      <span className="breadcrumb-item" onClick={() => onNavigate("")}>
        /
      </span>
      {parts.map((part, i) => {
        const subPath = parts.slice(0, i + 1).join("/");
        return (
          <span key={subPath}>
            <span className="breadcrumb-sep">/</span>
            <span className="breadcrumb-item" onClick={() => onNavigate(subPath)}>
              {part}
            </span>
          </span>
        );
      })}
    </nav>
  );
}

import type { FileItem } from "../types";
import { getDownloadUrl, deleteItem } from "../api/client";

interface Props {
  items: FileItem[];
  currentPath: string;
  onItemClick: (item: FileItem) => void;
  onNavigate: (path: string) => void;
  selectedFile: string | null;
  onRefresh: () => void;
}

const ICON_MAP: Record<string, string> = {
  directory: "\ud83d\udcc1",
  ".csv": "\ud83d\udcca",
  ".json": "{ }",
  ".html": "\ud83c\udf10",
  ".png": "\ud83d\uddbc",
  ".jpg": "\ud83d\uddbc",
  ".jpeg": "\ud83d\uddbc",
  ".docx": "\ud83d\udcc4",
  ".txt": "\ud83d\udcdd",
  ".py": "\ud83d\udc0d",
  ".sql": "\ud83d\uddc3",
  ".md": "\ud83d\udcdd",
};

function getIcon(item: FileItem): string {
  if (item.type === "directory") return ICON_MAP.directory;
  return ICON_MAP[item.extension || ""] || "\ud83d\udcc4";
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function FileList({ items, currentPath, onItemClick, onNavigate, selectedFile, onRefresh }: Props) {
  const parentPath = currentPath ? currentPath.split("/").slice(0, -1).join("/") : null;

  const handleDelete = async (e: React.MouseEvent, item: FileItem) => {
    e.stopPropagation();
    const itemPath = currentPath ? `${currentPath}/${item.name}` : item.name;
    if (!confirm(`Delete "${item.name}"?`)) return;
    try {
      await deleteItem(itemPath);
      onRefresh();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  return (
    <table className="file-table">
      <thead>
        <tr>
          <th></th>
          <th>Name</th>
          <th>Size</th>
          <th>Modified</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {parentPath !== null && (
          <tr className="file-row" onClick={() => onNavigate(parentPath)}>
            <td>\ud83d\udcc1</td>
            <td>..</td>
            <td></td>
            <td></td>
            <td></td>
          </tr>
        )}
        {items.map((item) => {
          const itemPath = currentPath ? `${currentPath}/${item.name}` : item.name;
          const isSelected = selectedFile === itemPath;
          return (
            <tr
              key={item.name}
              className={`file-row ${isSelected ? "selected" : ""}`}
              onClick={() => onItemClick(item)}
            >
              <td className="icon-cell">{getIcon(item)}</td>
              <td className="name-cell">
                {item.name}
                {item.type === "directory" && "/"}
              </td>
              <td className="size-cell">{formatSize(item.size)}</td>
              <td className="date-cell">{formatDate(item.modified)}</td>
              <td className="action-cell">
                {item.type === "file" && (
                  <>
                    <a
                      href={getDownloadUrl(itemPath)}
                      onClick={(e) => e.stopPropagation()}
                      className="btn-small"
                      title="Download"
                    >
                      &#x2B07;
                    </a>
                    <button onClick={(e) => handleDelete(e, item)} className="btn-small btn-danger" title="Delete">
                      &#x2715;
                    </button>
                  </>
                )}
                {item.type === "directory" && (
                  <button onClick={(e) => handleDelete(e, item)} className="btn-small btn-danger" title="Delete">
                    &#x2715;
                  </button>
                )}
              </td>
            </tr>
          );
        })}
        {items.length === 0 && (
          <tr>
            <td colSpan={5} className="empty-row">Empty directory</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

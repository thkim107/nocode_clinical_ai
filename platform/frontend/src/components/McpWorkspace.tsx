import { useState, useCallback, useEffect, useRef } from "react";
import type { FileItem, PreviewData } from "../types";
import { fetchLs, fetchPreview } from "../api/client";
import Chatbot from "./Chatbot";
import Breadcrumb from "./Breadcrumb";
import FileList from "./FileList";
import PreviewPanel from "./PreviewPanel";
import UploadModal from "./UploadModal";

const POLL_INTERVAL = 3000;

export default function McpWorkspace() {
  const [currentPath, setCurrentPath] = useState("");
  const [items, setItems] = useState<FileItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewData | { blobUrl: string; mediaType: string; modified: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showUpload, setShowUpload] = useState(false);

  const lastModifiedRef = useRef<number | string | null>(null);

  const loadDir = useCallback(async (path: string) => {
    try {
      const data = await fetchLs(path);
      setItems(data.items);
      setCurrentPath(path);
    } catch {}
  }, []);

  const loadPreview = useCallback(async (filePath: string) => {
    setPreviewLoading(true);
    try {
      const data = await fetchPreview(filePath);
      setPreview(data);
      if ("modified" in data) lastModifiedRef.current = data.modified;
    } catch {
      setPreview({ type: "error", message: "Failed to load preview", name: "", modified: 0, size: 0 });
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  // Poll file changes
  useEffect(() => {
    if (!selectedFile) return;
    const timer = setInterval(async () => {
      try {
        const data = await fetchPreview(selectedFile);
        if ("modified" in data && data.modified !== lastModifiedRef.current) {
          setPreview(data);
          lastModifiedRef.current = data.modified;
        }
      } catch {}
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [selectedFile]);

  // Poll directory
  useEffect(() => {
    const timer = setInterval(() => loadDir(currentPath), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [currentPath, loadDir]);

  useEffect(() => { loadDir(""); }, [loadDir]);

  const handleNavigate = (path: string) => {
    setSelectedFile(null);
    setPreview(null);
    loadDir(path);
  };

  const handleFileClick = (item: FileItem) => {
    if (item.type === "directory") {
      handleNavigate(currentPath ? `${currentPath}/${item.name}` : item.name);
    } else {
      const filePath = currentPath ? `${currentPath}/${item.name}` : item.name;
      setSelectedFile(filePath);
      lastModifiedRef.current = null;
      loadPreview(filePath);
    }
  };

  return (
    <div className="workspace-layout">
      {/* Left: Chatbot */}
      <div className="workspace-chat">
        <Chatbot />
      </div>

      {/* Right: File Manager */}
      <div className="workspace-files">
        <div className="workspace-files-header">
          <Breadcrumb path={currentPath} onNavigate={handleNavigate} />
          <div className="workspace-files-actions">
            <button onClick={() => loadDir(currentPath)} className="btn btn-icon" title="Refresh">&#x21bb;</button>
            <button onClick={() => setShowUpload(true)} className="btn btn-sm">Upload</button>
          </div>
        </div>

        <div className="workspace-files-body">
          <div className="workspace-file-list">
            <FileList
              items={items}
              currentPath={currentPath}
              onItemClick={handleFileClick}
              onNavigate={handleNavigate}
              selectedFile={selectedFile}
              onRefresh={() => loadDir(currentPath)}
            />
          </div>
          <div className="workspace-preview">
            {previewLoading ? (
              <div className="preview-loading">Loading...</div>
            ) : preview ? (
              <PreviewPanel data={preview} filePath={selectedFile || ""} />
            ) : (
              <div className="preview-empty">Select a file to preview</div>
            )}
          </div>
        </div>

        {showUpload && (
          <UploadModal
            currentPath={currentPath}
            onClose={() => setShowUpload(false)}
            onUploaded={() => { setShowUpload(false); loadDir(currentPath); }}
          />
        )}
      </div>
    </div>
  );
}

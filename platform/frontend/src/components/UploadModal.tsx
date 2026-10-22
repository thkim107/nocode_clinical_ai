import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { uploadFiles, createDir } from "../api/client";

interface Props {
  currentPath: string;
  onClose: () => void;
  onUploaded: () => void;
}

export default function UploadModal({ currentPath, onClose, onUploaded }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [newDirName, setNewDirName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback((accepted: File[]) => {
    setFiles((prev) => [...prev, ...accepted]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      await uploadFiles(currentPath, files);
      onUploaded();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const handleCreateDir = async () => {
    if (!newDirName.trim()) return;
    setError(null);
    try {
      const dirPath = currentPath ? `${currentPath}/${newDirName.trim()}` : newDirName.trim();
      await createDir(dirPath);
      onUploaded();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Upload / New Folder</h2>
          <button onClick={onClose} className="btn-close">&times;</button>
        </div>

        {error && <div className="error-banner">{error}</div>}

        <div className="modal-section">
          <h3>Upload Files</h3>
          <div {...getRootProps()} className={`dropzone ${isDragActive ? "active" : ""}`}>
            <input {...getInputProps()} />
            {isDragActive ? (
              <p>Drop files here...</p>
            ) : (
              <p>Drag & drop files here, or click to select</p>
            )}
          </div>
          {files.length > 0 && (
            <div className="file-queue">
              {files.map((f, i) => (
                <div key={i} className="file-queue-item">
                  <span>{f.name}</span>
                  <span className="file-queue-size">{(f.size / 1024).toFixed(1)} KB</span>
                  <button onClick={() => setFiles(files.filter((_, j) => j !== i))} className="btn-small btn-danger">
                    &times;
                  </button>
                </div>
              ))}
              <button onClick={handleUpload} disabled={uploading} className="btn btn-primary">
                {uploading ? "Uploading..." : `Upload ${files.length} file(s)`}
              </button>
            </div>
          )}
        </div>

        <div className="modal-section">
          <h3>New Folder</h3>
          <div className="new-dir-form">
            <input
              type="text"
              value={newDirName}
              onChange={(e) => setNewDirName(e.target.value)}
              placeholder="Folder name"
              onKeyDown={(e) => e.key === "Enter" && handleCreateDir()}
            />
            <button onClick={handleCreateDir} className="btn btn-primary">Create</button>
          </div>
        </div>
      </div>
    </div>
  );
}

import type { PreviewData } from "../types";
import CsvViewer from "./CsvViewer";
import CodeViewer from "./CodeViewer";
import DocxViewer from "./DocxViewer";
import ImageViewer from "./ImageViewer";
import { getDownloadUrl } from "../api/client";

interface Props {
  data: PreviewData | { blobUrl: string; mediaType: string; modified: string };
  filePath: string;
}

export default function PreviewPanel({ data, filePath }: Props) {
  // Binary image response
  if ("blobUrl" in data) {
    return <ImageViewer src={data.blobUrl} />;
  }

  switch (data.type) {
    case "csv":
      return <CsvViewer columns={data.columns} rows={data.rows} totalHint={data.total_hint} />;

    case "json":
      return (
        <div className="preview-content">
          <CodeViewer code={typeof data.content === "string" ? data.content : JSON.stringify(data.content, null, 2)} language="json" />
        </div>
      );

    case "html":
      return (
        <iframe
          className="html-preview"
          srcDoc={data.content}
          sandbox="allow-scripts"
          title="HTML Preview"
        />
      );

    case "text":
      return (
        <div className="preview-content">
          <CodeViewer code={data.content} language={data.extension?.replace(".", "") || "text"} />
        </div>
      );

    case "docx":
      return <DocxViewer elements={data.elements || []} />;

    case "unsupported":
      return (
        <div className="preview-unsupported">
          <p>Preview not available for this file type.</p>
          <a href={getDownloadUrl(filePath)} className="btn btn-primary">
            Download
          </a>
        </div>
      );

    case "error":
      return <div className="preview-error">Error: {data.message}</div>;

    default:
      return null;
  }
}

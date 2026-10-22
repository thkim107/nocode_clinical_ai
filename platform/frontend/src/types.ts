// File Manager types
export interface FileItem {
  name: string;
  type: "file" | "directory";
  size: number | null;
  modified: number;
  extension: string | null;
}

export interface LsResponse {
  path: string;
  items: FileItem[];
}

export interface PreviewBase {
  name: string;
  modified: number;
  size: number;
}

export interface CsvPreview extends PreviewBase {
  type: "csv";
  columns: string[];
  rows: (string | number)[][];
  total_hint: string;
}

export interface JsonPreview extends PreviewBase {
  type: "json";
  content: unknown;
}

export interface HtmlPreview extends PreviewBase {
  type: "html";
  content: string;
}

export interface TextPreview extends PreviewBase {
  type: "text";
  content: string;
  extension: string;
}

export interface DocxElement {
  kind: "paragraph" | "heading" | "table";
  text?: string;
  level?: number;
  rows?: string[][];
}

export interface DocxPreview extends PreviewBase {
  type: "docx";
  elements: DocxElement[];
  /** @deprecated kept for backward compat */
  paragraphs?: string[];
  tables?: string[][][];
}

export interface UnsupportedPreview extends PreviewBase {
  type: "unsupported";
}

export interface ErrorPreview extends PreviewBase {
  type: "error";
  message: string;
}

export type PreviewData =
  | CsvPreview
  | JsonPreview
  | HtmlPreview
  | TextPreview
  | DocxPreview
  | UnsupportedPreview
  | ErrorPreview;

// Research Planner types
export interface PlannerQuestion {
  question_id: string;
  target_section: string;
  pimo_category: string;
  question: string;
}

export interface PlannerSections {
  [key: string]: string;
}

// PubMed types
export interface PubMedPaper {
  Title: string;
  PMID: string;
  Authors: string;
  Journal: string;
  Year: number;
  Abstract: string;
  score: number;
  score_p: number;
  score_i: number;
  score_m: number;
  score_o: number;
  rationale: string;
  matched_queries: string[];
}

// Chat types
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolName?: string;
  toolInput?: unknown;
  toolResult?: string;
  toolLoading?: boolean;
  isStreaming?: boolean;
}

// Server-side session snapshot (GET /api/research/session/{user_code})
export interface PlannerQaPair extends PlannerQuestion {
  answer: string;
}

export interface SessionSnapshot {
  user_code: string;
  exists: boolean;
  prompt_lang: string;
  planner: {
    topic_raw: string;
    topic_refined: string;
    topic_en: string;
    questions: PlannerQuestion[];
    qa_pairs: PlannerQaPair[];
    sections: PlannerSections;
    status: string;
    updated_at: string;
  };
  pubmed: {
    papers: PubMedPaper[];
    top_references: PubMedPaper[];
  };
  document: {
    background: string;
    data_analysis: string;
    hypothesis: string;
  };
}

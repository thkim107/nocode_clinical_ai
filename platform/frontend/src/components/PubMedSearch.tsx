import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppState } from "../context/AppContext";
import { searchPubMed } from "../api/research";
import type { PubMedPaper } from "../types";

function downloadBlob(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

export default function PubMedSearch() {
  const { userCode, plannerSections, researchBackground, dataAnalysisMethod, pubmedPapers: papers, setPubmedPapers: setPapers, setTopReferences } = useAppState();

  const [summary, setSummary] = useState("");
  const [keywords, setKeywords] = useState("");
  const [status, setStatus] = useState("");
  const [searching, setSearching] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState<PubMedPaper | null>(null);
  const [sortKey, setSortKey] = useState<"score" | "Year">("score");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const hasSections = Object.keys(plannerSections).length > 0;

  const handleSearch = async () => {
    if (!hasSections) return alert("Generate Research Planner sections first.");
    setSearching(true);
    setPapers([]);
    setSummary("");
    setKeywords("");
    setStatus("Starting search...");

    try {
      const localPapers: PubMedPaper[] = [];
      let localSummary = "";

      for await (const line of searchPubMed(userCode, plannerSections, researchBackground, dataAnalysisMethod)) {
        if (line.startsWith("STATUS:")) {
          const msg = line.replace("STATUS:", "").trim();
          setStatus(msg);
          if (msg.includes("PIMO keywords =>")) {
            setKeywords(msg.split("=>")[1]?.trim() || "");
          }
        } else {
          try {
            const paper = JSON.parse(line) as PubMedPaper;
            if (paper.PMID) {
              localPapers.push(paper);
              setPapers([...localPapers]);
            }
          } catch {
            localSummary += line + "\n";
            setSummary(localSummary);
          }
        }
      }

      setPapers(localPapers);
      const sorted = [...localPapers].sort((a, b) => b.score - a.score).slice(0, 10);
      setTopReferences(sorted);
    } catch (e: any) {
      setStatus(`Error: ${e.message}`);
    } finally {
      setSearching(false);
      setStatus("");
    }
  };

  const top10 = [...papers].sort((a, b) => b.score - a.score).slice(0, 10);

  const handleDownloadCsv = () => {
    const escape = (s: string) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const header = ["Rank", "Score", "P", "I", "M", "O", "PMID", "Title", "Authors", "Journal", "Year", "Abstract", "Rationale"];
    const rows = top10.map((p, i) => [
      i + 1, p.score, p.score_p, p.score_i, p.score_m, p.score_o,
      p.PMID, escape(p.Title), escape(p.Authors), escape(p.Journal), p.Year,
      escape(p.Abstract), escape(p.rationale),
    ].join(","));
    downloadBlob([header.join(","), ...rows].join("\n"), `pubmed_top10_${userCode}.csv`, "text/csv;charset=utf-8");
  };

  const handleDownloadTxt = () => {
    const lines = [
      "=".repeat(60),
      "PubMed Search Results - Top 10",
      "=".repeat(60),
      "",
    ];
    if (keywords) lines.push(`Keywords: ${keywords}`, "");
    top10.forEach((p, i) => {
      lines.push(
        "-".repeat(60),
        `#${i + 1}  Score: ${p.score} (P:${p.score_p} I:${p.score_i} M:${p.score_m} O:${p.score_o})`,
        `Title: ${p.Title}`,
        `Authors: ${p.Authors}`,
        `Journal: ${p.Journal} (${p.Year})`,
        `PMID: ${p.PMID}`,
        `URL: https://pubmed.ncbi.nlm.nih.gov/${p.PMID}/`,
        "",
        "[Abstract]",
        p.Abstract || "N/A",
        "",
      );
      if (p.rationale) lines.push("[Rationale]", p.rationale, "");
    });
    lines.push("=".repeat(60));
    downloadBlob(lines.join("\n"), `pubmed_top10_${userCode}.txt`, "text/plain;charset=utf-8");
  };

  const sorted = [...papers].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
  });

  const toggleSort = (key: "score" | "Year") => {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(-1);
    }
  };

  return (
    <div className="panel">
      <h2>PubMed Literature Search</h2>

      <div className="info-card">
        <strong>Planner Context:</strong>{" "}
        {hasSections ? `${Object.keys(plannerSections).length} sections loaded` : "No sections - run Research Planner first"}
        {keywords && <div className="text-muted">Keywords: {keywords}</div>}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={handleSearch} disabled={searching || !hasSections} className="btn btn-primary">
          {searching ? "Searching..." : "Search PubMed"}
        </button>
        {papers.length > 0 && (
          <>
            <button onClick={handleDownloadCsv} className="btn btn-secondary">Download Top 10 (CSV)</button>
            <button onClick={handleDownloadTxt} className="btn btn-secondary">Download Top 10 (TXT)</button>
          </>
        )}
      </div>

      {status && <div className="loading-bar">{status}</div>}

      <div className="pubmed-layout">
        {/* Summary */}
        <div className="pubmed-summary">
          <h3>Research Summary</h3>
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary || "Run search to generate summary."}</ReactMarkdown>
          </div>
        </div>

        {/* Results Table */}
        <div className="pubmed-results">
          <h3>Search Results ({papers.length})</h3>
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th onClick={() => toggleSort("score")} className="sortable">
                    Score {sortKey === "score" ? (sortDir === -1 ? "v" : "^") : ""}
                  </th>
                  <th>P</th><th>I</th><th>M</th><th>O</th>
                  <th>Title</th>
                  <th onClick={() => toggleSort("Year")} className="sortable">
                    Year {sortKey === "Year" ? (sortDir === -1 ? "v" : "^") : ""}
                  </th>
                  <th>PMID</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((p) => (
                  <tr key={p.PMID} onClick={() => setSelectedPaper(p)} className="clickable-row">
                    <td className="center">{p.score}</td>
                    <td className="center">{p.score_p}</td>
                    <td className="center">{p.score_i}</td>
                    <td className="center">{p.score_m}</td>
                    <td className="center">{p.score_o}</td>
                    <td className="truncate">{p.Title}</td>
                    <td className="center">{p.Year}</td>
                    <td className="center">
                      <a
                        href={`https://pubmed.ncbi.nlm.nih.gov/${p.PMID}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        title="Open in PubMed"
                      >
                        {p.PMID}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Paper Detail Modal */}
      {selectedPaper && (
        <div className="modal-overlay" onClick={() => setSelectedPaper(null)}>
          <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedPaper.Title}</h3>
              <button onClick={() => setSelectedPaper(null)} className="btn-close">&times;</button>
            </div>
            <div className="modal-body">
              <div className="paper-meta">
                <span>
                  PMID:{" "}
                  <a href={`https://pubmed.ncbi.nlm.nih.gov/${selectedPaper.PMID}/`} target="_blank" rel="noopener noreferrer">
                    {selectedPaper.PMID}
                  </a>
                </span>
                <span>{selectedPaper.Journal} ({selectedPaper.Year})</span>
              </div>
              <div className="text-muted">{selectedPaper.Authors}</div>

              <div className="score-badges">
                <span className="badge badge-score">Score: {selectedPaper.score}</span>
                <span className="badge">P: {selectedPaper.score_p}</span>
                <span className="badge">I: {selectedPaper.score_i}</span>
                <span className="badge">M: {selectedPaper.score_m}</span>
                <span className="badge">O: {selectedPaper.score_o}</span>
              </div>

              {selectedPaper.Abstract && (
                <div className="paper-section">
                  <h4>Abstract</h4>
                  <p>{selectedPaper.Abstract}</p>
                </div>
              )}
              {selectedPaper.rationale && (
                <div className="paper-section paper-section-highlight">
                  <h4>Rationale</h4>
                  <p>{selectedPaper.rationale}</p>
                </div>
              )}

              <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                <a
                  href={`https://pubmed.ncbi.nlm.nih.gov/${selectedPaper.PMID}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-primary"
                >
                  View on PubMed
                </a>
                <a
                  href={`https://scholar.google.com/scholar?q=pmid:${selectedPaper.PMID}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn"
                >
                  Google Scholar
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

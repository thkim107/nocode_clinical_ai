import { useState } from "react";
import { useAppState } from "../context/AppContext";
import {
  getBackgroundQuestions, buildBackground,
  checkDataAnalysis, getDataAnalysis,
  getHypothesis, reviseDoc,
} from "../api/research";

export default function IrbDocumentation() {
  const state = useAppState();
  const { userCode, plannerSections, topReferences, researchBackground, setResearchBackground, dataAnalysisMethod, setDataAnalysisMethod, researchHypothesis, setResearchHypothesis } = state;

  const [loading, setLoading] = useState("");

  // Step 1: Background
  const [bgQuestions, setBgQuestions] = useState<Record<string, string>>({});
  const [bgAnswers, setBgAnswers] = useState<Record<string, string>>({});
  const [bgRevision, setBgRevision] = useState("");

  // Step 2: Data Analysis
  const [daQuestions, setDaQuestions] = useState<Record<string, string>>({});
  const [daRationale, setDaRationale] = useState("");
  const [daAnswers, setDaAnswers] = useState<Record<string, string>>({});
  const [daRevision, setDaRevision] = useState("");

  // Step 3: Hypothesis
  const [hypRevision, setHypRevision] = useState("");

  const hasSections = Object.keys(plannerSections).length > 0;
  const refs = topReferences.slice(0, 10);

  const basePayload = () => ({
    irb_research_title: plannerSections.research_purpose || "",
    irb_research_purpose: plannerSections.research_purpose || "",
    irb_research_design: plannerSections.research_design || "",
    irb_research_method: plannerSections.research_method || "",
    irb_validity_evaluation: plannerSections.validity_evaluation || "",
    planner_sections: plannerSections,
    reference_papers: refs,
  });

  // Step 1 handlers
  const handleBgQuestions = async () => {
    setLoading("Generating background questions...");
    try {
      const res = await getBackgroundQuestions(userCode, basePayload());
      const qs: Record<string, string> = {};
      Object.entries(res).forEach(([k, v]) => {
        if (k.startsWith("subquery")) qs[k] = v as string;
      });
      setBgQuestions(qs);
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  const handleBuildBackground = async () => {
    setLoading("Generating research background...");
    try {
      const payload = { ...basePayload(), background_sub_queries: bgAnswers };
      const res = await buildBackground(userCode, payload);
      setResearchBackground(res.research_background || Object.values(res)[0] || "");
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  // Step 2 handlers
  const handleDaQuestions = async () => {
    setLoading("Checking data analysis needs...");
    try {
      const res = await checkDataAnalysis(userCode, basePayload());
      const qs: Record<string, string> = {};
      if (res.Subqueries) {
        Object.entries(res.Subqueries).forEach(([k, v]) => { qs[k] = v as string; });
      }
      setDaQuestions(qs);
      setDaRationale(res.Rationale || "");
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  const handleBuildDa = async () => {
    setLoading("Generating data analysis method...");
    try {
      const payload = { ...basePayload(), data_analysis_sub_queries: daAnswers };
      const res = await getDataAnalysis(userCode, payload);
      setDataAnalysisMethod(res.analysis_utilization_method || Object.values(res)[0] || "");
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  // Step 3 handler
  const handleHypothesis = async () => {
    setLoading("Generating hypothesis...");
    try {
      const payload = { ...basePayload(), research_background: researchBackground };
      const res = await getHypothesis(userCode, payload);
      setResearchHypothesis(res.research_hypothesis || Object.values(res)[0] || "");
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  // Revise handlers
  const handleRevise = async (docType: string, current: string, request: string, setter: (v: string) => void, clearRevision: () => void) => {
    setLoading(`Revising ${docType}...`);
    try {
      const res = await reviseDoc(userCode, docType, current, request);
      setter(res.revised_content || Object.values(res)[0] || "");
      clearRevision();
    } catch (e: any) { alert(e.message); }
    finally { setLoading(""); }
  };

  const handleDownload = () => {
    const lines = [
      "=".repeat(60),
      "Research Plan",
      "=".repeat(60),
      "",
      `Research Title: ${plannerSections.research_purpose || ""}`,
      "",
      "-".repeat(40), "[Research Background]", "-".repeat(40),
      researchBackground || "Not generated", "",
      "-".repeat(40), "[Data Analysis Method]", "-".repeat(40),
      dataAnalysisMethod || "Not generated", "",
      "-".repeat(40), "[Research Hypothesis]", "-".repeat(40),
      researchHypothesis || "Not generated", "",
      "-".repeat(40), "[Top References Used]", "-".repeat(40),
    ];
    if (refs.length > 0) {
      refs.forEach((p, i) => {
        lines.push(`${i + 1}. ${p.Title || "N/A"} | PMID: ${p.PMID || "N/A"} | Score: ${p.score ?? "N/A"}`);
      });
    } else {
      lines.push("No references available");
    }
    lines.push("", "=".repeat(60));
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `research_plan_${userCode}.txt`;
    a.click();
  };

  return (
    <div className="panel">
      <h2>Research Document Generation</h2>

      <div className="info-card">
        <strong>Sources:</strong> Planner: {hasSections ? `${Object.keys(plannerSections).length} sections` : "None"} |
        PubMed References: {refs.length}
        {!hasSections && <div className="text-muted">Run Research Planner and PubMed Search first.</div>}
      </div>

      {/* Step 1: Research Background */}
      <details open className="step-section">
        <summary><h3>Step 1: Research Background</h3></summary>
        {Object.keys(bgQuestions).length === 0 ? (
          <button onClick={handleBgQuestions} disabled={!hasSections || !!loading} className="btn btn-primary">
            Generate Questions
          </button>
        ) : (
          <>
            {Object.entries(bgQuestions).map(([k, q]) => (
              <div key={k} className="question-card">
                <label className="question-text">{q}</label>
                <textarea
                  rows={2}
                  value={bgAnswers[k] || ""}
                  onChange={(e) => setBgAnswers({ ...bgAnswers, [k]: e.target.value })}
                  className="full-width"
                />
              </div>
            ))}
            <button onClick={handleBuildBackground} disabled={!!loading} className="btn btn-primary">
              Generate Background
            </button>
          </>
        )}
        {researchBackground && (
          <div className="result-box">
            <div className="markdown-body">{researchBackground}</div>
            <div className="revision-row">
              <input value={bgRevision} onChange={(e) => setBgRevision(e.target.value)} placeholder="Revision request..." />
              <button onClick={() => handleRevise("research_background", researchBackground, bgRevision, setResearchBackground, () => setBgRevision(""))} className="btn btn-sm">Revise</button>
            </div>
          </div>
        )}
      </details>

      {/* Step 2: Data Analysis Method */}
      <details className="step-section">
        <summary><h3>Step 2: Data Analysis Method</h3></summary>
        {Object.keys(daQuestions).length === 0 ? (
          <button onClick={handleDaQuestions} disabled={!researchBackground || !!loading} className="btn btn-primary">
            Generate Questions
          </button>
        ) : (
          <>
            {daRationale && <div className="info-card">{daRationale}</div>}
            {Object.entries(daQuestions).map(([k, q]) => (
              <div key={k} className="question-card">
                <label className="question-text">{q}</label>
                <textarea
                  rows={2}
                  value={daAnswers[k] || ""}
                  onChange={(e) => setDaAnswers({ ...daAnswers, [k]: e.target.value })}
                  className="full-width"
                />
              </div>
            ))}
            <button onClick={handleBuildDa} disabled={!!loading} className="btn btn-primary">
              Generate Data Analysis Method
            </button>
          </>
        )}
        {dataAnalysisMethod && (
          <div className="result-box">
            <div className="markdown-body">{dataAnalysisMethod}</div>
            <div className="revision-row">
              <input value={daRevision} onChange={(e) => setDaRevision(e.target.value)} placeholder="Revision request..." />
              <button onClick={() => handleRevise("data_analysis_method", dataAnalysisMethod, daRevision, setDataAnalysisMethod, () => setDaRevision(""))} className="btn btn-sm">Revise</button>
            </div>
          </div>
        )}
      </details>

      {/* Step 3: Research Hypothesis */}
      <details className="step-section">
        <summary><h3>Step 3: Research Hypothesis</h3></summary>
        <button onClick={handleHypothesis} disabled={!researchBackground || !!loading} className="btn btn-primary">
          Generate Hypothesis
        </button>
        {researchHypothesis && (
          <div className="result-box">
            <div className="markdown-body">{researchHypothesis}</div>
            <div className="revision-row">
              <input value={hypRevision} onChange={(e) => setHypRevision(e.target.value)} placeholder="Revision request..." />
              <button onClick={() => handleRevise("research_hypothesis", researchHypothesis, hypRevision, setResearchHypothesis, () => setHypRevision(""))} className="btn btn-sm">Revise</button>
            </div>
          </div>
        )}
      </details>

      {researchBackground && dataAnalysisMethod && researchHypothesis && (
        <button onClick={handleDownload} className="btn btn-secondary" style={{ marginTop: 16 }}>
          Download Research Plan
        </button>
      )}

      {loading && <div className="loading-bar">{loading}</div>}
    </div>
  );
}

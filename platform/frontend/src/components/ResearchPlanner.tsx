import { useState } from "react";
import { useAppState } from "../context/AppContext";
import { refineTopic, generateQuestions, generateSectionsChain, reviseSection } from "../api/research";

const SECTION_LABELS: Record<string, string> = {
  research_purpose: "Research Purpose",
  research_design: "Research Design",
  research_method: "Research Method",
  validity_evaluation: "Validity Evaluation",
  expected_effects: "Expected Effects",
  anticipated_results: "Anticipated Results",
};

export default function ResearchPlanner() {
  const {
    userCode,
    plannerTopicRaw: topicRaw, setPlannerTopicRaw: setTopicRaw,
    plannerTopic: refinedTopic, setPlannerTopic: setRefinedTopic,
    plannerTopicEn: topicEn, setPlannerTopicEn: setTopicEn,
    plannerQuestions: questions, setPlannerQuestions: setQuestions,
    plannerAnswers: answers, setPlannerAnswers: setAnswers,
    plannerSections, setPlannerSections,
  } = useAppState();
  const plannerTopic = refinedTopic;
  const [loading, setLoading] = useState("");
  const [revisionInputs, setRevisionInputs] = useState<Record<string, string>>({});
  const [revisingKey, setRevisingKey] = useState<string | null>(null);

  const handleRefine = async () => {
    setLoading("Refining topic...");
    try {
      const res = await refineTopic(userCode, topicRaw);
      setRefinedTopic(res.topic_refined || res.topic || topicRaw);
      setTopicEn(res.topic_en || "");
    } catch (e: any) {
      alert(e.message);
    } finally {
      setLoading("");
    }
  };

  const handleGenerateQuestions = async () => {
    setLoading("Generating questions...");
    try {
      const res = await generateQuestions(userCode, plannerTopic || refinedTopic);
      setQuestions(res.questions || []);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setLoading("");
    }
  };

  const handleGenerateSections = async () => {
    setLoading("Generating sections...");
    try {
      const qaPairs = questions.map((q) => ({
        ...q,
        answer: answers[q.question_id] || "",
      }));
      const res = await generateSectionsChain(userCode, plannerTopic, qaPairs);
      setPlannerSections(res.sections || res);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setLoading("");
    }
  };

  const handleDownload = () => {
    const lines = [
      "=".repeat(60),
      "Research Planner Result",
      "=".repeat(60),
      "",
      `Topic (Raw): ${topicRaw}`,
      `Topic (Refined): ${refinedTopic || plannerTopic}`,
      "",
    ];
    const sectionOrder = ["research_purpose", "research_design", "research_method", "validity_evaluation", "expected_effects", "anticipated_results"];
    for (const key of sectionOrder) {
      const text = plannerSections[key];
      if (!text) continue;
      lines.push("-".repeat(40), `[${SECTION_LABELS[key] || key}]`, "-".repeat(40), text, "");
    }
    lines.push("=".repeat(60));
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `research_planner_${userCode}.txt`;
    a.click();
  };

  const handleRevise = async (key: string) => {
    const req = revisionInputs[key];
    if (!req) return;
    setRevisingKey(key);
    try {
      const res = await reviseSection(userCode, key, req);
      const content = res.section_content || res[key] || "";
      setPlannerSections({ ...plannerSections, [key]: content });
      setRevisionInputs({ ...revisionInputs, [key]: "" });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setRevisingKey(null);
    }
  };

  return (
    <div className="panel">
      <h2>Interactive Research Planner</h2>

      {/* Step 1: Topic */}
      <section className="step-section">
        <h3>Step 1: Research Topic</h3>
        <textarea
          rows={4}
          value={topicRaw}
          onChange={(e) => setTopicRaw(e.target.value)}
          placeholder="Describe your research topic in detail..."
          className="full-width"
        />
        <button onClick={handleRefine} disabled={!topicRaw || !!loading} className="btn btn-primary">
          Refine Topic
        </button>
        {refinedTopic && (
          <div className="result-box">
            <strong>Refined:</strong> {refinedTopic}
            {topicEn && <div className="text-muted">EN: {topicEn}</div>}
          </div>
        )}
      </section>

      {/* Step 2: Questions */}
      {refinedTopic && (
        <section className="step-section">
          <h3>Step 2: Answer Questions</h3>
          {questions.length === 0 ? (
            <button onClick={handleGenerateQuestions} disabled={!!loading} className="btn btn-primary">
              Generate Questions
            </button>
          ) : (
            <>
              {questions.map((q) => (
                <div key={q.question_id} className="question-card">
                  <label>
                    <span className="badge">{SECTION_LABELS[q.target_section] || q.target_section}</span>
                    <span className="badge badge-outline">PIMO: {q.pimo_category}</span>
                    <div className="question-text">{q.question}</div>
                  </label>
                  <textarea
                    rows={3}
                    value={answers[q.question_id] || ""}
                    onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
                    className="full-width"
                  />
                </div>
              ))}
              <button onClick={handleGenerateSections} disabled={!!loading} className="btn btn-primary">
                Generate Sections
              </button>
            </>
          )}
        </section>
      )}

      {/* Step 3: Results */}
      {Object.keys(plannerSections).length > 0 && (
        <section className="step-section">
          <h3>Step 3: Planner Results</h3>
          {Object.entries(plannerSections).map(([key, content]) => (
            <details key={key} open className="section-card">
              <summary>{SECTION_LABELS[key] || key}</summary>
              <div className="section-content markdown-body">{content}</div>
              <div className="revision-row">
                <input
                  type="text"
                  placeholder="Revision request..."
                  value={revisionInputs[key] || ""}
                  onChange={(e) => setRevisionInputs({ ...revisionInputs, [key]: e.target.value })}
                  onKeyDown={(e) => e.key === "Enter" && handleRevise(key)}
                />
                <button
                  onClick={() => handleRevise(key)}
                  disabled={revisingKey === key}
                  className="btn btn-sm"
                >
                  {revisingKey === key ? "..." : "Revise"}
                </button>
              </div>
            </details>
          ))}
        </section>
      )}

      {Object.keys(plannerSections).length > 0 && (
        <button onClick={handleDownload} className="btn btn-secondary" style={{ marginTop: 16 }}>
          Download Planner Result
        </button>
      )}

      {loading && <div className="loading-bar">{loading}</div>}
    </div>
  );
}

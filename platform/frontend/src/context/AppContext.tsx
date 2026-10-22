import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { PlannerQuestion, PlannerSections, PubMedPaper } from "../types";
import { fetchSession } from "../api/research";

/**
 * Cross-tab application state.
 *
 * The server session store is the source of truth: every generating endpoint
 * persists its result under the user code, and this provider restores all
 * tabs from GET /api/research/session/{user_code} whenever the user code
 * changes (and on first load). Local state here is a cache of that.
 */
interface AppState {
  userCode: string;
  setUserCode: (v: string) => void;
  hydrating: boolean;
  reloadSession: () => Promise<void>;

  // Research Planner
  plannerTopicRaw: string;
  setPlannerTopicRaw: (v: string) => void;
  plannerTopic: string;            // refined topic
  setPlannerTopic: (v: string) => void;
  plannerTopicEn: string;
  setPlannerTopicEn: (v: string) => void;
  plannerQuestions: PlannerQuestion[];
  setPlannerQuestions: (v: PlannerQuestion[]) => void;
  plannerAnswers: Record<string, string>;
  setPlannerAnswers: (v: Record<string, string>) => void;
  plannerSections: PlannerSections;
  setPlannerSections: (v: PlannerSections) => void;

  // PubMed
  pubmedPapers: PubMedPaper[];
  setPubmedPapers: (v: PubMedPaper[]) => void;
  topReferences: PubMedPaper[];
  setTopReferences: (v: PubMedPaper[]) => void;

  // Research document
  researchBackground: string;
  setResearchBackground: (v: string) => void;
  dataAnalysisMethod: string;
  setDataAnalysisMethod: (v: string) => void;
  researchHypothesis: string;
  setResearchHypothesis: (v: string) => void;
}

const AppContext = createContext<AppState | null>(null);

const USER_CODE_KEY = "platform.userCode";

function loadUserCode(): string {
  try {
    return localStorage.getItem(USER_CODE_KEY) || "user";
  } catch {
    return "user";
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [userCode, setUserCode] = useState(loadUserCode);
  const [hydrating, setHydrating] = useState(false);

  const [plannerTopicRaw, setPlannerTopicRaw] = useState("");
  const [plannerTopic, setPlannerTopic] = useState("");
  const [plannerTopicEn, setPlannerTopicEn] = useState("");
  const [plannerQuestions, setPlannerQuestions] = useState<PlannerQuestion[]>([]);
  const [plannerAnswers, setPlannerAnswers] = useState<Record<string, string>>({});
  const [plannerSections, setPlannerSections] = useState<PlannerSections>({});
  const [pubmedPapers, setPubmedPapers] = useState<PubMedPaper[]>([]);
  const [topReferences, setTopReferences] = useState<PubMedPaper[]>([]);
  const [researchBackground, setResearchBackground] = useState("");
  const [dataAnalysisMethod, setDataAnalysisMethod] = useState("");
  const [researchHypothesis, setResearchHypothesis] = useState("");

  const requestSeq = useRef(0);

  const reloadSession = async () => {
    const code = userCode.trim();
    if (!code) return;
    const seq = ++requestSeq.current;
    setHydrating(true);
    try {
      const s = await fetchSession(code);
      if (seq !== requestSeq.current) return; // a newer request superseded this one
      setPlannerTopicRaw(s.planner.topic_raw || "");
      setPlannerTopic(s.planner.topic_refined || "");
      setPlannerTopicEn(s.planner.topic_en || "");
      setPlannerQuestions(s.planner.questions || []);
      const answers: Record<string, string> = {};
      for (const qa of s.planner.qa_pairs || []) answers[qa.question_id] = qa.answer || "";
      setPlannerAnswers(answers);
      setPlannerSections(s.planner.sections || {});
      setPubmedPapers(s.pubmed.papers || []);
      setTopReferences(s.pubmed.top_references || []);
      setResearchBackground(s.document.background || "");
      setDataAnalysisMethod(s.document.data_analysis || "");
      setResearchHypothesis(s.document.hypothesis || "");
    } catch (e) {
      console.warn("session restore failed", e);
    } finally {
      if (seq === requestSeq.current) setHydrating(false);
    }
  };

  // Restore from the server whenever the user code settles (debounced typing).
  useEffect(() => {
    try {
      localStorage.setItem(USER_CODE_KEY, userCode);
    } catch {}
    const timer = setTimeout(reloadSession, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userCode]);

  return (
    <AppContext.Provider
      value={{
        userCode, setUserCode, hydrating, reloadSession,
        plannerTopicRaw, setPlannerTopicRaw,
        plannerTopic, setPlannerTopic,
        plannerTopicEn, setPlannerTopicEn,
        plannerQuestions, setPlannerQuestions,
        plannerAnswers, setPlannerAnswers,
        plannerSections, setPlannerSections,
        pubmedPapers, setPubmedPapers,
        topReferences, setTopReferences,
        researchBackground, setResearchBackground,
        dataAnalysisMethod, setDataAnalysisMethod,
        researchHypothesis, setResearchHypothesis,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppState must be used within AppProvider");
  return ctx;
}

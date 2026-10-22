import { fetchWithRetry } from "./client";
import { API_BASE } from "./base";
import type { SessionSnapshot } from "../types";

const BASE = `${API_BASE}/research`;

function headers() {
  return { "Content-Type": "application/json" };
}

// Research Planner
export async function refineTopic(userCode: string, topicRaw: string) {
  const res = await fetchWithRetry(`${BASE}/research_plan/v2/topic/refine`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, topic_raw: topicRaw }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateQuestions(userCode: string, topic: string) {
  const res = await fetchWithRetry(`${BASE}/research_plan/v2/questions/generate`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, topic }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateSectionsChain(
  userCode: string,
  topic: string,
  qaPairs: { question_id: string; target_section: string; pimo_category: string; question: string; answer: string }[]
) {
  const res = await fetchWithRetry(`${BASE}/research_plan/v2/sections/generate_chain`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, topic, qa_pairs: qaPairs }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function reviseSection(userCode: string, sectionKey: string, revisionRequest: string) {
  const res = await fetchWithRetry(`${BASE}/research_plan/v2/sections/revise`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, section_key: sectionKey, revision_request: revisionRequest }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// PubMed Search (streaming) — no retry (streaming response)
export async function* searchPubMed(
  userCode: string,
  plannerSections: Record<string, string>,
  researchBackground: string,
  dataAnalysisMethod: string
) {
  const res = await fetchWithRetry(`${BASE}/pubmed_search/`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      user_code: userCode,
      research_plan_sections: plannerSections,
      research_plan_background: researchBackground,
      research_plan_data_analysis_method: dataAnalysisMethod,
    }),
  });
  if (!res.ok) throw new Error(await res.text());

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) yield line;
    }
  }
  if (buffer.trim()) yield buffer;
}

// IRB Documentation
export async function getBackgroundQuestions(userCode: string, payload: Record<string, unknown>) {
  const res = await fetchWithRetry(`${BASE}/research_plan/get_research_background_answer`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function buildBackground(userCode: string, payload: Record<string, unknown>) {
  const res = await fetchWithRetry(`${BASE}/research_plan/get_background_build_answer`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkDataAnalysis(userCode: string, payload: Record<string, unknown>) {
  const res = await fetchWithRetry(`${BASE}/research_plan/check_data_analysis`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getDataAnalysis(userCode: string, payload: Record<string, unknown>) {
  const res = await fetchWithRetry(`${BASE}/research_plan/get_data_analysis`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getHypothesis(userCode: string, payload: Record<string, unknown>) {
  const res = await fetchWithRetry(`${BASE}/research_plan/get_hypothesis`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function reviseDoc(userCode: string, docType: string, currentContent: string, revisionRequest: string) {
  const res = await fetchWithRetry(`${BASE}/research_plan/v2/docs/revise`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ user_code: userCode, doc_type: docType, current_content: currentContent, revision_request: revisionRequest }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// LLM Config
export async function getLlmConfig() {
  const res = await fetchWithRetry(`${BASE}/llm/config`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function setProviderModel(provider: string, model: string) {
  const res = await fetchWithRetry(`${BASE}/llm/provider_model`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ provider, model }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Session snapshot (restores all tabs from server state)
export async function fetchSession(userCode: string): Promise<SessionSnapshot> {
  const res = await fetchWithRetry(`${BASE}/session/${encodeURIComponent(userCode)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

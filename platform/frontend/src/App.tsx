import { useState } from "react";
import { useAppState } from "./context/AppContext";
import ResearchPlanner from "./components/ResearchPlanner";
import PubMedSearch from "./components/PubMedSearch";
import IrbDocumentation from "./components/IrbDocumentation";
import McpWorkspace from "./components/McpWorkspace";
import TelemetryViewer from "./components/TelemetryViewer";

const TABS = [
  { id: "planner", label: "Research Planner" },
  { id: "pubmed", label: "PubMed Search" },
  { id: "irb", label: "IRB Documentation" },
  { id: "workspace", label: "MCP Workspace" },
  { id: "telemetry", label: "Telemetry" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("planner");
  const { userCode, setUserCode, hydrating } = useAppState();

  return (
    <div className="app">
      <header className="header">
        <h1>Research AI Platform</h1>
        <div className="header-right">
          <label className="user-code-label">
            User:
            <input
              type="text"
              value={userCode}
              onChange={(e) => setUserCode(e.target.value)}
              className="user-code-input"
            />
          </label>
          {hydrating && <span className="text-muted">restoring…</span>}
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="tab-content">
        <div className="tab-pane" style={{ display: activeTab === "planner" ? "flex" : "none" }}><ResearchPlanner /></div>
        <div className="tab-pane" style={{ display: activeTab === "pubmed" ? "flex" : "none" }}><PubMedSearch /></div>
        <div className="tab-pane" style={{ display: activeTab === "irb" ? "flex" : "none" }}><IrbDocumentation /></div>
        <div className="tab-pane" style={{ display: activeTab === "workspace" ? "flex" : "none" }}><McpWorkspace /></div>
        {activeTab === "telemetry" && <div className="tab-pane"><TelemetryViewer /></div>}
      </main>
    </div>
  );
}

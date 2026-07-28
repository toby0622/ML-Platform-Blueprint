"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type ViewId =
  | "command"
  | "models"
  | "runs"
  | "deployments"
  | "playground"
  | "observability"
  | "evidence"
  | "audit";

type PortalMode = "demo" | "live";
type ConnectionState = "idle" | "loading" | "connected" | "unavailable";
type ActionKind = "train" | "promote" | "rollback" | null;

interface ModelSummary {
  name: string;
  version: number;
  versionCount: number;
  stage: string;
  stableVersion: number | null;
  canaryVersion: number | null;
  canaryWeight: number;
  accuracy: number | null;
  f1: number | null;
  rocAuc: number | null;
  brier: number | null;
  updatedAt: string;
}

interface RunSummary {
  id: string;
  model: string;
  status: string;
  accuracy: number | null;
  startedAt: string;
  revision: string;
}

interface LiveOverview {
  tenant: string;
  environment: string;
  summary: {
    models: number;
    versions: number;
    active_canaries: number;
    recent_runs: number;
  };
  models: Array<{
    name: string;
    version_count: number;
    latest_version: number | null;
    latest_stage: string | null;
    latest_metrics: Record<string, number> | null;
    created_at: string;
    deployment: {
      stable_version: number;
      canary_version: number | null;
      canary_weight: number;
      updated_at: string;
    } | null;
  }>;
  recent_runs: Array<{
    run_id: string;
    model_name: string;
    status: string;
    metrics: Record<string, number> | null;
    started_at: string;
    code_revision: string;
  }>;
}

const navigation: Array<{ id: ViewId; label: string; mark: string }> = [
  { id: "command", label: "Command Center", mark: "01" },
  { id: "models", label: "Models", mark: "02" },
  { id: "runs", label: "Runs", mark: "03" },
  { id: "deployments", label: "Deployments", mark: "04" },
  { id: "playground", label: "Inference", mark: "05" },
  { id: "observability", label: "Observability", mark: "06" },
  { id: "evidence", label: "Evidence", mark: "07" },
  { id: "audit", label: "Audit & Runbooks", mark: "08" },
];

const demoModels: Record<string, ModelSummary[]> = {
  "team-a": [
    {
      name: "churn-risk",
      version: 4,
      versionCount: 4,
      stage: "canary",
      stableVersion: 3,
      canaryVersion: 4,
      canaryWeight: 10,
      accuracy: 0.814,
      f1: 0.781,
      rocAuc: 0.872,
      brier: 0.148,
      updatedAt: "2026-07-28T12:44:00Z",
    },
    {
      name: "demand-forecast",
      version: 2,
      versionCount: 2,
      stage: "production",
      stableVersion: 2,
      canaryVersion: null,
      canaryWeight: 0,
      accuracy: 0.793,
      f1: 0.744,
      rocAuc: 0.841,
      brier: 0.171,
      updatedAt: "2026-07-27T08:18:00Z",
    },
  ],
  "team-b": [
    {
      name: "fraud-signal",
      version: 6,
      versionCount: 6,
      stage: "production",
      stableVersion: 6,
      canaryVersion: null,
      canaryWeight: 0,
      accuracy: 0.832,
      f1: 0.802,
      rocAuc: 0.901,
      brier: 0.132,
      updatedAt: "2026-07-28T06:31:00Z",
    },
  ],
};

const demoRuns: Record<string, RunSummary[]> = {
  "team-a": [
    {
      id: "run_01JZ4XW7A4",
      model: "churn-risk",
      status: "succeeded",
      accuracy: 0.814,
      startedAt: "2026-07-28T12:31:00Z",
      revision: "785da34",
    },
    {
      id: "run_01JZ4P9E2C",
      model: "demand-forecast",
      status: "succeeded",
      accuracy: 0.793,
      startedAt: "2026-07-27T08:02:00Z",
      revision: "785da34",
    },
    {
      id: "run_01JZ2K1M9Q",
      model: "churn-risk",
      status: "failed",
      accuracy: null,
      startedAt: "2026-07-26T14:19:00Z",
      revision: "71c9f02",
    },
  ],
  "team-b": [
    {
      id: "run_01JZ4R2K8B",
      model: "fraud-signal",
      status: "succeeded",
      accuracy: 0.832,
      startedAt: "2026-07-28T06:12:00Z",
      revision: "785da34",
    },
  ],
};

const benchmarkRows = [
  {
    scenario: "Baseline",
    c1: 171.956,
    c16: 1861.453,
    ttft: 61.197,
    e2e: 850.103,
    accent: "lime",
  },
  {
    scenario: "Prefix cache",
    c1: 170.665,
    c16: 1837.141,
    ttft: 33.225,
    e2e: 804.655,
    accent: "cyan",
  },
  {
    scenario: "Constrained batch",
    c1: 168.646,
    c16: 1640.258,
    ttft: 122.297,
    e2e: 972.267,
    accent: "amber",
  },
];

const auditEvents = [
  {
    type: "promotion_started",
    actor: "platform-operator",
    model: "churn-risk",
    detail: "v4 entered canary at 10% traffic",
    time: "12:44",
  },
  {
    type: "quality_gate_passed",
    actor: "policy-engine",
    model: "churn-risk",
    detail: "5 of 5 offline checks accepted",
    time: "12:43",
  },
  {
    type: "model_registered",
    actor: "training-pipeline",
    model: "churn-risk",
    detail: "v4 artifact and lineage committed",
    time: "12:39",
  },
  {
    type: "manual_rollback",
    actor: "on-call",
    model: "demand-forecast",
    detail: "restored v1 during rollout exercise",
    time: "Jul 26",
  },
];

const runbooks = [
  ["Canary latency regression", "Observe → halt → rollback → verify"],
  ["GPU capacity unavailable", "Triage scheduling and memory pressure"],
  ["Queue starvation", "Inspect quotas, priorities, and admission"],
  ["Registry or object-store outage", "Protect writes and restore service"],
];

function formatMetric(value: number | null, digits = 3): string {
  return value === null ? "—" : value.toFixed(digits);
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat("zh-TW", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function mapLiveModel(model: LiveOverview["models"][number]): ModelSummary {
  const metrics = model.latest_metrics ?? {};
  return {
    name: model.name,
    version: model.latest_version ?? 0,
    versionCount: model.version_count,
    stage: model.latest_stage ?? "registered",
    stableVersion: model.deployment?.stable_version ?? null,
    canaryVersion: model.deployment?.canary_version ?? null,
    canaryWeight: model.deployment?.canary_weight ?? 0,
    accuracy: metrics.accuracy ?? null,
    f1: metrics.f1 ?? null,
    rocAuc: metrics.roc_auc ?? null,
    brier: metrics.brier_score ?? null,
    updatedAt: model.deployment?.updated_at ?? model.created_at,
  };
}

function mapLiveRun(run: LiveOverview["recent_runs"][number]): RunSummary {
  return {
    id: run.run_id,
    model: run.model_name,
    status: run.status,
    accuracy: run.metrics?.accuracy ?? null,
    startedAt: run.started_at,
    revision: run.code_revision,
  };
}

export function PortalDashboard() {
  const [activeView, setActiveView] = useState<ViewId>("command");
  const [tenant, setTenant] = useState("team-a");
  const [mode, setMode] = useState<PortalMode>("demo");
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const [liveOverview, setLiveOverview] = useState<LiveOverview | null>(null);
  const [connectionMessage, setConnectionMessage] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [action, setAction] = useState<ActionKind>(null);
  const [toast, setToast] = useState("");
  const [modelName, setModelName] = useState("churn-risk");
  const [actor, setActor] = useState("portal-user");
  const [reason, setReason] = useState("Portal lifecycle operation");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [prediction, setPrediction] = useState<number | null>(null);
  const [features, setFeatures] = useState({
    tenure_months: 12,
    monthly_spend: 90,
    support_tickets: 2,
    usage_score: 55,
    payment_failures: 1,
    contract_months: 1,
  });
  const [chatInput, setChatInput] = useState("Summarize the platform readiness in one sentence.");
  const [chatOutput, setChatOutput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  const loadLiveOverview = useCallback(async (selectedTenant = tenant) => {
    setConnection("loading");
    setConnectionMessage("");
    try {
      const response = await fetch(`/api/platform/v1/tenants/${selectedTenant}/overview`, {
        headers: { "X-Tenant-Id": selectedTenant },
        cache: "no-store",
      });
      const body = (await response.json()) as LiveOverview | { error?: { message?: string } };
      if (!response.ok) {
        throw new Error(
          "error" in body ? body.error?.message ?? "Live backend unavailable" : "Unavailable",
        );
      }
      setLiveOverview(body as LiveOverview);
      setConnection("connected");
    } catch (error) {
      setLiveOverview(null);
      setConnection("unavailable");
      setConnectionMessage(error instanceof Error ? error.message : "Live backend unavailable");
    }
  }, [tenant]);

  function switchMode(nextMode: PortalMode) {
    setMode(nextMode);
    if (nextMode === "live") {
      void loadLiveOverview();
    } else {
      setConnection("idle");
      setLiveOverview(null);
      setConnectionMessage("");
    }
  }

  function switchTenant(nextTenant: string) {
    setTenant(nextTenant);
    if (mode === "live") {
      void loadLiveOverview(nextTenant);
    }
  }

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timeout = window.setTimeout(() => setToast(""), 4200);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const models = useMemo(
    () =>
      mode === "live" && liveOverview
        ? liveOverview.models.map(mapLiveModel)
        : demoModels[tenant],
    [liveOverview, mode, tenant],
  );
  const runs = useMemo(
    () =>
      mode === "live" && liveOverview
        ? liveOverview.recent_runs.map(mapLiveRun)
        : demoRuns[tenant],
    [liveOverview, mode, tenant],
  );
  const activeCanaries = models.filter((model) => model.canaryVersion !== null).length;
  const totalVersions = models.reduce((total, model) => total + model.versionCount, 0);
  const currentModel = models.find((model) => model.name === modelName) ?? models[0] ?? null;
  const modeLabel =
    mode === "demo"
      ? "Reviewed demo data"
      : connection === "connected"
        ? "Live backend connected"
        : connection === "loading"
          ? "Connecting to live backend"
          : "Live backend unavailable";

  function navigate(view: ViewId) {
    setActiveView(view);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function platformRequest(path: string, init: RequestInit) {
    const response = await fetch(`/api/platform/${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenant,
        ...init.headers,
      },
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body?.error?.message ?? "Platform request failed");
    }
    return body;
  }

  async function submitLifecycleAction(event: FormEvent) {
    event.preventDefault();
    if (!action) {
      return;
    }
    setIsSubmitting(true);
    try {
      if (mode === "demo") {
        await new Promise((resolve) => window.setTimeout(resolve, 550));
        setToast(`Demo recorded: ${action} for ${modelName}. No platform state was changed.`);
      } else if (action === "train") {
        await platformRequest(`v1/tenants/${tenant}/models/${modelName}/runs`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        setToast(`Training completed and a new ${modelName} version was registered.`);
      } else if (action === "promote") {
        if (!currentModel || currentModel.version < 1) {
          throw new Error("No registered model version is available for promotion");
        }
        await platformRequest(
          `v1/tenants/${tenant}/models/${currentModel.name}/versions/${currentModel.version}/promotion`,
          {
            method: "POST",
            body: JSON.stringify({ canary_weight: 10, actor, reason }),
          },
        );
        setToast(`${currentModel.name} v${currentModel.version} passed the promotion request.`);
      } else if (action === "rollback") {
        if (!currentModel) {
          throw new Error("No deployed model is available for rollback");
        }
        await platformRequest(
          `v1/tenants/${tenant}/models/${currentModel.name}/deployment/rollback`,
          {
            method: "POST",
            body: JSON.stringify({ target_version: null, actor, reason }),
          },
        );
        setToast(`${currentModel.name} rollback completed.`);
      }
      setAction(null);
      if (mode === "live") {
        await loadLiveOverview();
      }
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Operation failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function runPrediction(event: FormEvent) {
    event.preventDefault();
    if (mode === "demo") {
      const raw =
        features.monthly_spend * 0.004 +
        features.support_tickets * 0.11 +
        features.payment_failures * 0.16 -
        features.usage_score * 0.004 -
        features.contract_months * 0.012 +
        0.28;
      setPrediction(Math.max(0.03, Math.min(0.97, raw)));
      return;
    }
    if (!currentModel) {
      setToast("Train or select a model before running prediction.");
      return;
    }
    try {
      const body = await platformRequest(
        `v1/tenants/${tenant}/models/${currentModel.name}/predict`,
        {
          method: "POST",
          body: JSON.stringify({ instances: [features] }),
        },
      );
      const value = body.predictions?.[0]?.probability ?? body.predictions?.[0]?.score;
      setPrediction(typeof value === "number" ? value : null);
      setToast(`Prediction routed to model version ${body.model_version ?? "active"}.`);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Prediction failed");
    }
  }

  async function sendChat(event: FormEvent) {
    event.preventDefault();
    if (!chatInput.trim()) {
      return;
    }
    setChatBusy(true);
    setChatOutput("");
    try {
      if (mode === "demo") {
        await new Promise((resolve) => window.setTimeout(resolve, 480));
        setChatOutput(
          "The blueprint is ready for a reproducible local demo: lifecycle APIs, policy-gated deployment, observability, and the RTX 4080 SUPER vLLM path are all evidenced.",
        );
      } else {
        const response = await fetch("/api/llm/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: chatInput }),
        });
        const body = await response.json();
        if (!response.ok) {
          throw new Error(body?.error?.message ?? "LLM service unavailable");
        }
        setChatOutput(body.message);
      }
    } catch (error) {
      setToast(error instanceof Error ? error.message : "LLM request failed");
    } finally {
      setChatBusy(false);
    }
  }

  return (
    <main className="portal-shell">
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand-block">
          <div className="brand-symbol" aria-hidden="true">
            MP
          </div>
          <div>
            <p className="eyebrow">Blueprint / 01</p>
            <p className="brand-name">ML Platform</p>
          </div>
        </div>

        <nav className="primary-nav" aria-label="Portal navigation">
          {navigation.map((item) => (
            <button
              className={activeView === item.id ? "nav-item nav-item-active" : "nav-item"}
              key={item.id}
              onClick={() => navigate(item.id)}
              type="button"
            >
              <span className="nav-mark">{item.mark}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="environment-card">
            <div className="status-row">
              <span
                className={`status-dot ${
                  mode === "live" && connection !== "connected" ? "status-dot-warn" : ""
                }`}
              />
              <span>{modeLabel}</span>
            </div>
            <p>{mode === "demo" ? "Snapshot · 2026-07-28" : "Local control plane"}</p>
          </div>
          <a className="docs-link" href="http://localhost:8080/docs" target="_blank">
            API reference <span aria-hidden="true">↗</span>
          </a>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button
            aria-expanded={mobileNavOpen}
            aria-label="Toggle navigation"
            className="menu-button"
            onClick={() => setMobileNavOpen((value) => !value)}
            type="button"
          >
            <span />
            <span />
          </button>
          <div className="breadcrumb">
            <span>ML Platform</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{navigation.find((item) => item.id === activeView)?.label}</strong>
          </div>
          <div className="topbar-controls">
            <label className="select-wrap">
              <span className="sr-only">Select tenant</span>
              <select value={tenant} onChange={(event) => switchTenant(event.target.value)}>
                <option value="team-a">team-a</option>
                <option value="team-b">team-b</option>
              </select>
            </label>
            <div className="mode-switch" aria-label="Data mode">
              <button
                className={mode === "demo" ? "mode-active" : ""}
                onClick={() => switchMode("demo")}
                type="button"
              >
                Demo
              </button>
              <button
                className={mode === "live" ? "mode-active" : ""}
                onClick={() => switchMode("live")}
                type="button"
              >
                Live
              </button>
            </div>
            <button
              aria-label="Refresh live data"
              className="icon-button"
              disabled={mode !== "live" || connection === "loading"}
              onClick={() => void loadLiveOverview()}
              type="button"
            >
              ↻
            </button>
          </div>
        </header>

        {mode === "live" && connection === "unavailable" && (
          <div className="connection-banner" role="status">
            <div>
              <strong>Live control plane is not connected.</strong>
              <span>{connectionMessage || "Start the local Compose stack and retry."}</span>
            </div>
            <button onClick={() => void loadLiveOverview()} type="button">
              Retry
            </button>
          </div>
        )}

        <div className="view-content">
          {activeView === "command" && (
            <>
              <section className="hero">
                <div>
                  <p className="section-kicker">Operational command center</p>
                  <h1>
                    Model delivery,
                    <br />
                    without the <em>guesswork.</em>
                  </h1>
                  <p className="hero-copy">
                    One decision surface for training, lineage, policy gates, canary traffic,
                    inference, and reviewed GPU evidence.
                  </p>
                </div>
                <div className="hero-actions">
                  <button className="button-primary" onClick={() => setAction("train")} type="button">
                    <span>+</span> Train new version
                  </button>
                  <button
                    className="button-secondary"
                    onClick={() => navigate("playground")}
                    type="button"
                  >
                    Test inference
                  </button>
                </div>
              </section>

              <section className="metric-grid" aria-label="Platform summary">
                <article className="metric-card metric-card-featured">
                  <p>Control plane</p>
                  <div className="metric-value-row">
                    <strong>{mode === "live" && connection === "connected" ? "READY" : "DEMO"}</strong>
                    <span className="pulse-ring" />
                  </div>
                  <span>{mode === "live" ? "Registry and API readiness" : "Reviewed product walkthrough"}</span>
                </article>
                <article className="metric-card">
                  <p>Registered models</p>
                  <strong>{models.length.toString().padStart(2, "0")}</strong>
                  <span>{totalVersions} immutable versions</span>
                </article>
                <article className="metric-card">
                  <p>Active canaries</p>
                  <strong>{activeCanaries.toString().padStart(2, "0")}</strong>
                  <span>{activeCanaries ? "Policy-gated traffic split" : "No rollout in progress"}</span>
                </article>
                <article className="metric-card">
                  <p>GPU evidence</p>
                  <strong>900</strong>
                  <span>requests · zero errors</span>
                </article>
              </section>

              <section className="command-grid">
                <article className="panel lifecycle-panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-label">Active delivery</p>
                      <h2>{models[0]?.name ?? "No model registered"}</h2>
                    </div>
                    <button className="text-button" onClick={() => navigate("deployments")} type="button">
                      Open deployment <span>→</span>
                    </button>
                  </div>
                  {models[0] ? (
                    <>
                      <div className="traffic-visual">
                        <div className="version-node version-node-stable">
                          <span>Stable</span>
                          <strong>v{models[0].stableVersion ?? models[0].version}</strong>
                          <small>{100 - models[0].canaryWeight}% traffic</small>
                        </div>
                        <div className="traffic-line">
                          <span style={{ width: `${100 - models[0].canaryWeight}%` }} />
                        </div>
                        <div className="version-node version-node-canary">
                          <span>Canary</span>
                          <strong>{models[0].canaryVersion ? `v${models[0].canaryVersion}` : "—"}</strong>
                          <small>{models[0].canaryWeight}% traffic</small>
                        </div>
                      </div>
                      <div className="gate-strip">
                        {["Accuracy", "F1", "ROC-AUC", "Brier", "Sample size"].map((gate) => (
                          <div key={gate}>
                            <span className="gate-check">✓</span>
                            <span>{gate}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="empty-state">
                      <strong>No model state yet</strong>
                      <p>Use “Train new version” to create the first registered model.</p>
                    </div>
                  )}
                </article>

                <article className="panel benchmark-panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-label">Reviewed local evidence</p>
                      <h2>RTX 4080 SUPER</h2>
                    </div>
                    <span className="evidence-badge">Verified snapshot</span>
                  </div>
                  <div className="big-number">
                    <strong>1,861</strong>
                    <span>output tok/s</span>
                  </div>
                  <div className="throughput-chart" aria-label="Throughput by concurrency">
                    {[172, 308, 577, 989, 1861].map((value, index) => (
                      <div className="bar-column" key={value}>
                        <span className="bar-value">{value}</span>
                        <span
                          className="bar-fill"
                          style={{ height: `${Math.max(14, (value / 1861) * 100)}%` }}
                        />
                        <small>C{[1, 2, 4, 8, 16][index]}</small>
                      </div>
                    ))}
                  </div>
                  <p className="panel-note">
                    Baseline · 3 runs per level · 0.0% aggregate error rate
                  </p>
                </article>

                <article className="panel services-panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-label">Service map</p>
                      <h2>Platform surfaces</h2>
                    </div>
                  </div>
                  <div className="service-list">
                    {[
                      ["Platform API", "8080", mode === "live" && connection === "connected" ? "ready" : "demo"],
                      ["MLflow", "5000", "available"],
                      ["Grafana", "3000", "available"],
                      ["vLLM · Qwen 1.5B", "8000", "gpu ready"],
                    ].map(([name, port, status]) => (
                      <div className="service-row" key={name}>
                        <span className="service-icon">{name.slice(0, 2).toUpperCase()}</span>
                        <div>
                          <strong>{name}</strong>
                          <span>localhost:{port}</span>
                        </div>
                        <small>{status}</small>
                      </div>
                    ))}
                  </div>
                </article>

                <article className="panel activity-panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-label">Governance trail</p>
                      <h2>Recent activity</h2>
                    </div>
                    <button className="text-button" onClick={() => navigate("audit")} type="button">
                      Full audit <span>→</span>
                    </button>
                  </div>
                  <div className="activity-list">
                    {auditEvents.slice(0, 3).map((event) => (
                      <div className="activity-row" key={`${event.type}-${event.time}`}>
                        <span className="activity-mark" />
                        <div>
                          <strong>{event.type.replaceAll("_", " ")}</strong>
                          <span>
                            {event.model} · {event.detail}
                          </span>
                        </div>
                        <time>{event.time}</time>
                      </div>
                    ))}
                  </div>
                </article>
              </section>
            </>
          )}

          {activeView === "models" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Registry & lineage</p>
                  <h1>Models</h1>
                  <p>Compare the latest observed metrics with deployment state and policy thresholds.</p>
                </div>
                <button className="button-primary" onClick={() => setAction("train")} type="button">
                  <span>+</span> New training run
                </button>
              </div>
              <div className="table-panel">
                <div className="table-toolbar">
                  <span>{models.length} models in {tenant}</span>
                  <span className="data-provenance">{mode === "demo" ? "Demo data" : "Live registry"}</span>
                </div>
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th>Latest</th>
                        <th>Stage</th>
                        <th>Accuracy</th>
                        <th>F1</th>
                        <th>ROC-AUC</th>
                        <th>Brier ↓</th>
                        <th>Deployment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {models.map((model) => (
                        <tr key={model.name}>
                          <td>
                            <button
                              className="model-cell"
                              onClick={() => {
                                setModelName(model.name);
                                navigate("deployments");
                              }}
                              type="button"
                            >
                              <span>{model.name.slice(0, 2).toUpperCase()}</span>
                              <div>
                                <strong>{model.name}</strong>
                                <small>{model.versionCount} versions</small>
                              </div>
                            </button>
                          </td>
                          <td>v{model.version}</td>
                          <td>
                            <span className={`stage-pill stage-${model.stage}`}>{model.stage}</span>
                          </td>
                          <td>{formatMetric(model.accuracy)}</td>
                          <td>{formatMetric(model.f1)}</td>
                          <td>{formatMetric(model.rocAuc)}</td>
                          <td>{formatMetric(model.brier)}</td>
                          <td>
                            {model.canaryVersion
                              ? `v${model.stableVersion} → v${model.canaryVersion} · ${model.canaryWeight}%`
                              : model.stableVersion
                                ? `stable v${model.stableVersion}`
                                : "not deployed"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!models.length && (
                  <div className="empty-state table-empty">
                    <strong>No models found for {tenant}</strong>
                    <p>Start a training run to populate the model catalog.</p>
                  </div>
                )}
              </div>
              <div className="threshold-grid">
                {[
                  ["Accuracy", "≥ 0.72", "Higher is better"],
                  ["F1 score", "≥ 0.68", "Balance precision / recall"],
                  ["ROC-AUC", "≥ 0.78", "Ranking quality"],
                  ["Brier score", "≤ 0.20", "Calibration error"],
                  ["Evaluation", "≥ 100", "Minimum samples"],
                ].map(([name, value, detail]) => (
                  <article key={name}>
                    <span>{name}</span>
                    <strong>{value}</strong>
                    <small>{detail}</small>
                  </article>
                ))}
              </div>
            </section>
          )}

          {activeView === "runs" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Reproducible execution</p>
                  <h1>Training runs</h1>
                  <p>Every run captures parameters, dataset hash, code revision, metrics, and status.</p>
                </div>
                <button className="button-primary" onClick={() => setAction("train")} type="button">
                  <span>+</span> Start run
                </button>
              </div>
              <div className="run-layout">
                <div className="table-panel">
                  <div className="table-toolbar">
                    <span>Recent runs</span>
                    <span className="data-provenance">{mode === "demo" ? "Illustrative" : "SQLite registry"}</span>
                  </div>
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Run ID</th>
                          <th>Model</th>
                          <th>Status</th>
                          <th>Accuracy</th>
                          <th>Code revision</th>
                          <th>Started</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runs.map((run) => (
                          <tr key={run.id}>
                            <td className="mono-cell">{run.id}</td>
                            <td>{run.model}</td>
                            <td>
                              <span className={`run-status run-${run.status}`}>
                                <span /> {run.status}
                              </span>
                            </td>
                            <td>{formatMetric(run.accuracy)}</td>
                            <td className="mono-cell">{run.revision.slice(0, 8)}</td>
                            <td>{shortDate(run.startedAt)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <aside className="pipeline-card">
                  <p className="panel-label">Lifecycle contract</p>
                  <h2>Run execution</h2>
                  {["Validate request", "Generate dataset", "Train & evaluate", "Register artifact"].map(
                    (step, index) => (
                      <div className="pipeline-step" key={step}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{step}</strong>
                          <small>{index === 3 ? "Immutable version + model card" : "Deterministic reference step"}</small>
                        </div>
                      </div>
                    ),
                  )}
                  <p className="callout-note">
                    The reference API runs synchronously. A production profile hands this contract to
                    Kubeflow Pipelines and Kueue.
                  </p>
                </aside>
              </div>
            </section>
          )}

          {activeView === "deployments" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Policy-driven delivery</p>
                  <h1>Deployments</h1>
                  <p>Promote only after offline gates, then finalize or rollback with explicit evidence.</p>
                </div>
                <div className="heading-actions">
                  <button className="button-secondary" onClick={() => setAction("rollback")} type="button">
                    Rollback
                  </button>
                  <button className="button-primary" onClick={() => setAction("promote")} type="button">
                    Promote latest
                  </button>
                </div>
              </div>
              <div className="deployment-grid">
                {models.map((model) => (
                  <article
                    className={model.name === currentModel?.name ? "deployment-card deployment-card-active" : "deployment-card"}
                    key={model.name}
                    onClick={() => setModelName(model.name)}
                  >
                    <div className="deployment-card-head">
                      <div>
                        <span>{tenant}</span>
                        <h2>{model.name}</h2>
                      </div>
                      <span className={`stage-pill stage-${model.stage}`}>{model.stage}</span>
                    </div>
                    <div className="traffic-split">
                      <span
                        className="traffic-stable"
                        style={{ width: `${100 - model.canaryWeight}%` }}
                      />
                      <span className="traffic-canary" style={{ width: `${model.canaryWeight}%` }} />
                    </div>
                    <div className="traffic-legend">
                      <div>
                        <span className="legend-dot legend-stable" />
                        <p>
                          Stable <strong>v{model.stableVersion ?? "—"}</strong>
                        </p>
                        <small>{100 - model.canaryWeight}% traffic</small>
                      </div>
                      <div>
                        <span className="legend-dot legend-canary" />
                        <p>
                          Canary <strong>{model.canaryVersion ? `v${model.canaryVersion}` : "—"}</strong>
                        </p>
                        <small>{model.canaryWeight}% traffic</small>
                      </div>
                    </div>
                    <footer>
                      <span>Updated {shortDate(model.updatedAt)}</span>
                      <span>Open details →</span>
                    </footer>
                  </article>
                ))}
              </div>
              <div className="gate-detail panel">
                <div className="panel-header">
                  <div>
                    <p className="panel-label">Latest gate decision</p>
                    <h2>{currentModel?.name ?? "No deployment"}</h2>
                  </div>
                  <span className="gate-result">Accepted</span>
                </div>
                <div className="gate-table">
                  {[
                    ["Accuracy", currentModel?.accuracy, 0.72, "higher"],
                    ["F1 score", currentModel?.f1, 0.68, "higher"],
                    ["ROC-AUC", currentModel?.rocAuc, 0.78, "higher"],
                    ["Brier score", currentModel?.brier, 0.2, "lower"],
                  ].map(([name, observed, threshold, direction]) => {
                    const value = typeof observed === "number" ? observed : null;
                    const passed =
                      value !== null &&
                      (direction === "higher"
                        ? value >= Number(threshold)
                        : value <= Number(threshold));
                    return (
                      <div key={String(name)}>
                        <span className={passed ? "gate-check" : "gate-check gate-muted"}>
                          {passed ? "✓" : "—"}
                        </span>
                        <strong>{name}</strong>
                        <span>Observed {formatMetric(value)}</span>
                        <span>
                          Policy {direction === "higher" ? "≥" : "≤"} {Number(threshold).toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

          {activeView === "playground" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Safe serving surface</p>
                  <h1>Inference playground</h1>
                  <p>Exercise predictive routing and the local GPU LLM through the Portal boundary.</p>
                </div>
              </div>
              <div className="playground-grid">
                <form className="playground-card" onSubmit={runPrediction}>
                  <div className="playground-head">
                    <div>
                      <span>Predictive</span>
                      <h2>Churn risk</h2>
                    </div>
                    <span className="protocol-badge">Platform API</span>
                  </div>
                  <div className="feature-grid">
                    {Object.entries(features).map(([name, value]) => (
                      <label key={name}>
                        <span>{name.replaceAll("_", " ")}</span>
                        <input
                          min="0"
                          onChange={(event) =>
                            setFeatures((current) => ({
                              ...current,
                              [name]: Number(event.target.value),
                            }))
                          }
                          step="1"
                          type="number"
                          value={value}
                        />
                      </label>
                    ))}
                  </div>
                  <button className="button-primary full-button" type="submit">
                    Run routed prediction
                  </button>
                  <div className={prediction === null ? "prediction-result result-empty" : "prediction-result"}>
                    <div>
                      <span>Risk probability</span>
                      <strong>{prediction === null ? "—" : `${(prediction * 100).toFixed(1)}%`}</strong>
                    </div>
                    <div>
                      <span>Decision</span>
                      <strong>{prediction === null ? "Awaiting input" : prediction >= 0.5 ? "High risk" : "Low risk"}</strong>
                    </div>
                  </div>
                </form>

                <form className="playground-card llm-card" onSubmit={sendChat}>
                  <div className="playground-head">
                    <div>
                      <span>Generative</span>
                      <h2>Qwen 2.5 · 1.5B</h2>
                    </div>
                    <span className="protocol-badge protocol-gpu">RTX 4080 SUPER</span>
                  </div>
                  <div className="chat-window">
                    <div className="chat-message chat-system">
                      <span>System</span>
                      <p>You are connected through the Portal BFF with bounded output.</p>
                    </div>
                    {chatOutput && (
                      <div className="chat-message chat-assistant">
                        <span>Assistant</span>
                        <p>{chatOutput}</p>
                      </div>
                    )}
                  </div>
                  <label className="chat-input">
                    <span className="sr-only">Message to local LLM</span>
                    <textarea
                      maxLength={2000}
                      onChange={(event) => setChatInput(event.target.value)}
                      rows={4}
                      value={chatInput}
                    />
                  </label>
                  <button className="button-primary full-button" disabled={chatBusy} type="submit">
                    {chatBusy ? "Generating…" : "Send to local GPU"}
                  </button>
                  <p className="panel-note">
                    {mode === "demo"
                      ? "Demo response · switch to Live after starting vLLM."
                      : "Requests stay server-side; no Hugging Face token reaches the browser."}
                  </p>
                </form>
              </div>
            </section>
          )}

          {activeView === "observability" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Signals, not decoration</p>
                  <h1>Observability</h1>
                  <p>Use the Portal for operational context, then drill into the specialist tools.</p>
                </div>
              </div>
              <div className="observability-grid">
                {[
                  ["Prediction rate", "24.8", "req/s", "+12.4%", "Prometheus"],
                  ["Error ratio", "0.08", "%", "within SLO", "Grafana"],
                  ["p95 latency", "46.2", "ms", "−3.1 ms", "Grafana"],
                  ["GPU utilization", "98", "% p50", "reviewed snapshot", "Evidence"],
                ].map(([name, value, unit, change, source], index) => (
                  <article className="signal-card" key={name}>
                    <div className="signal-head">
                      <span>{name}</span>
                      <small>{source}</small>
                    </div>
                    <strong>
                      {value} <small>{unit}</small>
                    </strong>
                    <div className={`sparkline sparkline-${index + 1}`} aria-hidden="true">
                      {Array.from({ length: 14 }, (_, point) => (
                        <span key={point} />
                      ))}
                    </div>
                    <p>{change}</p>
                  </article>
                ))}
              </div>
              <div className="tool-grid">
                {[
                  ["Grafana", "Dashboards, SLO panels, and alert context", "http://localhost:3000"],
                  ["Prometheus", "Raw time-series queries and recording rules", "http://localhost:9090"],
                  ["MLflow", "Experiments, metrics, parameters, and artifacts", "http://localhost:5000"],
                  ["MinIO", "Local object-store inspection", "http://localhost:9001"],
                ].map(([name, description, href]) => (
                  <a className="tool-card" href={href} key={name} target="_blank">
                    <span>{name.slice(0, 2).toUpperCase()}</span>
                    <div>
                      <strong>{name}</strong>
                      <p>{description}</p>
                    </div>
                    <b>↗</b>
                  </a>
                ))}
              </div>
              <div className="truth-callout">
                <span>i</span>
                <p>
                  GPU values shown here are the reviewed 2026-07-28 benchmark snapshot—not live
                  telemetry. Live GPU panels remain unavailable until an exporter is connected.
                </p>
              </div>
            </section>
          )}

          {activeView === "evidence" && (
            <section className="detail-view">
              <div className="view-heading evidence-heading">
                <div>
                  <p className="section-kicker">Reproducible proof</p>
                  <h1>Benchmarks & evidence</h1>
                  <p>Measured locally, source-hashed, secret-free, and reviewed into the repository.</p>
                </div>
                <span className="evidence-seal">
                  <strong>900</strong>
                  measured requests
                </span>
              </div>
              <div className="evidence-hero-grid">
                <article>
                  <span>GPU</span>
                  <strong>RTX 4080 SUPER</strong>
                  <small>16,376 MiB · Compute 8.9</small>
                </article>
                <article>
                  <span>Runtime</span>
                  <strong>vLLM 0.23.0</strong>
                  <small>Digest pinned container image</small>
                </article>
                <article>
                  <span>Model</span>
                  <strong>Qwen 2.5 · 1.5B</strong>
                  <small>Revision 989aa798…</small>
                </article>
                <article>
                  <span>Quality</span>
                  <strong>0 errors</strong>
                  <small>Every run × concurrency slice passed</small>
                </article>
              </div>
              <div className="table-panel evidence-table-panel">
                <div className="table-toolbar">
                  <span>Three scenarios · concurrency 1, 2, 4, 8, 16</span>
                  <span className="data-provenance">Reviewed evidence</span>
                </div>
                <div className="data-table-wrap">
                  <table className="data-table evidence-table">
                    <thead>
                      <tr>
                        <th>Scenario</th>
                        <th>C1 output tok/s</th>
                        <th>C16 output tok/s</th>
                        <th>C16 p95 TTFT</th>
                        <th>C16 p95 E2E</th>
                        <th>Error rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {benchmarkRows.map((row) => (
                        <tr key={row.scenario}>
                          <td>
                            <span className={`scenario-mark scenario-${row.accent}`} />
                            <strong>{row.scenario}</strong>
                          </td>
                          <td>{row.c1.toFixed(3)}</td>
                          <td>{row.c16.toFixed(3)}</td>
                          <td>{row.ttft.toFixed(3)} ms</td>
                          <td>{row.e2e.toFixed(3)} ms</td>
                          <td>
                            <span className="zero-error">0.0%</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="evidence-notes">
                <article>
                  <span>01</span>
                  <div>
                    <strong>What is comparable</strong>
                    <p>Same model revision, prompts, max tokens, run count, and concurrency schedule.</p>
                  </div>
                </article>
                <article>
                  <span>02</span>
                  <div>
                    <strong>Prefix-cache caveat</strong>
                    <p>Exact repeated prompts make this a hot-cache upper bound, not a universal gain.</p>
                  </div>
                </article>
                <article>
                  <span>03</span>
                  <div>
                    <strong>Evidence integrity</strong>
                    <p>Source, image, prompt, raw result, telemetry, and manifest hashes are recorded.</p>
                  </div>
                </article>
              </div>
            </section>
          )}

          {activeView === "audit" && (
            <section className="detail-view">
              <div className="view-heading">
                <div>
                  <p className="section-kicker">Accountable operations</p>
                  <h1>Audit & runbooks</h1>
                  <p>Every lifecycle mutation records actor, reason, payload, version, and timestamp.</p>
                </div>
              </div>
              <div className="audit-layout">
                <article className="panel audit-timeline">
                  <div className="panel-header">
                    <div>
                      <p className="panel-label">Immutable trail</p>
                      <h2>Recent events</h2>
                    </div>
                    <span className="data-provenance">{mode === "demo" ? "Illustrative" : "Live registry"}</span>
                  </div>
                  {auditEvents.map((event) => (
                    <div className="audit-event" key={`${event.type}-${event.time}`}>
                      <span className="audit-line-mark" />
                      <time>{event.time}</time>
                      <div>
                        <strong>{event.type.replaceAll("_", " ")}</strong>
                        <p>{event.detail}</p>
                        <small>
                          {event.actor} · {tenant}/{event.model}
                        </small>
                      </div>
                    </div>
                  ))}
                </article>
                <aside className="runbook-list">
                  <div>
                    <p className="panel-label">Operator response</p>
                    <h2>Runbooks</h2>
                  </div>
                  {runbooks.map(([name, description], index) => (
                    <a href="#" key={name} onClick={(event) => event.preventDefault()}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{name}</strong>
                        <p>{description}</p>
                      </div>
                      <b>→</b>
                    </a>
                  ))}
                </aside>
              </div>
            </section>
          )}
        </div>
      </section>

      {action && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setAction(null)}>
          <form
            aria-labelledby="action-title"
            className="action-modal"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={submitLifecycleAction}
          >
            <button
              aria-label="Close action"
              className="modal-close"
              onClick={() => setAction(null)}
              type="button"
            >
              ×
            </button>
            <p className="section-kicker">{mode === "demo" ? "Demo operation" : "Live mutation"}</p>
            <h2 id="action-title">
              {action === "train"
                ? "Train a new version"
                : action === "promote"
                  ? "Promote the latest version"
                  : "Rollback deployment"}
            </h2>
            <p>
              {mode === "demo"
                ? "This walkthrough records no persistent state. Switch to Live to operate the local platform."
                : "This action changes platform state and will be written to the audit trail."}
            </p>
            <label>
              <span>Model name</span>
              <input
                disabled={action !== "train"}
                onChange={(event) => setModelName(event.target.value)}
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                required
                value={modelName}
              />
            </label>
            {action !== "train" && (
              <>
                <label>
                  <span>Actor</span>
                  <input
                    maxLength={128}
                    onChange={(event) => setActor(event.target.value)}
                    required
                    value={actor}
                  />
                </label>
                <label>
                  <span>Reason</span>
                  <textarea
                    maxLength={500}
                    minLength={3}
                    onChange={(event) => setReason(event.target.value)}
                    required
                    rows={3}
                    value={reason}
                  />
                </label>
              </>
            )}
            <div className="modal-actions">
              <button className="button-secondary" onClick={() => setAction(null)} type="button">
                Cancel
              </button>
              <button className="button-primary" disabled={isSubmitting} type="submit">
                {isSubmitting ? "Working…" : `Confirm ${action}`}
              </button>
            </div>
          </form>
        </div>
      )}

      {toast && (
        <div className="toast" role="status">
          <span>✓</span>
          {toast}
        </div>
      )}
    </main>
  );
}

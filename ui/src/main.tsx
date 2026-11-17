import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowLeftRight,
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  Clock3,
  Database,
  Download,
  GitBranch,
  Layers3,
  LogOut,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Terminal,
  Upload,
  X,
} from "lucide-react";
import {
  orderedSpans,
  depth,
  serviceGraph,
  type Execution,
  type Summary,
  type Span,
  type Job,
  type Change,
} from "./model";
import "./style.css";

type Page = "executions" | "replays" | "connect";
function App() {
  const [token, setToken] = useState(""),
    [draft, setDraft] = useState(""),
    [role, setRole] = useState(""),
    [page, setPage] = useState<Page>("executions");
  const [items, setItems] = useState<Summary[]>([]),
    [selected, setSelected] = useState<Execution | null>(null),
    [span, setSpan] = useState<Span | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState(""),
    [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false);
  const [baseline, setBaseline] = useState(""),
    [changes, setChanges] = useState<Change[] | null>(null),
    [tab, setTab] = useState("timeline");
  const [payment, setPayment] = useState(""),
    [expect, setExpect] = useState("502"),
    [delay, setDelay] = useState("0");
  const credentialRef = useRef("");
  const active = useRef("");
  const file = useRef<HTMLInputElement>(null);
  const replayKey = useRef<{ payload: string; key: string } | null>(null);
  async function api(
    path: string,
    options: RequestInit = {},
    credential = token,
  ) {
    const r = await fetch("/api" + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + credential,
        ...options.headers,
      },
    });
    if (path !== "/me" && credential !== credentialRef.current)
      throw new Error("Session changed; stale response discarded.");
    if (!r.ok) {
      const data = await r.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(`${r.status}: ${data.detail || "Request failed"}`);
    }
    return r.json();
  }
  async function load(offset = 0, credential = token) {
    setLoading(true);
    try {
      const data = await api(
        `/executions?q=${encodeURIComponent(query)}&outcome_filter=${filter}&offset=${offset}`,
        {},
        credential,
      );
      setItems((old) => (offset ? [...old, ...data.items] : data.items));
      setNext(data.next_offset);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  async function refreshJobs() {
    try {
      const data = await api("/replays");
      setJobs(data.items);
    } catch (e) {
      setError(String(e));
    }
  }
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const p = await api("/me", {}, draft.trim());
      if (p.role === "ingestor")
        throw new Error(
          "Use a reader or investigator credential in this console.",
        );
      credentialRef.current = draft.trim();
      setToken(draft.trim());
      setRole(p.role);
      setDraft("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function logout() {
    credentialRef.current = "";
    active.current = "";
    setToken("");
    setRole("");
    setItems([]);
    setJobs([]);
    setSelected(null);
    setSpan(null);
    setError("");
    setNotice("");
    setChanges(null);
  }
  useEffect(() => {
    if (token) void load();
  }, [token, filter]);
  useEffect(() => {
    if (!token || page !== "replays") return;
    void refreshJobs();
    const id = setInterval(() => void refreshJobs(), 2500);
    return () => clearInterval(id);
  }, [token, page]);
  async function open(id: string) {
    active.current = id;
    setError("");
    setSelected(null);
    setSpan(null);
    setChanges(null);
    setTab("timeline");
    try {
      const data = await api("/executions/" + id);
      if (active.current !== id) return;
      setSelected(data);
      setSpan(
        data.spans.find((s: Span) => s.status === "error") || data.spans[0],
      );
      setExpect(String(data.fixture?.captured_checkout_status || 201));
      setPayment("");
      replayKey.current = null;
    } catch (e) {
      setError(String(e));
    }
  }
  async function compare() {
    if (!selected || !baseline) return;
    setBusy(true);
    try {
      const data = await api(`/compare?left=${baseline}&right=${selected.id}`);
      setChanges(data.changes);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function replay() {
    if (!selected) return;
    setBusy(true);
    setError("");
    const body = JSON.stringify({
      execution_id: selected.id,
      expected_status: Number(expect),
      payment_status: payment ? Number(payment) : null,
      dependency_delay_ms: Number(delay),
    });
    if (replayKey.current?.payload !== body)
      replayKey.current = { payload: body, key: crypto.randomUUID() };
    try {
      await api("/replays", {
        method: "POST",
        body,
        headers: { "Idempotency-Key": replayKey.current.key },
      });
      replayKey.current = null;
      setNotice(
        "Replay queued. The worker will run the fixed checkout adapter.",
      );
      setPage("replays");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function upload(f: File) {
    setError("");
    if (f.size > 262144) {
      setError("Evidence must be smaller than 256 KiB.");
      return;
    }
    setBusy(true);
    try {
      const body = await f.text();
      JSON.parse(body);
      const result = await api("/executions", { method: "POST", body });
      setNotice(
        result.duplicate
          ? "This evidence is already stored."
          : "Evidence accepted and stored.",
      );
      await load();
      await open(result.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    if (!selected) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(selected, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `execution-${selected.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  const errors = items.filter((i) => i.outcome === "error").length;
  const graph = selected ? serviceGraph(selected.spans) : null;
  const total = selected
    ? Math.max(1, ...selected.spans.map((s) => s.start_ms + s.duration_ms))
    : 1;
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="Trace Atlas home">
          <span className="brand-icon">
            <GitBranch size={22} />
          </span>
          <span>
            trace<span className="brand-light">atlas</span>
            <small>EXECUTION INTELLIGENCE</small>
          </span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">TA</span>
          <div>
            Local workspace<small>Self-hosted · v0.1</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {(
            [
              ["executions", Layers3, "Executions"],
              ["replays", Play, "Replay laboratory"],
              ["connect", Terminal, "Connect sources"],
            ] as const
          ).map(([key, Icon, label]) => (
            <button
              key={key}
              className={page === key ? "nav active" : "nav"}
              onClick={() => setPage(key)}
            >
              <Icon size={18} />
              {label}
              {key === "executions" && (
                <span className="count">{items.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-dot" /> Evidence before inference
          <p>
            Inspect what happened.
            <br />
            Test what happens next.
          </p>
          <span className="version">REFERENCE RELEASE / 0.1</span>
        </div>
      </aside>
      <main>
        <header>
          <div className="crumb">
            Workspace <ChevronRight size={13} />{" "}
            <strong>
              {page === "executions"
                ? "Executions"
                : page === "replays"
                  ? "Replay laboratory"
                  : "Connect sources"}
            </strong>
          </div>
          <div className="header-right">
            <span className="local-tag">
              <span className="status-dot" />
              LOCAL
            </span>
            {token && (
              <>
                <span className="role">{role}</span>
                <button
                  className="icon-button"
                  onClick={logout}
                  aria-label="Sign out"
                >
                  <LogOut size={17} />
                </button>
              </>
            )}
          </div>
        </header>
        {!token ? (
          <section className="login">
            <div className="eyebrow">FOLLOW THE EVIDENCE</div>
            <h1>
              Every failure has a story.
              <br />
              <span>Make it reproducible.</span>
            </h1>
            <p>
              Investigate execution timelines, compare outcomes, and replay a
              bounded checkout flow with recorded dependency responses.
            </p>
            <form onSubmit={login}>
              <label htmlFor="credential">Workspace credential</label>
              <input
                id="credential"
                type="password"
                autoComplete="off"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Paste a reader or investigator credential"
                required
              />
              <button className="primary" disabled={busy}>
                {busy ? "Connecting…" : "Connect to workspace"}
                <ArrowRight size={17} />
              </button>
            </form>
            <small>
              <ShieldCheck size={14} /> Credentials stay in memory. Refreshing
              signs you out.
            </small>
            {error && (
              <div role="alert" className="alert">
                {error}
              </div>
            )}
            <div className="login-features">
              <span>
                <GitBranch />
                Follow service calls
              </span>
              <span>
                <ArrowLeftRight />
                Compare executions
              </span>
              <span>
                <Play />
                Replay evidence
              </span>
            </div>
          </section>
        ) : (
          <div className="content">
            {error && (
              <div role="alert" className="alert">
                {error}
                <button onClick={() => setError("")} aria-label="Dismiss error">
                  <X size={16} />
                </button>
              </div>
            )}
            {notice && (
              <div role="status" className="notice">
                {notice}
                <button
                  onClick={() => setNotice("")}
                  aria-label="Dismiss notice"
                >
                  <X size={16} />
                </button>
              </div>
            )}
            {page === "executions" && (
              <>
                <div className="page-heading">
                  <div>
                    <div className="eyebrow">INVESTIGATION WORKSPACE</div>
                    <h1>Executions</h1>
                    <p>From a failed request to the evidence behind it.</p>
                  </div>
                  <div className="actions">
                    <button onClick={() => void load()} disabled={loading}>
                      <RefreshCw size={15} />
                      Refresh
                    </button>
                    {role === "investigator" && (
                      <button
                        className="primary"
                        onClick={() => file.current?.click()}
                        disabled={busy}
                      >
                        <Upload size={15} />
                        Import evidence
                      </button>
                    )}
                    <input
                      ref={file}
                      type="file"
                      accept="application/json,.json"
                      hidden
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void upload(f);
                        e.target.value = "";
                      }}
                    />
                  </div>
                </div>
                <div className="stats">
                  <div>
                    <span>LOADED EXECUTIONS</span>
                    <strong>
                      {items.length}
                      <Layers3 />
                    </strong>
                    <small>Current result window</small>
                  </div>
                  <div>
                    <span>ERROR OUTCOMES</span>
                    <strong className="red">
                      {errors}
                      <Activity />
                    </strong>
                    <small>At least one error span</small>
                  </div>
                  <div>
                    <span>EVIDENCE MODEL</span>
                    <strong>
                      Immutable
                      <Database />
                    </strong>
                    <small>Versioned, tenant-scoped snapshots</small>
                  </div>
                </div>
                <div className="investigation">
                  <section className="execution-list">
                    <form
                      className="search"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void load();
                      }}
                    >
                      <Search size={16} />
                      <input
                        aria-label="Search executions"
                        placeholder="Search executions…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                      <button type="submit" aria-label="Run search">
                        <ArrowRight size={15} />
                      </button>
                    </form>
                    <div className="filters">
                      {[
                        ["", "All executions"],
                        ["error", "Errors"],
                        ["ok", "Successful"],
                      ].map(([v, l]) => (
                        <button
                          key={v}
                          className={filter === v ? "selected" : ""}
                          onClick={() => setFilter(v)}
                        >
                          {l}
                        </button>
                      ))}
                    </div>
                    <div className="list-label">
                      EXECUTION <span>OUTCOME</span>
                    </div>
                    {loading && !items.length ? (
                      <div className="empty">Loading evidence…</div>
                    ) : items.length === 0 ? (
                      <div className="empty">
                        <Box />
                        <h3>No executions yet</h3>
                        <p>
                          Run <code>atlas demo</code> or import a normalized
                          evidence file.
                        </p>
                      </div>
                    ) : (
                      items.map((item) => (
                        <button
                          className={
                            "execution-card " +
                            (selected?.id === item.id ? "chosen" : "")
                          }
                          key={item.id}
                          onClick={() => void open(item.id)}
                        >
                          <div>
                            <span className={"outcome " + item.outcome}>
                              {item.outcome === "error" ? "ERROR" : "OK"}
                            </span>
                            <time>
                              {new Date(item.created_at).toLocaleTimeString(
                                [],
                                { hour: "2-digit", minute: "2-digit" },
                              )}
                            </time>
                          </div>
                          <h3>{item.name}</h3>
                          <code>{item.id.slice(0, 8)}…</code>
                          <footer>
                            <span>
                              <GitBranch size={12} />
                              {item.span_count} spans
                            </span>
                            <span>{item.version}</span>
                          </footer>
                        </button>
                      ))
                    )}
                    {next !== null && (
                      <button
                        className="load-more"
                        onClick={() => void load(next)}
                        disabled={loading}
                      >
                        Load more
                      </button>
                    )}
                  </section>
                  <section className="detail">
                    {!selected ? (
                      <div className="empty selection">
                        <GitBranch size={42} />
                        <h2>Select an execution</h2>
                        <p>
                          Inspect its service path, span timeline, and captured
                          replay fixture.
                        </p>
                      </div>
                    ) : (
                      <>
                        <div className="detail-header">
                          <div>
                            <span
                              className={
                                "outcome " +
                                (selected.spans.some(
                                  (s) => s.status === "error",
                                )
                                  ? "error"
                                  : "ok")
                              }
                            >
                              {selected.spans.some((s) => s.status === "error")
                                ? "ERROR"
                                : "OK"}
                            </span>
                            <h2>{selected.name}</h2>
                            <code>{selected.id}</code>
                          </div>
                          <button
                            onClick={() => void download()}
                            className="icon-button"
                            aria-label="Export evidence"
                          >
                            <Download size={17} />
                          </button>
                        </div>
                        <div className="detail-tabs">
                          {[
                            ["timeline", "Trace timeline"],
                            ["compare", "Compare"],
                            ["replay", "Replay setup"],
                          ].map(([v, l]) => (
                            <button
                              key={v}
                              className={tab === v ? "active" : ""}
                              onClick={() => setTab(v)}
                            >
                              {l}
                            </button>
                          ))}
                        </div>
                        {tab === "timeline" && (
                          <>
                            <div className="service-path">
                              <div className="section-label">
                                OBSERVED SERVICES{" "}
                                <span>{graph?.services.length} services</span>
                              </div>
                              <div className="service-nodes">
                                {graph?.services.map((service, i) => (
                                  <React.Fragment key={service}>
                                    {i > 0 && (
                                      <ArrowRight size={16} className="muted" />
                                    )}
                                    <span
                                      className={
                                        "service-node " +
                                        (selected.spans.some(
                                          (s) =>
                                            s.service === service &&
                                            s.status === "error",
                                        )
                                          ? "has-error"
                                          : "")
                                      }
                                    >
                                      <Box size={15} />
                                      {service}
                                    </span>
                                  </React.Fragment>
                                ))}
                              </div>
                              <small>
                                {graph?.edges.join(" · ") ||
                                  "No cross-service parent edges"}{" "}
                                · Layout is a service inventory; edges come from
                                parent IDs.
                              </small>
                            </div>
                            <div className="timeline">
                              <div className="section-label">
                                SPAN WATERFALL{" "}
                                <span>Relative time · {total} ms</span>
                              </div>
                              {orderedSpans(selected.spans).map((s) => (
                                <button
                                  key={s.id}
                                  className={
                                    "span-row " +
                                    (span?.id === s.id ? "selected-span" : "")
                                  }
                                  onClick={() => setSpan(s)}
                                >
                                  <div
                                    className="span-name"
                                    style={{
                                      paddingLeft:
                                        Math.min(depth(s, selected.spans), 5) *
                                        12,
                                    }}
                                  >
                                    <span className={"dot " + s.status} />
                                    <strong>{s.service}</strong>
                                    <small>{s.operation}</small>
                                  </div>
                                  <div className="track">
                                    <span
                                      className={"bar " + s.status}
                                      style={{
                                        left: (s.start_ms / total) * 100 + "%",
                                        width:
                                          Math.max(
                                            1,
                                            (s.duration_ms / total) * 100,
                                          ) + "%",
                                      }}
                                    />
                                  </div>
                                  <span className="duration">
                                    {s.duration_ms} ms
                                  </span>
                                </button>
                              ))}
                            </div>
                            {span && (
                              <div className="span-inspector">
                                <div className="section-label">
                                  SPAN EVIDENCE <code>{span.id}</code>
                                </div>
                                <dl>
                                  <div>
                                    <dt>Operation</dt>
                                    <dd>{span.operation}</dd>
                                  </div>
                                  <div>
                                    <dt>HTTP status</dt>
                                    <dd
                                      className={
                                        span.status === "error" ? "red" : ""
                                      }
                                    >
                                      {span.http_status ?? "Not captured"}
                                    </dd>
                                  </div>
                                  <div>
                                    <dt>Parent span</dt>
                                    <dd>{span.parent_id || "Root span"}</dd>
                                  </div>
                                  {Object.entries(span.attributes).map(
                                    ([k, v]) => (
                                      <div key={k}>
                                        <dt>{k}</dt>
                                        <dd>{String(v)}</dd>
                                      </div>
                                    ),
                                  )}
                                </dl>
                                <p className="evidence-note">
                                  <ShieldCheck size={14} /> Observed evidence.
                                  This view does not infer root cause.
                                </p>
                              </div>
                            )}
                          </>
                        )}
                        {tab === "compare" && (
                          <div className="panel">
                            <h3>Compare with a baseline</h3>
                            <p>
                              Align spans by service, operation, and occurrence
                              order. Different request paths may not align
                              semantically.
                            </p>
                            <label>
                              Baseline execution
                              <select
                                value={baseline}
                                onChange={(e) => {
                                  setBaseline(e.target.value);
                                  setChanges(null);
                                }}
                              >
                                <option value="">Select an execution</option>
                                {items
                                  .filter((i) => i.id !== selected.id)
                                  .map((i) => (
                                    <option key={i.id} value={i.id}>
                                      {i.name} · {i.id.slice(0, 8)}
                                    </option>
                                  ))}
                              </select>
                            </label>
                            <button
                              className="primary"
                              disabled={!baseline || busy}
                              onClick={() => void compare()}
                            >
                              <ArrowLeftRight size={15} />
                              Compare evidence
                            </button>
                            {changes && (
                              <div className="comparison">
                                {changes.map((c) => (
                                  <div
                                    key={`${c.service}/${c.operation}/${c.occurrence}`}
                                  >
                                    <div>
                                      <strong>{c.service}</strong>
                                      <small>
                                        {c.operation} · occurrence{" "}
                                        {c.occurrence}
                                      </small>
                                      <code>
                                        {c.left_span || "∅"} →{" "}
                                        {c.right_span || "∅"}
                                      </code>
                                    </div>
                                    <span
                                      className={
                                        c.change === "changed" ? "red" : ""
                                      }
                                    >
                                      {c.left_status ?? "—"} →{" "}
                                      {c.right_status ?? "—"}
                                    </span>
                                    <span>
                                      {c.duration_delta_ms === null
                                        ? "—"
                                        : `${c.duration_delta_ms > 0 ? "+" : ""}${c.duration_delta_ms} ms`}
                                    </span>
                                    <span className="pill">{c.change}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                        {tab === "replay" && (
                          <div className="panel">
                            <div className="eyebrow">CHECKOUT-V1 ADAPTER</div>
                            <h3>Turn evidence into an experiment</h3>
                            <p>
                              A fresh subprocess runs the bundled checkout
                              application against local HTTP dependency
                              fixtures. It never contacts the captured services.
                            </p>
                            {selected.fixture ? (
                              <>
                                <div className="fixture">
                                  <span>
                                    Inventory{" "}
                                    <b>{selected.fixture.inventory_status}</b>
                                  </span>
                                  <span>
                                    Payment{" "}
                                    <b>{selected.fixture.payment_status}</b>
                                  </span>
                                  <span>
                                    Captured checkout{" "}
                                    <b>
                                      {
                                        selected.fixture
                                          .captured_checkout_status
                                      }
                                    </b>
                                  </span>
                                </div>
                                <div className="form-grid">
                                  <label>
                                    Payment response override
                                    <select
                                      value={payment}
                                      onChange={(e) =>
                                        setPayment(e.target.value)
                                      }
                                    >
                                      <option value="">
                                        Use captured response
                                      </option>
                                      <option value="200">
                                        200 · accepted
                                      </option>
                                      <option value="503">
                                        503 · unavailable
                                      </option>
                                    </select>
                                  </label>
                                  <label>
                                    Expected checkout status
                                    <select
                                      value={expect}
                                      onChange={(e) =>
                                        setExpect(e.target.value)
                                      }
                                    >
                                      <option value="201">201 · created</option>
                                      <option value="409">
                                        409 · inventory rejected
                                      </option>
                                      <option value="502">
                                        502 · payment failure
                                      </option>
                                    </select>
                                  </label>
                                  <label>
                                    Dependency delay
                                    <select
                                      value={delay}
                                      onChange={(e) => setDelay(e.target.value)}
                                    >
                                      <option value="0">No added delay</option>
                                      <option value="250">
                                        250 ms per request
                                      </option>
                                      <option value="1000">
                                        1,000 ms per request
                                      </option>
                                    </select>
                                  </label>
                                </div>
                                <button
                                  className="primary"
                                  disabled={busy || role !== "investigator"}
                                  onClick={() => void replay()}
                                >
                                  <Play size={15} />
                                  {busy ? "Queuing…" : "Queue replay"}
                                </button>
                                {role !== "investigator" && (
                                  <p>
                                    Investigator permission is required to queue
                                    a replay.
                                  </p>
                                )}
                              </>
                            ) : (
                              <div className="empty">
                                This execution has no supported fixture.
                                Investigation and comparison remain available.
                              </div>
                            )}
                            <p className="evidence-note">
                              This is a bounded reference adapter, not a
                              reconstruction of arbitrary application code.
                            </p>
                          </div>
                        )}
                      </>
                    )}
                  </section>
                </div>
              </>
            )}
            {page === "replays" && (
              <>
                <div className="page-heading">
                  <div>
                    <div className="eyebrow">CONTROLLED EXPERIMENTS</div>
                    <h1>Replay laboratory</h1>
                    <p>
                      Durable jobs. Explicit assertions. Inspectable outcomes.
                    </p>
                  </div>
                  <button onClick={() => void refreshJobs()}>
                    <RefreshCw size={15} />
                    Refresh
                  </button>
                </div>
                <div className="replay-banner">
                  <ShieldCheck />
                  <div>
                    <strong>Local fixtures. No production side effects.</strong>
                    <p>
                      Workers run only the fixed checkout adapter. A completed
                      job can still have a failed assertion.
                    </p>
                  </div>
                </div>
                {jobs.length === 0 ? (
                  <div className="empty">
                    <Play size={32} />
                    <h3>No experiments yet</h3>
                    <p>Select an execution, then open Replay setup.</p>
                    <button onClick={() => setPage("executions")}>
                      Browse executions
                    </button>
                  </div>
                ) : (
                  jobs.map((job) => (
                    <article className="job" key={job.id}>
                      <div className="job-heading">
                        <div>
                          <span
                            className={
                              "outcome " +
                              (job.result?.passed
                                ? "ok"
                                : job.result?.passed === false
                                  ? "error"
                                  : "neutral")
                            }
                          >
                            {job.result?.passed
                              ? "ASSERTION PASSED"
                              : job.result?.passed === false
                                ? "ASSERTION FAILED"
                                : job.status.toUpperCase()}
                          </span>
                          <h3>
                            Checkout replay <code>{job.id.slice(0, 8)}</code>
                          </h3>
                          <small>
                            {new Date(job.created_at).toLocaleString()} ·
                            attempt {job.attempts}
                          </small>
                        </div>
                        <div className="actions">
                          <button
                            onClick={() => {
                              setPage("executions");
                              void open(job.execution_id);
                            }}
                          >
                            View evidence
                            <ArrowRight size={14} />
                          </button>
                          {["queued", "running"].includes(job.status) &&
                            role === "investigator" && (
                              <button
                                onClick={async () => {
                                  try {
                                    await api(`/replays/${job.id}/cancel`, {
                                      method: "POST",
                                    });
                                    await refreshJobs();
                                  } catch (e) {
                                    setError(String(e));
                                  }
                                }}
                              >
                                Cancel
                              </button>
                            )}
                        </div>
                      </div>
                      {job.result && (
                        <>
                          <div className="job-metrics">
                            <span>
                              EXPECTED{" "}
                              <b>{job.result.expected_status ?? "—"}</b>
                            </span>
                            <span>
                              OBSERVED{" "}
                              <b>{job.result.observed_status ?? "—"}</b>
                            </span>
                            <span>
                              DURATION <b>{job.result.elapsed_ms ?? "—"} ms</b>
                            </span>
                            <span>
                              MATCHES CAPTURE{" "}
                              <b>
                                {job.result.matches_capture === undefined
                                  ? "—"
                                  : job.result.matches_capture
                                    ? "Yes"
                                    : "No"}
                              </b>
                            </span>
                          </div>
                          {job.result.calls && (
                            <div className="call-chain">
                              {job.result.calls.map((c, i) => (
                                <span key={i}>
                                  <Box size={14} />
                                  {c.service}
                                  <code>{c.status}</code>
                                </span>
                              ))}
                            </div>
                          )}
                          <p>{job.result.error || job.result.scope}</p>
                        </>
                      )}
                    </article>
                  ))
                )}
              </>
            )}
            {page === "connect" && (
              <>
                <div className="page-heading">
                  <div>
                    <div className="eyebrow">BRING YOUR EVIDENCE</div>
                    <h1>Connect sources</h1>
                    <p>One evidence model, three ways to investigate.</p>
                  </div>
                </div>
                <div className="connect-grid">
                  <article>
                    <Upload />
                    <h2>Normalized JSON</h2>
                    <p>
                      Import a complete execution with parent-linked spans. The
                      API validates graph structure, limits size, and drops
                      non-allowlisted attributes.
                    </p>
                    <code>POST /api/executions</code>
                    <p>
                      Schema version 1 · up to 200 spans · 256 KiB request limit
                    </p>
                  </article>
                  <article>
                    <Terminal />
                    <h2>Command line</h2>
                    <p>
                      Keep credentials in environment variables. Ingest,
                      inspect, compare, and queue an explicit replay assertion.
                    </p>
                    <pre>
                      atlas ingest execution.json{"\n"}atlas list{"\n"}atlas
                      compare LEFT RIGHT
                    </pre>
                  </article>
                  <article>
                    <GitBranch />
                    <h2>MCP tools</h2>
                    <p>
                      Give your assistant read-only investigation tools using a
                      reader credential. Evidence remains untrusted input.
                    </p>
                    <pre>atlas mcp</pre>
                    <p>
                      List executions · Read evidence · Compare · Read replay
                      results
                    </p>
                  </article>
                </div>
                <div className="replay-banner">
                  <Database />
                  <div>
                    <strong>
                      Native OTLP ingestion is not implemented in v0.1.
                    </strong>
                    <p>
                      Export or transform traces to the documented normalized
                      contract. Partial traces with missing parents are
                      rejected.
                    </p>
                  </div>
                </div>
              </>
            )}
            <footer className="page-footer">
              <span>
                <ShieldCheck size={13} />
                Tenant-scoped evidence
              </span>
              <span>Trace Atlas · Open-source reference platform</span>
            </footer>
          </div>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);

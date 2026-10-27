import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowDownLeft, ArrowUp, ArrowUpRight, BarChart3,
  CarFront, ChevronRight, CircleHelp, Clock3, Download, FileImage,
  FileVideo2, Gauge, Info, LoaderCircle, MapPin, Moon, RotateCcw, ShieldCheck, Sun, SlidersHorizontal,
  Sparkles, UploadCloud, Video, X,
} from "lucide-react";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const TrafficChart = lazy(() => import("./TrafficChart.jsx"));
const DIRECTIONS = ["North", "South", "East", "West"];
const COLORS = { North: "oklch(0.85 0.17 88)", South: "oklch(0.62 0.15 255)", East: "oklch(0.66 0.2 28)", West: "oklch(0.68 0.15 150)" };
const ICONS = { North: ArrowUp, South: ArrowDown, East: ArrowUpRight, West: ArrowDownLeft };
const PRESETS = {
  "Balanced traffic": { North: 8, South: 8, East: 8, West: 8 },
  "Heavy North traffic": { North: 32, South: 6, East: 9, West: 7 },
  "Rush hour": { North: 24, South: 20, East: 29, West: 19 },
  "Low night traffic": { North: 2, South: 1, East: 2, West: 1 },
};

async function request(url, options) {
  const response = await fetch(`${API}${url}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "The request could not be completed.");
  return body;
}

function imageUrl(path) {
  return path ? `${API}${path}` : "";
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function downloadReport(report) {
  const lines = [
    `# Adaptive Traffic Signal Plan — ${report.junction_name}`,
    "",
    `- Analysed: ${formatDate(report.analysed_at)}`,
    `- Input: ${report.source}`,
    `- Vehicles counted: ${report.total_vehicle_count}`,
    "",
    "## Direction summary",
    "",
    "| Direction | Vehicles | Recommended green | Status |",
    "|---|---:|---:|---|",
    ...DIRECTIONS.map((direction) =>
      `| ${direction} | ${report.counts[direction]} | ${report.green_times[direction]} sec | ${report.status[direction]} |`,
    ),
    "",
    "## Cycle summary",
    "",
    `- Total green: ${report.cycle.total_green_seconds} sec`,
    `- Yellow: ${report.cycle.yellow_seconds_per_phase} sec per phase`,
    `- All-red clearance: ${report.cycle.all_red_seconds_per_phase} sec per phase`,
    `- Estimated full cycle: ${report.cycle.estimated_full_cycle_seconds} sec`,
    "",
    `## Why this plan?`,
    "",
    report.explanation,
    "",
    `> ${report.safety_note}`,
    "",
    "Prototype decision support only. Never connect this report to a live traffic controller.",
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${report.junction_name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-signal-plan.md`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function DirectionIcon({ direction, size = 18 }) {
  const Icon = ICONS[direction];
  return <Icon size={size} strokeWidth={2.2} />;
}

function Header({ health, theme, onToggleTheme }) {
  const apiAvailable = health?.apiAvailable;
  return (
    <header className="topbar">
      <a className="brand" href="#top" aria-label="Adaptive Traffic Signal System home">
        <img src={theme === "light" ? "/urban-flow-light.png" : "/urban-flow-dark.png"} alt="UrbanFlow — Adaptive Traffic Signal System" />
      </a>
      <nav className="top-nav"><a className="active" href="#dashboard">Dashboard</a><a href="#analysis">Analysis</a><a href="#safety">Safety & limits</a></nav>
      <div className="topbar-actions">
        <button className="theme-toggle" type="button" onClick={onToggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} view`} title={`Switch to ${theme === "dark" ? "light" : "dark"} view`}>
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}<span>{theme === "dark" ? "Light" : "Dark"}</span>
        </button>
        <div className={`local-status ${health?.apiAvailable && !health?.computerVisionReady ? "vision-unavailable" : ""}`}>
          <span className={`status-dot ${!apiAvailable || (health?.apiAvailable && !health?.computerVisionReady) ? "offline" : ""}`} />
          {health === null ? "Checking local API" : !apiAvailable ? "API unavailable" : !health.computerVisionReady ? "Simulation ready · vision setup needed" : !health.modelAvailable ? "Local model needed" : "Local system online"}
        </div>
      </div>
    </header>
  );
}

function DirectionCard({ direction, report }) {
  const count = report?.counts?.[direction] ?? 0;
  const green = report?.green_times?.[direction] ?? 30;
  const status = report?.status?.[direction] ?? "Awaiting data";
  return (
    <article className="direction-card" style={{ "--direction": COLORS[direction] }}>
      <div className="direction-top"><span className="direction-icon"><DirectionIcon direction={direction} /></span><span className={`traffic-status ${status.toLowerCase().replace(" ", "-")}`}>{status}</span></div>
      <div className="direction-name">{direction}</div>
      <div className="direction-metrics"><div><strong>{count}</strong><span>vehicles</span></div><div className="metric-divider" /><div><strong>{green}<small>s</small></strong><span>green time</span></div></div>
      <div className="card-bar"><i style={{ width: `${Math.max(4, (green / 60) * 100)}%` }} /></div>
    </article>
  );
}

function JunctionDiagram({ report }) {
  return (
    <div className="junction">
      <div className="road road-ns" /><div className="road road-ew" />
      <div className="intersection" />
      <div className="lane-mark lane-n" /><div className="lane-mark lane-s" /><div className="lane-mark lane-e" /><div className="lane-mark lane-w" />
      <div className="junction-center"><span className="signal-lights"><i /><i className="lit" /><i /></span><small>JUNCTION</small></div>
      {DIRECTIONS.flatMap((direction) => {
        const count = report?.counts?.[direction];
        const cars = count == null ? 1 : Math.max(1, Math.min(3, Math.ceil(count / 14)));
        return Array.from({ length: cars }, (_, index) => (
          <div
            key={`${direction}-${index}`}
            className={`junction-car car-${direction.toLowerCase()} lane-${index % 2 ? "b" : "a"}`}
            style={{
              "--direction": COLORS[direction],
              animationDelay: `${(index * 2.6 + DIRECTIONS.indexOf(direction) * 1.3).toFixed(1)}s`,
              animationDuration: `${(6.5 + index * 1.7).toFixed(1)}s`,
            }}
          />
        ));
      })}
      {DIRECTIONS.map((direction) => {
        const Icon = ICONS[direction];
        return <div key={direction} className={`junction-label label-${direction.toLowerCase()}`} style={{ "--direction": COLORS[direction] }}><Icon size={15} />{direction}<b>{report?.counts?.[direction] ?? "—"}</b></div>;
      })}
    </div>
  );
}

function Dashboard({ report, setJunctionName }) {
  const [name, setName] = useState(report?.junction_name || "");
  useEffect(() => setName(report?.junction_name || ""), [report?.junction_name]);
  return (
    <>
      <section className="hero" id="dashboard">
        <div className="hero-copy">
          <div className="eyebrow"><span className="eyebrow-line" />LOCAL COMPUTER VISION <span className="eyebrow-tag">PROTOTYPE</span></div>
          <h1>Adaptive Traffic<br /><span>Signal System</span></h1>
          <p className="hero-subtitle">Using local computer vision to recommend smarter signal timings.</p>
          <div className="hero-actions"><a className="button button-primary" href="#analysis"><Sparkles size={16} />Analyse a junction<ChevronRight size={16} /></a><a className="text-link" href="#how-it-works">How it works <ArrowDown size={14} /></a></div>
          <div className="hero-facts"><span><ShieldCheck size={15} />Local processing</span><span><Gauge size={15} />Deterministic timing</span><span><CircleHelp size={15} />Decision support</span></div>
        </div>
        <div className="hero-visual"><div className="visual-glow" /><div className="visual-grid" /><JunctionDiagram report={report} /><div className="visual-caption"><span className="pulse-dot" />LIVE JUNCTION OVERVIEW <span>·</span> QUADRANT ZONES</div></div>
      </section>
      <section className="section-block directions-section">
        <div className="section-heading"><div><div className="eyebrow"><span className="eyebrow-line" />INTERSECTION OVERVIEW</div><h2>Traffic by direction</h2></div><div className="junction-name"><MapPin size={15} /><input aria-label="Junction name" value={name} placeholder="Junction name" onChange={(event) => { setName(event.target.value); setJunctionName(event.target.value); }} /></div></div>
        <div className="direction-grid">{DIRECTIONS.map((direction) => <DirectionCard key={direction} direction={direction} report={report} />)}</div>
        <div className="prototype-note"><Info size={16} /><span>Prototype only — recommendations must be reviewed before real-world use.</span></div>
      </section>
    </>
  );
}

function UploadAnalysis({ onReport, junctionName, greenBudget = 120, onBudgetChange }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => { if (preview.startsWith("blob:")) URL.revokeObjectURL(preview); }, [preview]);
  const acceptFile = (selected) => {
    if (!selected) return;
    const extension = selected.name.toLowerCase().split(".").pop();
    const isImage = ["jpg", "jpeg", "jpe", "png"].includes(extension) || ["image/jpeg", "image/png"].includes(selected.type);
    const isVideo = extension === "mp4" || selected.type === "video/mp4";
    if (!isImage && !isVideo) { setError("Choose a JPG, JPEG, PNG, or MP4 file."); return; }
    if (selected.size > 100 * 1024 * 1024) { setError("File is larger than the 100 MB limit."); return; }
    setError("");
    setFile(selected);
    setPreview(URL.createObjectURL(selected));
  };
  const analyse = async () => {
    if (!file) return;
    setBusy(true); setError("");
    const form = new FormData(); form.append("file", file);
    if (junctionName?.trim()) form.append("junction_name", junctionName.trim());
    form.append("green_budget", greenBudget);
    try {
      const endpoint = file.type.startsWith("video/") || file.name.toLowerCase().endsWith(".mp4") ? "/api/analyse-video" : "/api/analyse-image";
      const report = await request(endpoint, { method: "POST", body: form });
      onReport(report);
    } catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  };
  const reset = () => { setFile(null); setPreview(""); setError(""); if (inputRef.current) inputRef.current.value = ""; };
  return (
    <div className="upload-panel">
      <div className={`dropzone ${preview ? "has-preview" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); acceptFile(event.dataTransfer.files[0]); }}>
        <input ref={inputRef} type="file" accept=".jpg,.jpeg,.jpe,.png,.mp4,image/jpeg,image/png,video/mp4" hidden onChange={(event) => acceptFile(event.target.files[0])} />
        {preview ? <div className="preview-wrap">{file.type.startsWith("video/") || file.name.endsWith(".mp4") ? <video src={preview} controls /> : <img src={preview} alt="Uploaded junction preview" />}<div className="preview-footer"><span>{file.name}</span><button className="icon-button" onClick={reset} aria-label="Remove file"><X size={16} /></button></div></div> :
          <button className="drop-content" onClick={() => inputRef.current?.click()}><span className="upload-icon"><UploadCloud size={23} /></span><strong>Drop a junction image or video here</strong><span>or <u>browse files</u> from your device</span><small><FileImage size={13} /> JPG, JPEG, JPE, PNG <i /> <FileVideo2 size={13} /> MP4 · up to 100 MB</small></button>}
      </div>
      {error && <div className="inline-error"><AlertTriangle size={15} />{error}</div>}
      <CycleTimingControl budget={greenBudget} onChange={onBudgetChange} title="Signal Cycle Green Budget" description="Pre-set green budget before running video/image analysis" />
      <div className="upload-actions"><span className="local-process"><ShieldCheck size={14} />Files stay on this machine</span><button onClick={analyse} className="button button-primary analyse-button" disabled={!file || busy}>{busy ? <><LoaderCircle className="spin" size={16} />Detecting vehicles locally…</> : <><Sparkles size={16} />Analyse traffic</>}</button></div>
    </div>
  );
}

function Simulation({ onReport, junctionName, greenBudget = 120, onBudgetChange }) {
  const [counts, setCounts] = useState({ ...PRESETS["Balanced traffic"] });
  const [selectedPreset, setSelectedPreset] = useState("Balanced traffic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (direction, value) => { setCounts((previous) => ({ ...previous, [direction]: Math.max(0, Math.min(999, Number(value) || 0)) })); setSelectedPreset(""); };
  const simulate = async () => {
    setBusy(true); setError("");
    try { const report = await request("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ junction_name: junctionName || "Demo Junction", counts, green_budget: greenBudget }) }); onReport(report); }
    catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="simulation-panel">
      <div className="simulation-top"><div><span className="sim-icon"><Gauge size={18} /></span><div><strong>Manual count input</strong><small>Try a preset or enter your own counts.</small></div></div><select aria-label="Traffic preset" value={selectedPreset} onChange={(event) => { setSelectedPreset(event.target.value); if (event.target.value) setCounts({ ...PRESETS[event.target.value] }); }}><option value="">Choose a preset</option>{Object.keys(PRESETS).map((name) => <option key={name}>{name}</option>)}</select></div>
      <div className="count-input-grid">{DIRECTIONS.map((direction) => <label key={direction}><span style={{ color: COLORS[direction] }}><DirectionIcon direction={direction} size={15} />{direction}</span><div className="number-input"><button onClick={() => update(direction, counts[direction] - 1)} aria-label={`Decrease ${direction} count`}>−</button><input aria-label={`${direction} vehicle count`} type="number" min="0" max="999" value={counts[direction]} onChange={(event) => update(direction, event.target.value)} /><button onClick={() => update(direction, counts[direction] + 1)} aria-label={`Increase ${direction} count`}>+</button></div></label>)}</div>
      {error && <div className="inline-error"><AlertTriangle size={15} />{error}</div>}
      <CycleTimingControl budget={greenBudget} onChange={onBudgetChange} title="Signal Cycle Green Budget" description="Pre-set green budget before running simulation" />
      <button className="button button-secondary simulate-button" onClick={simulate} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={15} />}{busy ? "Building plan…" : "Use simulated traffic data"}<ChevronRight size={15} /></button>
    </div>
  );
}

function AnalysisSection({ onReport, junctionName, greenBudget = 120, onBudgetChange }) {
  const [mode, setMode] = useState("upload");
  return (
    <section className="section-block analysis-section" id="analysis">
      <div className="section-heading"><div><div className="eyebrow"><span className="eyebrow-line" />LOCAL ANALYSIS</div><h2>Give the junction a look</h2><p className="section-subtitle">Use a local YOLOv8 model to detect vehicles — or explore with sample counts.</p></div><span className="local-badge"><span className="status-dot" />PROCESSING STAYS LOCAL</span></div>
      <div className="analysis-card">
        <div className="mode-tabs" role="tablist" aria-label="Analysis mode"><button className={mode === "upload" ? "selected" : ""} onClick={() => setMode("upload")}><Video size={15} />Image / video</button><button className={mode === "simulate" ? "selected" : ""} onClick={() => setMode("simulate")}><Gauge size={15} />Simulated data</button></div>
        {mode === "upload" ? <UploadAnalysis onReport={onReport} junctionName={junctionName} greenBudget={greenBudget} onBudgetChange={onBudgetChange} /> : <Simulation onReport={onReport} junctionName={junctionName} greenBudget={greenBudget} onBudgetChange={onBudgetChange} />}
      </div>
      <div className="how-it-works" id="how-it-works"><span className="how-icon"><CircleHelp size={17} /></span><div><strong>How the prototype works</strong><p>OpenCV reads your upload; local YOLOv8 detects cars, motorcycles, buses, and trucks. Each bounding-box centre is assigned to one of four image quadrants. A separate deterministic rule distributes your configured green-time budget ({greenBudget}s) fairly.</p></div><span className="how-steps">INPUT <ChevronRight size={12} /> DETECT <ChevronRight size={12} /> RECOMMEND</span></div>
    </section>
  );
}


const CYCLE_PRESETS = [60, 90, 120, 150, 180, 240];

function CycleTimingControl({ budget, onChange, title = "Signal Cycle Green Budget", description = "Adjust green time budget from default 120s" }) {
  const update = (val) => {
    const clamped = Math.max(40, Math.min(600, Math.round(Number(val) || 120)));
    onChange(clamped);
  };
  return (
    <div className="cycle-adjuster">
      <div className="adjuster-header">
        <div className="adjuster-title">
          <SlidersHorizontal size={15} />
          <span>{title}</span>
          <span className="adjuster-desc">({description})</span>
        </div>
        <div className="adjuster-presets">
          {CYCLE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`preset-chip ${budget === preset ? "active" : ""}`}
              onClick={() => update(preset)}
            >
              {preset}s
            </button>
          ))}
        </div>
      </div>
      <div className="adjuster-inputs">
        <div className="adjuster-controls">
          <button type="button" onClick={() => update(budget - 10)} aria-label="Decrease budget">
            −
          </button>
          <input
            type="number"
            min="40"
            max="600"
            step="5"
            value={budget}
            onChange={(e) => update(e.target.value)}
            aria-label="Green budget seconds"
          />
          <button type="button" onClick={() => update(budget + 10)} aria-label="Increase budget">
            +
          </button>
        </div>
        <div className="adjuster-slider-wrap">
          <small>40s</small>
          <input
            type="range"
            min="40"
            max="300"
            step="5"
            value={budget}
            onChange={(e) => update(Number(e.target.value))}
            className="adjuster-slider"
            aria-label="Green budget slider"
          />
          <small>300s</small>
          <span className="adjuster-badge">
            {budget}s green · ~{budget + 20}s total cycle
          </span>
        </div>
      </div>
    </div>
  );
}

function calculateClientGreenTimes(counts, budget = 120) {
  const directions = ["North", "South", "East", "West"];
  const b = Math.max(40, Math.min(600, Math.round(Number(budget) || 120)));
  const minFloor = Math.max(5, Math.floor(b * 0.10));
  const maxCap = Math.min(Math.floor(b * 0.65), b - 3 * minFloor);

  let times = { North: minFloor, South: minFloor, East: minFloor, West: minFloor };
  let remaining = b - minFloor * 4;
  let weights = { ...counts };

  while (remaining > 0) {
    const active = directions.filter((d) => times[d] < maxCap);
    if (active.length === 0) {
      for (const d of directions) {
        if (remaining <= 0) break;
        times[d] += 1;
        remaining -= 1;
      }
      break;
    }
    const activeWeight = active.reduce((s, d) => s + (weights[d] || 0), 0);
    if (activeWeight === 0) {
      for (const d of active) weights[d] = 1;
    }
    const currentWeight = activeWeight === 0 ? active.length : activeWeight;
    const shares = {};
    for (const d of active) {
      shares[d] = (remaining * weights[d]) / currentWeight;
    }
    const capped = active.filter((d) => shares[d] >= maxCap - times[d]);
    if (capped.length > 0) {
      for (const d of capped) {
        const allowance = maxCap - times[d];
        times[d] += allowance;
        remaining -= allowance;
        weights[d] = 0;
      }
      continue;
    }
    const floors = {};
    let floorSum = 0;
    for (const d of active) {
      floors[d] = Math.floor(shares[d]);
      times[d] += floors[d];
      floorSum += floors[d];
    }
    let rem = remaining - floorSum;
    const sorted = [...active].sort((a, b) => {
      const diffA = shares[a] - floors[a];
      const diffB = shares[b] - floors[b];
      if (Math.abs(diffB - diffA) > 1e-6) return diffB - diffA;
      return weights[b] - weights[a];
    });
    for (let i = 0; i < rem; i++) {
      times[sorted[i]] += 1;
    }
    remaining = 0;
  }
  return times;
}

function updateReportBudget(report, budget) {
  const green_times = calculateClientGreenTimes(report.counts, budget);
  const total_green = Object.values(green_times).reduce((a, b) => a + b, 0);
  const yellow = report.cycle?.yellow_seconds_per_phase ?? 3;
  const allRed = report.cycle?.all_red_seconds_per_phase ?? 2;
  const fullCycle = total_green + 4 * (yellow + allRed);
  const busiest = DIRECTIONS.reduce((maxD, d) => (report.counts[d] > (report.counts[maxD] || 0) ? d : maxD), DIRECTIONS[0]);
  const explanation = report.total_vehicle_count === 0
    ? (report.source === "simulated" ? `No vehicles were entered, so each approach received an equal ${green_times.North}-second green time.` : `No vehicles were detected in any direction, so each approach received an equal ${green_times.North}-second green time.`)
    : `${busiest} received ${green_times[busiest]} seconds (${Math.round((green_times[busiest] / total_green) * 100)}% of the ${total_green}s green budget) because it had the highest detected traffic volume (${report.counts[busiest]} vehicles).`;

  return {
    ...report,
    green_times,
    explanation,
    cycle: {
      ...report.cycle,
      total_green_seconds: total_green,
      yellow_seconds_per_phase: yellow,
      all_red_seconds_per_phase: allRed,
      estimated_full_cycle_seconds: fullCycle,
    },
  };
}



function CycleAdjuster({ report, onUpdateReport }) {
  const currentBudget = report?.cycle?.total_green_seconds ?? 120;
  const [budget, setBudget] = useState(currentBudget);
  const [saving, setSaving] = useState(false);
  const timeoutRef = useRef(null);

  useEffect(() => {
    setBudget(report?.cycle?.total_green_seconds ?? 120);
  }, [report?.cycle?.total_green_seconds]);

  const applyBudget = (nextBudget) => {
    const val = Math.max(40, Math.min(600, Number(nextBudget) || 120));
    setBudget(val);
    if (!report) return;

    const updated = updateReportBudget(report, val);
    onUpdateReport(updated);

    if (report.report_id) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(async () => {
        try {
          setSaving(true);
          const serverReport = await request(`/api/reports/${report.report_id}/cycle`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ green_budget: val }),
          });
          onUpdateReport(serverReport);
        } catch (e) {
          console.warn("Could not sync cycle update with server:", e);
        } finally {
          setSaving(false);
        }
      }, 350);
    }
  };

  return (
    <div className="cycle-adjuster">
      <div className="adjuster-header">
        <div className="adjuster-title">
          <SlidersHorizontal size={15} />
          <span>Manual Cycle Timing Budget</span>
          {saving && <small style={{ marginLeft: 6, opacity: 0.6 }}>(Saving…)</small>}
        </div>
        <div className="adjuster-presets">
          {CYCLE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`preset-chip ${budget === preset ? "active" : ""}`}
              onClick={() => applyBudget(preset)}
            >
              {preset}s
            </button>
          ))}
        </div>
      </div>
      <div className="adjuster-inputs">
        <div className="adjuster-controls">
          <button
            type="button"
            onClick={() => applyBudget(budget - 10)}
            aria-label="Decrease green budget"
          >
            −
          </button>
          <input
            type="number"
            min="40"
            max="600"
            step="5"
            value={budget}
            onChange={(e) => applyBudget(e.target.value)}
            aria-label="Green budget seconds"
          />
          <button
            type="button"
            onClick={() => applyBudget(budget + 10)}
            aria-label="Increase green budget"
          >
            +
          </button>
        </div>
        <div className="adjuster-slider-wrap">
          <small>40s</small>
          <input
            type="range"
            min="40"
            max="300"
            step="5"
            value={budget}
            onChange={(e) => applyBudget(Number(e.target.value))}
            className="adjuster-slider"
            aria-label="Green budget slider"
          />
          <small>300s</small>
        </div>
      </div>
    </div>
  );
}

function Results({ report, onUpdateReport }) {
  if (!report) return <section className="section-block results-empty" id="results"><div className="empty-chart"><BarChart3 size={21} /></div><div><h3>Your signal plan will appear here</h3><p>Analyse an upload or run a simulation to generate a direction-by-direction recommendation.</p></div><span className="empty-indicator"><span />AWAITING ANALYSIS</span></section>;
  const data = DIRECTIONS.map((direction) => ({ direction, vehicles: report.counts[direction], green: report.green_times[direction] }));
  return (
    <section className="section-block results-section" id="results">
      <div className="section-heading result-heading"><div><div className="eyebrow"><span className="eyebrow-line" />ANALYSIS REPORT <span className="report-tag">{report.source === "simulated" ? "SIMULATION" : "LOCAL DETECTION"}</span></div><h2>Signal plan <span className="result-junction">{report.junction_name}</span></h2><p className="section-subtitle"><Clock3 size={14} /> Analysed {formatDate(report.analysed_at)}</p></div><button className="button button-outline" onClick={() => downloadReport(report)}><Download size={15} />Download signal plan</button></div>
      <div className="result-grid">
        <div className="result-main">
          <div className="result-card"><div className="result-card-heading"><div><h3>Traffic density & green time</h3><p>Vehicle volume compared with recommended seconds</p></div><div className="chart-legend"><span><i className="legend-vehicles" />Vehicles</span><span><i className="legend-green" />Green seconds</span></div></div>
            <div className="chart-area"><Suspense fallback={<div className="chart-loading"><LoaderCircle className="spin" size={17} />Loading chart…</div>}><TrafficChart data={data} colors={COLORS} /></Suspense></div>
            <div className="result-counts">{DIRECTIONS.map((direction) => <div key={direction}><span style={{ background: COLORS[direction] }} /><b>{direction}</b><strong>{report.counts[direction]}</strong><small>vehicles</small><em>{report.green_times[direction]}s</em></div>)}</div>
          </div>
          <div className="result-card cycle-card"><div className="result-card-heading"><div><h3>Cycle timing summary</h3><p>Assumptions for a demonstration plan</p></div><span className="cycle-total">{report.cycle.estimated_full_cycle_seconds}<small>s total</small></span></div><CycleAdjuster report={report} onUpdateReport={onUpdateReport} /><div className="cycle-stats"><div><span className="cycle-dot green-dot" /><small>Green budget</small><b>{report.cycle.total_green_seconds}<i>sec</i></b></div><div><span className="cycle-dot yellow-dot" /><small>Yellow / phase</small><b>{report.cycle.yellow_seconds_per_phase}<i>sec</i></b></div><div><span className="cycle-dot red-dot" /><small>All-red / phase</small><b>{report.cycle.all_red_seconds_per_phase}<i>sec</i></b></div><div><span className="cycle-dot blue-dot" /><small>Estimated full cycle</small><b>{report.cycle.estimated_full_cycle_seconds}<i>sec</i></b></div></div><p className="cycle-caveat"><Info size={14} />Yellow and all-red intervals are per-phase demo assumptions and are not included in the {report.cycle.total_green_seconds}-second green budget.</p></div>
        </div>
        <aside className="result-side">
          <div className="result-card media-card"><div className="result-card-heading"><div><h3>Detection preview</h3><p>Original input and locally annotated frame</p></div></div>{report.original_url && <div className="media-preview-block"><span className="media-label">ORIGINAL UPLOAD</span>{report.source === "video" ? <video src={imageUrl(report.original_url)} controls /> : <img src={imageUrl(report.original_url)} alt="Original junction upload" />}</div>}{report.annotated_url ? <div className="media-preview-block"><span className="media-label">YOLOV8 DETECTIONS</span><img src={imageUrl(report.annotated_url)} alt="Locally annotated vehicle detections" /></div> : <div className="no-media"><FileImage size={22} /><span>Simulation contains no source image.</span></div>}{report.analysis_note && <p className={`media-note ${report.total_vehicle_count === 0 && report.source !== "simulated" ? "media-note-warning" : ""}`}><Info size={13} />{report.analysis_note}</p>}{report.source !== "simulated" && <div className="detection-footer"><span><CarFront size={14} />{report.total_vehicle_count} vehicles detected</span>{report.detections?.length > 0 && <span>Mean confidence {Math.round(report.detections.reduce((sum, item) => sum + item.confidence, 0) / report.detections.length * 100)}%</span>}</div>}</div>
          <div className="why-card"><span className="why-icon"><Sparkles size={15} /></span><div><small>WHY THIS PLAN?</small><p>{report.explanation}</p></div></div>
        </aside>
      </div>
    </section>
  );
}

function Safety() {
  return <section className="safety-section" id="safety"><div className="safety-head"><span><ShieldCheck size={17} /></span><div><div className="eyebrow">SAFETY & LIMITATIONS</div><h2>Built for demonstrations, not deployment.</h2></div></div><div className="safety-grid"><div><AlertTriangle size={16} /><p>This is a prototype and <strong>does not directly control real traffic lights.</strong></p></div><div><CircleHelp size={16} /><p>Detection can be inaccurate in poor weather, darkness, occlusion, or crowded scenes.</p></div><div><ShieldCheck size={16} /><p>Real deployment needs traffic-engineering approval, pedestrian phases, emergency priority, hardware fail-safes, and extensive testing.</p></div><div><Sparkles size={16} /><p><strong>Future upgrade:</strong> track vehicles across video frames and configure road zones in the interface.</p></div></div><div className="safety-footer"><Info size={14} /><span>15–60 seconds per direction · 120-second total green budget · 3-second yellow + 2-second all-red per phase.</span><span>Validate all timings with traffic authorities.</span></div></section>;
}

export default function App() {
  const [report, setReport] = useState(null);
  const [junctionName, setJunctionName] = useState("");
  const [greenBudget, setGreenBudget] = useState(120);
  const [health, setHealth] = useState(null);
  const [theme, setTheme] = useState("dark");
  useEffect(() => { const saved = localStorage.getItem("urban-flow-theme"); if (saved) setTheme(saved); }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("urban-flow-theme", theme);
  }, [theme]);
  useEffect(() => {
    let active = true;
    const checkHealth = () => {
      request("/api/health")
        .then((status) => {
          if (active) {
            setHealth({
              apiAvailable: true,
              computerVisionReady: status.computer_vision_ready,
              modelAvailable: status.model_available,
              missingDependencies: Array.isArray(status.missing_dependencies) ? status.missing_dependencies : [],
            });
          }
        })
        .catch(() => { if (active) setHealth({ apiAvailable: false }); });
    };
    checkHealth();
    const interval = window.setInterval(checkHealth, 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, []);
  const showReport = (nextReport) => { setReport(nextReport); if (nextReport?.cycle?.total_green_seconds) setGreenBudget(nextReport.cycle.total_green_seconds); setTimeout(() => { const el = document.getElementById("results"); if (el) { el.scrollIntoView({ behavior: "smooth", block: "start" }); } }, 120); };
  return <div id="top" className="app-shell" data-theme={theme}><Header health={health} theme={theme} onToggleTheme={() => setTheme((current) => current === "dark" ? "light" : "dark")} />
    {health?.apiAvailable === false && <div className="setup-notice" role="status"><Info size={17} /><div><strong>Backend is not running</strong><p>Open PowerShell in the project folder and run <code>.\start-local.ps1</code>. This starts the API and website.</p></div><button type="button" onClick={() => window.location.reload()} aria-label="Retry backend connection"><RotateCcw size={15} />Retry</button></div>}
    {health?.apiAvailable && (!health.computerVisionReady || !health.modelAvailable) && <div className="setup-notice setup-notice-warning" role="status"><Info size={17} /><div><strong>{!health.computerVisionReady ? "Image/video analysis needs setup" : "Local YOLO model is missing"}</strong><p>{!health.computerVisionReady ? `Missing packages: ${health.missingDependencies.join(", ") || "OpenCV and Ultralytics"}. Run .\\backend\\setup.ps1, then restart the backend.` : "Download yolov8n.pt into backend\\, then restart the backend. Simulated counts are ready now."}</p></div></div>}
    <main><Dashboard report={report} setJunctionName={setJunctionName} /><AnalysisSection onReport={showReport} junctionName={junctionName} greenBudget={greenBudget} onBudgetChange={(b) => { setGreenBudget(b); if (report) { setReport(updateReportBudget(report, b)); if (report.report_id) { request(`/api/reports/${report.report_id}/cycle`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ green_budget: b }) }).then(setReport).catch(() => {}); } } }} /><Results report={report} onUpdateReport={setReport} /><Safety /></main><footer className="footer"><a className="brand footer-brand" href="#top" aria-label="UrbanFlow home"><img src={theme === "light" ? "/urban-flow-light.png" : "/urban-flow-dark.png"} alt="UrbanFlow" /></a><span>Local computer vision · OpenCV + YOLOv8 · No cloud AI</span><a href="#safety">Safety & limitations <ArrowUp size={13} /></a></footer></div>;
}

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const app = $("#app");
const modalRoot = $("#modal-root");
const toastRoot = $("#toast-root");
const uploadInput = $("#asset-upload-input");

const NAV = [
  ["dashboard", "◫", "Visão geral"],
  ["projects", "▦", "Projetos"],
  ["agent", "✦", "Diretor IA"],
  ["workflow", "⌘", "Workflow nodal"],
  ["jobs", "◷", "Fila e jobs"],
  ["gallery", "▧", "Galeria"],
  ["engines", "◉", "Engines e modelos"],
  ["providers", "☁", "Providers"],
  ["governance", "◎", "Governança"],
  ["settings", "⚙", "Configurações"],
];

const REFERENCE_ROLES = [
  "reference", "character", "style", "composition", "product", "environment",
  "start_frame", "end_frame", "mask", "front", "left", "right", "back", "top", "bottom",
];

const state = {
  route: location.hash.slice(1) || "dashboard",
  loading: true,
  fatalError: null,
  online: false,
  bootstrap: null,
  projects: [],
  currentProject: null,
  graph: { version: 2, nodes: [], edges: [], metadata: {} },
  selectedNodeId: null,
  connectingFrom: null,
  history: [],
  future: [],
  jobs: [],
  assets: [],
  engines: [],
  profiles: {},
  providers: [],
  providerStatus: [],
  providerStatusCheckedAt: null,
  providerDiagnosticResult: null,
  agentResult: null,
  templates: [],
  governance: null,
  settings: null,
  paletteQuery: "",
  dirty: false,
  busy: new Set(),
  eventSource: null,
  timers: [],
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  if (!value) return "0 B";
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index > 1 ? 2 : 1)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "—";
  try { return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)); }
  catch { return value; }
}

function toast(message, type = "info", timeout = 5000) {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.textContent = message;
  toastRoot.append(element);
  setTimeout(() => element.remove(), timeout);
}

async function api(path, options = {}) {
  const config = { ...options, headers: { ...(options.headers || {}) } };
  if (options.body && !(options.body instanceof FormData) && typeof options.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, config);
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = payload?.error?.message || payload?.detail?.message || payload?.detail || payload?.message || `HTTP ${response.status}`;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function setBusy(key, enabled) {
  if (enabled) state.busy.add(key); else state.busy.delete(key);
  renderTopbar();
}

function deepCopy(value) { return JSON.parse(JSON.stringify(value)); }

function pushHistory() {
  state.history.push(deepCopy(state.graph));
  if (state.history.length > 80) state.history.shift();
  state.future = [];
  state.dirty = true;
}

function undo() {
  const previous = state.history.pop();
  if (!previous) return;
  state.future.push(deepCopy(state.graph));
  state.graph = previous;
  state.selectedNodeId = null;
  state.dirty = true;
  renderWorkflow();
}

function redo() {
  const next = state.future.pop();
  if (!next) return;
  state.history.push(deepCopy(state.graph));
  state.graph = next;
  state.selectedNodeId = null;
  state.dirty = true;
  renderWorkflow();
}

function catalogItem(type) { return state.bootstrap?.node_catalog?.find(item => item.type === type); }
function currentNode() { return state.graph.nodes.find(node => node.id === state.selectedNodeId) || null; }

function defaultConfig(item) {
  const config = {};
  for (const field of item.fields || []) config[field.key] = deepCopy(field.default ?? "");
  return config;
}

function newNodeId(type) {
  const stem = type.replaceAll(".", "-");
  let index = 1;
  while (state.graph.nodes.some(node => node.id === `${stem}-${index}`)) index += 1;
  return `${stem}-${index}`;
}

function nodeSummary(node) {
  const config = node.config || {};
  if (node.type === "input.text") return config.text || "Prompt vazio";
  if (node.type === "input.asset") return config.asset_id || "Selecione um asset";
  if (node.type === "input.references") return `${Array.isArray(config.references) ? config.references.length : 0} referências tipadas`;
  if (["llm.enhance", "agent.director", "vision.analyze"].includes(node.type)) return `${config.provider || "local.ollama"} · ${config.model || "modelo padrão"}`;
  if (node.type.endsWith(".generate") || ["image.edit", "video.first_last", "video.reference"].includes(node.type)) return `${config.provider || config.engine || "provider"} · ${config.model || config.profile_id || "modelo configurado"}`;
  if (node.type.includes("upscale")) return `${config.scale || 2}× · ${config.model || "modelo padrão"}`;
  if (node.type.includes("interpolate")) return `${config.target_fps || 60} fps · ${config.engine || "rife"}`;
  if (node.type === "media.export") return `${config.codec || "h265"} · ${config.filename || "filme-final.mp4"}`;
  return catalogItem(node.type)?.description || node.type;
}

async function initialize() {
  try {
    const [bootstrap, projectData, jobsData, assetsData, governance] = await Promise.all([
      api("/api/bootstrap"),
      api("/api/projects"),
      api("/api/jobs?limit=100"),
      api("/api/assets?limit=200"),
      api("/api/governance/snapshot"),
    ]);
    state.bootstrap = bootstrap;
    state.projects = projectData.items;
    state.jobs = jobsData.items;
    state.assets = assetsData.items;
    state.governance = governance;
    state.providers = bootstrap.providers || [];
    state.templates = bootstrap.workflow_templates || [];
    state.online = true;
    const savedProjectId = localStorage.getItem("cinenode.currentProjectId");
    state.currentProject = state.projects.find(project => project.id === savedProjectId) || state.projects[0] || null;
    if (state.currentProject) state.graph = deepCopy(state.currentProject.graph);
    state.loading = false;
    render();
    connectEvents();
    startPolling();
  } catch (error) {
    state.loading = false;
    state.fatalError = error;
    render();
  }
}

function shell(content) {
  const profile = state.bootstrap?.app?.profile || {};
  return `
    <div class="app-shell">
      <header class="topbar" id="topbar">${topbarHtml()}</header>
      <aside class="sidebar">
        <div class="nav-group-title">Produção</div>
        ${NAV.slice(0, 8).map(navButton).join("")}
        <div class="nav-group-title">Administração local</div>
        ${NAV.slice(8).map(navButton).join("")}
        <div class="profile-card"><strong>${escapeHtml(profile.display_name || "Administrador local")}</strong><span>${escapeHtml(profile.role || "super_admin")}</span></div>
      </aside>
      <main class="main" id="main">${content}</main>
    </div>`;
}

function navButton([route, icon, label]) {
  return `<button class="nav-button ${state.route === route ? "active" : ""}" data-route="${route}"><span class="nav-icon">${icon}</span>${escapeHtml(label)}</button>`;
}

function topbarHtml() {
  const busy = state.busy.size > 0;
  return `
    <div class="brand"><img class="brand-mark" src="/brand.svg" alt=""><span class="brand-copy"><strong>Avangard Visual</strong><span>Local creative OS · v${escapeHtml(state.bootstrap?.app?.version || "0.3.0")}</span></span></div>
    ${state.projects.length ? `<select id="top-project-select" class="select project-selector" aria-label="Projeto atual">${state.projects.map(project => `<option value="${project.id}" ${project.id === state.currentProject?.id ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("")}</select>` : ""}
    <div class="topbar-spacer"></div>
    <span class="status-pill"><span class="status-dot ${state.online ? "online" : ""}"></span>${state.online ? "Local ativo" : "Bridge offline"}</span>
    ${state.route === "workflow" ? `<button class="btn" id="save-project" ${!state.currentProject || busy ? "disabled" : ""}>${state.dirty ? "● " : ""}Salvar</button><button class="btn primary" id="run-project" ${!state.currentProject || busy ? "disabled" : ""}>▶ Executar</button>` : ""}
  `;
}

function renderTopbar() {
  const topbar = $("#topbar");
  if (topbar) topbar.innerHTML = topbarHtml();
  bindTopbar();
}

function render() {
  if (state.loading) {
    app.innerHTML = `<div class="empty-state" style="height:100vh"><div><span class="spinner"></span><strong>Inicializando o núcleo local</strong><div>Banco, fila, governança e interface.</div></div></div>`;
    return;
  }
  if (state.fatalError) {
    app.innerHTML = `<div class="empty-state" style="height:100vh"><div><strong>Não foi possível iniciar</strong><div class="error-state mono">${escapeHtml(state.fatalError.message)}</div><br><button class="btn primary" onclick="location.reload()">Tentar novamente</button></div></div>`;
    return;
  }
  let content = "";
  if (state.route === "dashboard") content = dashboardHtml();
  if (state.route === "projects") content = projectsHtml();
  if (state.route === "agent") content = agentHtml();
  if (state.route === "workflow") content = workflowHtml();
  if (state.route === "jobs") content = jobsHtml();
  if (state.route === "gallery") content = galleryHtml();
  if (state.route === "engines") content = enginesHtml();
  if (state.route === "providers") content = providersHtml();
  if (state.route === "governance") content = governanceHtml();
  if (state.route === "settings") content = settingsHtml();
  app.innerHTML = shell(content);
  bindShell();
  bindRoute();
}

function bindShell() {
  $$("[data-route]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.route)));
  bindTopbar();
}

function bindTopbar() {
  $("#top-project-select")?.addEventListener("change", event => selectProject(event.target.value));
  $("#save-project")?.addEventListener("click", saveCurrentProject);
  $("#run-project")?.addEventListener("click", runCurrentProject);
}

function navigate(route) {
  state.route = route;
  location.hash = route;
  render();
}

window.addEventListener("hashchange", () => {
  const route = location.hash.slice(1);
  if (NAV.some(item => item[0] === route)) { state.route = route; render(); }
});

function dashboardHtml() {
  const summary = state.governance?.summary || {};
  const running = state.jobs.filter(job => job.status === "RUNNING").length;
  const failed = state.jobs.filter(job => job.status === "FAILED").length;
  const profileCount = Object.keys(state.profiles || {}).length;
  return `<section class="page studio-home">
    <div class="hero-stage">
      <div class="hero-copy">
        <span class="eyebrow"><i></i> INFERÊNCIA LOCAL · CONTROLE TOTAL</span>
        <h1>Da referência ao<br><em>frame final.</em></h1>
        <p>Dirija imagens, filmes e objetos 3D em um canvas nodal. O agente monta o fluxo; você mantém cada decisão, modelo e arquivo sob controle.</p>
        <div class="hero-actions"><button class="btn primary hero-primary" data-route="agent">✦ Dirigir com IA</button><button class="btn hero-secondary" data-route="workflow">Abrir canvas nodal</button></div>
        <div class="trust-row"><span>LOCAL-FIRST</span><span>24 TIPOS DE NÓ</span><span>4K / 8K PIPELINE</span><span>SEM UPLOAD OBRIGATÓRIO</span></div>
      </div>
      <div class="pipeline-window" aria-label="Fluxo visual de produção">
        <div class="pipeline-top"><span><i></i><i></i><i></i></span><b>SEQUENCE_01.AV</b><small>${state.online ? "MOTOR ONLINE" : "MOTOR OFFLINE"}</small></div>
        <div class="pipeline-canvas">
          <div class="pipeline-glow"></div>
          <article class="mini-node source-node"><span>01 · INPUT</span><strong>Referências</strong><small>personagem · estilo · frame</small><i class="node-port out"></i></article>
          <article class="mini-node director-node"><span>02 · AGENT</span><strong>Diretor IA</strong><small>continuidade + plano</small><i class="node-port in"></i><i class="node-port out"></i></article>
          <article class="mini-node render-node"><span>03 · GENERATE</span><strong>Render local</strong><small>imagem · vídeo · 3D</small><i class="node-port in"></i><i class="node-port out"></i></article>
          <article class="mini-node export-node"><span>04 · DELIVERY</span><strong>Master 4K</strong><small>upscale + export</small><i class="node-port in"></i></article>
          <svg viewBox="0 0 720 330" preserveAspectRatio="none" aria-hidden="true"><path d="M176 96 C235 96 205 176 275 176"/><path d="M427 176 C475 176 450 91 512 91"/><path d="M595 133 C595 210 505 237 455 259"/></svg>
        </div>
        <div class="timeline-strip"><span>00:00</span><div><i style="width:68%"></i><b></b></div><span>00:08</span></div>
      </div>
    </div>
    <div class="creation-grid">
      ${creationCard("01", "Imagem", "Texto, edição e múltiplas referências", "IMAGE", "agent")}
      ${creationCard("02", "Filme", "Start/end frame, takes e continuidade", "FILM", "agent")}
      ${creationCard("03", "Objeto 3D", "Imagem ou vistas frontal/lateral/traseira", "3D", "agent")}
      <button class="creation-card import-card" data-upload-asset><span class="creation-index">＋</span><div><strong>Importar referências</strong><small>Imagem · vídeo · áudio · malha</small></div><span class="creation-arrow">↑</span></button>
    </div>
    <div class="grid cols-4">
      ${metric("Projetos", state.projects.length, "Persistidos em SQLite")}
      ${metric("Jobs ativos", running, `${state.jobs.length} execuções registradas`)}
      ${metric("Assets", state.assets.length, "Galeria local")}
      ${metric("Modelos", profileCount || "A verificar", profileCount ? "Perfis registrados" : "Abra Engines e modelos")}
    </div>
    <div class="grid cols-2" style="margin-top:14px">
      <article class="card"><div class="card-header"><h2>Execuções recentes</h2><button class="btn small" data-route="jobs">Ver fila</button></div><div class="card-body">${recentJobsHtml()}</div></article>
      <article class="card"><div class="card-header"><h2>Estado estrutural</h2><span class="badge ${state.governance?.state}">${escapeHtml(state.governance?.state || "EMPTY")}</span></div><div class="card-body">
        <div class="module-row"><strong>Banco e migrations</strong><span class="muted">SQLite WAL</span><span class="badge DONE">OK</span></div>
        <div class="module-row"><strong>Fila GPU</strong><span class="muted">1 job por vez</span><span class="badge ${running ? "RUNNING" : "DONE"}">${running ? "ATIVA" : "PRONTA"}</span></div>
        <div class="module-row"><strong>Falhas abertas</strong><span class="muted">Jobs + alertas</span><span class="badge ${failed ? "FAILED" : "DONE"}">${failed}</span></div>
        <div class="module-row"><strong>Modelos locais</strong><span class="muted">Validar arquivos</span><button class="btn small" data-route="engines">Verificar</button></div>
      </div></article>
    </div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Roadmap e alertas reais</h2><div class="actions"><span class="badge ${state.governance?.state}">${Number(summary.progressPercent || 0).toFixed(0)}%</span><button class="btn small" data-route="governance">Abrir governança</button></div></div><div class="card-body">${alertsCompactHtml()}</div></article>
  </section>`;
}

function creationCard(index, title, description, tag, route) {
  return `<button class="creation-card" data-route="${route}"><span class="creation-index">${index}</span><div><strong>${title}</strong><small>${description}</small></div><span class="creation-tag">${tag}</span><span class="creation-arrow">↗</span></button>`;
}

function metric(label, value, detail) { return `<article class="card metric"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div><div class="metric-detail">${escapeHtml(detail)}</div></article>`; }

function recentJobsHtml() {
  if (!state.jobs.length) return `<div class="empty-state"><div><strong>Nenhuma execução</strong>Crie um workflow e execute.</div></div>`;
  return state.jobs.slice(0, 6).map(job => `<div class="module-row"><span><strong class="mono">${escapeHtml(job.id.slice(-10))}</strong><br><small class="muted">${formatDate(job.created_at)}</small></span><div><div class="progress"><span style="width:${Number(job.progress || 0)}%"></span></div></div><span class="badge ${job.status}">${job.status}</span></div>`).join("");
}

function alertsCompactHtml() {
  const alerts = (state.governance?.alerts || []).filter(item => item.status === "OPEN").slice(0, 4);
  if (!alerts.length) return `<span class="badge DONE">Sem alertas abertos</span>`;
  return alerts.map(alert => `<div class="alert ${alert.severity}"><h4>${escapeHtml(alert.id)} · ${escapeHtml(alert.severity)} · ${escapeHtml(alert.kind)}</h4><p>${escapeHtml(alert.fact)}</p><p><strong>Ação:</strong> ${escapeHtml(alert.action)}</p></div>`).join("");
}

function projectsHtml() {
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Projetos</h1><p class="page-subtitle">Cada projeto preserva o grafo, histórico de jobs e assets.</p></div><button class="btn primary" data-action="new-project">＋ Novo projeto</button></div>
  <article class="card"><div class="table-wrap"><table><thead><tr><th>Projeto</th><th>Nós</th><th>Atualização</th><th></th></tr></thead><tbody>
    ${state.projects.length ? state.projects.map(project => `<tr><td><strong>${escapeHtml(project.name)}</strong><br><small class="muted">${escapeHtml(project.description || "Sem descrição")}</small></td><td>${project.graph?.nodes?.length || 0}</td><td>${formatDate(project.updated_at)}</td><td><div class="actions"><button class="btn small" data-open-project="${project.id}">Abrir</button><button class="btn small danger" data-delete-project="${project.id}">Excluir</button></div></td></tr>`).join("") : `<tr><td colspan="4"><div class="empty-state"><div><strong>Nenhum projeto</strong>Crie o primeiro projeto para iniciar.</div></div></td></tr>`}
  </tbody></table></div></article></section>`;
}


function assetThumb(asset) {
  if (asset.mime_type?.startsWith("image/")) return `<img src="/media/${asset.id}" alt="${escapeHtml(asset.original_name || asset.id)}" loading="lazy">`;
  if (asset.mime_type?.startsWith("video/")) return `<video src="/media/${asset.id}" muted preload="metadata"></video>`;
  if (asset.kind === "mesh") return `<div class="asset-glyph">3D</div>`;
  return `<div class="asset-glyph">${escapeHtml((asset.kind || "file").toUpperCase())}</div>`;
}

function providerSelectOptions(selected = "auto") {
  const items = [`<option value="auto" ${selected === "auto" ? "selected" : ""}>Automático · local primeiro</option>`];
  for (const provider of state.providers) {
    items.push(`<option value="${escapeHtml(provider.id)}" ${selected === provider.id ? "selected" : ""}>${escapeHtml(provider.label)} · ${escapeHtml(provider.scope)}</option>`);
  }
  return items.join("");
}

function agentHtml() {
  const result = state.agentResult;
  return `<section class="page agent-page">
    <div class="page-header"><div><h1 class="page-title">Diretor IA de produção</h1><p class="page-subtitle">Descreva o resultado, selecione qualquer quantidade de referências e o agente cria um DAG executável com análise visual, continuidade, geração, pós e exportação.</p></div><div class="actions"><button class="btn" data-upload-asset>↑ Importar referências</button><button class="btn" data-route="providers">Configurar providers</button></div></div>
    <form id="agent-form" class="agent-layout">
      <article class="card"><div class="card-header"><h2>1 · Brief e entrega</h2><span class="badge READY">DAG VALIDADO</span></div><div class="card-body agent-form-grid">
        <label class="field full"><span class="field-label">O que deve ser criado</span><textarea class="textarea agent-brief" name="brief" required maxlength="12000" placeholder="Ex.: filme cinematográfico de 15 s preservando exatamente a personagem, roupa, arquitetura e luz das referências; começar no primeiro frame e terminar no último…"></textarea></label>
        <label class="field"><span class="field-label">Resultado</span><select class="select" name="target"><option value="image">Imagem</option><option value="video">Vídeo</option><option value="film" selected>Filme / sequência de takes</option><option value="3d">Modelo 3D</option></select></label>
        <label class="field"><span class="field-label">Provider</span><select class="select" name="provider">${providerSelectOptions("auto")}</select></label>
        <label class="field"><span class="field-label">Modelo/endpoint opcional</span><input class="input" name="model" placeholder="owner/model, fal-ai/..., Kling, Tripo…"></label>
        <label class="field"><span class="field-label">Proporção</span><select class="select" name="aspect_ratio"><option>1:1</option><option>4:3</option><option>3:2</option><option selected>16:9</option><option>9:16</option><option>21:9</option></select></label>
        <label class="field"><span class="field-label">Duração total</span><input class="input" type="number" name="duration_seconds" value="8" min="1" max="600"></label>
        <label class="field"><span class="field-label">Entrega</span><select class="select" name="output_resolution"><option value="preview">Preview</option><option value="1080p">1080p</option><option value="4k" selected>4K</option><option value="8k">8K</option></select></label>
        <label class="field"><span class="field-label">Nome do projeto</span><input class="input" name="project_name" maxlength="160" placeholder="Produção criada pelo agente"></label>
        <label class="field"><span class="field-label">Planejador do DAG</span><select class="select" name="planner_mode"><option value="auto" selected>Auto · tenta Ollama e registra fallback</option><option value="llm">Exigir Ollama · falhar se indisponível</option><option value="rules">Regras determinísticas</option></select></label>
        <label class="field"><span class="field-label">Modelo do agente opcional</span><input class="input" name="agent_model" placeholder="qwen3:8b-q4_K_M"></label>
        <label class="check-field"><input type="checkbox" name="local_first" checked><span><strong>Priorizar local</strong><small>Cloud somente quando escolhido ou quando não houver capacidade local.</small></span></label>
        <label class="check-field"><input type="checkbox" name="use_llm" checked><span><strong>Direção por LLM/VLM</strong><small>Ollama local analisa e compõe a direção durante a execução.</small></span></label>
      </div></article>
      <article class="card"><div class="card-header"><h2>2 · Referências com função</h2><span class="muted">até 32</span></div><div class="card-body">
        <p class="muted">Marque os arquivos e informe a função. Para vídeo entre dois quadros, use exatamente <span class="mono">start_frame</span> e <span class="mono">end_frame</span>. Para 3D multiview, use front/left/right/back/top/bottom.</p>
        ${state.assets.length ? `<div class="reference-picker">${state.assets.map(asset => `<article class="reference-card"><label class="reference-check"><input type="checkbox" data-agent-reference="${asset.id}"><span class="reference-thumb">${assetThumb(asset)}</span><span class="reference-name">${escapeHtml(asset.original_name || asset.id)}</span></label><select class="select small-select" data-agent-role="${asset.id}">${REFERENCE_ROLES.map(role => `<option value="${role}">${role}</option>`).join("")}</select><input class="input" type="number" data-agent-weight="${asset.id}" value="1" min="0" max="2" step="0.1" aria-label="Peso"><input class="input" data-agent-note="${asset.id}" maxlength="500" placeholder="Observação opcional"></article>`).join("")}</div>` : `<div class="empty-state"><div><strong>Sem referências</strong><p>Importe imagens ou vídeos. Texto puro também funciona quando o provider escolhido suporta.</p><button type="button" class="btn primary" data-upload-asset>Importar arquivos</button></div></div>`}
      </div><div class="card-footer"><button class="btn primary agent-submit" type="submit">✦ Criar workflow executável</button></div></article>
    </form>
    ${result ? `<article class="card" style="margin-top:14px"><div class="card-header"><h2>Último plano criado</h2><span class="badge ${result.validation?.valid ? "DONE" : "FAILED"}">${result.validation?.valid ? "VÁLIDO" : "INVÁLIDO"}</span></div><div class="card-body"><div class="grid cols-4">${metric("Nós", result.graph?.nodes?.length || 0, "DAG persistido")}${metric("Conexões", result.graph?.edges?.length || 0, "Portas tipadas")}${metric("Provider", result.decisions?.provider || "—", result.decisions?.model || "modelo automático")}${metric("Referências", result.decisions?.reference_roles?.length || 0, (result.decisions?.reference_roles || []).join(", ") || "texto puro")}</div><div class="decision-list">${(result.explanation || []).map(item => `<div>• ${escapeHtml(item)}</div>`).join("")}</div></div></article>` : ""}
  </section>`;
}

function providersHtml() {
  const statuses = new Map(state.providerStatus.map(item => [item.id, item]));
  const diagnostic = state.providerDiagnosticResult;
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Providers locais e cloud</h1><p class="page-subtitle">Um contrato único para imagem, edição, vídeo, start/end frame, multirreferência, LLM/VLM e 3D. Chaves ficam em variáveis de ambiente; nenhuma chave é exibida.</p></div><div class="actions"><button class="btn primary" data-action="refresh-providers">Verificar todos</button><button class="btn" data-route="settings">Editar configuração</button></div></div>
    <div class="provider-grid">${state.providers.map(provider => {
      const status = statuses.get(provider.id);
      const available = status?.available ?? false;
      const checked = Boolean(status);
      return `<article class="card provider-card"><div class="card-header"><h2>${escapeHtml(provider.label)}</h2><span class="badge ${checked ? (available ? "DONE" : "FAILED") : "PENDING"}">${checked ? (available ? "PRONTO" : "INDISPONÍVEL") : "NÃO VERIFICADO"}</span></div><div class="card-body"><div class="mono provider-id">${escapeHtml(provider.id)}</div><div class="provider-meta"><span>${escapeHtml(provider.scope)}</span><span>${provider.enabled === false ? "desativado" : "ativado"}</span><span>${provider.configured === false ? "não configurado" : "configurado"}</span></div><div class="capability-list">${(provider.capabilities || []).map(cap => `<span class="badge">${escapeHtml(cap)}</span>`).join("")}</div>${provider.api_key_env ? `<div class="field-help">Chave: <span class="mono">${escapeHtml(provider.api_key_env)}</span></div>` : ""}${provider.models?.length ? `<div class="field-help">Modelos: ${provider.models.map(escapeHtml).join(", ")}</div>` : ""}<p class="muted">${escapeHtml(status?.detail || provider.notes || "")}</p></div></article>`;
    }).join("")}</div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Diagnóstico com chamada real</h2><span class="muted">não é apenas teste de chave</span></div><form id="provider-diagnostic-form" class="card-body agent-form-grid">
      <label class="field"><span class="field-label">Provider</span><select class="select" name="provider_id">${state.providers.map(provider => `<option value="${provider.id}">${escapeHtml(provider.label)} · ${escapeHtml(provider.id)}</option>`).join("")}</select></label>
      <label class="field"><span class="field-label">Operação</span><select class="select" name="operation"><option value="enhance_prompt">Aprimorar prompt</option><option value="vision">Analisar referência</option><option value="image">Gerar imagem</option><option value="image_edit">Editar imagem</option><option value="video">Gerar vídeo</option><option value="mesh">Gerar 3D</option></select></label>
      <label class="field full"><span class="field-label">Prompt/instrução</span><textarea class="textarea" name="prompt" placeholder="Prompt usado na chamada real"></textarea></label>
      <label class="field"><span class="field-label">Modelo</span><input class="input" name="model" placeholder="modelo ou owner/model"></label>
      <label class="field"><span class="field-label">Endpoint override</span><input class="input" name="endpoint" placeholder="opcional"></label>
      <label class="field full"><span class="field-label">Parâmetros avançados JSON</span><textarea class="textarea mono" name="parameters">{}</textarea></label>
      <div class="field full"><span class="field-label">Referências da chamada</span><div class="diagnostic-assets">${state.assets.map(asset => `<label><input type="checkbox" data-provider-reference="${asset.id}"> ${escapeHtml(asset.original_name || asset.id)} <select class="select inline-select" data-provider-role="${asset.id}">${REFERENCE_ROLES.map(role => `<option>${role}</option>`).join("")}</select></label>`).join("") || `<span class="muted">Nenhum asset importado.</span>`}</div></div>
      <div class="full actions"><button class="btn primary" type="submit">Executar chamada real</button></div>
    </form>${diagnostic ? `<div class="card-body"><pre class="diagnostic-result">${escapeHtml(JSON.stringify(diagnostic, null, 2))}</pre></div>` : ""}</article>
  </section>`;
}

function workflowHtml() {
  if (!state.currentProject) return `<section class="page"><div class="empty-state"><div><strong>Nenhum projeto selecionado</strong><p>Crie um projeto antes de montar o workflow.</p><button class="btn primary" data-action="new-project">Criar projeto</button></div></div></section>`;
  const groups = {};
  for (const item of state.bootstrap.node_catalog) {
    if (state.paletteQuery && !`${item.label} ${item.type} ${item.description}`.toLowerCase().includes(state.paletteQuery.toLowerCase())) continue;
    (groups[item.category] ||= []).push(item);
  }
  return `<section class="workflow-page">
    <div class="workflow-toolbar">
      <button class="btn small" data-workflow="undo" ${!state.history.length ? "disabled" : ""}>↶ Undo</button>
      <button class="btn small" data-workflow="redo" ${!state.future.length ? "disabled" : ""}>↷ Redo</button>
      <button class="btn small" data-workflow="validate">✓ Validar</button>
      <button class="btn small" data-workflow="preflight">◉ Pré-voo real</button>
      <button class="btn small" data-workflow="fit">⌖ Centralizar</button>
      <span class="muted">${state.graph.nodes.length} nós · ${state.graph.edges.length} conexões</span>
      <span class="spacer"></span><span class="muted"><span class="kbd">Del</span> excluir · <span class="kbd">Ctrl S</span> salvar</span>
    </div>
    <aside class="node-palette"><input class="input palette-search" id="palette-search" placeholder="Buscar nó…" value="${escapeHtml(state.paletteQuery)}">${Object.entries(groups).map(([category, items]) => `<div class="palette-group"><h3>${escapeHtml(category)}</h3>${items.map(item => `<button class="palette-node" data-add-node="${item.type}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.description)}</span></button>`).join("")}</div>`).join("")}</aside>
    <div class="canvas-wrap" id="canvas-wrap"><div class="node-canvas" id="node-canvas"><svg class="edge-layer" id="edge-layer"></svg>${state.graph.nodes.map(nodeHtml).join("")}</div>${state.connectingFrom ? `<div class="connection-banner">Conectando <strong>${escapeHtml(state.connectingFrom.nodeId)}.${escapeHtml(state.connectingFrom.handleId)}</strong> (${escapeHtml(state.connectingFrom.type)}) · clique numa entrada ou Esc</div>` : ""}</div>
    ${inspectorHtml()}
  </section>`;
}

function nodeHtml(node) {
  const item = catalogItem(node.type) || { label: node.type, inputs: [], outputs: [] };
  const inputs = item.inputs || [];
  const outputs = item.outputs || [];
  const rows = Math.max(1, inputs.length, outputs.length);
  const minHeight = 78 + rows * 26;
  const connecting = state.connectingFrom;
  const portTop = index => 62 + index * 26;
  return `<article class="workflow-node ${state.selectedNodeId === node.id ? "selected" : ""}" data-node-id="${node.id}" style="left:${Number(node.position?.x || 0)}px;top:${Number(node.position?.y || 0)}px;min-height:${minHeight}px">
    <div class="node-head" data-drag-handle="${node.id}"><span class="node-type-dot"></span><span class="node-title">${escapeHtml(item.label)}</span><span class="node-id">${escapeHtml(node.id)}</span></div>
    <div class="node-body"><div class="node-summary">${escapeHtml(nodeSummary(node))}</div></div>
    ${inputs.map((port, index) => `<button class="port input port-type-${escapeHtml(port.type)}" style="top:${portTop(index)}px" data-port-input-node="${node.id}" data-port-input-handle="${escapeHtml(port.id)}" title="Entrada ${escapeHtml(port.label)} · ${escapeHtml(port.type)}${port.required ? " · obrigatória" : ""}" aria-label="Conectar entrada ${escapeHtml(port.label)}"></button><span class="port-label input-label" style="top:${portTop(index) - 6}px">${escapeHtml(port.label)}${port.multiple ? " ×N" : ""}</span>`).join("")}
    ${outputs.map((port, index) => `<button class="port output port-type-${escapeHtml(port.type)} ${connecting?.nodeId === node.id && connecting?.handleId === port.id ? "pending" : ""}" style="top:${portTop(index)}px" data-port-output-node="${node.id}" data-port-output-handle="${escapeHtml(port.id)}" data-port-output-type="${escapeHtml(port.type)}" title="Saída ${escapeHtml(port.label)} · ${escapeHtml(port.type)}" aria-label="Iniciar conexão da saída ${escapeHtml(port.label)}"></button><span class="port-label output-label" style="top:${portTop(index) - 6}px">${escapeHtml(port.label)}</span>`).join("")}
  </article>`;
}

function inspectorHtml() {
  const node = currentNode();
  if (!node) return `<aside class="inspector"><div class="inspector-head"><strong>Inspector</strong></div><div class="inspector-empty">Selecione um nó para editar parâmetros. Toda alteração é real e será persistida ao salvar.</div></aside>`;
  const item = catalogItem(node.type) || { label: node.type, fields: [] };
  return `<aside class="inspector"><div class="inspector-head"><strong>${escapeHtml(item.label)}</strong><div class="mono subtle">${escapeHtml(node.type)}</div></div><div class="inspector-body">
    <label class="field"><span class="field-label">ID do nó</span><input class="input mono" value="${escapeHtml(node.id)}" data-node-id-field></label>
    ${(item.fields || []).map(field => fieldHtml(field, node.config?.[field.key])).join("")}
    <button class="btn danger" data-delete-selected>Excluir nó</button>
  </div></aside>`;
}

function fieldHtml(field, value) {
  const key = escapeHtml(field.key);
  const label = escapeHtml(field.label);
  const common = `data-node-field="${key}"`;
  if (field.type === "textarea") return `<label class="field"><span class="field-label">${label}</span><textarea class="textarea" ${common}>${escapeHtml(value ?? "")}</textarea></label>`;
  if (field.type === "json") return `<label class="field"><span class="field-label">${label}</span><textarea class="textarea mono" ${common} data-json-field>${escapeHtml(JSON.stringify(value ?? {}, null, 2))}</textarea><span class="field-help">JSON validado ao sair do campo.</span></label>`;
  if (field.type === "select") return `<label class="field"><span class="field-label">${label}</span><select class="select" ${common}>${(field.options || []).map(option => `<option value="${escapeHtml(option)}" ${String(option) === String(value) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select></label>`;
  if (field.type === "checkbox") return `<label class="check-field inspector-check"><input type="checkbox" ${common} ${value ? "checked" : ""}><span><strong>${label}</strong></span></label>`;
  if (field.type === "asset") return `<label class="field"><span class="field-label">${label}</span><select class="select" ${common}><option value="">Selecione…</option>${state.assets.map(asset => `<option value="${asset.id}" ${asset.id === value ? "selected" : ""}>${escapeHtml(asset.original_name || asset.id)}</option>`).join("")}</select><button class="btn small" type="button" data-upload-asset>Importar asset</button></label>`;
  if (field.type === "references") return referencesFieldHtml(field, value);
  if (field.type === "model_profile") {
    const profiles = Object.entries(state.profiles).filter(([, profile]) => !field.kind || profile.kind === field.kind);
    return `<label class="field"><span class="field-label">${label}</span><select class="select" ${common}>${profiles.map(([id, profile]) => `<option value="${id}" ${id === value ? "selected" : ""}>${escapeHtml(profile.label || id)}${profile.ready === false ? " · ausente" : ""}</option>`).join("")}</select></label>`;
  }
  const type = field.type === "number" ? "number" : "text";
  return `<label class="field"><span class="field-label">${label}</span><input class="input" type="${type}" value="${escapeHtml(value ?? "")}" ${field.min != null ? `min="${field.min}"` : ""} ${field.max != null ? `max="${field.max}"` : ""} ${field.step != null ? `step="${field.step}"` : ""} ${common}></label>`;
}

function referencesFieldHtml(field, value) {
  const items = Array.isArray(value) ? value : [];
  const roles = field.roles || REFERENCE_ROLES;
  const selected = new Set(items.map(item => item.asset_id));
  const available = state.assets.filter(asset => !selected.has(asset.id));
  return `<div class="field reference-editor" data-reference-editor="${escapeHtml(field.key)}"><span class="field-label">${escapeHtml(field.label)}</span>
    <div class="reference-editor-list">${items.map((item, index) => {
      const asset = state.assets.find(candidate => candidate.id === item.asset_id);
      return `<div class="reference-editor-row"><span class="reference-editor-name">${escapeHtml(asset?.original_name || item.asset_id)}</span><select class="select" data-reference-prop="role" data-reference-index="${index}">${roles.map(role => `<option value="${role}" ${role === item.role ? "selected" : ""}>${role}</option>`).join("")}</select><input class="input" type="number" min="0" max="2" step="0.1" value="${Number(item.weight ?? 1)}" data-reference-prop="weight" data-reference-index="${index}"><button class="btn small danger" type="button" data-remove-reference="${index}">×</button></div>`;
    }).join("") || `<span class="field-help">Nenhuma referência selecionada.</span>`}</div>
    <div class="reference-editor-add"><select class="select" data-reference-add-asset><option value="">Adicionar asset…</option>${available.map(asset => `<option value="${asset.id}">${escapeHtml(asset.original_name || asset.id)}</option>`).join("")}</select><select class="select" data-reference-add-role>${roles.map(role => `<option value="${role}">${role}</option>`).join("")}</select><button class="btn small" type="button" data-add-reference>Adicionar</button></div><button class="btn small" type="button" data-upload-asset>Importar arquivo</button>
  </div>`;
}

function jobsHtml() {
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Fila e jobs</h1><p class="page-subtitle">Fila GPU sequencial, cancelamento, retry, progresso e causa real das falhas.</p></div><button class="btn" data-action="refresh-jobs">↻ Atualizar</button></div>
  <article class="card"><div class="table-wrap"><table><thead><tr><th>ID / projeto</th><th>Status</th><th>Progresso</th><th>Início / fim</th><th>Resultado</th><th></th></tr></thead><tbody>${state.jobs.length ? state.jobs.map(job => `<tr><td><strong class="mono">${escapeHtml(job.id)}</strong><br><small class="muted">${escapeHtml(job.project_id || "workflow avulso")}</small></td><td><span class="badge ${job.status}">${job.status}</span>${job.current_node_id ? `<br><small class="muted mono">${escapeHtml(job.current_node_id)}</small>` : ""}</td><td style="min-width:170px"><div class="progress"><span style="width:${Number(job.progress || 0)}%"></span></div><small>${Number(job.progress || 0).toFixed(1)}%</small></td><td><small>${formatDate(job.started_at)}<br>${formatDate(job.finished_at)}</small></td><td>${job.error_message ? `<div class="error-state"><strong>${escapeHtml(job.error_code)}</strong><br>${escapeHtml(job.error_message)}</div>` : job.result ? `${job.result.assets?.length || 0} assets` : "—"}</td><td><div class="actions">${["QUEUED","RUNNING"].includes(job.status) ? `<button class="btn small danger" data-cancel-job="${job.id}">Cancelar</button>` : ""}${["FAILED","CANCELLED"].includes(job.status) ? `<button class="btn small" data-retry-job="${job.id}">Retry</button>` : ""}</div></td></tr>`).join("") : `<tr><td colspan="6"><div class="empty-state"><div><strong>Fila vazia</strong>Nenhum job foi criado.</div></div></td></tr>`}</tbody></table></div></article></section>`;
}

function galleryHtml() {
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Galeria local</h1><p class="page-subtitle">Arquivos produzidos e importados, com checksum e vínculo ao job.</p></div><div class="actions"><button class="btn" data-upload-asset>↑ Importar</button><button class="btn" data-action="refresh-assets">↻ Atualizar</button></div></div>
  ${state.assets.length ? `<div class="gallery">${state.assets.map(asset => `<article class="card asset-card"><div class="asset-preview">${asset.mime_type?.startsWith("image/") ? `<img src="/media/${asset.id}" alt="${escapeHtml(asset.original_name || asset.id)}" loading="lazy">` : asset.mime_type?.startsWith("video/") ? `<video src="/media/${asset.id}" controls preload="metadata"></video>` : `<span class="mono muted">${escapeHtml(asset.kind)}</span>`}</div><div class="asset-meta"><div class="asset-name"><strong>${escapeHtml(asset.original_name || asset.id)}</strong></div><small class="muted">${formatBytes(asset.size_bytes)} · ${formatDate(asset.created_at)}</small><br><small class="mono subtle">${escapeHtml(asset.metadata?.sha256?.slice(0, 16) || "sem hash")}</small><div class="actions" style="margin-top:8px"><a class="btn small" href="/media/${asset.id}" target="_blank" rel="noopener">Abrir</a><button class="btn small" data-copy="${escapeHtml(asset.id)}">Copiar ID</button></div></div></article>`).join("")}</div>` : `<div class="empty-state"><div><strong>Galeria vazia</strong><p>Execute um workflow ou importe um arquivo.</p><button class="btn primary" data-upload-asset>Importar asset</button></div></div>`}
  </section>`;
}

function enginesHtml() {
  const statuses = state.engines;
  const profileEntries = Object.entries(state.profiles);
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Engines e modelos</h1><p class="page-subtitle">Detecção local real. Ausências não são convertidas em saídas simuladas.</p></div><button class="btn primary" data-action="check-engines">Verificar agora</button></div>
  <div class="grid cols-3">${statuses.length ? statuses.map(item => `<article class="card metric"><div class="metric-label">${escapeHtml(item.engine_id)}</div><div class="metric-value" style="font-size:18px"><span class="badge ${item.available ? "DONE" : "FAILED"}">${item.available ? "DISPONÍVEL" : "AUSENTE"}</span></div><div class="metric-detail mono">${escapeHtml(item.version || item.detail || "")}</div><div class="metric-detail">${escapeHtml(item.detail || "")}</div></article>`).join("") : `<article class="card metric"><div class="loading"><span class="spinner"></span>Execute a verificação.</div></article>`}</div>
  <article class="card" style="margin-top:14px"><div class="card-header"><h2>Perfis de inferência</h2><span class="muted">RTX 4090 Laptop · 16 GB</span></div><div class="table-wrap"><table><thead><tr><th>Perfil</th><th>Tipo / engine</th><th>Base</th><th>Arquivos</th></tr></thead><tbody>${profileEntries.map(([id, profile]) => `<tr><td><strong>${escapeHtml(profile.label || id)}</strong><br><small class="mono muted">${escapeHtml(id)}</small></td><td>${escapeHtml(profile.kind)} · ${escapeHtml(profile.engine)}</td><td><span class="mono">${profile.defaults?.width || "?"}×${profile.defaults?.height || "?"}</span><br><small>${profile.defaults?.steps || "?"} steps</small></td><td>${profile.ready ? `<span class="badge DONE">PRONTO</span>` : `<span class="badge FAILED">${profile.missing_files?.length || 0} AUSENTES</span><details><summary>caminhos</summary><div class="mono">${(profile.missing_files || []).map(file => `<div>${escapeHtml(file.field)}: ${escapeHtml(file.path)}</div>`).join("")}</div></details>`}</td></tr>`).join("")}</tbody></table></div></article>
  <div class="error-state" style="margin-top:14px"><strong>4K/8K:</strong> gere na resolução-base eficiente do modelo e finalize por upscale em tiles. O sistema não mascara pós-processamento como geração nativa.</div>
  </section>`;
}

function governanceHtml() {
  const data = state.governance;
  if (!data) return `<section class="page"><div class="loading"><span class="spinner"></span>Carregando governança…</div></section>`;
  const pending = data.tasks.filter(task => task.status === "PENDING");
  const alerts = data.alerts.filter(alert => alert.status === "OPEN");
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Governança</h1><p class="page-subtitle">Fonte única: <span class="mono">/api/governance/snapshot</span> · gerado em ${formatDate(data.generatedAt)}</p></div><div class="actions"><span class="badge ${data.state}">${data.state}</span><button class="btn" data-action="refresh-governance">↻ Atualizar</button></div></div>
    <div class="grid cols-4">${metric("Tarefas", data.summary.totalTasks, `${data.summary.doneTasks} concluídas`)}${metric("Pendentes", data.summary.pendingTasks, "Roadmap aberto")}${metric("Alertas", data.summary.openAlerts, "Bugs, gaps e riscos")}${metric("Progresso", `${data.summary.progressPercent.toFixed(2)}%`, `${data.summary.documents} documentos`)}</div>
    <div class="split" style="margin-top:14px"><article class="card"><div class="card-header"><h2>Módulos</h2></div><div class="card-body">${data.modules.map(module => `<div class="module-row"><span><strong>${escapeHtml(module.module_id)}</strong> · ${escapeHtml(module.module_title)}</span><div class="progress"><span style="width:${module.total ? module.done/module.total*100 : 0}%"></span></div><span>${module.done}/${module.total}</span></div>`).join("")}</div></article>
    <article class="card"><div class="card-header"><h2>Alertas abertos</h2><span class="badge ${alerts.length ? "HIGH" : "DONE"}">${alerts.length}</span></div><div class="card-body">${alerts.length ? alerts.map(alert => `<div class="alert ${alert.severity}"><h4>${escapeHtml(alert.id)} · ${escapeHtml(alert.severity)}</h4><p>${escapeHtml(alert.fact)}</p><p><strong>Ação:</strong> ${escapeHtml(alert.action)}</p></div>`).join("") : `<span class="badge DONE">Nenhum alerta aberto</span>`}</div></article></div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Todo task e roadmap</h2><span class="muted">${pending.length} pendentes</span></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Módulo</th><th>Tarefa</th><th>Fonte</th><th>Status</th></tr></thead><tbody>${data.tasks.map(task => `<tr><td class="mono">${escapeHtml(task.id)}</td><td>${escapeHtml(task.category)}</td><td>${escapeHtml(task.title)}</td><td class="mono">${escapeHtml(task.source_path)}:${task.source_line}</td><td><button class="badge ${task.status}" data-toggle-task="${task.id}" data-task-status="${task.status}">${task.status}</button></td></tr>`).join("")}</tbody></table></div></article>
    <div class="grid cols-2" style="margin-top:14px"><article class="card"><div class="card-header"><h2>Changelog</h2></div><div class="card-body">${data.changelog.map(change => `<div class="module-row"><strong>v${escapeHtml(change.release)}</strong><span>${escapeHtml(change.category)} · ${escapeHtml(change.description)}</span><span class="mono">L${change.source_line}</span></div>`).join("")}</div></article>
    <article class="card"><div class="card-header"><h2>Logs de governança</h2></div><div class="card-body log-list">${data.logs.slice(0,60).map(log => `<div class="log-row ${log.level}"><strong>${escapeHtml(log.level)} · ${escapeHtml(log.event)}</strong><br><small class="muted">${formatDate(log.created_at)}</small><div class="mono subtle">${escapeHtml(JSON.stringify(log.detail))}</div></div>`).join("")}</div></article></div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Documentação sincronizada</h2></div><div class="card-body actions">${data.documents.map(doc => `<a class="btn" href="${escapeHtml(doc.link.replace('/docs/','/docs-files/'))}" target="_blank" rel="noopener">${escapeHtml(doc.name)}</a>`).join("")}</div></article>
  </section>`;
}

function settingsHtml() {
  if (!state.settings) return `<section class="page"><div class="page-header"><div><h1 class="page-title">Configurações</h1></div></div><button class="btn primary" data-action="load-settings">Carregar configurações</button></section>`;
  const engines = state.settings.engines || {};
  const profiles = state.settings.model_profiles || {};
  const providers = state.settings.providers || {};
  return `<section class="page"><div class="page-header"><div><h1 class="page-title">Configurações do superadministrador</h1><p class="page-subtitle">Paths locais, providers, modelos, backup e operação. Segredos reais não são exibidos nem persistidos no JSON; informe somente o nome da variável de ambiente.</p></div><button class="btn primary" data-action="save-settings">Salvar alterações</button></div>
    <div class="grid cols-2"><article class="card"><div class="card-header"><h2>Engines locais</h2></div><div class="card-body"><label class="field"><span class="field-label">Configuração JSON</span><textarea id="settings-engines" class="textarea code-editor">${escapeHtml(JSON.stringify(engines,null,2))}</textarea></label></div></article>
    <article class="card"><div class="card-header"><h2>Providers cloud</h2></div><div class="card-body"><label class="field"><span class="field-label">Configuração JSON</span><textarea id="settings-providers" class="textarea code-editor">${escapeHtml(JSON.stringify(providers,null,2))}</textarea></label><p class="field-help">Exemplo: <span class="mono">{"cloud.freepik":{"enabled":true,"api_key_env":"FREEPIK_API_KEY"}}</span></p></div></article></div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Perfis de modelos locais</h2></div><div class="card-body"><label class="field"><span class="field-label">Configuração JSON</span><textarea id="settings-profiles" class="textarea code-editor">${escapeHtml(JSON.stringify(profiles,null,2))}</textarea></label></div></article>
    <div class="grid cols-2" style="margin-top:14px"><article class="card"><div class="card-header"><h2>Dados e recuperação</h2></div><div class="card-body"><div class="actions"><button class="btn" data-action="create-backup">Criar backup completo</button><button class="btn" data-action="list-backups">Listar backups</button></div><div id="backup-results" class="mono muted" style="margin-top:12px"></div></div></article>
    <article class="card"><div class="card-header"><h2>Caminhos locais</h2></div><div class="card-body mono">${Object.entries(state.bootstrap.paths || {}).map(([key,value]) => `<div style="margin-bottom:8px"><strong>${escapeHtml(key)}</strong><br><span class="muted">${escapeHtml(value)}</span></div>`).join("")}</div></article></div>
    <article class="card" style="margin-top:14px"><div class="card-header"><h2>Governança da conta</h2></div><div class="card-body actions"><button class="btn" data-route="governance">Changelog</button><button class="btn" data-route="governance">Roadmap</button><button class="btn" data-route="governance">Tasks</button><button class="btn" data-route="governance">Alertas e logs</button></div></article>
  </section>`;
}

function bindRoute() {
  $$("[data-route]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.route)));
  $$("[data-action='new-project']").forEach(button => button.addEventListener("click", openNewProjectModal));
  $$('[data-open-project]').forEach(button => button.addEventListener("click", () => { selectProject(button.dataset.openProject); navigate("workflow"); }));
  $$('[data-delete-project]').forEach(button => button.addEventListener("click", () => deleteProject(button.dataset.deleteProject)));
  $$('[data-upload-asset]').forEach(button => button.addEventListener("click", () => uploadInput.click()));
  $$('[data-copy]').forEach(button => button.addEventListener("click", () => navigator.clipboard.writeText(button.dataset.copy).then(() => toast("ID copiado"))));
  $("[data-action='refresh-jobs']")?.addEventListener("click", refreshJobs);
  $("[data-action='refresh-assets']")?.addEventListener("click", refreshAssets);
  $("[data-action='check-engines']")?.addEventListener("click", checkEngines);
  $("[data-action='refresh-providers']")?.addEventListener("click", refreshProviderStatus);
  $("#agent-form")?.addEventListener("submit", runAgentPlan);
  $("#provider-diagnostic-form")?.addEventListener("submit", runProviderDiagnostic);
  $("[data-action='refresh-governance']")?.addEventListener("click", refreshGovernance);
  $("[data-action='load-settings']")?.addEventListener("click", loadSettings);
  $("[data-action='save-settings']")?.addEventListener("click", saveSettings);
  $("[data-action='create-backup']")?.addEventListener("click", createBackup);
  $("[data-action='list-backups']")?.addEventListener("click", listBackups);
  $$('[data-cancel-job]').forEach(button => button.addEventListener("click", () => cancelJob(button.dataset.cancelJob)));
  $$('[data-retry-job]').forEach(button => button.addEventListener("click", () => retryJob(button.dataset.retryJob)));
  $$('[data-toggle-task]').forEach(button => button.addEventListener("click", () => toggleTask(button.dataset.toggleTask, button.dataset.taskStatus)));
  if (state.route === "workflow") bindWorkflow();
  if (state.route === "settings" && !state.settings) loadSettings(false);
  if (state.route === "engines" && (!state.engines.length || !Object.keys(state.profiles).length)) checkEngines(false);
  if (state.route === "providers" && !state.providerStatus.length) refreshProviderStatus(false);
}

function openNewProjectModal() {
  modalRoot.innerHTML = `<div class="modal-backdrop"><form class="modal" id="new-project-form"><div class="modal-head"><h2>Novo projeto</h2><button type="button" class="btn ghost" data-close-modal>✕</button></div><div class="modal-body"><label class="field"><span class="field-label">Nome</span><input class="input" name="name" required maxlength="160" autofocus></label><label class="field"><span class="field-label">Descrição</span><textarea class="textarea" name="description" maxlength="4000"></textarea></label></div><div class="modal-actions"><button type="button" class="btn" data-close-modal>Cancelar</button><button class="btn primary">Criar</button></div></form></div>`;
  $$('[data-close-modal]', modalRoot).forEach(button => button.addEventListener("click", closeModal));
  $("#new-project-form").addEventListener("submit", async event => {
    event.preventDefault();
    const data = new FormData(event.target);
    try {
      setBusy("new-project", true);
      const project = await api("/api/projects", { method: "POST", body: { name: data.get("name"), description: data.get("description"), graph: { version: 2, nodes: [], edges: [], metadata: { template: false } } } });
      state.projects.unshift(project); selectProject(project.id); closeModal(); navigate("workflow"); toast("Projeto criado");
    } catch (error) { toast(error.message, "error"); }
    finally { setBusy("new-project", false); }
  });
}
function closeModal() { modalRoot.innerHTML = ""; }

async function selectProject(id) {
  if (state.dirty && state.currentProject && !confirm("Há alterações não salvas. Trocar de projeto mesmo assim?")) { renderTopbar(); return; }
  const project = state.projects.find(item => item.id === id);
  if (!project) return;
  state.currentProject = project;
  state.graph = deepCopy(project.graph);
  state.selectedNodeId = null; state.connectingFrom = null; state.history = []; state.future = []; state.dirty = false;
  localStorage.setItem("cinenode.currentProjectId", id);
  render();
}

async function deleteProject(id) {
  const project = state.projects.find(item => item.id === id);
  if (!project || !confirm(`Excluir o projeto “${project.name}”? Os assets permanecem auditáveis.`)) return;
  try { await api(`/api/projects/${id}`, { method: "DELETE" }); state.projects = state.projects.filter(item => item.id !== id); if (state.currentProject?.id === id) { state.currentProject = state.projects[0] || null; state.graph = deepCopy(state.currentProject?.graph || {version:2,nodes:[],edges:[],metadata:{}}); } render(); toast("Projeto excluído"); }
  catch (error) { toast(error.message, "error"); }
}

async function saveCurrentProject() {
  if (!state.currentProject) return;
  try {
    setBusy("save", true);
    const project = await api(`/api/projects/${state.currentProject.id}`, { method: "PUT", body: { graph: state.graph } });
    state.currentProject = project;
    state.projects = state.projects.map(item => item.id === project.id ? project : item);
    state.dirty = false;
    renderTopbar(); toast("Workflow salvo");
  } catch (error) { toast(`Falha ao salvar: ${error.message}`, "error", 8000); }
  finally { setBusy("save", false); }
}

async function runCurrentProject() {
  if (!state.currentProject) return;
  try {
    setBusy("run", true);
    await saveCurrentProject();
    const preflight = await api("/api/workflows/preflight", { method: "POST", body: state.graph });
    if (!preflight.ready) {
      const reasons = preflight.blocking.slice(0, 6).map(item => `${item.node_id || "workflow"}: ${item.message}`).join("; ");
      throw new Error(`Pré-voo bloqueado (${preflight.summary.blocked}): ${reasons}`);
    }
    const job = await api("/api/jobs", { method: "POST", body: { project_id: state.currentProject.id } });
    state.jobs.unshift(job); toast(`Job ${job.id} enfileirado`); navigate("jobs");
  } catch (error) { toast(`Execução não iniciada: ${error.message}`, "error", 10000); }
  finally { setBusy("run", false); }
}

function addNode(type) {
  const item = catalogItem(type); if (!item) return;
  pushHistory();
  const wrap = $("#canvas-wrap");
  const x = (wrap?.scrollLeft || 0) + 300 + Math.random() * 80;
  const y = (wrap?.scrollTop || 0) + 180 + Math.random() * 80;
  const node = { id: newNodeId(type), type, position: { x: Math.round(x), y: Math.round(y) }, config: defaultConfig(item) };
  state.graph.nodes.push(node); state.selectedNodeId = node.id; renderWorkflow();
}

function renderWorkflow() {
  if (state.route !== "workflow") return;
  const main = $("#main");
  if (!main) return;
  const scroll = $("#canvas-wrap");
  const left = scroll?.scrollLeft || 0, top = scroll?.scrollTop || 0;
  main.innerHTML = workflowHtml();
  bindRoute();
  const next = $("#canvas-wrap"); if (next) { next.scrollLeft = left; next.scrollTop = top; }
  drawEdges();
  renderTopbar();
}

function bindWorkflow() {
  $("#palette-search")?.addEventListener("input", event => { state.paletteQuery = event.target.value; renderWorkflow(); });
  $$('[data-add-node]').forEach(button => button.addEventListener("click", () => addNode(button.dataset.addNode)));
  $$('[data-node-id]').forEach(node => node.addEventListener("click", event => { if (event.target.closest(".port")) return; state.selectedNodeId = node.dataset.nodeId; renderWorkflow(); }));
  $$('[data-port-output-node]').forEach(port => port.addEventListener("click", event => {
    event.stopPropagation();
    state.connectingFrom = { nodeId: port.dataset.portOutputNode, handleId: port.dataset.portOutputHandle, type: port.dataset.portOutputType };
    renderWorkflow();
  }));
  $$('[data-port-input-node]').forEach(port => port.addEventListener("click", event => {
    event.stopPropagation();
    connectTo(port.dataset.portInputNode, port.dataset.portInputHandle);
  }));
  $$('[data-drag-handle]').forEach(handle => bindNodeDrag(handle));
  $$('[data-node-field]').forEach(field => field.addEventListener("change", () => updateNodeField(field)));
  $$('[data-add-reference]').forEach(button => button.addEventListener("click", () => addNodeReference(button.closest('[data-reference-editor]'))));
  $$('[data-remove-reference]').forEach(button => button.addEventListener("click", () => removeNodeReference(Number(button.dataset.removeReference))));
  $$('[data-reference-prop]').forEach(field => field.addEventListener("change", () => updateNodeReference(Number(field.dataset.referenceIndex), field.dataset.referenceProp, field)));
  $("[data-node-id-field]")?.addEventListener("change", event => renameNode(event.target.value));
  $("[data-delete-selected]")?.addEventListener("click", deleteSelectedNode);
  $$('[data-upload-asset]').forEach(button => button.addEventListener("click", () => uploadInput.click()));
  $("[data-workflow='undo']")?.addEventListener("click", undo);
  $("[data-workflow='redo']")?.addEventListener("click", redo);
  $("[data-workflow='validate']")?.addEventListener("click", validateCurrentWorkflow);
  $("[data-workflow='preflight']")?.addEventListener("click", preflightCurrentWorkflow);
  $("[data-workflow='fit']")?.addEventListener("click", fitCanvas);
  drawEdges();
}

function bindNodeDrag(handle) {
  handle.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const nodeId = handle.dataset.dragHandle;
    const node = state.graph.nodes.find(item => item.id === nodeId); if (!node) return;
    event.preventDefault(); handle.setPointerCapture(event.pointerId);
    const startX = event.clientX, startY = event.clientY, originX = Number(node.position.x), originY = Number(node.position.y);
    pushHistory();
    const move = moveEvent => {
      node.position.x = Math.max(0, Math.round(originX + moveEvent.clientX - startX));
      node.position.y = Math.max(0, Math.round(originY + moveEvent.clientY - startY));
      const element = $(`[data-node-id="${CSS.escape(nodeId)}"]`);
      if (element) { element.style.left = `${node.position.x}px`; element.style.top = `${node.position.y}px`; drawEdges(); }
    };
    const end = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", end); state.dirty = true; renderTopbar(); };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", end);
  });
}

function connectTo(targetId, targetHandle) {
  const source = state.connectingFrom;
  if (!source) { toast("Escolha primeiro uma porta de saída", "warn"); return; }
  if (source.nodeId === targetId) { toast("Um nó não pode conectar em si mesmo", "warn"); return; }
  if (state.graph.edges.some(edge => edge.source === source.nodeId && edge.target === targetId && edge.source_handle === source.handleId && edge.target_handle === targetHandle)) { toast("Conexão já existe", "warn"); return; }
  pushHistory();
  const edge = {
    id: `edge-${source.nodeId}-${source.handleId}-${targetId}-${targetHandle}-${Date.now()}`,
    source: source.nodeId,
    target: targetId,
    source_handle: source.handleId,
    target_handle: targetHandle,
  };
  state.graph.edges.push(edge); state.connectingFrom = null;
  validateGraphLocally().then(result => {
    const edgeErrors = (result.errors || []).filter(item => item.edge_id === edge.id);
    const cycleError = (result.errors || []).find(item => item.code === "WORKFLOW_CYCLE");
    if (edgeErrors.length || cycleError) {
      state.graph.edges = state.graph.edges.filter(item => item.id !== edge.id);
      toast([...edgeErrors, ...(cycleError ? [cycleError] : [])].map(item => item.message).join("; "), "error");
    }
    renderWorkflow();
  }).catch(error => { state.graph.edges = state.graph.edges.filter(item => item.id !== edge.id); toast(error.message, "error"); renderWorkflow(); });
}

async function validateGraphLocally() { return api("/api/workflows/validate", { method: "POST", body: state.graph }); }
async function validateCurrentWorkflow() { try { const result = await validateGraphLocally(); if (result.valid) toast(`Workflow válido · ${result.order.length} nós · terminais: ${result.terminal_nodes.join(", ") || "nenhum"}`); else toast(result.errors.map(item => item.message).join("; "), "error", 10000); } catch (error) { toast(error.message, "error"); } }
async function preflightCurrentWorkflow() {
  try {
    const result = await api("/api/workflows/preflight", { method: "POST", body: state.graph });
    const rows = result.checks.map(item => `<tr><td><span class="badge ${item.ready ? "SUCCEEDED" : "FAILED"}">${item.ready ? "PRONTO" : "BLOQUEADO"}</span></td><td class="mono">${escapeHtml(item.node_id || "workflow")}</td><td>${escapeHtml(item.message)}</td><td><small class="mono">${escapeHtml(item.code)}</small></td></tr>`).join("");
    modalRoot.innerHTML = `<div class="modal-backdrop"><div class="modal wide"><div class="modal-head"><div><h2>Pré-voo real</h2><p class="muted">${result.ready ? "Todas as dependências detectáveis estão prontas." : `${result.summary.blocked} bloqueio(s) impedem a execução.`}</p></div><button type="button" class="btn ghost" data-close-modal>✕</button></div><div class="modal-body"><div class="table-wrap"><table><thead><tr><th>Estado</th><th>Nó</th><th>Diagnóstico</th><th>Código</th></tr></thead><tbody>${rows || `<tr><td colspan="4">Nenhuma dependência externa.</td></tr>`}</tbody></table></div></div><div class="modal-actions"><button type="button" class="btn" data-close-modal>Fechar</button></div></div></div>`;
    $$('[data-close-modal]', modalRoot).forEach(button => button.addEventListener("click", closeModal));
    toast(result.ready ? "Pré-voo aprovado" : "Pré-voo bloqueado; veja os requisitos", result.ready ? "success" : "error", 8000);
  } catch (error) { toast(`Pré-voo falhou: ${error.message}`, "error", 10000); }
}

function updateNodeField(field) {
  const node = currentNode(); if (!node) return;
  let value = field.type === "checkbox" ? field.checked : field.value;
  if (field.type === "number") value = Number(value);
  if (field.dataset.jsonField != null) {
    try { value = JSON.parse(value || "{}"); field.style.borderColor = ""; }
    catch (error) { field.style.borderColor = "var(--danger)"; toast(`JSON inválido: ${error.message}`, "error"); return; }
  }
  pushHistory(); node.config[field.dataset.nodeField] = value; state.dirty = true; renderWorkflow();
}

function addNodeReference(editor) {
  const node = currentNode(); if (!node || !editor) return;
  const assetId = $('[data-reference-add-asset]', editor)?.value;
  const role = $('[data-reference-add-role]', editor)?.value || "reference";
  if (!assetId) { toast("Selecione um asset", "warn"); return; }
  pushHistory();
  const key = editor.dataset.referenceEditor;
  const items = Array.isArray(node.config[key]) ? node.config[key] : [];
  if (items.some(item => item.asset_id === assetId)) { toast("Asset já adicionado", "warn"); return; }
  node.config[key] = [...items, { asset_id: assetId, role, weight: 1.0, note: "" }];
  state.dirty = true; renderWorkflow();
}

function removeNodeReference(index) {
  const node = currentNode(); if (!node) return;
  const item = catalogItem(node.type)?.fields?.find(field => field.type === "references");
  if (!item) return;
  pushHistory();
  const values = Array.isArray(node.config[item.key]) ? [...node.config[item.key]] : [];
  values.splice(index, 1); node.config[item.key] = values; state.dirty = true; renderWorkflow();
}

function updateNodeReference(index, property, field) {
  const node = currentNode(); if (!node) return;
  const item = catalogItem(node.type)?.fields?.find(candidate => candidate.type === "references");
  if (!item) return;
  const values = Array.isArray(node.config[item.key]) ? deepCopy(node.config[item.key]) : [];
  if (!values[index]) return;
  pushHistory(); values[index][property] = property === "weight" ? Number(field.value) : field.value;
  node.config[item.key] = values; state.dirty = true; renderWorkflow();
}

function renameNode(value) {
  const node = currentNode(); if (!node) return;
  const clean = String(value).trim();
  if (!/^[A-Za-z0-9._-]{1,100}$/.test(clean)) { toast("ID inválido", "error"); renderWorkflow(); return; }
  if (state.graph.nodes.some(item => item.id === clean && item !== node)) { toast("ID já existe", "error"); renderWorkflow(); return; }
  pushHistory(); const old = node.id; node.id = clean;
  for (const edge of state.graph.edges) { if (edge.source === old) edge.source = clean; if (edge.target === old) edge.target = clean; }
  state.selectedNodeId = clean; state.dirty = true; renderWorkflow();
}

function deleteSelectedNode() {
  const id = state.selectedNodeId; if (!id) return;
  pushHistory(); state.graph.nodes = state.graph.nodes.filter(node => node.id !== id); state.graph.edges = state.graph.edges.filter(edge => edge.source !== id && edge.target !== id); state.selectedNodeId = null; state.connectingFrom = null; renderWorkflow();
}

function drawEdges() {
  const svg = $("#edge-layer"); if (!svg) return;
  const canvas = $("#node-canvas"); if (!canvas) return;
  const canvasRect = canvas.getBoundingClientRect();
  svg.innerHTML = state.graph.edges.map(edge => {
    const sourceNode = $(`[data-node-id="${CSS.escape(edge.source)}"]`);
    const targetNode = $(`[data-node-id="${CSS.escape(edge.target)}"]`);
    if (!sourceNode || !targetNode) return "";
    const sourcePort = edge.source_handle ? $(`[data-port-output-node="${CSS.escape(edge.source)}"][data-port-output-handle="${CSS.escape(edge.source_handle)}"]`) : $('[data-port-output-node]', sourceNode);
    const targetPort = edge.target_handle ? $(`[data-port-input-node="${CSS.escape(edge.target)}"][data-port-input-handle="${CSS.escape(edge.target_handle)}"]`) : $('[data-port-input-node]', targetNode);
    const sourceRect = (sourcePort || sourceNode).getBoundingClientRect();
    const targetRect = (targetPort || targetNode).getBoundingClientRect();
    const x1 = sourceRect.left - canvasRect.left + sourceRect.width / 2;
    const y1 = sourceRect.top - canvasRect.top + sourceRect.height / 2;
    const x2 = targetRect.left - canvasRect.left + targetRect.width / 2;
    const y2 = targetRect.top - canvasRect.top + targetRect.height / 2;
    const bend = Math.max(70, Math.abs(x2 - x1) * .45);
    return `<path class="edge-path ${state.selectedNodeId === edge.source || state.selectedNodeId === edge.target ? "active" : ""}" d="M ${x1} ${y1} C ${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}"></path>`;
  }).join("");
}

function fitCanvas() {
  const wrap = $("#canvas-wrap"); if (!wrap || !state.graph.nodes.length) return;
  const minX = Math.min(...state.graph.nodes.map(node => Number(node.position.x || 0)));
  const minY = Math.min(...state.graph.nodes.map(node => Number(node.position.y || 0)));
  wrap.scrollTo({ left: Math.max(0, minX - 120), top: Math.max(0, minY - 120), behavior: "smooth" });
}

async function runAgentPlan(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const references = $$('[data-agent-reference]:checked', form).map(input => {
    const id = input.dataset.agentReference;
    return {
      asset_id: id,
      role: $(`[data-agent-role="${CSS.escape(id)}"]`, form)?.value || "reference",
      weight: Number($(`[data-agent-weight="${CSS.escape(id)}"]`, form)?.value || 1),
      note: $(`[data-agent-note="${CSS.escape(id)}"]`, form)?.value || "",
    };
  });
  const payload = {
    brief: String(data.get("brief") || "").trim(),
    target: data.get("target"),
    references,
    provider: data.get("provider") || "auto",
    model: String(data.get("model") || "").trim(),
    local_first: data.get("local_first") === "on",
    aspect_ratio: data.get("aspect_ratio") || "16:9",
    duration_seconds: Number(data.get("duration_seconds") || 5),
    output_resolution: data.get("output_resolution") || "4k",
    create_project: true,
    project_name: String(data.get("project_name") || "").trim() || null,
    use_llm: data.get("use_llm") === "on",
    planner_mode: data.get("planner_mode") || "auto",
    agent_model: String(data.get("agent_model") || "").trim(),
  };
  try {
    setBusy("agent", true);
    const result = await api("/api/agent/plan", { method: "POST", body: payload });
    state.agentResult = result;
    if (!result.validation?.valid) throw new Error((result.validation?.errors || []).map(item => item.message).join("; ") || "O agente criou um grafo inválido");
    if (result.project) {
      state.projects = [result.project, ...state.projects.filter(item => item.id !== result.project.id)];
      state.currentProject = result.project;
      state.graph = deepCopy(result.project.graph);
      state.selectedNodeId = null; state.connectingFrom = null; state.history = []; state.future = []; state.dirty = false;
      localStorage.setItem("cinenode.currentProjectId", result.project.id);
      toast(`Workflow criado: ${result.graph.nodes.length} nós e ${result.graph.edges.length} conexões`);
      navigate("workflow");
    } else { render(); }
  } catch (error) { toast(`Agente não criou o workflow: ${error.message}`, "error", 12000); }
  finally { setBusy("agent", false); }
}

async function refreshProviderStatus(renderAfter = true) {
  try {
    setBusy("providers", true);
    const [catalog, status] = await Promise.all([api("/api/providers/catalog"), api("/api/providers/status")]);
    state.providers = catalog.items || [];
    state.providerStatus = status.items || [];
    state.providerStatusCheckedAt = status.checked_at;
    if (renderAfter && state.route === "providers") render();
  } catch (error) { toast(`Falha ao verificar providers: ${error.message}`, "error", 10000); }
  finally { setBusy("providers", false); }
}

async function runProviderDiagnostic(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  let parameters;
  try { parameters = JSON.parse(String(data.get("parameters") || "{}")); }
  catch (error) { toast(`Parâmetros JSON inválidos: ${error.message}`, "error"); return; }
  const model = String(data.get("model") || "").trim();
  const endpoint = String(data.get("endpoint") || "").trim();
  if (model) parameters.model = model;
  if (endpoint) parameters.endpoint = endpoint;
  const references = $$('[data-provider-reference]:checked', form).map(input => {
    const id = input.dataset.providerReference;
    return { asset_id: id, role: $(`[data-provider-role="${CSS.escape(id)}"]`, form)?.value || "reference", weight: 1, note: "diagnostic" };
  });
  try {
    setBusy("provider-diagnostic", true);
    state.providerDiagnosticResult = await api("/api/providers/invoke", { method: "POST", body: {
      provider_id: data.get("provider_id"), operation: data.get("operation"), prompt: String(data.get("prompt") || ""), negative_prompt: "", references, parameters,
    }});
    toast("Chamada real concluída");
    await refreshAssets(false); render();
  } catch (error) {
    state.providerDiagnosticResult = { error: error.message, payload: error.payload || null };
    toast(`Chamada falhou: ${error.message}`, "error", 12000); render();
  } finally { setBusy("provider-diagnostic", false); }
}

async function refreshJobs(renderAfter = true) { try { state.jobs = (await api("/api/jobs?limit=100")).items; if (renderAfter && state.route === "jobs") render(); } catch (error) { state.online = false; toast(error.message, "error"); renderTopbar(); } }
async function refreshAssets(renderAfter = true) { try { state.assets = (await api("/api/assets?limit=200")).items; if (renderAfter && state.route === "gallery") render(); } catch (error) { toast(error.message, "error"); } }
async function refreshGovernance(renderAfter = true) { try { state.governance = await api("/api/governance/snapshot", { headers: { "Cache-Control": "no-cache" } }); if (renderAfter && state.route === "governance") render(); } catch (error) { toast(`Governança indisponível: ${error.message}`, "error"); } }

async function cancelJob(id) { try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); toast("Cancelamento solicitado"); await refreshJobs(); } catch (error) { toast(error.message, "error"); } }
async function retryJob(id) { try { const job = await api(`/api/jobs/${id}/retry`, { method: "POST" }); state.jobs.unshift(job); toast(`Retry ${job.id} enfileirado`); render(); } catch (error) { toast(error.message, "error"); } }

async function checkEngines(renderAfter = true) {
  try { setBusy("engines", true); const [status, profiles] = await Promise.all([api("/api/engines/status"), api("/api/model-profiles")]); state.engines = status.items; state.profiles = profiles.items; if (renderAfter && state.route === "engines") render(); }
  catch (error) { toast(`Falha ao verificar engines: ${error.message}`, "error", 8000); }
  finally { setBusy("engines", false); }
}

async function loadSettings(renderAfter = true) { try { state.settings = await api("/api/settings"); if (renderAfter && state.route === "settings") render(); } catch (error) { toast(error.message, "error"); } }
async function saveSettings() {
  try {
    const engines = JSON.parse($("#settings-engines").value);
    const profiles = JSON.parse($("#settings-profiles").value);
    const providers = JSON.parse($("#settings-providers").value);
    state.settings = await api("/api/settings", { method: "PATCH", body: { values: { engines, model_profiles: profiles, providers } } });
    state.providers = (await api("/api/providers/catalog")).items;
    state.providerStatus = [];
    toast("Configurações salvas"); await checkEngines(false); render();
  } catch (error) { toast(`Configuração inválida: ${error.message}`, "error", 10000); }
}

async function createBackup() { const target = $("#backup-results"); try { target.textContent = "Criando backup…"; const result = await api("/api/backups", { method: "POST", body: { include_assets: true, include_outputs: true } }); target.textContent = `${result.path}\nSHA-256 ${result.sha256}\n${formatBytes(result.size_bytes)}`; toast("Backup concluído"); } catch (error) { target.textContent = error.message; toast(error.message, "error"); } }
async function listBackups() { const target = $("#backup-results"); try { const data = await api("/api/backups"); target.textContent = data.items.length ? data.items.map(item => `${item.name} · ${formatBytes(item.size_bytes)} · ${item.sha256.slice(0,16)}…`).join("\n") : "Nenhum backup."; } catch (error) { target.textContent = error.message; } }
async function toggleTask(id, status) { try { const next = status === "DONE" ? "PENDING" : "DONE"; state.governance = await api(`/api/governance/tasks/${id}`, { method: "PATCH", body: { status: next, evidence: { source: "superadmin-ui" } } }); render(); } catch (error) { toast(error.message, "error"); } }

uploadInput.addEventListener("change", async () => {
  const files = [...(uploadInput.files || [])]; if (!files.length) return;
  let imported = 0;
  try {
    setBusy("upload", true);
    for (const file of files) {
      const form = new FormData(); form.append("file", file);
      const query = state.currentProject ? `?project_id=${encodeURIComponent(state.currentProject.id)}` : "";
      const asset = await api(`/api/assets/upload${query}`, { method: "POST", body: form });
      state.assets.unshift(asset); imported += 1;
    }
    toast(`${imported} arquivo(s) importado(s)`);
    if (["gallery", "workflow", "agent", "providers"].includes(state.route)) render();
  } catch (error) { toast(`Upload falhou após ${imported} arquivo(s): ${error.message}`, "error", 10000); }
  finally { uploadInput.value = ""; setBusy("upload", false); }
});

function connectEvents() {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource("/api/events"); state.eventSource = source;
  source.addEventListener("connected", () => { state.online = true; renderTopbar(); });
  source.addEventListener("jobs.updated", () => refreshJobs(state.route === "jobs" || state.route === "dashboard"));
  source.addEventListener("gallery.updated", () => refreshAssets(state.route === "gallery"));
  source.addEventListener("governance.updated", () => refreshGovernance(state.route === "governance"));
  source.addEventListener("projects.updated", async () => { state.projects = (await api("/api/projects")).items; renderTopbar(); });
  source.onerror = () => { state.online = false; renderTopbar(); };
}

function startPolling() {
  for (const timer of state.timers) clearInterval(timer);
  state.timers = [
    setInterval(() => refreshJobs(state.route === "jobs" || state.route === "dashboard"), 3000),
    setInterval(() => refreshGovernance(state.route === "governance"), 15000),
    setInterval(() => refreshAssets(state.route === "gallery"), 15000),
    setInterval(() => { if (state.route === "providers") refreshProviderStatus(false); }, 30000),
  ];
  window.addEventListener("focus", () => { refreshGovernance(state.route === "governance"); refreshJobs(state.route === "jobs"); if (state.route === "providers") refreshProviderStatus(false); });
  window.addEventListener("oraculo:governance-updated", () => refreshGovernance(state.route === "governance"));
}

window.addEventListener("keydown", event => {
  const tag = document.activeElement?.tagName;
  const editing = ["INPUT", "TEXTAREA", "SELECT"].includes(tag);
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveCurrentProject(); }
  if (state.route === "workflow" && !editing && (event.key === "Delete" || event.key === "Backspace")) { event.preventDefault(); deleteSelectedNode(); }
  if (state.route === "workflow" && !editing && event.key === "Escape") { state.connectingFrom = null; state.selectedNodeId = null; renderWorkflow(); }
  if (state.route === "workflow" && !editing && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); }
});

window.addEventListener("beforeunload", event => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("resize", () => { if (state.route === "workflow") drawEdges(); });

initialize();

/*
 * Arcane card for Home Assistant.
 *
 * Shows one Arcane environment's containers as a list with a status dot,
 * CPU, memory and an update badge. Tapping a row restarts the container
 * (or starts it if it's stopped), after a confirmation.
 *
 * Served by the Arcane integration itself, so it needs no separate install.
 * Data comes from each container's State sensor, whose attributes carry
 * arcane_container, arcane_environment, cpu_percent, memory_usage and so on.
 */

const CARD_VERSION = "0.1.0";

const SORTS = ["name", "state", "cpu", "memory"];
const TAP_ACTIONS = ["restart", "more-info", "none"];

const STATE_ORDER = { running: 0, restarting: 1, paused: 2, created: 3, exited: 4, dead: 5 };

function containerStates(hass) {
  return Object.values(hass.states).filter(
    (s) => s.entity_id.startsWith("sensor.") && s.attributes && s.attributes.arcane_container
  );
}

function environments(hass) {
  const envs = new Map();
  for (const s of containerStates(hass)) {
    const id = String(s.attributes.arcane_environment);
    if (!envs.has(id)) envs.set(id, s.attributes.arcane_environment_name || id);
  }
  return [...envs.entries()].map(([id, name]) => ({ id, name }));
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  const mib = bytes / 1048576;
  if (mib >= 1024) return `${(mib / 1024).toFixed(1)} GB`;
  return `${Math.round(mib)} MB`;
}

function dotClass(state, attrs) {
  if (state === "unavailable" || state === "unknown") return "unknown";
  if (state === "running") return attrs.health === "unhealthy" ? "busy" : "up";
  if (state === "restarting" || state === "paused" || state === "created") return "busy";
  return "down";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

class ArcaneCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = null; // entity_id waiting on a confirm
    this._busy = new Set(); // entity_ids with an action in flight
    this._errors = new Map();
    this._signature = "";
  }

  static getConfigElement() {
    return document.createElement("arcane-card-editor");
  }

  static getStubConfig(hass) {
    const envs = environments(hass);
    return { environment: envs.length ? envs[0].id : "0" };
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    if (config.sort && !SORTS.includes(config.sort)) throw new Error(`sort must be one of ${SORTS.join(", ")}`);
    if (config.tap_action && !TAP_ACTIONS.includes(config.tap_action))
      throw new Error(`tap_action must be one of ${TAP_ACTIONS.join(", ")}`);
    this._config = {
      show_stopped: true,
      sort: "name",
      tap_action: "restart",
      confirm: true,
      show_header: true,
      ...config,
    };
    this._signature = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const rows = this._rows();
    // Only redraw when one of this card's containers changed.
    const signature = rows.map((s) => `${s.entity_id}|${s.last_updated}|${s.state}`).join(",");
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return 1 + Math.ceil(this._rows().length / 2);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _environmentId() {
    if (this._config.environment !== undefined && this._config.environment !== null && this._config.environment !== "")
      return String(this._config.environment);
    const envs = this._hass ? environments(this._hass) : [];
    return envs.length ? envs[0].id : null;
  }

  _rows() {
    if (!this._hass || !this._config) return [];
    const env = this._environmentId();
    const filter = (this._config.filter || "").toLowerCase().trim();
    const exclude = (this._config.exclude || []).map((x) => String(x).toLowerCase());
    let rows = containerStates(this._hass).filter((s) => String(s.attributes.arcane_environment) === env);
    if (!this._config.show_stopped) rows = rows.filter((s) => s.state === "running" || s.state === "restarting");
    if (filter) rows = rows.filter((s) => s.attributes.arcane_container.toLowerCase().includes(filter));
    if (exclude.length) rows = rows.filter((s) => !exclude.includes(s.attributes.arcane_container.toLowerCase()));
    const byName = (a, b) => a.attributes.arcane_container.localeCompare(b.attributes.arcane_container);
    const sorts = {
      name: byName,
      state: (a, b) => (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9) || byName(a, b),
      cpu: (a, b) => (b.attributes.cpu_percent || 0) - (a.attributes.cpu_percent || 0) || byName(a, b),
      memory: (a, b) => (b.attributes.memory_usage || 0) - (a.attributes.memory_usage || 0) || byName(a, b),
    };
    return rows.sort(sorts[this._config.sort] || byName);
  }

  _actionFor(stateObj) {
    return stateObj.state === "running" || stateObj.state === "restarting" ? "restart" : "start";
  }

  _onRowTap(entityId) {
    const mode = this._config.tap_action;
    if (mode === "none") return;
    if (mode === "more-info") return this._moreInfo(entityId);
    if (this._busy.has(entityId)) return;
    if (this._config.confirm) {
      this._pending = this._pending === entityId ? null : entityId;
      this._render();
    } else {
      this._run(entityId);
    }
  }

  async _run(entityId) {
    const stateObj = this._hass.states[entityId];
    if (!stateObj) return;
    const action = this._actionFor(stateObj);
    this._pending = null;
    this._busy.add(entityId);
    this._errors.delete(entityId);
    this._render();
    try {
      await this._hass.callService("arcane", action, {}, { entity_id: entityId });
    } catch (err) {
      this._errors.set(entityId, err && err.message ? err.message : String(err));
    } finally {
      this._busy.delete(entityId);
      this._render();
    }
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._config || !this._hass) return;
    const rows = this._rows();
    const envId = this._environmentId();
    const envName =
      (rows[0] && rows[0].attributes.arcane_environment_name) ||
      (environments(this._hass).find((e) => e.id === envId) || {}).name ||
      "Arcane";
    const title = this._config.title ?? envName;
    const running = rows.filter((s) => s.state === "running").length;
    const updates = rows.filter((s) => s.attributes.update_available).length;

    const header = this._config.show_header
      ? `<div class="header">
          <div class="title">${escapeHtml(title)}</div>
          <div class="summary">${running}/${rows.length} running${
            updates ? ` · <span class="upd-text">${updates} update${updates === 1 ? "" : "s"}</span>` : ""
          }</div>
        </div>`
      : "";

    const body = rows.length
      ? rows.map((s) => this._rowHtml(s)).join("")
      : `<div class="empty">${
          envId === null
            ? "No Arcane containers found. Is the Arcane integration set up?"
            : "No containers to show for this environment."
        }</div>`;

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        ${header}
        <div class="list">${body}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll(".row[data-entity]").forEach((el) => {
      el.addEventListener("click", () => this._onRowTap(el.dataset.entity));
    });
    this.shadowRoot.querySelectorAll("[data-info]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._moreInfo(el.dataset.info);
      });
    });
    this.shadowRoot.querySelectorAll("[data-confirm]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._run(el.dataset.confirm);
      });
    });
    this.shadowRoot.querySelectorAll("[data-cancel]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._pending = null;
        this._render();
      });
    });
  }

  _rowHtml(s) {
    const a = s.attributes;
    const running = s.state === "running";
    const busy = this._busy.has(s.entity_id);
    const dot = busy ? "busy pulse" : dotClass(s.state, a);
    const cpu = running && a.cpu_percent !== null && a.cpu_percent !== undefined ? `${Number(a.cpu_percent).toFixed(1)}%` : "";
    const mem = running ? formatBytes(a.memory_usage) : "";
    const stateLabel = running ? (a.health && a.health !== "healthy" ? a.health : "") : s.state;
    const badge = a.update_available
      ? `<span class="badge" title="${escapeHtml(
          a.latest_version ? `${a.current_version || "current"} → ${a.latest_version}` : "Newer image available"
        )}">update</span>`
      : "";
    const action = this._actionFor(s);
    const confirm =
      this._pending === s.entity_id
        ? `<div class="confirm">
            <span>${action === "restart" ? "Restart" : "Start"} ${escapeHtml(a.arcane_container)}?</span>
            <button class="go" data-confirm="${escapeHtml(s.entity_id)}">${action === "restart" ? "Restart" : "Start"}</button>
            <button data-cancel="1">Cancel</button>
          </div>`
        : "";
    const error = this._errors.get(s.entity_id);
    return `
      <div class="row${this._config.tap_action === "none" ? " static" : ""}" data-entity="${escapeHtml(s.entity_id)}">
        <span class="dot ${dot}"></span>
        <span class="name" title="${escapeHtml(a.image || "")}">${escapeHtml(a.arcane_container)}${
          stateLabel ? ` <span class="state">${escapeHtml(stateLabel)}</span>` : ""
        }</span>
        <span class="badge-slot">${badge}</span>
        <span class="metric cpu">${cpu}</span>
        <span class="metric mem">${mem}</span>
        <ha-icon class="info" icon="mdi:information-outline" data-info="${escapeHtml(s.entity_id)}"></ha-icon>
      </div>
      ${confirm}
      ${error ? `<div class="error">${escapeHtml(error)}</div>` : ""}`;
  }
}

const STYLE = `
  ha-card { padding: 12px 0 8px; }
  .header { display: flex; align-items: baseline; justify-content: space-between; padding: 0 16px 8px; gap: 8px; }
  .title { font-size: 1.2em; font-weight: 500; color: var(--primary-text-color); }
  .summary { font-size: 0.9em; color: var(--secondary-text-color); white-space: nowrap; }
  .upd-text { color: var(--info-color, #4a8fd4); }
  .row {
    display: grid; grid-template-columns: 12px minmax(0, 1fr) auto 3.6em 4.6em 24px;
    align-items: center; gap: 10px; padding: 6px 16px; cursor: pointer; min-height: 32px;
  }
  .row.static { cursor: default; }
  .row:hover { background: var(--secondary-background-color); }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--disabled-color, #8a8272); }
  .dot.up { background: var(--success-color, #43a047); }
  .dot.busy { background: var(--warning-color, #d38b3a); }
  .dot.down { background: var(--error-color, #c4553f); }
  .dot.pulse { animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: 0.3; } }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--primary-text-color); }
  .state { font-size: 0.8em; color: var(--secondary-text-color); }
  .badge {
    font-size: 0.72em; padding: 1px 7px; border-radius: 9px; text-transform: uppercase; letter-spacing: 0.04em;
    background: var(--info-color, #4a8fd4); color: var(--text-primary-color, #fff);
  }
  .metric { text-align: right; font-variant-numeric: tabular-nums; font-size: 0.9em; color: var(--secondary-text-color); }
  .info { --mdc-icon-size: 18px; color: var(--secondary-text-color); cursor: pointer; }
  .confirm {
    display: flex; align-items: center; gap: 8px; padding: 4px 16px 8px 38px; font-size: 0.9em;
    color: var(--primary-text-color);
  }
  .confirm span { flex: 1; }
  .confirm button {
    font: inherit; border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color);
    border-radius: 6px; padding: 4px 10px; cursor: pointer;
  }
  .confirm button.go { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .error { padding: 0 16px 6px 38px; font-size: 0.85em; color: var(--error-color, #c4553f); }
  .empty { padding: 8px 16px; color: var(--secondary-text-color); }
`;

class ArcaneCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    if (first) this._render();
  }

  _schema() {
    const envs = this._hass ? environments(this._hass) : [];
    return [
      {
        name: "environment",
        selector: { select: { mode: "dropdown", options: envs.map((e) => ({ value: e.id, label: e.name })) } },
      },
      { name: "title", selector: { text: {} } },
      {
        type: "grid",
        name: "",
        schema: [
          {
            name: "sort",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "name", label: "Name" },
                  { value: "state", label: "State" },
                  { value: "cpu", label: "CPU" },
                  { value: "memory", label: "Memory" },
                ],
              },
            },
          },
          {
            name: "tap_action",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "restart", label: "Restart (or start if stopped)" },
                  { value: "more-info", label: "Show details" },
                  { value: "none", label: "Nothing" },
                ],
              },
            },
          },
        ],
      },
      { name: "filter", selector: { text: {} } },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "show_stopped", selector: { boolean: {} } },
          { name: "confirm", selector: { boolean: {} } },
          { name: "show_header", selector: { boolean: {} } },
        ],
      },
    ];
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) =>
        ({
          environment: "Environment",
          title: "Title (defaults to the environment name)",
          sort: "Sort by",
          tap_action: "Tapping a container",
          filter: "Only show containers whose name contains",
          show_stopped: "Show stopped containers",
          confirm: "Ask before restarting",
          show_header: "Show header",
        })[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const key of ["title", "filter"]) if (config[key] === "") delete config[key];
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.data = {
      show_stopped: true,
      sort: "name",
      tap_action: "restart",
      confirm: true,
      show_header: true,
      ...this._config,
    };
  }
}

if (!customElements.get("arcane-card")) customElements.define("arcane-card", ArcaneCard);
if (!customElements.get("arcane-card-editor")) customElements.define("arcane-card-editor", ArcaneCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "arcane-card")) {
  window.customCards.push({
    type: "arcane-card",
    name: "Arcane",
    description: "Containers on an Arcane environment, with status, CPU, memory, updates and tap-to-restart.",
    preview: true,
    documentationURL: "https://github.com/TheWarBoys2/arcane_ha",
  });
}

console.info(`%c ARCANE-CARD %c ${CARD_VERSION} `, "color:#fff;background:#4a8fd4", "color:#4a8fd4");

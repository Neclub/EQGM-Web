/* EQ Gear Management — HTML setup page */

const state = {
  filePaths: [],
  roster: [],
  selectedRoster: new Set(),
  includeSpells: false,
  includeAchievements: false,
  includeSlot2: true,
  includeType5: true,
  includeType18: true,
  includeRaidBis: true,
  includeAnniversary: false,
  optionsTab: "options",
  useWeightOverrides: false,
  weightDefaults: null,
  weightEdits: null,
  weightsClassKey: null,
  outputFormat: "both",
  generating: false,
};

const OUTPUT_FORMATS = ["excel", "html", "both"];
const DEFAULT_WINDOW_WIDTH = 982;
const DEFAULT_WINDOW_HEIGHT = 765;

const $ = (id) => document.getElementById(id);

function api(method, ...args) {
  if (!window.pywebview || !pywebview.api || !pywebview.api[method]) {
    return Promise.reject(new Error("App API not available."));
  }
  return Promise.resolve(pywebview.api[method](...args));
}

function showToast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(showToast._timer);
  const ms = isError ? 4500 : 2200;
  showToast._timer = setTimeout(() => el.classList.add("hidden"), ms);
}

function errorText(err) {
  if (err == null) return "";
  if (typeof err === "string") return err.trim();
  if (err && err.message) return String(err.message).trim();
  return String(err).trim();
}

function showErrorDialog(message, title = "Error") {
  const text = errorText(message);
  if (!text) return;
  showModal(`
    <div class="modal">
      <div class="modal-header"><h2>${escapeHtml(title)}</h2></div>
      <div class="modal-body">
        <p class="error-dialog-message">${escapeHtml(text)}</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-primary" id="modalClose">OK</button>
      </div>
    </div>`);
  const closeBtn = $("modalClose");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeModal);
    closeBtn.focus();
  }
}

function showModal(html) {
  $("modalRoot").innerHTML = `<div class="modal-backdrop" id="modalBackdrop">${html}</div>`;
  const backdrop = $("modalBackdrop");
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) closeModal();
  });
  const modalHeader = document.querySelector("#modalRoot .modal-header");
  if (modalHeader) modalHeader.addEventListener("mousedown", startWindowDrag);
}

function closeModal() {
  $("modalRoot").innerHTML = "";
}

async function fitWindowTo(size) {
  if (!size) return;
  const availW = screen.availWidth || screen.width || 0;
  const availH = screen.availHeight || screen.height || 0;
  if (
    availW &&
    availH &&
    window.outerWidth >= availW - 16 &&
    window.outerHeight >= availH - 16
  ) {
    return;
  }
  try {
    await api("fit_window", size.width, size.height);
  } catch (_) {
    /* window resize is best-effort outside pywebview */
  }
}

function folderPickerNeededSize() {
  const modal = document.querySelector("#modalRoot .modal");
  const list = $("pickerList");
  if (!modal || !list) return null;
  const header = modal.querySelector(".modal-header");
  const footer = modal.querySelector(".modal-footer");
  const filter = modal.querySelector(".picker-filter");
  const toolbar = modal.querySelector(".modal-body .toolbar");
  const labels = modal.querySelectorAll(".modal-body .field-label");
  let labelH = 0;
  labels.forEach((el) => { labelH += el.offsetHeight; });
  const chrome =
    (header ? header.offsetHeight : 0) +
    (footer ? footer.offsetHeight : 0) +
    (filter ? filter.offsetHeight : 0) +
    (toolbar ? toolbar.offsetHeight : 0) +
    labelH +
    56;
  const frame = Math.max(0, (window.outerHeight || 0) - (window.innerHeight || 0)) || 72;
  const availH = screen.availHeight || screen.height || 1080;
  return {
    width: Math.max(DEFAULT_WINDOW_WIDTH, Math.ceil((modal.scrollWidth || 600) + 64)),
    height: Math.min(availH, Math.ceil(chrome + list.scrollHeight + frame)),
  };
}

function columnContentHeight(el) {
  if (!el) return 0;
  const style = getComputedStyle(el);
  const gap = parseFloat(style.rowGap || style.gap) || 0;
  const kids = [...el.children].filter((c) => !c.classList.contains("hidden"));
  let h = 0;
  kids.forEach((child, i) => {
    h += Math.max(child.scrollHeight, child.offsetHeight);
    if (i) h += gap;
  });
  return h;
}

function setupNeededSize() {
  const app = $("app");
  if (!app) return null;
  const header = document.querySelector(".app-header");
  const action = document.querySelector(".action-bar");
  const settings = document.querySelector(".settings-column");
  const appStyle = getComputedStyle(app);
  const padY =
    (parseFloat(appStyle.paddingTop) || 0) + (parseFloat(appStyle.paddingBottom) || 0);
  const gap = parseFloat(appStyle.rowGap || appStyle.gap) || 0;
  const workspaceH = Math.max(columnContentHeight(settings), 280);
  const inner =
    (header ? header.offsetHeight : 0) +
    workspaceH +
    (action ? action.offsetHeight : 0) +
    padY +
    gap * 2 +
    8;
  const frame = Math.max(0, (window.outerHeight || 0) - (window.innerHeight || 0)) || 72;
  const availH = screen.availHeight || screen.height || 1080;
  return {
    width: Math.max(DEFAULT_WINDOW_WIDTH, window.outerWidth || DEFAULT_WINDOW_WIDTH),
    height: Math.min(availH, Math.ceil(inner + frame)),
  };
}

function rosterNeededSize() {
  const list = $("rosterList");
  const shell = $("rosterShell");
  if (!list || !shell || !state.roster.length) return null;
  const overflow = list.scrollHeight - shell.clientHeight;
  if (overflow <= 8) return null;
  const frame = Math.max(0, (window.outerHeight || 0) - (window.innerHeight || 0)) || 72;
  const availH = screen.availHeight || screen.height || 1080;
  return {
    width: Math.max(DEFAULT_WINDOW_WIDTH, window.outerWidth || DEFAULT_WINDOW_WIDTH),
    height: Math.min(availH, Math.ceil((window.innerHeight || DEFAULT_WINDOW_HEIGHT) + overflow + frame)),
  };
}

function fitSetupWindow() {
  const setup = setupNeededSize();
  const roster = rosterNeededSize();
  const size = {
    width: Math.max(setup?.width || 0, roster?.width || 0, DEFAULT_WINDOW_WIDTH),
    height: Math.max(setup?.height || 0, roster?.height || 0, DEFAULT_WINDOW_HEIGHT),
  };
  return fitWindowTo(size);
}

let fitSetupTimer = 0;
function scheduleFitSetupWindow() {
  clearTimeout(fitSetupTimer);
  fitSetupTimer = setTimeout(() => {
    void fitSetupWindow();
  }, 16);
}

function resetUI() {
  closeModal();
  const helpMenu = $("helpMenu");
  if (helpMenu) helpMenu.classList.add("hidden");
  clearTimeout(showToast._timer);
  const toast = $("toast");
  if (toast) toast.classList.add("hidden");
}

function toggleChip(el, on) {
  el.classList.toggle("on", on);
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/`/g, "&#96;");
}

function formatElapsed(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return "";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m ${String(rem).padStart(2, "0")}s`;
}

function showGenProgress(fraction, message) {
  const wrap = $("genProgress");
  const bar = $("genProgressBar");
  if (!wrap || !bar) return;
  const pct = Math.max(0, Math.min(100, Math.round((Number(fraction) || 0) * 1000) / 10));
  wrap.classList.remove("hidden");
  wrap.setAttribute("aria-hidden", "false");
  wrap.setAttribute("aria-valuenow", String(Math.round(pct)));
  bar.style.width = `${pct}%`;
  if (message) {
    $("status").textContent = message;
    $("status").classList.remove("ok");
  }
}

function hideGenProgress() {
  const wrap = $("genProgress");
  const bar = $("genProgressBar");
  if (wrap) {
    wrap.classList.add("hidden");
    wrap.setAttribute("aria-hidden", "true");
    wrap.setAttribute("aria-valuenow", "0");
  }
  if (bar) bar.style.width = "0%";
}

function syncOutputFormatChips() {
  OUTPUT_FORMATS.forEach((fmt) => {
    const chip = $(`chipFormat${fmt[0].toUpperCase()}${fmt.slice(1)}`);
    if (chip) toggleChip(chip, state.outputFormat === fmt);
  });
}

function buildingStatusText() {
  if (state.outputFormat === "html") return "Building HTML…";
  if (state.outputFormat === "excel") return "Building workbook…";
  return "Building workbook and HTML…";
}

async function setOutputFormat(format, { persist = true } = {}) {
  if (!OUTPUT_FORMATS.includes(format)) return;
  state.outputFormat = format;
  syncOutputFormatChips();
  if (!persist) return;
  try {
    const result = await api("set_output_format", format);
    if (result && result.outputFormat) state.outputFormat = result.outputFormat;
    syncOutputFormatChips();
  } catch (_) {
    /* preference save is best-effort */
  }
}

let eventsBound = false;
let startupUpdateChecked = false;

async function initApp() {
  resetUI();
  bindEvents();
  syncOutputFormatChips();
  refreshUI();

  if (!window.pywebview || !pywebview.api) return;

  try {
    const info = await api("get_version");
    $("versionBadge").textContent = `v${info.version}`;
    if (info.logoDataUri) {
      $("logo").src = info.logoDataUri;
      const favicon = $("favicon");
      if (favicon) favicon.href = info.logoDataUri;
    }
  } catch (_) {
    $("versionBadge").textContent = "";
  }

  try {
    const prefs = await api("get_gui_prefs");
    if (prefs && prefs.outputFormat) {
      await setOutputFormat(prefs.outputFormat, { persist: false });
    }
  } catch (_) {
    /* defaults already applied */
  }

  void loadTierColorPanel();
  void checkForUpdatesOnStartup();
}

function startWindowDrag(event) {
  if (event.button !== 0) return;
  if (event.target.closest("button, a, input, select, textarea, label")) return;
  event.preventDefault();
  void api("start_window_drag");
}

function bindEvents() {
  if (eventsBound) return;
  eventsBound = true;

  const header = document.querySelector(".app-header");
  if (header) header.addEventListener("mousedown", startWindowDrag);

  $("helpBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    $("helpMenu").classList.toggle("hidden");
  });
  document.addEventListener("click", () => $("helpMenu").classList.add("hidden"));
  $("helpMenu").addEventListener("click", (e) => e.stopPropagation());

  $("helpTiers").addEventListener("click", () => {
    $("helpMenu").classList.add("hidden");
    showHelpTiers();
  });
  $("helpUpdates").addEventListener("click", () => {
    $("helpMenu").classList.add("hidden");
    checkForUpdates();
  });
  $("helpClearCache").addEventListener("click", () => {
    $("helpMenu").classList.add("hidden");
    showClearCacheConfirm();
  });
  $("helpAbout").addEventListener("click", async () => {
    $("helpMenu").classList.add("hidden");
    showAbout();
  });

  $("btnFolder").addEventListener("click", browseFolder);
  $("rosterList").addEventListener("dragover", onRosterDragOver);
  $("rosterList").addEventListener("drop", (e) => e.preventDefault());
  $("btnUp").addEventListener("click", () => moveRoster(-1));
  $("btnDown").addEventListener("click", () => moveRoster(1));
  $("btnRemove").addEventListener("click", removeSelected);
  $("btnClear").addEventListener("click", clearAll);
  $("btnBrowse").addEventListener("click", browseOutput);
  $("btnGenerate").addEventListener("click", generateReport);
  $("btnResetTierColors").addEventListener("click", resetTierColorsFromPanel);

  $("chipSpells").addEventListener("click", () => {
    if ($("chipSpells").disabled) return;
    state.includeSpells = !state.includeSpells;
    toggleChip($("chipSpells"), state.includeSpells);
    updateStatus();
  });
  $("chipAchievements").addEventListener("click", () => {
    if ($("chipAchievements").disabled) return;
    state.includeAchievements = !state.includeAchievements;
    toggleChip($("chipAchievements"), state.includeAchievements);
    updateStatus();
  });
  $("chipSlot2Augs").addEventListener("click", () => {
    if ($("chipSlot2Augs").disabled) return;
    state.includeSlot2 = !state.includeSlot2;
    toggleChip($("chipSlot2Augs"), state.includeSlot2);
    syncSlot2Options();
    updateStatus();
  });
  $("chipType5Augs").addEventListener("click", () => {
    if ($("chipType5Augs").disabled) return;
    state.includeType5 = !state.includeType5;
    toggleChip($("chipType5Augs"), state.includeType5);
    updateStatus();
  });
  $("chipType18Augs").addEventListener("click", () => {
    if ($("chipType18Augs").disabled) return;
    state.includeType18 = !state.includeType18;
    toggleChip($("chipType18Augs"), state.includeType18);
    updateStatus();
  });
  $("chipRaidBis").addEventListener("click", () => {
    if ($("chipRaidBis").disabled) return;
    state.includeRaidBis = !state.includeRaidBis;
    toggleChip($("chipRaidBis"), state.includeRaidBis);
    updateStatus();
  });
  $("includeAnniversary").addEventListener("change", () => {
    state.includeAnniversary = $("includeAnniversary").checked;
  });
  $("tabAugOptions").addEventListener("click", () => setOptionsTab("options"));
  $("tabAdvancedWeights").addEventListener("click", () => setOptionsTab("advanced"));
  bindAdvancedWeightsTip();
  $("useWeightOverrides").addEventListener("change", () => {
    state.useWeightOverrides = $("useWeightOverrides").checked;
    renderWeightGrid();
    syncOptionsTabs(state.roster.length === 1);
  });
  $("btnResetWeights").addEventListener("click", () => { void resetWeightDefaults(); });
  OUTPUT_FORMATS.forEach((fmt) => {
    const chip = $(`chipFormat${fmt[0].toUpperCase()}${fmt.slice(1)}`);
    if (!chip) return;
    chip.addEventListener("click", () => {
      void setOutputFormat(fmt);
    });
  });
}

async function browseFolder() {
  try {
    const folder = await api("pick_folder");
    if (!folder) return;
    const data = await api("discover_folder_choices", folder);
    if (!data.choices.length) {
      showToast(`No inventory, spell, or achievement files found in:\n${folder}`, true);
      return;
    }
    showFolderPicker(data);
  } catch (err) {
    showToast(String(err), true);
  }
}

function showFolderPicker(data) {
  const serverOptions = ['<option value="">All servers</option>']
    .concat(data.servers.map((s) => `<option value="${escapeAttr(s.slug)}">${escapeHtml(s.label)} (${escapeHtml(s.slug)})</option>`))
    .join("");

  const rows = data.choices.map((c, i) => `
    <label class="picker-item" data-server="${escapeAttr(c.server)}" data-index="${i}">
      <input type="checkbox" checked data-index="${i}">
      <div class="picker-body">
        <div class="char-card-host" data-choice-index="${i}"></div>
        ${c.summary ? `<div class="picker-summary">${escapeHtml(c.summary)}</div>` : ""}
      </div>
    </label>`).join("");

  showModal(`
    <div class="modal wide">
      <div class="modal-header">
        <h2>Characters in folder</h2>
        <div class="path">${escapeHtml(data.folder)}</div>
        <p style="margin:8px 0 0;font-size:12px;color:var(--muted)">Choose which characters to add. Spell files in SpellData are grouped with each character.</p>
      </div>
      <div class="modal-body">
        <div class="picker-filter">
          <div class="field-label">Server</div>
          <select id="pickerServer">${serverOptions}</select>
        </div>
        <div class="field-label">Characters</div>
        <div class="picker-list" id="pickerList">${rows}</div>
        <div class="toolbar" style="margin-top:10px">
          <button type="button" class="btn btn-secondary" id="pickerAll">Select all</button>
          <button type="button" class="btn btn-secondary" id="pickerNone">Select none</button>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" id="pickerCancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="pickerAdd">Add selected</button>
      </div>
    </div>`);

  data.choices.forEach((c, i) => {
    const host = document.querySelector(`.char-card-host[data-choice-index="${i}"]`);
    if (!host) return;
    host.appendChild(
      ClassVisuals.createCard({
        character: c.character,
        classAbbr: c.classAbbr,
        server: c.server,
        serverDisplay: c.serverDisplay,
      })
    );
  });

  const visiblePickerItems = () =>
    Array.from(document.querySelectorAll(".picker-item:not(.hidden-row)"));

  const filterRows = () => {
    const slug = $("pickerServer").value;
    document.querySelectorAll(".picker-item").forEach((row) => {
      const match = !slug || row.dataset.server.toLowerCase() === slug.toLowerCase();
      row.classList.toggle("hidden-row", !match);
    });
    void fitWindowTo(folderPickerNeededSize());
  };
  $("pickerServer").addEventListener("change", filterRows);
  filterRows();

  $("pickerAll").addEventListener("click", () => {
    visiblePickerItems().forEach((row) => {
      row.querySelector("input").checked = true;
    });
  });
  $("pickerNone").addEventListener("click", () => {
    visiblePickerItems().forEach((row) => {
      row.querySelector("input").checked = false;
    });
  });
  $("pickerCancel").addEventListener("click", closeModal);
  $("pickerAdd").addEventListener("click", () => {
    const selected = [];
    visiblePickerItems().forEach((row) => {
      const cb = row.querySelector("input");
      if (!cb || !cb.checked) return;
      const idx = Number(cb.dataset.index);
      selected.push(data.choices[idx]);
    });
    if (!selected.length) {
      showToast("Select at least one character.", true);
      return;
    }
    const newPaths = [];
    selected.forEach((c) => newPaths.push(...c.paths));
    addPaths(newPaths);
    closeModal();
  });
}

async function addPaths(paths) {
  let added = false;
  for (const raw of paths) {
    if (!state.filePaths.includes(raw)) {
      state.filePaths.push(raw);
      added = true;
    }
  }
  if (!added) return;
  state.filePaths.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  await rebuildRoster();
  await refreshToggles();
  await refreshOutputDefault();
  refreshUI();
}

async function rebuildRoster() {
  if (!state.filePaths.length) {
    state.roster = [];
    return;
  }
  state.roster = await api("build_roster", state.filePaths);
}

async function refreshToggles() {
  const spellsBtn = $("chipSpells");
  const achBtn = $("chipAchievements");
  if (!state.filePaths.length) {
    state.includeSpells = false;
    state.includeAchievements = false;
    state.includeSlot2 = false;
    state.includeType5 = false;
    state.includeType18 = false;
    state.includeRaidBis = false;
    spellsBtn.disabled = true;
    achBtn.disabled = true;
    const slot2Btn = $("chipSlot2Augs");
    slot2Btn.disabled = true;
    const type5Btn = $("chipType5Augs");
    type5Btn.disabled = true;
    const type18Btn = $("chipType18Augs");
    type18Btn.disabled = true;
    const raidBisBtn = $("chipRaidBis");
    raidBisBtn.disabled = true;
    toggleChip(spellsBtn, false);
    toggleChip(achBtn, false);
    toggleChip(slot2Btn, false);
    toggleChip(type5Btn, false);
    toggleChip(type18Btn, false);
    toggleChip(raidBisBtn, false);
    syncSlot2Options();
    return;
  }
  const spellInfo = await api("spell_bindings", state.filePaths);
  const achInfo = await api("achievement_info", state.filePaths);
  spellsBtn.disabled = false;
  achBtn.disabled = false;
  const slot2Btn = $("chipSlot2Augs");
  slot2Btn.disabled = false;
  const type5Btn = $("chipType5Augs");
  type5Btn.disabled = false;
  const type18Btn = $("chipType18Augs");
  type18Btn.disabled = false;
  const raidBisBtn = $("chipRaidBis");
  raidBisBtn.disabled = false;
  state.includeSpells = spellInfo.hasSpells;
  state.includeAchievements = achInfo.hasAchievements;
  state.includeSlot2 = true;
  state.includeType5 = true;
  state.includeType18 = true;
  state.includeRaidBis = true;
  toggleChip(spellsBtn, state.includeSpells);
  toggleChip(achBtn, state.includeAchievements);
  toggleChip(slot2Btn, state.includeSlot2);
  toggleChip(type5Btn, state.includeType5);
  toggleChip(type18Btn, state.includeType18);
  toggleChip(raidBisBtn, state.includeRaidBis);
  syncSlot2Options();
}

async function refreshOutputDefault() {
  const current = $("outputPath").value;
  const next = await api("default_output_path", state.filePaths, current);
  $("outputPath").value = next;
}

let rosterSuppressClick = false;
let rosterDragFrom = null;
let rosterDropInsert = null;

function canDragRoster() {
  return !state.generating && state.roster.length > 1;
}

function rosterNameItems() {
  return [...document.querySelectorAll("#rosterList .roster-item")];
}

function clearRosterDropSlot() {
  document.querySelectorAll("#rosterList .roster-drop-slot").forEach((el) => el.remove());
  document.querySelectorAll(".drop-spread-above, .drop-spread-below, .drop-pair").forEach((el) => {
    el.classList.remove("drop-spread-above", "drop-spread-below", "drop-pair");
  });
  const list = $("rosterList");
  if (list) list.classList.remove("roster-dragging");
}

function rosterInsertIndexAt(clientY) {
  const items = rosterNameItems();
  for (let i = 0; i < items.length; i++) {
    const rect = items[i].getBoundingClientRect();
    if (clientY < rect.top + rect.height / 2) return i;
  }
  return items.length;
}

function showRosterDropSlot(insertIndex) {
  const list = $("rosterList");
  if (!list) return;
  const items = rosterNameItems();
  const from = rosterDragFrom;
  const samePlace = from != null && (insertIndex === from || insertIndex === from + 1);
  list.classList.add("roster-dragging");

  if (samePlace) {
    document.querySelectorAll("#rosterList .roster-drop-slot").forEach((el) => el.remove());
    document.querySelectorAll(".drop-spread-above, .drop-spread-below, .drop-pair").forEach((el) => {
      el.classList.remove("drop-spread-above", "drop-spread-below", "drop-pair");
    });
    rosterDropInsert = from;
    return;
  }

  if (rosterDropInsert === insertIndex && list.querySelector(".roster-drop-slot")) return;
  rosterDropInsert = insertIndex;

  document.querySelectorAll(".drop-spread-above, .drop-spread-below, .drop-pair").forEach((el) => {
    el.classList.remove("drop-spread-above", "drop-spread-below", "drop-pair");
  });

  let slot = list.querySelector(".roster-drop-slot");
  if (!slot) {
    slot = document.createElement("li");
    slot.className = "roster-drop-slot";
    slot.setAttribute("aria-hidden", "true");
  }
  const target = items[insertIndex] || null;
  if (target) list.insertBefore(slot, target);
  else list.appendChild(slot);

  const above = insertIndex > 0 ? items[insertIndex - 1] : null;
  const below = insertIndex < items.length ? items[insertIndex] : null;
  if (above) above.classList.add("drop-spread-below");
  if (below) below.classList.add("drop-spread-above");
  if (above && below) {
    above.classList.add("drop-pair");
    below.classList.add("drop-pair");
  }
}

function onRosterDragOver(e) {
  if (rosterDragFrom == null) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
  showRosterDropSlot(rosterInsertIndexAt(e.clientY));
}

function moveRosterEntry(entries, from, insertAt) {
  const next = entries.slice();
  const [item] = next.splice(from, 1);
  let dest = insertAt;
  if (from < insertAt) dest -= 1;
  dest = Math.max(0, Math.min(next.length, dest));
  next.splice(dest, 0, item);
  return { next, dest };
}

function renderRoster() {
  const list = $("rosterList");
  list.innerHTML = "";
  const servers = new Set(state.roster.map((e) => (e.server || "").toLowerCase()));
  const showServer = servers.size > 1;
  const draggable = canDragRoster();
  state.roster.forEach((entry, idx) => {
    const li = document.createElement("li");
    li.className = "roster-item";
    li.dataset.index = String(idx);
    li.draggable = draggable;
    if (draggable) li.title = "Drag to reorder";
    if (state.selectedRoster.has(idx)) li.classList.add("selected");
    if (draggable) {
      const grip = document.createElement("span");
      grip.className = "roster-grip";
      grip.setAttribute("aria-hidden", "true");
      li.appendChild(grip);
    }
    li.appendChild(
      ClassVisuals.createCard({
        character: entry.character,
        classAbbr: entry.classAbbr,
        server: showServer ? entry.server : null,
      })
    );
    li.addEventListener("click", (e) => {
      if (rosterSuppressClick) {
        rosterSuppressClick = false;
        return;
      }
      if (e.ctrlKey || e.metaKey) {
        if (state.selectedRoster.has(idx)) state.selectedRoster.delete(idx);
        else state.selectedRoster.add(idx);
      } else {
        state.selectedRoster.clear();
        state.selectedRoster.add(idx);
      }
      renderRoster();
    });
    if (draggable) bindRosterItemDrag(li);
    list.appendChild(li);
  });
  $("emptyState").classList.toggle("hidden", state.roster.length > 0);
}

function bindRosterItemDrag(li) {
  li.addEventListener("dragstart", (e) => {
    if (!canDragRoster()) {
      e.preventDefault();
      return;
    }
    rosterSuppressClick = true;
    rosterDragFrom = Number(li.dataset.index);
    rosterDropInsert = rosterDragFrom;
    li.classList.add("dragging");
    $("rosterList")?.classList.add("roster-dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", li.dataset.index || "");
  });
  li.addEventListener("dragover", onRosterDragOver);
  li.addEventListener("drop", (e) => {
    e.preventDefault();
  });
  li.addEventListener("dragend", () => {
    void finishRosterDrag();
    setTimeout(() => {
      rosterSuppressClick = false;
    }, 0);
  });
}

async function finishRosterDrag() {
  const from = rosterDragFrom;
  const insertAt = rosterDropInsert;
  const dragged = document.querySelector("#rosterList .roster-item.dragging");
  if (dragged) dragged.classList.remove("dragging");
  clearRosterDropSlot();
  rosterDragFrom = null;
  rosterDropInsert = null;

  if (from == null || insertAt == null || from === insertAt) {
    renderRoster();
    return;
  }
  const { next, dest } = moveRosterEntry(state.roster, from, insertAt);
  const unchanged = next.every((entry, i) => entry === state.roster[i]);
  state.roster = next;
  state.selectedRoster.clear();
  state.selectedRoster.add(dest);
  if (!unchanged) {
    await api("save_roster_order", state.roster.map((e) => e.personaKey));
  }
  renderRoster();
}

async function moveRoster(delta) {
  if (state.selectedRoster.size !== 1) return;
  const index = [...state.selectedRoster][0];
  const newIndex = index + delta;
  if (newIndex < 0 || newIndex >= state.roster.length) return;
  const [item] = state.roster.splice(index, 1);
  state.roster.splice(newIndex, 0, item);
  state.selectedRoster.clear();
  state.selectedRoster.add(newIndex);
  await api("save_roster_order", state.roster.map((e) => e.personaKey));
  renderRoster();
}

async function removeSelected() {
  if (!state.selectedRoster.size) return;
  const removing = [...state.selectedRoster].map((i) => state.roster[i]);
  const removingKeys = removing.map((e) => e.personaKey);
  const dropPaths = await api("paths_for_removal", removingKeys, state.roster, state.filePaths);
  state.filePaths = state.filePaths.filter((p) => !dropPaths.includes(p));
  state.selectedRoster.clear();
  await rebuildRoster();
  await refreshToggles();
  await refreshOutputDefault();
  refreshUI();
}

async function clearAll() {
  if (!state.filePaths.length) return;
  if (!confirm("Remove all characters from the list?")) return;
  state.filePaths = [];
  state.roster = [];
  state.selectedRoster.clear();
  await refreshToggles();
  refreshUI();
}

async function browseOutput() {
  try {
    const folder = await api("pick_output_folder", $("outputPath").value);
    if (!folder) return;
    const next = await api("default_output_path", state.filePaths, folder);
    $("outputPath").value = next;
  } catch (err) {
    showToast(String(err), true);
  }
}

async function updateStatus() {
  const status = $("status");
  status.classList.remove("ok");
  if (!state.filePaths.length) {
    status.textContent = "Ready • No files loaded";
    return;
  }
  const split = await api("split_paths", state.filePaths);
  const parts = [];
  if (split.inventory.length) parts.push(`${split.inventory.length} inventory`);
  if (split.spells.length) parts.push(`${split.spells.length} MissingSpells`);
  if (split.achievements.length) parts.push(`${split.achievements.length} Achievements`);
  const summary = parts.join(", ") || `${state.filePaths.length} files`;
  let text = state.filePaths.length === 1
    ? `Ready • ${basename(state.filePaths[0])} (${summary})`
    : `Ready • ${state.filePaths.length} files (${summary})`;

  if (state.includeSpells) {
    const spellInfo = await api("spell_bindings", state.filePaths);
    if (spellInfo.spellCount) {
      const label = spellInfo.usePersonaLabel ? "persona" : "character";
      const plural = spellInfo.spellCount !== 1 ? "s" : "";
      text += ` • ${spellInfo.spellCount} spell ${label}${plural}`;
    }
    if (spellInfo.warnings.length) {
      text += ` • ${spellInfo.warnings.length} warning(s)`;
    }
  }
  if (state.includeAchievements) {
    const achInfo = await api("achievement_info", state.filePaths);
    if (achInfo.achievementCount) {
      const label = achInfo.achievementCount === 1 ? "achievement file" : "achievement files";
      text += ` • ${achInfo.achievementCount} ${label}`;
    }
  }
  if (state.includeSlot2) text += " • Type 7/8 Augs";
  if (state.includeType5) text += " • Type 5 Augs";
  if (state.includeType18) text += " • Type 18/19 Augs";
  if (state.includeRaidBis) text += " • Raid BiS";
  status.textContent = text;
}

function setGenerating(on) {
  state.generating = on;
  $("btnGenerate").disabled = on;
  $("btnFolder").disabled = on;
  $("btnUp").disabled = on;
  $("btnDown").disabled = on;
  $("btnRemove").disabled = on;
  $("btnClear").disabled = on;
  $("btnBrowse").disabled = on;
  OUTPUT_FORMATS.forEach((fmt) => {
    const chip = $(`chipFormat${fmt[0].toUpperCase()}${fmt.slice(1)}`);
    if (chip) chip.disabled = on;
  });
  renderRoster();
  syncSlot2Options();
}

function hideInfoBubble() {
  const bubble = $("infoBubble");
  if (bubble) bubble.classList.add("hidden");
}

function bindAdvancedWeightsTip() {
  const wrap = $("tabAdvancedWeightsWrap");
  if (!wrap || wrap.dataset.tipBound) return;
  wrap.dataset.tipBound = "1";
  wrap.addEventListener("mouseenter", () => {
    if (!wrap.classList.contains("show-tip")) return;
    let bubble = $("infoBubble");
    if (!bubble) {
      bubble = document.createElement("div");
      bubble.id = "infoBubble";
      bubble.className = "info-bubble hidden";
      document.body.appendChild(bubble);
    }
    bubble.textContent = wrap.dataset.tip || "Only used for single characters.";
    bubble.classList.remove("hidden");
    const r = wrap.getBoundingClientRect();
    bubble.style.left = `${Math.round(r.left + r.width / 2)}px`;
    bubble.style.top = `${Math.round(r.bottom + 8)}px`;
  });
  wrap.addEventListener("mouseleave", hideInfoBubble);
}

function syncSlot2Options() {
  const wrap = $("slot2Options");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !state.includeSlot2 || !state.filePaths.length);
  syncOptionsTabs(state.roster.length === 1);
}

function setOptionsTab(tab) {
  const single = state.roster.length === 1;
  if (tab === "advanced" && !single) tab = "options";
  state.optionsTab = tab;
  syncOptionsTabs(single);
  if (tab === "advanced") void ensureWeightDefaultsLoaded();
}

function syncOptionsTabs(single) {
  const tabOptions = $("tabAugOptions");
  const tabAdvanced = $("tabAdvancedWeights");
  const paneOptions = $("paneAugOptions");
  const paneAdvanced = $("paneAdvancedWeights");
  const hint = $("advancedWeightsHint");
  if (!tabOptions || !tabAdvanced || !paneOptions || !paneAdvanced) return;

  if (!single && state.optionsTab === "advanced") {
    state.optionsTab = "options";
    state.useWeightOverrides = false;
    state.weightDefaults = null;
    state.weightEdits = null;
    state.weightsClassKey = null;
  }

  tabAdvanced.disabled = !single || state.generating || !state.includeSlot2;
  const useOv = $("useWeightOverrides");
  if (useOv) {
    useOv.disabled = !single || state.generating || !state.includeSlot2;
    useOv.checked = state.useWeightOverrides && single;
  }
  const resetBtn = $("btnResetWeights");
  if (resetBtn) {
    resetBtn.disabled = !single || state.generating || !state.useWeightOverrides;
  }
  const onAdvanced = state.optionsTab === "advanced" && single && state.includeSlot2;
  tabOptions.classList.toggle("on", !onAdvanced);
  tabAdvanced.classList.toggle("on", onAdvanced);
  tabOptions.setAttribute("aria-selected", String(!onAdvanced));
  tabAdvanced.setAttribute("aria-selected", String(onAdvanced));
  const tipWrap = $("tabAdvancedWeightsWrap");
  if (tipWrap) {
    const showMultiTip = !single && state.includeSlot2 && state.filePaths.length;
    tipWrap.classList.toggle("show-tip", showMultiTip);
    if (showMultiTip) {
      tipWrap.dataset.tip = "Only used for single characters.";
    } else {
      delete tipWrap.dataset.tip;
      hideInfoBubble();
    }
  }
  paneOptions.classList.toggle("hidden", onAdvanced);
  paneAdvanced.classList.toggle("hidden", !onAdvanced);
  if (hint) {
    hint.textContent = single
      ? "Edit class default scoring weights for this file. 0-10"
      : "Available with exactly one character on the roster.";
  }
  if (onAdvanced) void ensureWeightDefaultsLoaded();
  scheduleFitSetupWindow();
}

async function ensureWeightDefaultsLoaded() {
  if (state.optionsTab !== "advanced" || state.roster.length !== 1) return;
  const entry = state.roster[0];
  const classKey = entry.classAbbr || "";
  if (state.weightsClassKey === classKey && state.weightDefaults && state.weightEdits) {
    renderWeightGrid();
    return;
  }
  try {
    const info = await api("get_class_weight_defaults", classKey || null, null);
    state.weightDefaults = info;
    state.weightEdits = { ...(info.weights || {}) };
    state.weightsClassKey = classKey;
    renderWeightGrid();
  } catch (err) {
    showToast(String(err.message || err), true);
  }
}

function renderWeightGrid() {
  const grid = $("weightGrid");
  const meta = $("advancedWeightsMeta");
  if (!grid || !meta) return;
  const info = state.weightDefaults;
  if (!info) {
    meta.textContent = "Loading defaults…";
    grid.innerHTML = "";
    return;
  }
  const cls = info.classAbbr || "unknown";
  const role = info.role || "—";
  meta.innerHTML = `Profile: <strong>${escapeHtml(info.profileLabel || info.profile)}</strong>
    · Class: <strong>${escapeHtml(cls)}</strong>
    · Role: <strong>${escapeHtml(role)}</strong>`;
  const labels = info.labels || {};
  const edits = state.weightEdits || {};
  const keys = Object.keys(info.weights || {});
  grid.innerHTML = "";
  keys.forEach((key) => {
    const row = document.createElement("label");
    row.className = "weight-row";
    const label = labels[key] || key;
    const val = edits[key] != null ? edits[key] : 0;
    row.innerHTML = `<span title="${escapeAttr(key)}">${escapeHtml(label)}</span>
      <input type="number" step="0.1" data-stat="${escapeAttr(key)}" value="${escapeAttr(val)}">`;
    const input = row.querySelector("input");
    input.disabled = !state.useWeightOverrides || state.generating;
    input.addEventListener("change", () => {
      const n = Number(input.value);
      if (!Number.isFinite(n)) return;
      state.weightEdits = state.weightEdits || {};
      state.weightEdits[key] = n;
    });
    grid.appendChild(row);
  });
  scheduleFitSetupWindow();
}

async function resetWeightDefaults() {
  if (state.optionsTab !== "advanced" || state.roster.length !== 1) return;
  state.weightsClassKey = null;
  await ensureWeightDefaultsLoaded();
  const status = $("advancedResetStatus");
  if (!status) return;
  status.textContent = "Weights reset to class defaults";
  status.classList.add("on");
  clearTimeout(resetWeightDefaults._timer);
  resetWeightDefaults._timer = setTimeout(() => {
    status.classList.remove("on");
  }, 2200);
}

async function generateReport() {
  if (state.generating) return;
  const outputPath = $("outputPath").value.trim();
  const split = await api("split_paths", state.filePaths);
  if (!split.inventory.length) {
    showToast("Add at least one *-Inventory.txt file (MissingSpells alone is not enough).", true);
    return;
  }
  if (!outputPath) {
    showToast("Choose where to save the report.", true);
    return;
  }

  setGenerating(true);
  $("status").classList.remove("ok");
  $("status").textContent = buildingStatusText();
  if (state.includeSlot2) showGenProgress(0, "Fetching from EQ Resource…");
  else if (state.includeType5) showGenProgress(0, "Fetching from EQ Resource…");
  else if (state.includeType18) showGenProgress(0, "Fetching from EQ Resource…");
  else if (state.includeRaidBis) showGenProgress(0, "Fetching from EQ Resource…");

  const useAdvanced =
    state.includeSlot2 &&
    state.roster.length === 1 &&
    state.useWeightOverrides &&
    state.weightEdits &&
    Object.keys(state.weightEdits).length > 0;
  const config = {
    paths: state.filePaths,
    outputPath,
    slotFilter: "all",
    includeSpells: state.includeSpells,
    includeAchievements: state.includeAchievements,
    includeSlot2: state.includeSlot2,
    includeType5: state.includeType5,
    includeType18: state.includeType18,
    includeRaidBis: state.includeRaidBis,
    includeAnniversary: state.includeAnniversary,
    advancedWeights: !!useAdvanced,
    sessionWeights: useAdvanced ? { ...(state.weightEdits || {}) } : null,
    outputFormat: state.outputFormat,
    characterColumnOrder: state.roster.map((e) => e.personaKey),
  };

  try {
    await api("generate_report", config);
  } catch (err) {
    setGenerating(false);
    hideGenProgress();
    resetUI();
    $("status").textContent = "Export failed.";
    showErrorDialog(err, "Export failed");
  }
}

window.onGenerateProgress = function (payload) {
  if (!payload) return;
  showGenProgress(payload.fraction, payload.message);
};

window.onGenerateComplete = async function (result) {
  setGenerating(false);
  hideGenProgress();
  resetUI();
  if (!result.ok) {
    $("status").textContent = "Export failed.";
    const msg = result.error || "Export failed.";
    showErrorDialog(msg, "Export failed");
    return;
  }
  $("status").classList.add("ok");
  const n = (state.roster && state.roster.length) || 0;
  const elapsed = formatElapsed(result.elapsedSeconds);
  const doneName = result.xlsx
    ? basename(result.xlsx)
    : result.html
      ? basename(result.html)
      : "report";
  const extra = elapsed
    ? `Done • ${n} character(s) • ${elapsed}`
    : `Done — ${doneName}`;
  $("status").textContent = extra;

  const savedLines = [];
  if (result.xlsx) savedLines.push(result.xlsx);
  if (result.html) savedLines.push(result.html);
  let msg = savedLines.length ? `Saved:\n${savedLines.join("\n")}` : "Saved.";
  if (result.warnings && result.warnings.length) {
    msg += "\n\n" + result.warnings.join("\n");
  }
  showToast(msg.replace(/\n/g, " • "));

  if (result.html) {
    try {
      await api("open_html_report", result.html);
    } catch (err) {
      const detail = errorText(err) || String(err);
      showErrorDialog(`Report saved but browser failed to open: ${detail}`, "Could not open report");
    }
  }
};

function refreshUI() {
  renderRoster();
  syncSlot2Options();
  updateStatus();
  scheduleFitSetupWindow();
}

function modalAlreadyOpen() {
  return Boolean($("modalRoot") && $("modalRoot").innerHTML.trim());
}

function showUpdateAvailableModal(info) {
  if (!info || !info.downloadUrl) return;
  const latest = escapeHtml(info.latest || "");
  const current = escapeHtml(info.current || "");
  showModal(`
    <div class="modal">
      <div class="modal-header"><h2>Update available</h2></div>
      <div class="modal-body">
        <p>A newer version of EQGM is available.</p>
        <p style="margin-top:12px">Current version: <strong>${current}</strong></p>
        <p>Newest version: <strong>${latest}</strong></p>
        <p style="margin-top:12px">Would you like to download the latest version?</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" id="updateNo">No</button>
        <button type="button" class="btn btn-primary" id="updateYes">Yes</button>
      </div>
    </div>`);
  $("updateNo").addEventListener("click", closeModal);
  $("updateYes").addEventListener("click", async () => {
    try {
      const result = await api("open_update_download", info.downloadUrl);
      if (!result || !result.ok) {
        showToast((result && result.error) || "Could not open the download.", true);
        return;
      }
      closeModal();
    } catch (err) {
      showToast(err && err.message ? err.message : String(err), true);
    }
  });
}

async function checkForUpdatesOnStartup() {
  if (startupUpdateChecked) return;
  startupUpdateChecked = true;
  let info;
  try {
    info = await api("check_for_updates");
  } catch (_) {
    return;
  }
  if (!info || info.status !== "update" || !info.downloadUrl) return;
  if (modalAlreadyOpen()) return;
  showUpdateAvailableModal(info);
}

async function checkForUpdates() {
  showModal(`
    <div class="modal">
      <div class="modal-header"><h2>Check for Updates</h2></div>
      <div class="modal-body"><p>Checking for updates…</p></div>
    </div>`);
  let info;
  try {
    info = await api("check_for_updates");
  } catch (err) {
    info = { ok: false, status: "error", message: err && err.message ? err.message : String(err) };
  }
  if (!info || info.status === "error" || info.ok === false) {
    const detail = info && info.message ? escapeHtml(info.message) : "Could not reach GitHub Releases.";
    showModal(`
      <div class="modal">
        <div class="modal-header"><h2>Check for Updates</h2></div>
        <div class="modal-body">
          <p>Could not check for updates.</p>
          <p style="margin-top:12px;color:var(--muted);font-size:12px">${detail}</p>
        </div>
        <div class="modal-footer"><button type="button" class="btn" id="modalClose">Close</button></div>
      </div>`);
    $("modalClose").addEventListener("click", closeModal);
    return;
  }
  if (info.status === "latest") {
    const current = escapeHtml(info.current || "");
    const latest = escapeHtml(info.latest || current);
    showModal(`
      <div class="modal">
        <div class="modal-header"><h2>Check for Updates</h2></div>
        <div class="modal-body">
          <p>You have the latest version.</p>
          <p style="margin-top:12px">Current version: <strong>${current}</strong></p>
          <p>Newest version: <strong>${latest}</strong></p>
        </div>
        <div class="modal-footer"><button type="button" class="btn" id="modalClose">Close</button></div>
      </div>`);
    $("modalClose").addEventListener("click", closeModal);
    return;
  }
  showUpdateAvailableModal(info);
}

function showClearCacheConfirm() {
  showModal(`
    <div class="modal">
      <div class="modal-header"><h2>Clear Cache</h2></div>
      <div class="modal-body">
        <p>EQGM stores catalog, item, and icon data under <code>%LOCALAPPDATA%\\EQGM\\</code>
          so Generate Report can skip re-fetching. Clearing it deletes that data.</p>
        <p style="margin-top:12px">Settings, folder, colors, weight overrides, and last_report.log are kept.</p>
        <p style="margin-top:12px"><strong>The cache will be rebuilt the next time you generate a report</strong>
          (needs network).</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" id="clearCacheCancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="clearCacheConfirm">Clear Cache</button>
      </div>
    </div>`);
  $("clearCacheCancel").addEventListener("click", closeModal);
  $("clearCacheConfirm").addEventListener("click", async () => {
    try {
      const result = await api("clear_cache");
      if (!result || !result.ok) {
        showToast((result && result.error) || "Could not clear the cache.", true);
        return;
      }
      closeModal();
      const n = Array.isArray(result.deleted) ? result.deleted.length : 0;
      if (n === 0) {
        showToast("No cache files to clear.");
      } else {
        showToast(`Cleared ${n} cache item${n === 1 ? "" : "s"}. Rebuilds on next Generate Report.`);
      }
      if (result.errors && result.errors.length) {
        showToast(result.errors[0], true);
      }
    } catch (err) {
      showToast(err && err.message ? err.message : String(err), true);
    }
  });
}

async function openWebsite() {
  try {
    const result = await api("open_website");
    if (!result || !result.ok) {
      showToast((result && result.error) || "Could not open the website.", true);
    }
  } catch (err) {
    showToast(err && err.message ? err.message : String(err), true);
  }
}

async function showAbout() {
  const info = await api("get_version");
  const version = escapeHtml(info.version || "");
  showModal(`
    <div class="modal">
      <div class="modal-header"><h2>About EQ Gear Management</h2></div>
      <div class="modal-body">
        <p><strong>EQGM ${version}</strong></p>
        <p style="margin-top:12px;color:var(--muted);font-size:12px">
          Builds team Excel workbooks and optional HTML reports from EverQuest
          /outputfile inventory, spell, and achievement files.
        </p>
        <p style="margin-top:8px;font-size:12px;color:var(--muted)">
          Sheets include Team Gear, Gear T-Level, Missing Runes, Missing Spells,
          Rune Inventory, Unmade Gear, achievements, augs, Raid BiS, and more.
        </p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-primary" id="aboutWebsite">Website</button>
        <button type="button" class="btn" id="modalClose">Close</button>
      </div>
    </div>`);
  $("modalClose").addEventListener("click", closeModal);
  $("aboutWebsite").addEventListener("click", () => openWebsite());
}

async function showHelpTiers() {
  const data = await api("tier_legend");
  const rows = (data.rows || []).map((r) => `
    <div class="legend-row">
      <div class="legend-swatch" style="background:#${escapeHtml(String(r.color || ""))}"></div>
      <span>${escapeHtml(r.label)}</span>
    </div>`).join("");

  showModal(`
    <div class="modal wide">
      <div class="modal-header"><h2>Gear tier colors</h2></div>
      <div class="modal-body">
        <p style="color:var(--muted);font-size:12px;margin-top:0">Semantic tier buckets. Team Gear and Gear T-Level use the same cell colors.${data.isCustom ? " Showing your custom palette." : ""}</p>
        ${rows}
        <p style="margin-top:12px;font-size:12px;color:var(--muted)">
          Evolver: equipped items whose inventory file includes the final augment row. Tier is resolved first;
          Evolver only when the item has no recognized tier pattern.
        </p>
        <p style="font-size:12px;color:var(--muted)">Unlisted items show as red (???). Team Gear names and Gear T-Level codes link to EQ Resource; hover a name or T-code for an inspect card.</p>
        <p style="margin-top:12px;font-size:12px;color:var(--muted)">Change colors in the Gear tier colors panel on the main screen.</p>
        <p style="margin-top:16px;font-weight:600">Visible vs non-visible slots</p>
        <p style="font-size:12px">Visible: ${data.visibleSlots.join(", ")}</p>
        <p style="font-size:12px">Non-visible: ${data.nonVisibleSlots.join(", ")}</p>
      </div>
      <div class="modal-footer"><button type="button" class="btn" id="modalClose">Close</button></div>
    </div>`);
  $("modalClose").addEventListener("click", closeModal);
}

async function loadTierColorPanel() {
  const grid = $("tierColorGrid");
  if (!grid) return;
  let data;
  try {
    data = await api("tier_legend");
  } catch (_) {
    return;
  }
  renderTierColorPanel(data);
}

function renderTierColorPanel(data) {
  const grid = $("tierColorGrid");
  const resetBtn = $("btnResetTierColors");
  if (!grid) return;
  const rows = data && data.rows ? data.rows : [];
  grid.innerHTML = rows.map((r) => {
    const key = escapeHtml(r.key);
    const hex = escapeHtml(String(r.color || "").toLowerCase());
    const label = escapeHtml(r.label || "");
    return `
      <div class="tier-color-item">
        <input type="color" class="legend-swatch-input" data-tier-key="${key}"
          value="#${hex}" title="Change color for ${label}" aria-label="Color for ${label}">
        <span class="tier-color-label">${label}</span>
      </div>`;
  }).join("");
  if (resetBtn) resetBtn.disabled = !data.isCustom;
  grid.querySelectorAll(".legend-swatch-input").forEach((input) => {
    input.addEventListener("change", async () => {
      const key = input.getAttribute("data-tier-key");
      if (!key) return;
      try {
        const result = await api("set_tier_color", key, input.value);
        applyTierColorPanelResult(result);
      } catch (err) {
        showToast(err && err.message ? err.message : String(err), true);
      }
    });
  });
}

function applyTierColorPanelResult(result) {
  if (!result || !result.rows) return;
  const grid = $("tierColorGrid");
  if (grid) {
    result.rows.forEach((r) => {
      const input = grid.querySelector(`[data-tier-key="${r.key}"]`);
      if (input) input.value = `#${String(r.color || "").toLowerCase()}`;
    });
  }
  const resetBtn = $("btnResetTierColors");
  if (resetBtn) resetBtn.disabled = !result.isCustom;
}

async function resetTierColorsFromPanel() {
  try {
    const result = await api("reset_tier_colors");
    applyTierColorPanelResult(result);
  } catch (err) {
    showToast(err && err.message ? err.message : String(err), true);
  }
}

function basename(p) {
  const parts = p.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || p;
}

function bootApp() {
  void initApp();
}

window.initApp = initApp;
document.addEventListener("DOMContentLoaded", bootApp);
window.addEventListener("pywebviewready", bootApp);
if (document.readyState !== "loading") bootApp();

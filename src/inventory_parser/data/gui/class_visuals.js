/* Class icons, colors, and roster card rendering for the setup GUI. */

const ClassVisuals = (() => {
  const STROKE = "1.75";
  const DEFAULT = {
    color: "#8b93a7",
    bg: "rgba(139, 147, 167, 0.12)",
    glow: "rgba(139, 147, 167, 0.2)",
    icon: "class-unknown",
  };

  const THEMES = {
    BER: { color: "#f97316", bg: "rgba(249, 115, 22, 0.14)", glow: "rgba(249, 115, 22, 0.25)", icon: "class-ber" },
    BRD: { color: "#eab308", bg: "rgba(234, 179, 8, 0.14)", glow: "rgba(234, 179, 8, 0.25)", icon: "class-brd" },
    BST: { color: "#84cc16", bg: "rgba(132, 204, 22, 0.14)", glow: "rgba(132, 204, 22, 0.25)", icon: "class-bst" },
    CLR: { color: "#22c55e", bg: "rgba(34, 197, 94, 0.14)", glow: "rgba(34, 197, 94, 0.25)", icon: "class-clr" },
    DRU: { color: "#10b981", bg: "rgba(16, 185, 129, 0.14)", glow: "rgba(16, 185, 129, 0.25)", icon: "class-dru" },
    ENC: { color: "#ec4899", bg: "rgba(236, 72, 153, 0.14)", glow: "rgba(236, 72, 153, 0.25)", icon: "class-enc" },
    MAG: { color: "#ef4444", bg: "rgba(239, 68, 68, 0.14)", glow: "rgba(239, 68, 68, 0.25)", icon: "class-mag" },
    MNK: { color: "#f59e0b", bg: "rgba(245, 158, 11, 0.14)", glow: "rgba(245, 158, 11, 0.25)", icon: "class-mnk" },
    NEC: { color: "#a855f7", bg: "rgba(168, 85, 247, 0.14)", glow: "rgba(168, 85, 247, 0.25)", icon: "class-nec" },
    PAL: { color: "#facc15", bg: "rgba(250, 204, 21, 0.14)", glow: "rgba(250, 204, 21, 0.25)", icon: "class-pal" },
    RNG: { color: "#65a30d", bg: "rgba(101, 163, 13, 0.14)", glow: "rgba(101, 163, 13, 0.25)", icon: "class-rng" },
    ROG: { color: "#94a3b8", bg: "rgba(148, 163, 184, 0.14)", glow: "rgba(148, 163, 184, 0.25)", icon: "class-rog" },
    SHD: { color: "#9333ea", bg: "rgba(147, 51, 234, 0.14)", glow: "rgba(147, 51, 234, 0.25)", icon: "class-shd" },
    SHM: { color: "#06b6d4", bg: "rgba(6, 182, 212, 0.14)", glow: "rgba(6, 182, 212, 0.25)", icon: "class-shm" },
    WAR: { color: "#dc2626", bg: "rgba(220, 38, 38, 0.14)", glow: "rgba(220, 38, 38, 0.25)", icon: "class-war" },
    WIZ: { color: "#3b82f6", bg: "rgba(59, 130, 246, 0.14)", glow: "rgba(59, 130, 246, 0.25)", icon: "class-wiz" },
  };

  function theme(classAbbr) {
    const key = (classAbbr || "").toUpperCase();
    return THEMES[key] || DEFAULT;
  }

  function svgUse(symbolId) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + symbolId);
    svg.appendChild(use);
    return svg;
  }

  function createIcon(classAbbr) {
    const t = theme(classAbbr);
    const wrap = document.createElement("div");
    wrap.className = "char-icon";
    wrap.style.setProperty("--class-color", t.color);
    wrap.style.setProperty("--class-bg", t.bg);
    wrap.style.setProperty("--class-glow", t.glow);
    wrap.appendChild(svgUse(t.icon));
    return wrap;
  }

  function createBadge(classAbbr) {
    if (!classAbbr) return null;
    const t = theme(classAbbr);
    const badge = document.createElement("span");
    badge.className = "class-badge";
    badge.textContent = classAbbr.toUpperCase();
    badge.style.setProperty("--class-color", t.color);
    badge.style.setProperty("--class-bg", t.bg);
    return badge;
  }

  function createCard({ character, classAbbr, server, serverDisplay }) {
    const card = document.createElement("div");
    card.className = "char-card-inner";

    card.appendChild(createIcon(classAbbr));

    const meta = document.createElement("div");
    meta.className = "char-meta";

    const top = document.createElement("div");
    top.className = "char-row-top";

    const name = document.createElement("span");
    name.className = "char-name";
    name.textContent = character;
    top.appendChild(name);

    const badge = createBadge(classAbbr);
    if (badge) top.appendChild(badge);

    meta.appendChild(top);

    if (server) {
      const serverEl = document.createElement("div");
      serverEl.className = "char-server";
      serverEl.textContent = serverDisplay || server;
      meta.appendChild(serverEl);
    }

    card.appendChild(meta);
    return card;
  }

  return { theme, createIcon, createBadge, createCard };
})();

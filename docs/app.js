(() => {
  const PREFS_KEY = "brief-prefs-v1";
  const READ_KEY = "brief-read-v1";
  const $ = (id) => document.getElementById(id);

  const prefs = Object.assign({ topics: null, size: "normal" }, safeParse(localStorage.getItem(PREFS_KEY)));
  let readIds = new Set(safeParse(localStorage.getItem(READ_KEY)) || []);
  let brief = null;

  function safeParse(s) { try { return JSON.parse(s); } catch { return null; } }
  function savePrefs() { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); }

  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else n.setAttribute(k, v);
    }
    for (const k of kids) if (k) n.append(k);
    return n;
  }
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  function enabledTopics() {
    const all = brief.topics;
    if (!prefs.topics) return all.filter((t) => t.default_on).map((t) => t.id);
    // Topics added later to the feed list follow their default until changed.
    const known = new Set(prefs.known || []);
    return all.filter((t) => prefs.topics.includes(t.id) || (!known.has(t.id) && t.default_on)).map((t) => t.id);
  }

  // Topics in the reader's chosen order; topics they've never ordered keep their default spot.
  function orderedTopics() {
    const order = prefs.order || [];
    const pos = (t) => {
      const i = order.indexOf(t.id);
      return i >= 0 ? i : order.length + brief.topics.indexOf(t);
    };
    return [...brief.topics].sort((a, b) => pos(a) - pos(b));
  }

  function prettyDate(iso) {
    const d = new Date(iso + "T12:00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  }

  function render() {
    const on = enabledTopics();
    const topics = orderedTopics().filter((t) => on.includes(t.id));
    const byTopic = Object.fromEntries(topics.map((t) => [t.id, []]));
    for (const s of brief.stories) if (byTopic[s.topic]) byTopic[s.topic].push(s);

    const updated = new Date(brief.generated_at);
    $("dateline").textContent = `${prettyDate(brief.date)} · updated ${updated.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

    // Overview
    const rank = Object.fromEntries(topics.map((t, i) => [t.id, i]));
    const ov = brief.overview.filter((o) => on.includes(o.topic) && o.topic !== "myteams")
      .map((o, i) => [o, i]).sort((a, b) => (rank[a[0].topic] - rank[b[0].topic]) || (a[1] - b[1]))
      .map(([o]) => o).slice(0, 6);
    const list = $("overview-list");
    list.replaceChildren(...ov.map((o) => {
      const t = brief.topics.find((x) => x.id === o.topic);
      return el("li", {}, el("span", { class: "tag", text: t ? t.emoji : "" }), document.createTextNode(o.text));
    }));
    $("overview").hidden = ov.length === 0;

    // Chips + sections
    const chips = [], sections = [];
    for (const t of topics) {
      const stories = byTopic[t.id];
      if (!stories.length) continue;
      chips.push(el("a", { href: `#t-${t.id}`, text: `${t.emoji} ${t.name}` }));
      const sec = el("section", { class: "topic", id: `t-${t.id}` }, el("h2", { text: `${t.emoji}  ${t.name}` }));
      for (const s of stories) sec.append(storyCard(s));
      sections.push(sec);
    }
    $("chips").replaceChildren(...chips);
    $("sections").replaceChildren(...sections);
    $("status").textContent = sections.length ? "" : "No stories for your topics today. Try turning on more in Settings.";
  }

  function storyCard(s) {
    const first = s.sources[0];
    const card = el("article", { class: "card story" + (readIds.has(s.id + brief.date) ? " read" : "") });
    const h = el("h3", {}, el("a", { href: safeUrl(first && first.url), target: "_blank", rel: "noopener", text: s.headline }));
    card.append(h);
    if (s.summary) card.append(el("p", { class: s.topic === "myteams" ? "gameline" : "", text: s.summary }));
    if (s.stat) card.append(el("p", { class: "stat" }, el("b", { text: "⭐ Standout: " }), document.createTextNode(s.stat)));
    if (s.why) card.append(el("p", { class: "why" }, el("b", { text: "Why it matters: " }), document.createTextNode(s.why)));
    if (s.sources.length) {
      const meta = el("div", { class: "meta" }, document.createTextNode("Read more: "));
      s.sources.forEach((src, i) => {
        if (i) meta.append(document.createTextNode(" · "));
        meta.append(el("a", { href: safeUrl(src.url), target: "_blank", rel: "noopener", text: src.name }));
      });
      card.append(meta);
    }
    card.addEventListener("click", (e) => {
      if (e.target.closest("a")) {
        readIds.add(s.id + brief.date);
        localStorage.setItem(READ_KEY, JSON.stringify([...readIds].slice(-300)));
        card.classList.add("read");
      }
    });
    return card;
  }

  function renderSettings() {
    const on = enabledTopics();
    const rows = orderedTopics().map((t, i, all) => {
      const box = el("input", { type: "checkbox", "data-id": t.id, "aria-label": `Show ${t.name}` });
      box.checked = on.includes(t.id);
      box.addEventListener("change", () => {
        const ids = [...$("topic-toggles").querySelectorAll("input")].filter((x) => x.checked).map((x) => x.dataset.id);
        prefs.topics = ids;
        prefs.known = brief.topics.map((x) => x.id);
        savePrefs();
        render();
      });
      const move = (delta) => {
        const ids = all.map((x) => x.id);
        const j = i + delta;
        if (j < 0 || j >= ids.length) return;
        [ids[i], ids[j]] = [ids[j], ids[i]];
        prefs.order = ids;
        savePrefs();
        render();
        renderSettings();
      };
      const up = el("button", { type: "button", class: "move", "aria-label": `Move ${t.name} up`, text: "▲" });
      const down = el("button", { type: "button", class: "move", "aria-label": `Move ${t.name} down`, text: "▼" });
      up.disabled = i === 0;
      down.disabled = i === all.length - 1;
      up.addEventListener("click", () => move(-1));
      down.addEventListener("click", () => move(1));
      return el("div", { class: "row" }, el("span", { class: "moves" }, up, down), el("span", { class: "tname", text: `${t.emoji}  ${t.name}` }), box);
    });
    $("topic-toggles").replaceChildren(...rows);
    document.querySelectorAll('input[name="size"]').forEach((r) => { r.checked = r.value === prefs.size; });
    $("about").textContent = brief.ai_summaries
      ? "Summaries are written by Claude from headlines collected from NPR, BBC, the New York Times and other outlets each morning. Tap a source to read the full story."
      : "Summaries come from the outlets' own descriptions (NPR, BBC, the New York Times and others), collected each morning. Tap a source to read the full story.";
  }

  function applySize() { document.documentElement.classList.toggle("large", prefs.size === "large"); }

  async function loadJson(path) {
    const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  async function load(date) {
    try {
      brief = await loadJson(date ? `data/archive/${date}.json` : "data/latest.json");
      render();
    } catch (e) {
      $("dateline").textContent = "";
      $("status").textContent = "Couldn't load the brief. Check your connection, then close and reopen the app.";
    }
  }

  async function loadDays() {
    try {
      const { dates } = await loadJson("data/index.json");
      const picker = $("day-picker");
      picker.replaceChildren(...dates.map((d, i) => el("option", { value: d, text: i === 0 ? "Today" : prettyDate(d) })));
      picker.addEventListener("change", () => {
        load(picker.selectedIndex === 0 ? null : picker.value);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    } catch { $("day-picker").parentElement.hidden = true; }
  }

  $("open-settings").addEventListener("click", () => { if (brief) { renderSettings(); $("settings").showModal(); } });
  document.querySelectorAll('input[name="size"]').forEach((r) => r.addEventListener("change", () => {
    prefs.size = r.value; savePrefs(); applySize();
  }));
  $("settings").addEventListener("click", (e) => { if (e.target === $("settings")) $("settings").close(); });

  // Opening the app from the home screen after a while: fetch the newest brief.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && $("day-picker").selectedIndex <= 0) load(null);
  });

  applySize();
  load(null);
  loadDays();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
})();

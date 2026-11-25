(() => {
  const PREFS_KEY = "brief-prefs-v1";
  const READ_KEY = "brief-read-v1";
  const $ = (id) => document.getElementById(id);

  const prefs = Object.assign({ topics: null, size: "normal", rate: "1", voice: "" }, safeParse(localStorage.getItem(PREFS_KEY)));
  let readIds = new Set(safeParse(localStorage.getItem(READ_KEY)) || []);
  let brief = null;

  if (prefs.rate === "1.3") prefs.rate = "1.15"; // "Fastest" was replaced by "Slower"
  function safeParse(s) { try { return JSON.parse(s); } catch { return null; } }
  function savePrefs(sync = true) {
    if (sync) prefs.updated = Date.now();
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    if (sync) scheduleSync();
  }

  // ---- settings saved to the project (docs/config.json), so they survive the phone wiping
  // its storage, and so the daily job can read the AI switch. Writing needs a GitHub token
  // (fine-grained, this repo only, Contents read and write) pasted once in Settings.
  const TOKEN_KEY = "brief-gh-token";
  const REPO = "croyal008/daily-brief";
  const CONFIG_PATH = "docs/config.json";
  let config = { ai_summaries: true };
  let syncTimer = null;

  async function loadConfig() {
    try {
      const r = await fetch(`config.json?t=${Date.now()}`, { cache: "no-store" });
      if (r.ok) config = Object.assign({ ai_summaries: true }, await r.json());
    } catch {}
    const saved = config.app;
    // Adopt the saved copy when this phone has nothing (storage wiped) or the saved copy is newer.
    if (saved && (!prefs.updated || (saved.updated || 0) > prefs.updated)) {
      for (const k of ["topics", "known", "order", "size", "rate", "listenMode"]) {
        if (saved[k] !== undefined) prefs[k] = saved[k];
      }
      if (prefs.rate === "1.3") prefs.rate = "1.15";
      prefs.updated = saved.updated || Date.now();
      savePrefs(false);
      return true;
    }
    return false;
  }

  function scheduleSync() {
    if (!localStorage.getItem(TOKEN_KEY)) return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncConfig, 1500);
  }

  async function syncConfig() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return false;
    const api = `https://api.github.com/repos/${REPO}/contents/${CONFIG_PATH}`;
    const headers = { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" };
    config.app = {
      topics: prefs.topics, known: prefs.known, order: prefs.order, size: prefs.size,
      rate: prefs.rate, listenMode: prefs.listenMode, updated: prefs.updated || Date.now(),
    };
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const cur = await fetch(`${api}?ref=main&t=${Date.now()}`, { headers, cache: "no-store" });
        if (cur.status === 401 || cur.status === 403) { setSyncStatus("GitHub token was rejected. Paste a new one."); return false; }
        const sha = cur.ok ? (await cur.json()).sha : undefined;
        const body = JSON.stringify(config, null, 1) + "\n";
        const res = await fetch(api, {
          method: "PUT", headers,
          body: JSON.stringify({
            message: "Update app settings", branch: "main", sha,
            content: btoa(unescape(encodeURIComponent(body))),
          }),
        });
        if (res.ok) { setSyncStatus("Saved to your project ✓"); return true; }
        if (res.status !== 409) { setSyncStatus(`Couldn't save (GitHub said ${res.status}).`); return false; }
      }
    } catch { setSyncStatus("Couldn't reach GitHub. Try again when you're online."); }
    return false;
  }

  function renderWeatherLoc() {
    const name = (config.weather && config.weather.name) || (brief && brief.weather && brief.weather.location) || "San Antonio, TX";
    $("wx-current").textContent = name;
    $("wx-results").replaceChildren();
  }

  async function findPlaces() {
    const text = $("wx-input").value.trim();
    if (!text) return;
    const [city, ...rest] = text.split(",").map((x) => x.trim());
    const want = rest.join(" ").toLowerCase();
    $("wx-status").textContent = "Searching…";
    try {
      const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=10&language=en&format=json`);
      let found = ((await r.json()).results || []);
      if (want) {
        const hit = (p) => [p.admin1, p.country, p.country_code, US_STATES[p.admin1]].some((v) => v && v.toLowerCase().startsWith(want));
        found = found.filter(hit).concat(found.filter((p) => !hit(p)));
      }
      found = found.slice(0, 5);
      $("wx-status").textContent = found.length ? "Tap your location:" : "No places found. Try just the city name.";
      $("wx-results").replaceChildren(...found.map((p) => {
        const label = p.country_code === "US"
          ? `${p.name}, ${US_STATES[p.admin1] || p.admin1 || "US"}`
          : [p.name, p.admin1, p.country].filter(Boolean).join(", ");
        const b = el("button", { type: "button", class: "wx-pick", text: label });
        b.addEventListener("click", () => pickPlace({ name: label, lat: p.latitude, lon: p.longitude }));
        return b;
      }));
    } catch { $("wx-status").textContent = "Couldn't search right now. Check your connection."; }
  }

  async function pickPlace(place) {
    if (!localStorage.getItem(TOKEN_KEY)) {
      $("wx-status").textContent = "Paste your GitHub token in the AI section below first, then pick again.";
      return;
    }
    const before = config.weather;
    config.weather = place;
    $("wx-status").textContent = "Saving…";
    if (await syncConfig()) {
      renderWeatherLoc();
      $("wx-input").value = "";
      $("wx-status").textContent = `Weather will be for ${place.name}, starting with tomorrow's brief ✓`;
    } else {
      config.weather = before;
      $("wx-status").textContent = "Couldn't save. Try again in a moment.";
    }
  }

  const US_STATES = {
    Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA", Colorado: "CO", Connecticut: "CT",
    Delaware: "DE", Florida: "FL", Georgia: "GA", Hawaii: "HI", Idaho: "ID", Illinois: "IL", Indiana: "IN", Iowa: "IA",
    Kansas: "KS", Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD", Massachusetts: "MA", Michigan: "MI",
    Minnesota: "MN", Mississippi: "MS", Missouri: "MO", Montana: "MT", Nebraska: "NE", Nevada: "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", Ohio: "OH",
    Oklahoma: "OK", Oregon: "OR", Pennsylvania: "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    Tennessee: "TN", Texas: "TX", Utah: "UT", Vermont: "VT", Virginia: "VA", Washington: "WA", "West Virginia": "WV",
    Wisconsin: "WI", Wyoming: "WY", "District of Columbia": "DC",
  };

  function setSyncStatus(t) { const n = $("sync-status"); if (n) n.textContent = t; }

  function renderSync() {
    const has = !!localStorage.getItem(TOKEN_KEY);
    $("ai-toggle").checked = config.ai_summaries !== false;
    $("token-row").hidden = has;
    $("sync-forget").hidden = !has;
    if (!$("sync-status").textContent) {
      setSyncStatus(has ? "Your settings are saved to your project, so they come back if the phone resets them."
                        : "Paste a GitHub token once so the AI switch works and your topic settings are backed up.");
    }
  }

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
    // Start from the reader's saved order, then slot any topic they haven't ordered yet
    // (like a newly added one) into its default position, so new sections don't sink to the bottom.
    const byId = Object.fromEntries(brief.topics.map((t) => [t.id, t]));
    const list = (prefs.order || []).filter((id) => byId[id]).map((id) => byId[id]);
    brief.topics.forEach((t, i) => {
      if (!list.includes(t)) list.splice(Math.min(i, list.length), 0, t);
    });
    return list;
  }

  function shortDate(iso) {
    return new Date(iso + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
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
    const d = new Date(brief.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
    $("dateline").textContent = `${d} · ${updated.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

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
      if (t.id === "weather") {
        if (brief.weather) {
          chips.push(el("a", { href: "#t-weather", text: `${t.emoji} ${t.name}` }));
          sections.push(weatherSection(t, brief.weather));
        }
        continue;
      }
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

  function weatherSection(t, w) {
    const sec = el("section", { class: "topic", id: "t-weather" }, el("h2", { text: `${t.emoji}  ${t.name} · ${w.location}` }));
    const d = w.today;
    const today = el("article", { class: "card weather" });
    today.append(el("div", { class: "wx-now" },
      el("span", { class: "wx-big", text: d.emoji }),
      el("div", {},
        el("div", { class: "wx-temps" }, el("b", { text: `${d.high}°` }), document.createTextNode(` / ${d.low}°`)),
        el("div", { class: "wx-desc", text: `${d.desc} · ${d.rain}% chance of rain` }))));
    today.append(el("p", { text: d.summary }));
    if (d.slots && d.slots.length) {
      today.append(el("div", { class: "wx-slots" }, ...d.slots.map((x) => el("div", { class: "wx-slot" },
        el("span", { class: "wx-label", text: x.label }),
        el("span", { class: "wx-emoji", text: x.emoji }),
        el("b", { text: `${x.temp}°` }),
        el("span", { class: "wx-rain", text: `💧${x.rain}%` })))));
    }
    const facts = [`Feels like ${d.feels_low}° to ${d.feels_high}°`,
      `Wind ${d.wind} mph` + (d.gust > d.wind + 5 ? `, gusts ${d.gust}` : ""),
      `UV ${d.uv}`, `Sunrise ${d.sunrise}`, `Sunset ${d.sunset}`];
    if (d.precip_in >= 0.05) facts.splice(1, 0, `Rain ${d.precip_in} in`);
    today.append(el("p", { class: "wx-facts", text: facts.join(" · ") }));
    sec.append(today);
    if (w.days && w.days.length) {
      const week = el("article", { class: "card weather" }, el("h3", { text: "Next 7 days" }));
      for (const x of w.days) {
        const name = new Date(x.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
        week.append(el("div", { class: "wx-day" },
          el("span", { class: "wx-dname", text: name }),
          el("span", { class: "wx-emoji", text: x.emoji }),
          el("span", { class: "wx-ddesc", text: x.desc }),
          el("span", { class: "wx-rain", text: x.rain >= 10 ? `💧${x.rain}%` : "" }),
          el("span", { class: "wx-hl" }, el("b", { text: `${x.high}°` }), document.createTextNode(` ${x.low}°`))));
      }
      sec.append(week);
    }
    return sec;
  }

  function storyCard(s) {
    const first = s.sources[0];
    const card = el("article", { class: "card story" + (readIds.has(s.id + brief.date) ? " read" : ""), "data-sid": s.id });
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
      await loadPodcast();
    } catch (e) {
      $("dateline").textContent = "";
      $("status").textContent = "Couldn't load the brief. Check your connection, then close and reopen the app.";
    }
  }

  async function loadDays() {
    try {
      const { dates } = await loadJson("data/index.json");
      const picker = $("day-picker");
      picker.replaceChildren(...dates.map((d, i) => el("option", { value: d, text: i === 0 ? `Today · ${shortDate(d)}` : shortDate(d) })));
      const label = () => {
        $("day-label").textContent = picker.selectedIndex <= 0 ? "Past briefs ▾" : `${shortDate(picker.value)} ▾`;
      };
      label();
      picker.addEventListener("change", () => {
        label();
        stopListening();
        load(picker.selectedIndex === 0 ? null : picker.value);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    } catch { $("day-wrap").hidden = true; }
  }


  // ------------------------------------------------------------ listening
  // Reads the brief aloud with the phone's built-in voice, like a short podcast.
  const synth = window.speechSynthesis;
  const player = { queue: [], index: 0, playing: false, paused: false };

  const UNITS = [
    [/(\d+)\/(\d+)/g, "$1 of $2"], [/\bYDS\b/g, "yards"], [/\bTD\b/g, "touchdown"], [/\bTDs\b/g, "touchdowns"],
    [/\bINT\b/g, "interception"], [/\bCAR\b/g, "carries"], [/\bREC\b/g, "catches"], [/\bPTS\b/g, "points"],
    [/\bREB\b/g, "rebounds"], [/\bAST\b/g, "assists"], [/\bBLK\b/g, "blocks"], [/\bSTL\b/g, "steals"],
  ];
  function spokenStat(t) {
    let out = t;
    for (const [re, rep] of UNITS) out = out.replace(re, rep);
    return out.replace(/(\d+) touchdown\b/g, (m, n) => (n === "1" ? "1 touchdown" : `${n} touchdowns`));
  }

  function spokenGame(s) {
    const m = s.headline.match(/^(✅|❌|➖)\s+(.+?)\s+(\d+),\s+(.+?)\s+(\d+)$/);
    if (!m) return `${s.headline}.`;
    const [, mark, me, a, opp, b] = m;
    let line = mark === "✅" ? `The ${me} beat the ${opp}, ${a} to ${b}.`
      : mark === "❌" ? `The ${me} lost to the ${opp}, ${b} to ${a}.`
      : `The ${me} and the ${opp} tied at ${a}.`;
    const rec = (s.summary || "").match(/Record (\d+)-(\d+)(?:-(\d+))?/);
    if (rec) line += ` They're now ${rec[1]} and ${rec[2]}${rec[3] ? ` and ${rec[3]}` : ""}.`;
    if (s.stat) {
      const [who, what] = s.stat.split(/:\s*/, 2);
      line += ` ${who} led the way with ${spokenStat(what || "").replace(/, ([^,]+)$/, " and $1")}.`;
    }
    return line;
  }

  const clean = (t) => (t || "").replace(/[“”]/g, '"').replace(/\s+/g, " ").trim();
  const endStop = (t) => (/[.!?]"?$/.test(t) ? t : t + ".");

  function buildScript() {
    const on = enabledTopics();
    const topics = orderedTopics().filter((t) => on.includes(t.id));
    const q = [];
    const day = new Date(brief.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    const hour = new Date().getHours();
    const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    q.push({ text: `${hello}. Here's your Daily Brief for ${day}.`, label: "Intro" });
    let first = true;
    if (brief.weather && on.includes("weather")) {
      q.push({ text: `First, the weather in ${brief.weather.location}. ${brief.weather.today.summary}`, label: "🌤️ Weather" });
      first = false;
    }
    for (const t of topics) {
      const stories = brief.stories.filter((s) => s.topic === t.id);
      if (!stories.length) continue;
      const name = { myteams: "your teams", us: "U.S. news", world: "world news" }[t.id]
        || t.name.replace(/\s*\(light\)/i, "").replace(/&/g, "and").toLowerCase();
      const lead = first ? `First up, ${name}.` : `Next, ${name}.`;
      first = false;
      stories.forEach((s, i) => {
        let text = t.id === "myteams" ? spokenGame(s)
          : [endStop(clean(s.headline)), s.summary ? endStop(clean(s.summary)) : "", s.why ? `Why it matters: ${endStop(clean(s.why))}` : ""].filter(Boolean).join(" ");
        if (i === 0) text = `${lead} ${text}`;
        else if (t.id !== "myteams") text = `${["Also,", "Meanwhile,", "And finally,"][i === stories.length - 1 && i > 1 ? 2 : (i - 1) % 2]} ${text}`;
        q.push({ text, sid: s.id, label: `${t.emoji} ${t.name} · ${i + 1} of ${stories.length}` });
      });
    }
    q.push({ text: "That's your brief. Have a great day.", label: "Wrapping up" });
    return q;
  }

  function pickVoice() {
    const voices = synth.getVoices().filter((v) => /^en(-|_|$)/i.test(v.lang));
    if (prefs.voice) {
      const v = voices.find((x) => x.voiceURI === prefs.voice);
      if (v) return v;
    }
    const us = voices.filter((v) => /en[-_]US/i.test(v.lang));
    return us.find((v) => /premium/i.test(v.name)) || us.find((v) => /enhanced/i.test(v.name))
      || us.find((v) => /^(Ava|Samantha|Allison|Evan|Zoe|Nathan|Tom)\b/.test(v.name))
      || us.find((v) => v.default) || us[0] || voices[0] || null;
  }

  function highlight(item) {
    document.querySelectorAll(".story.speaking").forEach((c) => c.classList.remove("speaking"));
    $("player-now").textContent = item ? item.label : "";
    if (item && item.sid) {
      const card = document.querySelector(`.story[data-sid="${CSS.escape(item.sid)}"]`);
      if (card) {
        card.classList.add("speaking");
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }

  // Queue everything from `start` onward in one go: iPhone only lets speech start from a tap,
  // and a pre-filled queue keeps playing from one story to the next without another tap.
  function speakFrom(start) {
    synth.cancel();
    player.index = Math.max(0, Math.min(start, player.queue.length - 1));
    player.playing = true;
    player.paused = false;
    $("p-toggle").textContent = "⏸";
    $("p-toggle").setAttribute("aria-label", "Pause");
    const voice = pickVoice();
    player.queue.slice(player.index).forEach((item, k) => {
      const u = new SpeechSynthesisUtterance(item.text);
      if (voice) { u.voice = voice; u.lang = voice.lang; } else u.lang = "en-US";
      u.rate = parseFloat(prefs.rate) || 1;
      const idx = player.index + k;
      u.onstart = () => { player.index = idx; highlight(item); };
      if (idx === player.queue.length - 1) u.onend = () => { if (player.playing && !player.paused) stopListening(); };
      synth.speak(u);
    });
  }

  // ---- recorded podcast (made each morning on GitHub; keeps playing with the screen locked)
  const audioEl = $("podcast");
  let podcast = null; // contents of data/audio.json when it matches the brief on screen

  async function loadPodcast() {
    try {
      const p = await loadJson("data/audio.json");
      podcast = brief && p.date === brief.date ? p : null;
    } catch { podcast = null; }
  }

  const useRecorded = () => podcast && prefs.listenMode !== "device";

  function chapterAt(t) {
    let i = 0;
    podcast.chapters.forEach((c, k) => { if (c.t <= t + 0.05) i = k; });
    return i;
  }

  function seekChapter(delta) {
    const i = chapterAt(audioEl.currentTime);
    // "Back" restarts the current story unless we're right at its start.
    const target = delta < 0 && audioEl.currentTime - podcast.chapters[i].t > 3 ? i : i + delta;
    const c = podcast.chapters[Math.max(0, Math.min(target, podcast.chapters.length - 1))];
    audioEl.currentTime = c.t;
    showChapter();
  }

  let lastChapter = -1;
  function showChapter() {
    if (!podcast) return;
    const i = chapterAt(audioEl.currentTime);
    if (i === lastChapter) return;
    lastChapter = i;
    const c = podcast.chapters[i];
    highlight({ label: c.label, sid: c.sid });
  }

  function setToggle(playing) {
    $("p-toggle").textContent = playing ? "⏸" : "▶";
    $("p-toggle").setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  function startRecorded() {
    const posKey = "brief-pos-" + podcast.url;
    if (!audioEl.src.endsWith(podcast.url)) {
      audioEl.src = podcast.url;
      const saved = parseFloat(localStorage.getItem(posKey) || "0");
      if (saved > 0 && saved < podcast.duration - 10) audioEl.currentTime = saved;
    }
    audioEl.playbackRate = parseFloat(prefs.rate) || 1;
    audioEl.play().catch(() => {});
    player.playing = true;
    lastChapter = -1;
    if ("mediaSession" in navigator) {
      const day = new Date(brief.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
      navigator.mediaSession.metadata = new MediaMetadata({
        title: `Daily Brief · ${day}`, artist: "Daily Brief", album: "Your morning news",
        artwork: [{ src: "icons/icon-512.png", sizes: "512x512", type: "image/png" }],
      });
      const ms = navigator.mediaSession;
      ms.setActionHandler("play", () => audioEl.play());
      ms.setActionHandler("pause", () => audioEl.pause());
      ms.setActionHandler("previoustrack", () => seekChapter(-1));
      ms.setActionHandler("nexttrack", () => seekChapter(1));
      try { ms.setActionHandler("seekbackward", () => { audioEl.currentTime = Math.max(0, audioEl.currentTime - 15); }); } catch {}
      try { ms.setActionHandler("seekforward", () => { audioEl.currentTime += 15; }); } catch {}
    }
  }

  audioEl.addEventListener("timeupdate", () => {
    showChapter();
    if (podcast) localStorage.setItem("brief-pos-" + podcast.url, String(audioEl.currentTime));
  });
  audioEl.addEventListener("play", () => setToggle(true));
  audioEl.addEventListener("pause", () => setToggle(false));
  // If the recording can't be loaded, fall back to the phone's own voice.
  audioEl.addEventListener("error", () => {
    if (player.mode !== "recorded" || !player.playing) return;
    if (podcast && podcast.backup_url && audioEl.src !== podcast.backup_url) {
      audioEl.src = podcast.backup_url;
      audioEl.play().catch(() => {});
      return;
    }
    if (!synth) return;
    const code = audioEl.error ? audioEl.error.code : "?";
    localStorage.setItem("brief-audio-error", `${new Date().toLocaleString()} (error ${code})`);
    $("player-now").textContent = "Podcast didn't load, using iPhone voice";
    player.mode = "device";
    player.queue = buildScript();
    speakFrom(0);
  });
  audioEl.addEventListener("ended", () => {
    if (podcast) localStorage.removeItem("brief-pos-" + podcast.url);
    stopListening();
  });

  // ---- shared controls
  async function startListening() {
    if (!brief) return;
    if (!podcast && prefs.listenMode !== "device") await loadPodcast();
    $("player").hidden = false;
    document.body.classList.add("playing");
    if (useRecorded()) {
      player.mode = "recorded";
      startRecorded();
    } else if (synth) {
      player.mode = "device";
      player.queue = buildScript();
      speakFrom(0);
    }
  }

  function stopListening() {
    player.playing = false;
    player.paused = false;
    if (synth) synth.cancel();
    audioEl.pause();
    highlight(null);
    $("player").hidden = true;
    document.body.classList.remove("playing");
  }

  function togglePause() {
    if (!player.playing) return;
    if (player.mode === "recorded") {
      if (audioEl.paused) audioEl.play(); else audioEl.pause();
      return;
    }
    if (player.paused) {
      // Resuming by re-speaking the current story is more reliable on iPhone than resume().
      speakFrom(player.index);
    } else {
      player.paused = true;
      synth.cancel();
      setToggle(false);
    }
  }

  function renderVoices() {
    const sel = $("voice-picker");
    if (!synth) { $("voice-row").hidden = true; return; }
    const voices = synth.getVoices().filter((v) => /^en(-|_|$)/i.test(v.lang));
    const current = pickVoice();
    sel.replaceChildren(...voices.map((v) => {
      const o = el("option", { value: v.voiceURI, text: `${v.name} (${v.lang.replace("_", "-")})` });
      if (current && v.voiceURI === current.voiceURI) o.selected = true;
      return o;
    }));
  }

  $("listen").hidden = false;
  $("listen").addEventListener("click", () => (player.playing ? stopListening() : startListening()));
  $("p-toggle").addEventListener("click", togglePause);
  $("p-stop").addEventListener("click", stopListening);
  $("p-next").addEventListener("click", () => {
    if (!player.playing) return;
    if (player.mode === "recorded") seekChapter(1); else speakFrom(player.index + 1);
  });
  $("p-prev").addEventListener("click", () => {
    if (!player.playing) return;
    if (player.mode === "recorded") seekChapter(-1); else speakFrom(player.index - 1);
  });
  document.querySelectorAll('input[name="rate"]').forEach((r) => r.addEventListener("change", () => {
    prefs.rate = r.value; savePrefs();
    audioEl.playbackRate = parseFloat(prefs.rate) || 1;
  }));
  document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
    prefs.listenMode = r.value; savePrefs();
    if (player.playing) stopListening();
    updateVoiceRow();
  }));
  function updateVoiceRow() {
    $("voice-row").hidden = prefs.listenMode !== "device" && !!podcast;
    $("voice-tip").hidden = $("voice-row").hidden;
  }
  if (synth) {
    $("voice-picker").addEventListener("change", (e) => {
      prefs.voice = e.target.value; savePrefs();
      const u = new SpeechSynthesisUtterance("This is how your brief will sound.");
      const v = pickVoice(); if (v) { u.voice = v; u.lang = v.lang; }
      u.rate = parseFloat(prefs.rate) || 1;
      synth.cancel(); synth.speak(u);
    });
    synth.addEventListener?.("voiceschanged", () => { if ($("settings").open) renderVoices(); });
  }

  $("open-settings").addEventListener("click", () => {
    if (!brief) return;
    renderSettings();
    renderVoices();
    document.querySelectorAll('input[name="rate"]').forEach((r) => { r.checked = r.value === String(prefs.rate); });
    document.querySelectorAll('input[name="mode"]').forEach((r) => { r.checked = r.value === (prefs.listenMode || "recorded"); });
    $("mode-row").hidden = !podcast || !synth;
    updateVoiceRow();
    setSyncStatus("");
    renderSync();
    renderWeatherLoc();
    $("wx-status").textContent = "";
    const err = localStorage.getItem("brief-audio-error");
    $("audio-error").hidden = !err;
    $("audio-error").textContent = err ? `Last time the podcast wouldn't load: ${err}` : "";
    $("settings").showModal();
  });
  document.querySelectorAll('input[name="size"]').forEach((r) => r.addEventListener("change", () => {
    prefs.size = r.value; savePrefs(); applySize();
  }));
  $("settings").addEventListener("click", (e) => { if (e.target === $("settings")) $("settings").close(); });

  // Opening the app from the home screen after a while: fetch the newest brief.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && $("day-picker").selectedIndex <= 0 && !player.playing) load(null);
  });

  $("ai-toggle").addEventListener("change", async (e) => {
    if (!localStorage.getItem(TOKEN_KEY)) {
      e.target.checked = config.ai_summaries !== false;
      setSyncStatus("Paste a GitHub token below first, then flip this again.");
      $("token-input").focus();
      return;
    }
    const before = config.ai_summaries;
    config.ai_summaries = e.target.checked;
    setSyncStatus("Saving…");
    if (!(await syncConfig())) { config.ai_summaries = before; e.target.checked = before !== false; }
    else setSyncStatus(e.target.checked ? "AI is on, starting with the next brief ✓" : "AI is off, starting with the next brief ✓");
  });
  $("wx-find").addEventListener("click", findPlaces);
  $("wx-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findPlaces(); } });
  $("token-save").addEventListener("click", async () => {
    const t = $("token-input").value.trim();
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    $("token-input").value = "";
    setSyncStatus("Checking…");
    if (await syncConfig()) renderSync();
    else localStorage.removeItem(TOKEN_KEY);
  });
  $("sync-forget").addEventListener("click", () => {
    localStorage.removeItem(TOKEN_KEY);
    setSyncStatus("Token removed from this phone.");
    renderSync();
  });

  applySize();
  loadConfig().then((changed) => { if (changed) { applySize(); if (brief) render(); } });
  load(null);
  loadDays();
  let swReg = null;
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").then((r) => { swReg = r; }).catch(() => {});
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && swReg) swReg.update().catch(() => {});
    });
  }

  // ---- pull down at the top of the page to refresh (the home screen app has no reload button)
  const ptr = $("ptr");
  let pullStart = null, pullDist = 0;
  const PULL_AT = 80;
  window.addEventListener("touchstart", (e) => {
    if (window.scrollY > 0 || $("settings").open || e.touches.length !== 1) { pullStart = null; return; }
    pullStart = e.touches[0].clientY; pullDist = 0;
  }, { passive: true });
  window.addEventListener("touchmove", (e) => {
    if (pullStart === null) return;
    pullDist = Math.max(0, e.touches[0].clientY - pullStart);
    if (window.scrollY > 0) pullDist = 0;
    const shown = Math.min(pullDist, 120);
    ptr.style.height = `${shown * 0.6}px`;
    ptr.textContent = pullDist > PULL_AT ? "Release to refresh" : (pullDist > 15 ? "Pull to refresh" : "");
  }, { passive: true });
  window.addEventListener("touchend", async () => {
    if (pullStart === null) return;
    const go = pullDist > PULL_AT;
    pullStart = null;
    if (!go) { ptr.style.height = "0"; ptr.textContent = ""; return; }
    ptr.textContent = "Refreshing…";
    try { if (swReg) await swReg.update(); } catch {}
    location.reload();
  });
})();

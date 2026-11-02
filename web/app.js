const $ = (s, el = document) => el.querySelector(s);
const FIELDS = ["title", "date", "start_time", "end_time", "location_text", "room", "free_food"];
const REVIEW_MAP = { location: "location_text" };

function sessionId() {
  try {
    let id = localStorage.getItem("polo_session");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("polo_session", id);
    }
    return id;
  } catch {
    return "anon";
  }
}
const SESSION = sessionId();

function localToday() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function log(type, capture_id, data = {}) {
  fetch("/api/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, session: SESSION, capture_id, data }),
  }).catch(() => {});
}

async function shrink(file, max = 2800) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.9));
  } catch {
    return file;
  }
}

function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.toggle("error", isError);
}

let CONFIG = { dev: false, models: [] };

async function loadConfig() {
  try {
    CONFIG = await (await fetch("/api/config")).json();
  } catch {
    return;
  }
  if (!CONFIG.dev) return;
  const select = $("#model");
  const groups = {};
  CONFIG.models.forEach((m) => {
    if (!groups[m.provider]) {
      groups[m.provider] = Object.assign(document.createElement("optgroup"), { label: m.provider });
      select.append(groups[m.provider]);
    }
    groups[m.provider].append(Object.assign(document.createElement("option"), {
      value: m.id,
      textContent: m.note ? `${m.label} (${m.note})` : m.label,
      disabled: !m.available,
      selected: m.id === CONFIG.default_model,
    }));
  });
  $("#dev").hidden = false;
}

function metaLine(model, body, err) {
  if (err) return `${model}: ${err}`;
  const m = body.meta;
  const cost = m.cost_usd == null ? "" : m.cost_usd === 0 ? " · free" : ` · $${m.cost_usd.toFixed(4)}`;
  const n = body.events.length;
  return `${m.model} · ${(m.latency_ms / 1000).toFixed(1)}s${cost} · ${n} event${n === 1 ? "" : "s"}`;
}

async function runOne(model, image, text, group) {
  const form = new FormData();
  if (image) form.append("image", image, "poster.jpg");
  if (text) form.append("text", text);
  form.append("captured_on", localToday());
  form.append("session", SESSION);
  form.append("source", image ? "photo" : "text");
  if (model) form.append("model", model);

  let body;
  try {
    const res = await fetch("/api/extract", { method: "POST", body: form });
    body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `Server error ${res.status}, check the terminal`);
  } catch (err) {
    if (group) $(".group-head", group).textContent = metaLine(model, null, err.message);
    throw err;
  }
  if (group) $(".group-head", group).textContent = metaLine(model, body);
  const target = group ? $(".group-body", group) : $("#results");
  body.events.forEach((ev) => {
    const card = render(ev, body.capture_id, body.sources);
    group ? target.append(card) : target.prepend(card);
  });
  return body;
}

function newGroup(model) {
  const g = document.createElement("section");
  g.className = "group";
  g.innerHTML = '<h3 class="group-head"></h3><div class="group-body"></div>';
  $(".group-head", g).textContent = `${model}: working…`;
  return g;
}

async function extract(file) {
  const text = $("#text").value.trim();
  if (!file && !text) return setStatus("Snap a poster or paste some text first.", true);
  const image = file ? await shrink(file) : null;

  let models = [null];
  if (CONFIG.dev) {
    models = $("#compare").checked
      ? CONFIG.models.filter((m) => m.available && !(image && m.vision === false)).map((m) => m.id)
      : [$("#model").value || null];
  }
  const grouped = CONFIG.dev;

  $("#go").disabled = true;
  setStatus(models.length > 1 ? `Running ${models.length} models…` : "Reading the poster…");
  const wrap = document.createElement("div");
  if (grouped) $("#results").prepend(wrap);
  const results = await Promise.allSettled(
    models.map((m) => {
      const group = grouped ? newGroup(m || CONFIG.default_model) : null;
      if (group) wrap.append(group);
      return runOne(m, image, text, group);
    }),
  );
  $("#go").disabled = false;
  $("#photo").value = "";

  const ok = results.filter((r) => r.status === "fulfilled").map((r) => r.value);
  if (!ok.length) return setStatus(results[0].reason.message, true);
  const found = Math.max(...ok.map((b) => b.events.length));
  if (!found) {
    setStatus(ok[0].is_event_source ? "Couldn't find an event in that." : "That doesn't look like an event.", true);
  } else {
    setStatus(models.length > 1 ? "Done. Compare the results below." : `Found ${found} event${found > 1 ? "s" : ""}. Check the details.`);
    $("#text").value = "";
  }
}

function readCard(card, original) {
  const ev = { ...original };
  card.querySelectorAll("[data-f]").forEach((inp) => {
    const f = inp.dataset.f;
    ev[f] = inp.type === "checkbox" ? inp.checked : inp.value.trim() || null;
  });
  ev.all_day = !ev.start_time;
  if (ev.location_text !== original.location_text) {
    ev.building_code = null;
    ev.building_name = null;
  }
  return ev;
}

function editedFields(ev, original) {
  return FIELDS.filter((f) => (ev[f] ?? null) !== (original[f] ?? null));
}

function gcalUrl(ev) {
  if (!ev.date) return null;
  const d = ev.date.replaceAll("-", "");
  let dates;
  if (!ev.start_time) {
    const next = new Date(ev.date + "T12:00:00");
    next.setDate(next.getDate() + 1);
    dates = `${d}/${next.toISOString().slice(0, 10).replaceAll("-", "")}`;
  } else {
    const t = (s) => s.replace(":", "") + "00";
    let end = ev.end_time;
    if (!end) {
      const [h, m] = ev.start_time.split(":").map(Number);
      end = `${String(Math.min(h + 1, 23)).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    }
    dates = `${d}T${t(ev.start_time)}/${d}T${t(end)}`;
  }
  const where = ev.building_name
    ? `${ev.building_code}${ev.room ? " " + ev.room : ""}, ${ev.building_name}, UBC Vancouver`
    : ev.location_text || "";
  const details = [ev.description, ev.organizer && `Host: ${ev.organizer}`, ev.link, "Added with Polo"]
    .filter(Boolean).join("\n");
  const p = new URLSearchParams({ action: "TEMPLATE", text: ev.title, dates, ctz: "America/Vancouver", details, location: where });
  return "https://calendar.google.com/calendar/render?" + p;
}

function renderSources(el, sources = []) {
  sources.forEach((src) => {
    const line = document.createElement("span");
    const label = src.from === "qr" ? "QR" : "Link";
    if (src.read && src.url) {
      const a = Object.assign(document.createElement("a"), { href: src.url, target: "_blank", rel: "noopener" });
      a.textContent = src.title || new URL(src.url).hostname;
      line.append(`🔗 ${label}: checked `, a);
    } else if (src.url) {
      line.textContent = `🔗 ${label}: ${new URL(src.url).hostname} (${src.note || "not read"})`;
    } else {
      line.textContent = `🔗 QR: “${src.title}”`;
    }
    el.append(line);
  });
}

function render(original, captureId, sources) {
  const card = $("#event-tpl").content.firstElementChild.cloneNode(true);
  let visibility = "private";

  FIELDS.forEach((f) => {
    const inp = card.querySelector(`[data-f="${f}"]`);
    if (inp.type === "checkbox") inp.checked = !!original[f];
    else inp.value = original[f] ?? "";
  });
  (original.needs_review || []).forEach((f) => {
    const inp = card.querySelector(`[data-f="${REVIEW_MAP[f] || f}"]`);
    if (inp) inp.classList.add("review");
  });
  $(".building", card).textContent = original.building_name
    ? `📍 ${original.building_name} (${original.building_code})`
    : "";
  $(".desc", card).textContent = [original.organizer, original.cost, original.description].filter(Boolean).join(" · ");
  renderSources($(".sources", card), sources);

  card.querySelectorAll(".seg button").forEach((btn) =>
    btn.addEventListener("click", () => {
      visibility = btn.dataset.v;
      card.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b === btn));
      log("visibility", captureId, { visibility });
    }),
  );

  const finalize = (action) => {
    const ev = readCard(card, original);
    log("save", captureId, { action, visibility, edited: editedFields(ev, original), needs_review: original.needs_review });
    return ev;
  };

  $(".ics", card).addEventListener("click", async () => {
    const ev = finalize("ics");
    if (!ev.date) return alertCard(card, "Add a date first.");
    const res = await fetch("/api/ics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: [ev], capture_id: captureId, session: SESSION }),
    });
    if (!res.ok) return alertCard(card, "Couldn't build the calendar file.");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "polo-event.ics" });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    card.classList.add("saved");
  });

  $(".gcal", card).addEventListener("click", (e) => {
    const ev = finalize("google");
    const url = gcalUrl(ev);
    if (!url) {
      e.preventDefault();
      return alertCard(card, "Add a date first.");
    }
    e.currentTarget.href = url;
    card.classList.add("saved");
  });

  $(".drop", card).addEventListener("click", () => {
    log("dismiss", captureId, { title: original.title });
    card.remove();
  });

  return card;
}

function alertCard(card, msg) {
  let p = $(".card-error", card);
  if (!p) {
    p = Object.assign(document.createElement("p"), { className: "card-error" });
    $(".actions", card).before(p);
  }
  p.textContent = msg;
}

loadConfig();
$("#photo").addEventListener("change", (e) => e.target.files[0] && extract(e.target.files[0]));
$("#go").addEventListener("click", () => extract(null));

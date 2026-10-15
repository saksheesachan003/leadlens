"use strict";

const $ = (s) => document.querySelector(s);
const state = {
  lens: "sales",
  industries: new Set(),
  config: null,
  jobId: null,
  job: null,
  polling: null,
  file: null,
  filters: { tier: null, q: "", verifiedOnly: false, minScore: 0 },
};

const LENS_HINT = {
  sales: "Ranks by who you can reach and how well they fit.",
  acquisition: "Ranks established, owner-run businesses with room to grow after a buy.",
};
const TIER_COLORS = { Hot: "var(--gold)", Warm: "var(--sage)", Cold: "var(--cold)", Unreachable: "var(--brick)" };
const STATUS_LABEL = { valid: "Verified", risky: "Risky", unverified: "Not verified", invalid: "Invalid" };

// Everything shown comes from scraped websites, so it is always escaped.
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  return body;
}

// ---------------- setup ----------------
async function init() {
  state.config = await api("/api/config");
  const chips = $("#industries");
  state.config.industries.forEach((name) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = name;
    b.setAttribute("aria-pressed", "false");
    b.onclick = () => {
      const on = !state.industries.has(name);
      on ? state.industries.add(name) : state.industries.delete(name);
      b.setAttribute("aria-pressed", String(on));
      rescoreIfReady();
    };
    chips.appendChild(b);
  });

  document.querySelectorAll(".lens button").forEach((b) =>
    b.addEventListener("click", () => setLens(b.dataset.lens)));

  setupDrop();
  $("#jobForm").addEventListener("submit", (e) => { e.preventDefault(); run(); });
  $("#demoBtn").onclick = () => {
    $("#domains").value = state.config.demo_domains.join("\n");
    clearFile();
    run();
  };
  $("#q").oninput = (e) => { state.filters.q = e.target.value.trim(); render(); };
  $("#verifiedOnly").onchange = (e) => { state.filters.verifiedOnly = e.target.checked; render(); };
  $("#minScore").oninput = (e) => { state.filters.minScore = +e.target.value; $("#minScoreOut").textContent = e.target.value; render(); };
  $("#exportBtn").onclick = exportCsv;
  $("#copyBtn").onclick = copyEmails;
  $("#closeDrawer").onclick = closeDrawer;
  $("#scrim").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

function setLens(lens) {
  if (lens === state.lens) return;
  state.lens = lens;
  document.querySelectorAll(".lens button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.lens === lens)));
  $("#lensHint").textContent = LENS_HINT[lens];
  rescoreIfReady();
}

function setupDrop() {
  const drop = $("#drop"), input = $("#csvFile");
  const pick = () => input.click();
  drop.onclick = pick;
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  input.onchange = () => input.files[0] && setFile(input.files[0]);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && setFile(e.dataTransfer.files[0]));
}

function setFile(f) {
  state.file = f;
  $("#drop").classList.add("has-file");
  $("#dropTitle").textContent = f.name;
  $("#dropHint").textContent = "Will be used instead of the pasted list. Click to change.";
}
function clearFile() {
  state.file = null;
  $("#csvFile").value = "";
  $("#drop").classList.remove("has-file");
  $("#dropTitle").textContent = "Upload a CSV instead";
  $("#dropHint").textContent = "We find the website column for you.";
}

// ---------------- running a job ----------------
async function run() {
  const err = $("#formError");
  err.hidden = true;
  const text = $("#domains").value.trim();
  if (!state.file && !text) {
    err.textContent = "Add at least one website, upload a CSV, or try the demo companies.";
    err.hidden = false;
    return;
  }
  $("#runBtn").disabled = true;
  $("#runBtn").textContent = "Reading websites…";
  try {
    let res;
    if (state.file) {
      const fd = new FormData();
      fd.append("file", state.file);
      fd.append("lens", state.lens);
      fd.append("industries", [...state.industries].join("|"));
      res = await api("/api/jobs/upload", { method: "POST", body: fd });
    } else {
      res = await api("/api/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lens: state.lens, industries: [...state.industries] }),
      });
    }
    state.jobId = res.job_id;
    state.filters.tier = null;
    $("#empty").hidden = true;
    $("#board").hidden = false;
    $("#progressWrap").hidden = false;
    poll();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    resetRunBtn();
  }
}

function resetRunBtn() {
  $("#runBtn").disabled = false;
  $("#runBtn").textContent = "Find and score leads";
}

async function poll() {
  clearTimeout(state.polling);
  try {
    state.job = await api(`/api/jobs/${state.jobId}`);
  } catch (e) {
    $("#progressText").textContent = e.message;
    resetRunBtn();
    return;
  }
  const { done, total, status } = state.job;
  $("#progressBar").style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
  $("#progressText").textContent = status === "done"
    ? `Checked ${total} ${total === 1 ? "site" : "sites"}.`
    : `Checked ${done} of ${total} sites…`;
  render();
  if (status === "done" || status === "failed") {
    resetRunBtn();
    setTimeout(() => ($("#progressWrap").hidden = true), 1200);
    if (status === "failed") toast("Something went wrong on our side. Results so far are shown.");
    // Lens or industries may have changed while it was running.
    if (state.job.lens !== state.lens || !sameSet(state.job.industries, state.industries)) rescoreIfReady();
    return;
  }
  state.polling = setTimeout(poll, 700);
}

const sameSet = (arr, set) => arr.length === set.size && arr.every((x) => set.has(x));

async function rescoreIfReady() {
  if (!state.job || state.job.status !== "done") return;
  state.job = await api(`/api/jobs/${state.jobId}/rescore`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lens: state.lens, industries: [...state.industries] }),
  });
  render();
  toast(state.lens === "acquisition" ? "Re-ranked for acquisition targets" : "Re-ranked for sales outreach");
}

// ---------------- rendering ----------------
function filtered() {
  const f = state.filters;
  return (state.job?.leads || []).filter((l) => {
    if (f.tier && l.tier !== f.tier) return false;
    if (l.score < f.minScore) return false;
    if (f.verifiedOnly && l.best_email_status !== "valid") return false;
    if (f.q) {
      const hay = [l.company_name, l.domain, l.industry, l.location, l.best_email, l.contact_name].join(" ").toLowerCase();
      if (!hay.includes(f.q.toLowerCase())) return false;
    }
    return true;
  });
}

function render() {
  const job = state.job;
  if (!job) return;
  const leads = job.leads;
  const counts = { Hot: 0, Warm: 0, Cold: 0, Unreachable: 0 };
  leads.forEach((l) => (counts[l.tier] = (counts[l.tier] || 0) + 1));
  const verified = leads.filter((l) => l.best_email_status === "valid").length;

  const meta = [`${verified} verified ${verified === 1 ? "email" : "emails"}`];
  if (job.duplicates_removed) meta.push(`${job.duplicates_removed} ${job.duplicates_removed === 1 ? "duplicate" : "duplicates"} removed`);
  if (job.invalid_inputs.length) meta.push(`${job.invalid_inputs.length} skipped as not a website`);

  $("#summary").innerHTML = Object.entries(counts)
    .filter(([t, n]) => n || t !== "Unreachable")
    .map(([t, n]) => `<button class="tierpill" data-tier="${t}" aria-pressed="${state.filters.tier === t}">
        <span class="dot" style="background:${TIER_COLORS[t]}"></span><b>${n}</b>${t}</button>`).join("")
    + `<span class="meta">${esc(meta.join(", "))}</span>`;
  document.querySelectorAll(".tierpill").forEach((b) => (b.onclick = () => {
    state.filters.tier = state.filters.tier === b.dataset.tier ? null : b.dataset.tier;
    render();
  }));

  const notice = $("#notice");
  if (job.invalid_inputs.length) {
    notice.hidden = false;
    notice.textContent = `Skipped because they don't look like websites: ${job.invalid_inputs.slice(0, 5).join(", ")}${job.invalid_inputs.length > 5 ? "…" : ""}`;
  } else notice.hidden = true;

  const rows = filtered();
  $("#noMatch").hidden = rows.length > 0 || leads.length === 0;
  $("#rows").innerHTML = rows.map(rowHtml).join("");
  document.querySelectorAll("#rows tr").forEach((tr) => {
    const open = () => openDrawer(tr.dataset.domain);
    tr.onclick = (e) => { if (!e.target.closest("a")) open(); };
    tr.onkeydown = (e) => { if (e.key === "Enter") open(); };
  });
}

function signals(l) {
  const s = [];
  if (l.years_in_business) s.push(`${l.years_in_business} yrs`);
  if (l.family_or_owner_operated) s.push("Owner-run");
  if (l.employee_hint) s.push(`~${l.employee_hint} staff`);
  if (l.hiring) s.push("Hiring");
  if (l.location) s.push(l.location);
  if (l.industry && !l.industry.startsWith("Other")) s.push(l.industry);
  return s.slice(0, 4);
}

function rowHtml(l) {
  const contact = l.best_email
    ? `${l.contact_name ? `<b>${esc(l.contact_name)}${l.contact_title ? `, ${esc(l.contact_title)}` : ""}</b>` : ""}
       <span class="email"><span class="status ${esc(l.best_email_status)}" title="${esc(STATUS_LABEL[l.best_email_status])}"></span>${esc(l.best_email)}</span>`
    : `<span class="muted">${l.error ? "" : "No email found"}</span>`;
  return `<tr tabindex="0" class="tier-${esc(l.tier)}${l.tier === "Unreachable" ? " unreachable" : ""}" data-domain="${esc(l.domain)}">
    <td class="c-score"><div class="score"><b>${l.score}</b><i><span style="width:${l.score}%"></span></i><span class="tiertag">${esc(l.tier)}</span></div></td>
    <td class="co"><b>${esc(l.company_name)}</b><a href="${safeUrl(l.website)}" target="_blank" rel="noopener noreferrer">${esc(l.domain)}</a></td>
    <td class="contact">${contact}</td>
    <td class="c-phone">${esc((l.phones || [])[0] || "")}</td>
    <td><div class="tags">${l.error ? `<span class="tag">${esc(l.error)}</span>` : signals(l).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</div></td>
    <td class="next">${esc(l.next_action)}</td>
  </tr>`;
}

// ---------------- detail drawer ----------------
function openDrawer(domain) {
  const l = state.job.leads.find((x) => x.domain === domain);
  if (!l) return;
  const positive = l.reasons.filter((r) => r.points > 0);
  const facts = [
    ["Industry", l.industry],
    ["Founded", l.founded_year ? `${l.founded_year} (${l.years_in_business} years)` : null],
    ["Location", l.location],
    ["Team size", l.employee_hint ? `About ${l.employee_hint}` : null],
    ["Owner-run", l.family_or_owner_operated ? "Yes, says so on the site" : null],
    ["Site last updated", l.last_site_update_year],
    ["Website tools", (l.tech_stack || []).join(", ") || null],
    ["Secure site", l.error ? null : (l.https ? "Yes (HTTPS)" : "No")],
    ["Socials", Object.keys(l.socials || {}).length ? Object.entries(l.socials).map(([k, u]) => `<a href="${safeUrl(u)}" target="_blank" rel="noopener noreferrer">${esc(k)}</a>`).join(", ") : null, true],
  ].filter(([, v]) => v);

  $("#drawer").className = `drawer open tier-${l.tier}`;
  $("#drawerBody").innerHTML = `
    <h3 id="dTitle">${esc(l.company_name)}</h3>
    <a class="muted" href="${safeUrl(l.website)}" target="_blank" rel="noopener noreferrer">${esc(l.website)}</a>
    ${l.description ? `<p class="desc">${esc(l.description)}</p>` : ""}
    <div class="bigscore"><b>${l.score}</b><span>${esc(l.tier)} lead for ${state.job.lens === "acquisition" ? "acquisition" : "sales outreach"}</span></div>
    <div class="breakdown" aria-hidden="true">${positive.map((r) => `<span style="width:${r.points}%" title="+${r.points} ${esc(r.text)}"></span>`).join("")}</div>
    <ul class="reasons">${l.reasons.map((r) => `<li class="${r.points ? "" : "zero"}"><span class="pts">${r.points ? "+" + r.points : "0"}</span><span>${esc(r.text)}</span></li>`).join("")}</ul>
    <div class="nextbox">Next step: ${esc(l.next_action)}</div>

    <h4>Contacts</h4>
    ${(l.emails || []).length || (l.phones || []).length ? `<ul class="clist">
      ${(l.emails || []).map((e) => `<li><div class="row1"><span class="email"><span class="status ${esc(e.status)}"></span>${esc(e.email)}</span>
        <button class="copy" data-copy="${esc(e.email)}">Copy</button></div>
        <div class="checks">${esc(STATUS_LABEL[e.status])}${e.name ? `, ${esc(e.name)}${e.title ? " (" + esc(e.title) + ")" : ""}` : ""}. ${esc((e.checks || []).join(". "))}</div></li>`).join("")}
      ${(l.phones || []).map((p) => `<li><div class="row1"><span>${esc(p)}</span><button class="copy" data-copy="${esc(p)}">Copy</button></div></li>`).join("")}
    </ul>` : `<p class="muted">No contact details found on the pages we read.</p>`}

    ${facts.length ? `<h4>Company profile</h4><dl class="facts">${facts.map(([k, v, raw]) => `<dt>${k}</dt><dd>${raw ? v : esc(v)}</dd>`).join("")}</dl>` : ""}
    ${(l.pages_scanned || []).length ? `<h4>Pages read</h4><ul class="pages">${l.pages_scanned.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>` : ""}
  `;
  $("#drawerBody").querySelectorAll(".copy").forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  $("#closeDrawer").focus();
}

function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
}

// ---------------- export & copy ----------------
function exportCsv() {
  if (!state.jobId) return;
  const f = state.filters;
  const p = new URLSearchParams({ min_score: f.minScore, verified_only: f.verifiedOnly });
  if (f.tier) p.set("tier", f.tier);
  if (f.q) p.set("q", f.q);
  window.location.href = `/api/jobs/${state.jobId}/export.csv?${p}`;
  toast(`Exported ${filtered().filter((l) => l.tier !== "Unreachable").length} leads`);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); }
  catch { toast("Copy isn't available in this browser"); }
}

function copyEmails() {
  const emails = filtered().map((l) => l.best_email).filter(Boolean);
  if (!emails.length) return toast("No emails in the current view");
  copy(emails.join(", "));
}

init().catch((e) => { $("#formError").textContent = `Couldn't load: ${e.message}`; $("#formError").hidden = false; });

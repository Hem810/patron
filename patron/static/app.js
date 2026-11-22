const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safe = (u) => (/^https?:\/\//.test(u || "") ? esc(u) : "#");
const out = (u, label) => `<a href="${safe(u)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
const inr = (n) => (n == null ? "To be agreed" : "₹" + Number(n).toLocaleString("en-IN"));
const list = (items) => `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
const STEP = {brief:"Read request",discover:"Search papers",screen:"Screen relevance",deepen:"Check each researcher",rank:"Rank labs",rivals:"Check competitors",packet:"Draft agreement"};
const CHECK = {link_found:"public link",lead_only:"possible link",none_found:"none found",not_checked:"not checked"};
const ACTIVE = ["queued", "running", "approved"];
let current = location.hash.slice(1), last = "", timer;

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} :
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error);
  return data;
}

function progress(v) {
  const {status, message} = v.job;
  const steps = v.stages.map((s) => {
    const cls = v.done.includes(s) ? "done" : (status === "running" && message === s ? "now" : "");
    return `<span class="${cls}">${STEP[s]}</span>`;
  }).join("");
  const banners = {
    awaiting_approval: ["", "Waiting for a person. Nothing has been sent."],
    sent: ["ok", message], approved: ["", "Approved. Delivering to the sandbox."],
    rejected: ["bad", "Rejected. Nothing was sent."], needs_input: ["", message],
    insufficient: ["", message], failed: ["bad", message],
  };
  const b = banners[status];
  return `<div class="steps">${steps}</div>` + (b ? `<div class="banner ${b[0]}">${esc(b[1])}
    ${status === "failed" ? '<button class="plain" data-do="retry">Retry from the last checkpoint</button>' : ""}</div>` : "");
}

function recommendation(v) {
  const p = v.packet;
  if (!p) return "";
  const l = p.lab, b = p.budget;
  return `<div class="card pick">
    <div class="mute">Fund this lab</div>
    <h2>${esc(l.name)}, ${esc(l.institution)}</h2>
    <span class="tag ${esc(p.decision.confidence)}">${p.decision.confidence === "close call" ? "close call: speak to both" : esc(p.decision.confidence) + " evidence"}</span>
    ${list(p.decision.reasons)}
    <p>${inr(b.total)} total: ${inr(b.research)} research, ${inr(b.overhead)} overhead.
      <a href="/proposal/${esc(v.job.id)}" target="_blank" rel="noopener">Read the proposal and agreement</a></p>
    <details data-k="evidence"><summary>Evidence: ${l.papers.length} papers</summary>
      ${l.papers.map((x) => `<p>${out(x.url, x.title)} <span class="mute">${esc(x.date)}</span>
        <blockquote>${esc(x.passage)}<br>${out(x.record_url, x.field)} · retrieved ${esc(x.retrieved_at)}
        · record hash ${esc(x.sha256.slice(0, 10))}</blockquote></p>`).join("")}
    </details></div>`;
}

function competitors(v) {
  const r = v.rivals;
  if (!r) return "";
  const labs = v.rank.labs.filter((l) => r.checks.some((c) => c.lab === l.key));
  if (!r.rivals.length) return `<div class="card"><h3>Competitors</h3><p>Not checked, because none were named.</p></div>`;
  const nameOf = (k) => labs.find((l) => l.key === k);
  return `<div class="card"><h3>Is a competitor already there?</h3><div class="scroll"><table>
    <tr><th>Lab</th>${r.rivals.map((x) => `<th>${esc(x)}</th>`).join("")}</tr>
    ${labs.map((l) => `<tr><td>${esc(l.name)}<div class="mute">${esc(l.institution)}</div></td>${r.rivals.map((x) => {
      const c = r.checks.find((q) => q.lab === l.key && q.rival === x);
      return `<td><span class="tag ${c.status}">${CHECK[c.status]}</span></td>`;
    }).join("")}</tr>`).join("")}</table></div>
    ${r.links.map((x) => `<p><span class="tag ${x.strength}">${esc(x.strength)}</span>
      ${esc(nameOf(x.lab)?.institution)} and ${esc(x.rival)}, ${esc(x.scope)} level
      <blockquote>${esc(x.passage)}<br>${out(x.url, x.source)} · ${esc(x.field)} · ${esc(x.date || "date not stated")}
      · retrieved ${esc(x.retrieved_at)}</blockquote></p>`).join("")}</div>`;
}

function industry(v) {
  const ties = v.rivals?.industry || [];
  if (!ties.length) return "";
  return `<div class="card"><h3>Industry ties nobody asked about</h3>${ties.map((x) =>
    `<p><b>${esc(v.rank.labs.find((l) => l.key === x.lab)?.institution)}</b>
      <blockquote>${esc(x.passage)}<br>${out(x.url, x.source)} · ${esc(x.field)} · ${esc(x.date || "date not stated")}
      · retrieved ${esc(x.retrieved_at)}</blockquote></p>`).join("")}</div>`;
}

function elsewhere(v) {
  const ties = v.rivals?.elsewhere || [];
  if (!ties.length) return "";
  return `<div class="card"><h3>Where your competitors already do research</h3>${ties.map((x) =>
    `<p><b>${esc(x.rival)}</b>
      <blockquote>${esc(x.passage)}<br>${out(x.url, x.source)} · ${esc(x.field)} · ${esc(x.date || "date not stated")}
      · retrieved ${esc(x.retrieved_at)}</blockquote></p>`).join("")}</div>`;
}

function ranking(v) {
  if (!v.rank?.labs.length) return "";
  const p = v.packet, open = v.job.status === "awaiting_approval";
  const checked = new Set((v.rivals?.checks || []).map((c) => c.lab));
  return `<div class="card"><h3>Why not the others?</h3><div class="scroll"><table>
    <tr><th>Researcher</th><th class="n">Score</th><th class="n">On topic</th><th class="n">As lead</th><th class="n">Recent</th><th></th></tr>
    ${v.rank.labs.map((l, i) => `<tr>
      <td><b>${esc(l.name)}</b><div class="mute">${esc(l.institution)}</div>
        ${p?.decision.why_not[l.key] ? `<div class="mute">${esc(p.decision.why_not[l.key])}</div>` : ""}
        ${l.cautions.map((c) => `<div class="mute">Caution: ${esc(c)}</div>`).join("")}</td>
      <td class="n">${l.score}</td><td class="n">${l.counts.fit}</td><td class="n">${l.counts.lead}</td><td class="n">${l.counts.recent}</td>
      <td>${p?.decision.pick === l.key ? "Selected" :
        open && (checked.has(l.key) || (!checked.size && i < 4)) ? `<button class="plain" data-do="choose" data-key="${esc(l.key)}">Choose</button>` : ""}</td>
    </tr>`).join("")}</table></div></div>`;
}

function approval(v) {
  if (v.job.status !== "awaiting_approval" || !v.packet) return "";
  return `<div class="card"><h3>Your decision</h3>${list(v.packet.decision.questions)}
    <input id="approver" type="text" placeholder="Name of the approver" aria-label="Name of the approver">
    <div class="row"><button data-do="approve">Approve and send to sandbox</button>
      <button class="no" data-do="reject">Reject</button></div>
    <div class="mute">Approval binds to packet ${esc(v.packet.sha.slice(0, 12))}.</div></div>`;
}

function unknowns(v) {
  return v.packet ? `<div class="card"><h3>What I could not verify</h3>${list(v.packet.unknowns)}</div>` : "";
}

function side(v, history) {
  let html = "";
  if (v) {
    const c = v.cost, n = v.counts;
    if (v.brief) html += `<div class="card"><h3>What I understood</h3><p>${esc(v.brief.problem)}</p>
      <div class="mute">Company: ${esc(v.brief.client || "not named")}<br>Budget: ${inr(v.brief.budget_inr)}<br>
      Competitors: ${esc(v.brief.rivals.join(", ") || "none named")}</div>
      ${n.searched ? `<p class="mute">${n.searched} papers searched since ${esc(n.since)}, ${n.screened ?? "…"} screened, ${n.relevant ?? "…"} on topic.</p>
      <details data-k="phrases"><summary>Search terms used</summary>${list(n.phrases)}</details>` : ""}</div>`;
    html += `<div class="card"><h3>Cost of this job</h3>
      <p><b>${inr(c.inr)}</b> in data against a ${inr(c.price)} price (assumed)</p>
      <div class="mute">${c.credits} of ${c.limits.credits} credits · ${c.calls} of ${c.limits.http_calls} calls ·
      ${c.tokens} local model tokens · ${c.limits.seconds}s limit</div>
      <details data-k="ledger"><summary>Ledger</summary><table>${v.ledger.map((x) =>
        `<tr><td>${esc(x.op)}<div class="mute">${esc(x.service)}</div></td><td>${esc(x.outcome)}</td><td class="n">${x.ms ?? ""} ms</td></tr>`).join("")}</table></details>
      ${v.approvals.map((a) => `<p class="mute">${esc(a.decision)} by ${esc(a.approver)} at ${esc(a.at)}</p>`).join("")}
      ${v.actions.map((a) => `<p class="mute">${esc(a.kind)}: ${esc(a.target)}</p>`).join("")}</div>`;
  }
  return html + `<div class="card history"><h3>Jobs</h3>${history.map((j) =>
    `<button class="plain" data-open="${esc(j.id)}">${esc(j.request.slice(0, 64))}<div class="mute">${esc(j.status)}</div></button>`).join("") || '<p class="mute">None yet.</p>'}</div>`;
}

async function refresh() {
  clearTimeout(timer);
  let wait = 4000;
  try {
    const history = await api("/api/jobs");
    const v = current ? await api(`/api/jobs/${current}`).catch(() => null) : null;
    if (v && ACTIVE.includes(v.job.status)) wait = 1000;
    const snap = JSON.stringify([v, history]);
    if (snap !== last) {
      last = snap;
      const typed = $("approver")?.value;
      const open = [...document.querySelectorAll("details[open]")].map((d) => d.dataset.k);
      $("state").innerHTML = v ? progress(v) : "";
      $("result").innerHTML = v ? recommendation(v) + approval(v) + competitors(v) + elsewhere(v) + industry(v) + ranking(v) + unknowns(v) : "";
      $("side").innerHTML = side(v, history);
      if (typed && $("approver")) $("approver").value = typed;
      document.querySelectorAll("details").forEach((d) => { d.open = open.includes(d.dataset.k); });
    }
  } catch (err) {
    $("note").textContent = "The server is not answering. It resumes unfinished jobs when restarted.";
    wait = 1500;
  }
  timer = setTimeout(refresh, wait);
}

$("ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const job = await api("/api/jobs", {request: $("request").value, fresh: $("fresh").checked});
    current = location.hash = job.id;
    $("note").textContent = job.duplicate ? "Repeat request: opened the existing job." : "";
    last = "";
    refresh();
  } catch (err) { $("note").textContent = err.message; }
});

document.addEventListener("click", async (event) => {
  const opener = event.target.closest("[data-open]");
  if (opener) { current = location.hash = opener.dataset.open; last = ""; return refresh(); }
  const button = event.target.closest("[data-do]");
  if (!button) return;
  const verb = button.dataset.do;
  const sha = JSON.parse(last)[0]?.packet?.sha;
  try {
    await api(`/api/jobs/${current}/${verb}`, {sha, approver: $("approver")?.value || "", key: button.dataset.key});
    $("note").textContent = "";
    refresh();
  } catch (err) { $("note").textContent = err.message; }
});

addEventListener("hashchange", () => { current = location.hash.slice(1); last = ""; refresh(); });
refresh();

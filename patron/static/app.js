const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safe = (u) => (/^https?:\/\//.test(u || "") ? esc(u) : "#");
const out = (u, label, cls = "") => `<a class="${cls}" href="${safe(u)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
const inr = (n, digits = 0) => n == null ? "To be agreed" : "₹" + Number(n).toLocaleString("en-IN", {maximumFractionDigits: digits});
const num = (n) => n == null ? "…" : Number(n).toLocaleString("en-IN");
const plural = (n, one, many = one + "s") => `${num(n)} ${n === 1 ? one : many}`;
const list = (items) => `<ul class="plain">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

const PATHS = {
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.2v.1"/>',
  minus: '<path d="M6 12h12"/>',
  question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.6 2.6 0 1 1 3.6 2.6c-.8.4-1.1.9-1.1 1.7M12 17v.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  doc: '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
};
const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${PATHS[name]}</svg>`;
const pill = (tone, name, label) => `<span class="pill ${tone}">${icon(name)}${esc(label)}</span>`;

const STEP = {
  brief: ["Understand the request", "Problem, budget and competitors"],
  discover: ["Search live research", "Papers from the last five years"],
  screen: ["Screen for relevance", "Keep only work on this problem"],
  deepen: ["Investigate researchers", "Search each likely lab head by name"],
  rank: ["Rank the labs", "Scored by rules, not by the model"],
  rivals: ["Check for competitors", "Papers, announcements and partnerships"],
  packet: ["Draft the agreement", "Budget, milestones and terms"],
};
const STATUS = {
  queued: ["live", "clock", "Starting"], running: ["live", "clock", "Researching"],
  awaiting_approval: ["warn", "clock", "Awaiting approval"], approved: ["live", "clock", "Delivering"],
  sent: ["good", "check", "Sent to sandbox"], rejected: ["bad", "x", "Rejected"],
  needs_input: ["warn", "question", "Needs detail"], insufficient: ["warn", "question", "Cannot verify"],
  failed: ["bad", "alert", "Stopped"],
};
const CHECK = {
  link_found: ["bad", "alert", "Link found"], lead_only: ["warn", "question", "Unconfirmed lead"],
  none_found: ["good", "check", "None found"], not_checked: ["", "minus", "Not checked"],
};
const EVIDENCE = {
  confirmed: ["bad", "alert", "Confirmed link"], lead: ["warn", "question", "Unconfirmed lead"],
  reported: ["", "doc", "Reported"],
};
const CONFIDENCE = {
  good: ["good", "check", "Good evidence"], "close call": ["warn", "alert", "Close call: speak to both"],
  limited: ["warn", "question", "Limited evidence"],
};
const TABS = [["overview", "Overview"], ["competitors", "Competitors"], ["labs", "Labs compared"], ["evidence", "Evidence"], ["audit", "Cost & audit"]];
const ACTIVE = ["queued", "running", "approved"];

let current = location.hash.slice(1);
let view = null, jobs = [], tab = "overview", approver = "", timer, toastTimer, round = 0;
const painted = {};

// Only regions whose markup changed are replaced, so typing, focus and scrolling survive polling.
function paint(id, html) {
  if (painted[id] === html) return;
  const el = $(id), active = document.activeElement;
  const key = el.contains(active) ? active.dataset.f : null;
  painted[id] = html;
  el.innerHTML = html;
  if (key) [...el.querySelectorAll("[data-f]")].find((x) => x.dataset.f === key)?.focus({preventScroll: true});
}

function toast(message) {
  $("toast").textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").textContent = ""; }, 5000);
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} :
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw Object.assign(new Error(data.error), {status: res.status});
  return data;
}

const day = (value) => {
  if (!value) return "Date not stated";
  const parts = String(value).slice(0, 10).split("-").map(Number);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return [parts[2], months[parts[1] - 1], parts[0]].filter(Boolean).join(" ");
};
const clock = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const initials = (name) => name.replace(/[^\p{L}\s.-]/gu, "").split(/[\s.]+/).filter(Boolean)
  .filter((_, i, all) => i === 0 || i === all.length - 1).map((w) => w[0]).join("").toUpperCase();
const labOf = (v, key) => v.rank?.labs.find((l) => l.key === key);
const labelled = (map, key) => pill(...(map[key] || ["", "minus", key]));
const meter = (value, max, label) => {
  const share = Math.min(100, Math.max(0, max ? (100 * value) / max : 0));
  return `<div class="meter" title="${esc(label)}" role="img" aria-label="${esc(label)}"><i style="width:${share}%"></i></div>`;
};

function source(x) {
  return `<div class="source"><span>${esc(day(x.date))}</span>${out(x.url, x.source)}
    <span>Field: ${esc(x.field)}</span><span>Retrieved ${esc(day(x.retrieved_at))}</span></div>`;
}

function historyList() {
  return jobs.map((j) => {
    const [tone, , label] = STATUS[j.status] || ["", "", j.status];
    return `<button type="button" data-open="${esc(j.id)}" data-f="h-${esc(j.id)}" ${j.id === current ? 'aria-current="page"' : ""}>
      <span class="t">${esc(j.request)}</span><span class="s"><i class="dot ${tone}"></i>${esc(label)}</span></button>`;
  }).join("") || '<p class="none">Your requests will appear here.</p>';
}

function jobHead(v) {
  const b = v.brief;
  return `<div class="reqline"><h1 class="sr">Research request</h1><p>${esc(v.job.request)}</p>${b ? `<div class="meta">
      <span>Company <b>${esc(b.client || "not named")}</b></span>
      <span>Budget <b>${inr(b.budget_inr)}</b></span>
      <span>Competitors <b>${esc(b.rivals.join(", ") || "none named")}</b></span></div>` : ""}</div>
    <div class="headstate">${labelled(STATUS, v.job.status)}<span class="clock" id="clock"></span></div>`;
}

function stepDetail(v, step) {
  const n = v.counts;
  const found = {
    brief: () => v.brief && "Request understood",
    discover: () => n.searched != null && `${plural(n.searched, "paper")} found`,
    screen: () => n.screened != null && `${plural(n.screened, "title")} screened`,
    deepen: () => n.relevant != null && `${plural(n.relevant, "paper")} on topic`,
    rank: () => v.rank && `${plural(v.rank.labs.length, "lab")} shortlisted`,
    rivals: () => v.rivals && `${plural(v.rivals.checks.length, "check")} recorded`,
  };
  return (v.done.includes(step) && found[step]?.()) || STEP[step][1];
}

function working(v) {
  const next = v.stages.find((s) => !v.done.includes(s)) || "packet";
  const n = v.counts, leaders = v.rank?.labs.slice(0, 3) || [];
  return `<div class="card working">
    <div class="intro">
      <div class="kicker">Step ${v.stages.indexOf(next) + 1} of ${v.stages.length}</div>
      <h2>${esc(STEP[next][0])}</h2>
      <p>${esc(v.brief?.problem || "Reading what your company needs.")}</p>
      ${n.searched != null ? `<div class="livefacts">
        <div><b>${num(n.searched)}</b><span>papers found</span></div>
        ${n.screened != null ? `<div><b>${num(n.screened)}</b><span>titles screened</span></div>` : ""}
        ${n.relevant != null ? `<div><b>${num(n.relevant)}</b><span>on topic</span></div>` : ""}</div>` : ""}
      ${leaders.length ? `<div class="candidates"><div class="kicker">Leading before the competitor check</div>
        ${leaders.map((l) => `<p>${esc(l.name)}<span>${esc(l.institution)}</span></p>`).join("")}</div>` : ""}
    </div>
    <ol class="steps">${v.stages.map((s) => {
      const state = v.done.includes(s) ? "done" : s === next ? "now" : "";
      return `<li class="${state}"><span class="node">${state === "done" ? icon("check") : ""}</span>
        <div><b>${esc(STEP[s][0])}</b><small>${esc(stepDetail(v, s))}</small></div></li>`;
    }).join("")}</ol></div>`;
}

function flow(v) {
  const {status, message} = v.job;
  if (status === "queued" || status === "running") return working(v);
  const notice = (tone, name, head, text, action = "") => `<div class="notice ${tone}">${icon(name)}
    <div><b>${esc(head)}</b>${esc(text)}${action ? `<div class="actions">${action}</div>` : ""}</div></div>`;
  const edit = '<button class="secondary small" type="button" data-edit data-f="edit">Edit the request</button>';
  if (status === "needs_input") return notice("", "question", "One detail is needed", message, edit);
  if (status === "insufficient") return notice("", "question", "Not enough evidence to recommend a lab", message, edit);
  if (status === "failed") return notice("bad", "alert", "The run stopped safely", message,
    '<button class="secondary small" type="button" data-do="retry" data-f="retry">Retry from the last checkpoint</button>');
  if (status === "awaiting_approval" && message) return notice("", "alert", "Review again", message);
  return "";
}

function hero(v) {
  const p = v.packet;
  if (!p) return "";
  const l = p.lab, d = p.decision;
  const moved = d.reasons.filter((r) => !/^\d/.test(r));
  const tile = (value, label) => `<div class="stat"><b>${num(value)}</b><span>${label}</span></div>`;
  return `<div class="card pick">
    <div class="pickhead"><div class="avatar" aria-hidden="true">${esc(initials(l.name))}</div>
      <div class="who"><div class="kicker">${d.overridden ? "Selected lab" : "Recommended lab to fund"}</div>
        <h2>${esc(l.name)}</h2><div class="inst">${esc(l.institution)}</div></div>
      ${labelled(CONFIDENCE, d.confidence)}</div>
    <div class="stats">${tile(l.counts.fit, "Papers on this problem")}${tile(l.counts.lead, "As last author")}
      ${tile(l.counts.recent, "Recent papers")}${tile(l.counts.grants, "Naming a grant")}</div>
    ${moved.map((r) => `<div class="override">${esc(r.charAt(0).toUpperCase() + r.slice(1))}.</div>`).join("")}</div>`;
}

function linkItem(v, x) {
  const lab = labOf(v, x.lab);
  return `<div class="item"><div class="line"><b>${esc(x.rival)} and ${esc(lab?.institution)}</b>${labelled(EVIDENCE, x.strength)}</div>
    <p class="why">${x.scope === "person" ? `Names ${esc(lab?.name)}` : "Institute-level link"}. ${esc(x.reason)}</p>
    <blockquote>${esc(x.passage)}</blockquote>${source(x)}</div>`;
}

function chooseButton(v, l, i) {
  if (v.job.status !== "awaiting_approval" || v.packet?.decision.pick === l.key) return "";
  const checks = v.rivals?.checks || [];
  if (checks.length ? !checks.some((c) => c.lab === l.key) : i >= 3) return "";
  return `<button class="secondary small" type="button" data-do="choose" data-key="${esc(l.key)}" data-f="choose-${esc(l.key)}"
    aria-label="Select ${esc(l.name)}">Select</button>`;
}

function overview(v) {
  const p = v.packet, d = p.decision;
  const findings = (v.rivals?.links || []).filter((x) => x.strength === "confirmed").map((x) => {
    const lab = labOf(v, x.lab);
    const role = x.lab === d.pick ? "the selected lab" : d.backups.includes(x.lab) ? "a backup lab" : "a shortlisted lab";
    const where = x.scope === "person" ? lab?.name : lab?.institution;
    return `<div class="card pad finding">${pill("bad", "alert", `Competitor link at ${role}`)}
      <h3>${esc(x.rival)} has a published link to ${esc(where)}</h3>
      <blockquote>${esc(x.passage)}</blockquote>${source(x)}
      <p class="fine">A question to ask before funding. It isn't proof of a conflict.</p></div>`;
  }).join("");
  const notes = v.brief?.notes || [];
  const backups = p.backups.map((l) => `<div class="item"><div class="line">
      <div><b>${esc(l.name)}</b><span class="sub">${esc(l.institution)}</span></div>
      ${chooseButton(v, l, v.rank.labs.findIndex((x) => x.key === l.key))}</div>
      <p class="why">${esc(d.why_not[l.key])}</p></div>`).join("");
  return `${notes.length ? `<div class="notice">${icon("alert")}<div><b>Check the brief</b>${notes.map(esc).join(" ")}</div></div>` : ""}
    ${findings}
    <div class="card pad"><div class="title"><h3>Alternatives considered</h3></div>
      <div>${backups || '<p class="fine">No other lab met the evidence bar.</p>'}</div></div>
    <div class="card pad"><div class="title"><h3>What Patron could not verify</h3></div>${list(p.unknowns)}</div>`;
}

function competitors(v) {
  const r = v.rivals;
  if (!r) return "";
  const block = (title, note, items) => items.length
    ? `<div class="card pad"><div class="title"><h3>${title}</h3><span>${note}</span></div><div>${items.join("")}</div></div>` : "";
  let html;
  if (r.rivals.length) {
    const labs = v.rank.labs.filter((l) => r.checks.some((c) => c.lab === l.key));
    html = `<div class="card"><div class="scroll"><table class="matrix">
      <thead><tr><th scope="col">Shortlisted lab</th>${r.rivals.map((x) => {
        const company = r.companies?.find((c) => c.given === x);
        const unresolved = r.checks.some((c) => c.rival === x && c.identity === "unresolved");
        const sub = company ? `Matched: ${company.matched}` : unresolved ? "Company not identified" : "Name as given";
        return `<th scope="col">${esc(x)}<span class="sub">${esc(sub)}</span></th>`;
      }).join("")}</tr></thead>
      <tbody>${labs.map((l) => `<tr class="${v.packet?.decision.pick === l.key ? "selected" : ""}">
        <td><b>${esc(l.name)}</b><span class="sub">${esc(l.institution)}</span></td>
        ${r.rivals.map((x) => {
          const c = r.checks.find((q) => q.lab === l.key && q.rival === x);
          return `<td>${labelled(CHECK, c?.status || "not_checked")}</td>`;
        }).join("")}</tr>`).join("")}</tbody></table></div></div>`;
  } else {
    html = `<div class="notice">${icon("minus")}<div><b>Competitors not checked</b>None were named in the request.</div></div>`;
  }
  html += block("Links and leads", "Only a confirmed link is treated as fact", r.links.map((x) => linkItem(v, x)));
  html += block("Reported research links of your competitors", "Includes institutes outside the shortlist", (r.elsewhere || []).map((x) =>
    `<div class="item"><b>${esc(x.rival)}</b><blockquote>${esc(x.passage)}</blockquote>${source(x)}</div>`));
  html += block("Industry ties you didn't ask about", "Reported at a shortlisted institute", (r.industry || []).map((x) =>
    `<div class="item"><b>${esc(labOf(v, x.lab)?.institution)}</b><blockquote>${esc(x.passage)}</blockquote>${source(x)}</div>`));
  return html;
}

function labs(v) {
  const p = v.packet;
  return `<div class="card"><div class="scroll"><table class="labs">
    <thead><tr><th scope="col">Researcher</th><th scope="col">Score of 100</th><th scope="col" class="n">On topic</th>
      <th scope="col" class="n">As lead</th><th scope="col" class="n">Recent</th><th scope="col"><span class="sr">Action</span></th></tr></thead>
    <tbody>${v.rank.labs.map((l, i) => `<tr class="${p?.decision.pick === l.key ? "selected" : ""}">
      <td><b>${esc(l.name)}</b><span class="sub">${esc(l.institution)}</span>
        ${p?.decision.why_not[l.key] ? `<span class="sub">${esc(p.decision.why_not[l.key])}</span>` : ""}
        ${l.cautions.map((c) => `<span class="caution">${esc(c)}</span>`).join("")}</td>
      <td><b>${esc(l.score)}</b>${meter(l.score, 100, `${l.name}: ${l.score} out of 100`)}</td>
      <td class="n">${num(l.counts.fit)}</td><td class="n">${num(l.counts.lead)}</td><td class="n">${num(l.counts.recent)}</td>
      <td>${p?.decision.pick === l.key ? pill("good", "check", "Selected") : chooseButton(v, l, i)}</td></tr>`).join("")}</tbody>
    </table></div></div>
    <p class="fine">Scores come from rules: on-topic, last-authored and recent papers, grants and company co-authors. Citations and prestige are not used.</p>`;
}

function evidence(v) {
  const l = v.packet.lab;
  return `<div class="card pad"><div class="title"><h3>${plural(l.papers.length, "paper")} by ${esc(l.name)}</h3>
      <span>Affiliation as printed on each record</span></div>
    <div>${l.papers.map((x) => `<div class="item paper">
      <div class="line">${out(x.url, x.title, "t")}${x.lead ? '<span class="pill">Last author</span>' : ""}</div>
      <p class="p">${esc(x.passage)}</p>
      <div class="source"><span>${esc(day(x.date))}</span>${out(x.record_url, "Open record")}
        <span>Field: ${esc(x.field)}</span><span>Retrieved ${esc(day(x.retrieved_at))}</span>
        <span>Hash ${esc(x.sha256.slice(0, 10))}</span></div></div>`).join("")}</div></div>`;
}

function audit(v) {
  const c = v.cost, n = v.counts;
  const fact = (value, label, used, max) => `<div><b>${value}</b>${max ? meter(used, max, `${used} of ${max}`) : ""}<span>${label}</span></div>`;
  const trail = [...v.approvals.map((a) => [a.at, `${a.decision === "approve" ? "Approved" : "Rejected"} by ${a.approver}`]),
    ...v.actions.map((a) => [a.at, `Sandbox email written: ${a.target}`])];
  return `<div class="card pad"><div class="title"><h3>Cost of this job</h3><span>Against an assumed price of ${inr(c.price)}</span></div>
      <div class="facts">${fact(inr(c.inr, 2), "Data cost")}
        ${fact(esc(c.credits), `of ${c.limits.credits} credits allowed`, c.credits, c.limits.credits)}
        ${fact(num(c.calls), `of ${c.limits.http_calls} calls allowed`, c.calls, c.limits.http_calls)}
        ${fact(num(c.tokens), "local model tokens")}</div></div>
    ${trail.length ? `<div class="card pad"><div class="title"><h3>Approval and delivery</h3></div><div>${trail.map(([at, what]) =>
      `<div class="item"><div class="line"><b>${esc(what)}</b><span class="sub">${esc(new Date(at).toLocaleString("en-IN"))}</span></div></div>`).join("")}</div></div>` : ""}
    ${n.phrases ? `<div class="card pad"><div class="title"><h3>Search terms used</h3><span>Since ${esc(day(n.since))}</span></div>${list(n.phrases)}</div>` : ""}
    <div class="card"><div class="scroll"><table>
      <thead><tr><th scope="col">Call</th><th scope="col">Service</th><th scope="col">Outcome</th><th scope="col" class="n">Credits</th><th scope="col" class="n">Time</th></tr></thead>
      <tbody>${v.ledger.map((x) => `<tr><td>${esc(x.op)}</td><td>${esc(x.service)}</td><td>${esc(x.outcome)} ${esc(x.detail)}</td>
        <td class="n">${esc(x.credits || "")}</td><td class="n">${x.ms ? `${(x.ms / 1000).toFixed(1)} s` : ""}</td></tr>`).join("")}</tbody>
      </table></div></div>`;
}

const PANELS = {overview, competitors, labs, evidence, audit};

function body(v) {
  if (!v.packet) return ["insufficient", "failed", "needs_input"].includes(v.job.status) && v.ledger.length ? audit(v) : "";
  const links = (v.rivals?.links || []).filter((x) => x.strength === "confirmed").length;
  const counts = {competitors: links, labs: v.rank?.labs.length, evidence: v.packet.lab.papers.length};
  return `<div class="tabs" role="tablist" aria-label="Result details">${TABS.map(([id, label]) =>
    `<button type="button" role="tab" id="tab-${id}" data-tab="${id}" data-f="tab-${id}" aria-controls="panel"
      aria-selected="${id === tab}" tabindex="${id === tab ? 0 : -1}">${esc(label)}${counts[id]
      ? `<span class="count ${id === "competitors" ? "bad" : ""}">${counts[id]}</span>` : ""}</button>`).join("")}</div>
    <div id="panel" role="tabpanel" aria-labelledby="tab-${tab}">${PANELS[tab](v)}</div>`;
}

function rail(v) {
  const p = v.packet;
  if (!p) return "";
  const status = v.job.status, b = p.budget;
  const money = `<div class="amount"><b>${inr(b.total)}</b><span>Total over 12 months, excluding taxes</span></div>
    <div class="kv"><span>Research</span><b>${inr(b.research)}</b></div>
    <div class="kv"><span>Institute overhead</span><b>${inr(b.overhead)}</b></div>
    <a class="secondary doc" href="/proposal/${esc(v.job.id)}" target="_blank" rel="noopener" data-f="doc">${icon("doc")}Read proposal and agreement</a>`;
  let main;
  if (status === "awaiting_approval") {
    main = `<form class="card pad decide" id="decision" data-sha="${esc(p.sha)}">
      <h3>Your decision</h3><p>Nothing has been sent. Read the agreement before you approve.</p>${money}
      <label class="field" for="approver">Name of the approver</label>
      <input id="approver" data-f="approver" type="text" maxlength="80" autocomplete="off" placeholder="Full name">
      <div class="go"><button class="primary" data-do="approve" data-f="approve">Approve and send</button>
        <button class="danger" type="button" data-do="reject" data-f="reject">Reject</button></div>
      <div class="error" id="decision-error" role="alert"></div>
      <div class="fine">Sends once to ${esc(p.email?.to || "the sandbox")}. Approval is bound to packet ${esc(p.sha.slice(0, 12))}.</div></form>`;
  } else if (status === "sent") {
    const last = v.approvals[v.approvals.length - 1];
    main = `<div class="card pad receipt"><div class="tick">${icon("check")}</div><h3>Approved and delivered</h3>
      <p>${last ? `Approved by ${esc(last.approver)}. ` : ""}Written once to the sandbox outbox. No real person was contacted.</p>${money}
      <div class="fine">To ${esc(p.email?.to || "the sandbox")}. Packet ${esc(p.sha.slice(0, 12))}.</div></div>`;
  } else {
    const head = status === "rejected" ? "Rejected. Nothing was sent." : status === "approved" ? "Approved. Delivering to the sandbox." : "Deliverable";
    main = `<div class="card pad decide"><h3>${esc(head)}</h3>${money}</div>`;
  }
  return `<div class="rail">${main}
    <div class="card pad questions"><div class="title"><h3>Ask before signing</h3></div>
      <ol>${p.decision.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol></div>
    <div class="card pad milestones"><div class="title"><h3>Milestones</h3></div>
      <ol>${b.milestones.map((m) => `<li><span>Month ${esc(m.month)}</span><span>${esc(m.deliverable)}</span>
        <b>${m.amount == null ? `${esc(m.pct)}%` : inr(m.amount)}</b></li>`).join("")}</ol></div></div>`;
}

function tick() {
  const el = $("clock");
  if (!view || !el) return;
  const start = Date.parse(view.job.created);
  if (view.job.status === "queued" || view.job.status === "running") {
    el.textContent = `${clock(Date.now() - start)} elapsed`;
    return;
  }
  const end = Math.max(0, ...view.ledger.map((x) => Date.parse(x.at) + (x.ms || 0)));
  // A resumed job's wall time would include the hours it was stopped, so long gaps are not shown as research time.
  el.textContent = end > start && end - start < 900000 ? `Researched in ${clock(end - start)}` : "";
}

function render() {
  const v = current ? view : null;
  $("home").hidden = !!current;
  $("job").hidden = !v;
  paint("history", historyList());
  document.title = v?.packet ? `${v.packet.lab.name} · Patron` : "Patron · research sponsorship desk";
  if (!v) return;
  paint("head", jobHead(v));
  paint("flow", flow(v));
  paint("hero", hero(v));
  paint("rail", rail(v));
  paint("body", body(v));
  $("grid").classList.toggle("norail", !v.packet);
  if ($("approver") && $("approver").value !== approver) $("approver").value = approver;
  tick();
}

async function refresh() {
  clearTimeout(timer);
  const mine = ++round, id = current;
  let wait = 4000;
  try {
    const history = await api("/api/jobs");
    let found = null;
    if (id) {
      try { found = await api(`/api/jobs/${encodeURIComponent(id)}`); } catch (err) {
        if (err.status !== 404) throw err;
      }
    }
    if (mine !== round || id !== current) return;
    jobs = history;
    view = found;
    if (id && !found) {
      current = "";
      clearHash();
      toast("That request isn't in this workspace.");
    }
    if (found && ACTIVE.includes(found.job.status)) wait = 1000;
    $("offline").hidden = true;
    render();
  } catch (err) {
    if (mine !== round) return;
    $("offline").hidden = false;
    wait = 1500;
  }
  timer = setTimeout(refresh, wait);
}

function clearHash() {
  window.history.replaceState(null, "", location.pathname);
}

function show(id) {
  if (id === current) return;
  current = id;
  view = null;
  tab = "overview";
  approver = "";
  $("drawer").classList.remove("open");
  $("menu").setAttribute("aria-expanded", "false");
  window.scrollTo(0, 0);
  render();
  refresh();
}

function go(id) {
  if (id) location.hash = id;
  else if (location.hash) window.history.pushState(null, "", location.pathname);
  show(id);
}

function newRequest(text) {
  go("");
  $("drawer").classList.remove("open");
  $("menu").setAttribute("aria-expanded", "false");
  if (text !== undefined) $("request").value = text;
  $("request").focus();
}

function selectTab(id) {
  tab = id;
  render();
}

async function act(button) {
  const verb = button.dataset.do, id = current;
  const form = $("decision"), error = $("decision-error");
  const name = ($("approver")?.value || "").trim();
  if ((verb === "approve" || verb === "reject") && !name) {
    error.textContent = "Enter the name of the person deciding.";
    $("approver").focus();
    return;
  }
  if (error) error.textContent = "";
  button.disabled = true;
  try {
    // The hash travels with the decision panel, so what is approved is what was on screen.
    await api(`/api/jobs/${id}/${verb}`, {sha: form?.dataset.sha, approver: name, key: button.dataset.key});
    if (verb === "choose") toast("Lab changed. The agreement was redrafted and needs approval.");
    await refresh();
  } catch (err) {
    if (error && verb !== "choose") error.textContent = err.message;
    else toast(err.message);
  } finally {
    button.disabled = false;
  }
}

$("ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("submit").disabled = true;
  try {
    const job = await api("/api/jobs", {request: $("request").value, fresh: $("fresh").checked});
    if (job.duplicate) toast("Repeat request: opened the existing job.");
    $("request").value = "";
    $("fresh").checked = false;
    go(job.id);
  } catch (err) {
    toast(err.message || "The server isn't answering.");
  } finally {
    $("submit").disabled = false;
  }
});

$("request").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    $("ask").requestSubmit();
  }
});

document.addEventListener("submit", (event) => {
  if (event.target.id !== "decision") return;
  event.preventDefault();
  act(event.target.querySelector('[data-do="approve"]'));
});

document.addEventListener("input", (event) => {
  if (event.target.id === "approver") approver = event.target.value;
});

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-skip],[data-new],[data-open],[data-tab],[data-edit],[data-do],#menu");
  if (!el) return;
  if (el.hasAttribute("data-skip")) { event.preventDefault(); return $("main").focus(); }
  if (el.hasAttribute("data-new")) { event.preventDefault(); return newRequest(); }
  if (el.dataset.open) return go(el.dataset.open);
  if (el.dataset.tab) return selectTab(el.dataset.tab);
  if (el.hasAttribute("data-edit")) return newRequest(view.job.request);
  if (el.id === "menu") return el.setAttribute("aria-expanded", String($("drawer").classList.toggle("open")));
  if (el.dataset.do === "approve") return; // handled by the form, so Enter and click behave the same
  act(el);
});

document.addEventListener("keydown", (event) => {
  const from = event.target.closest?.('[role="tab"]');
  if (!from) return;
  const ids = TABS.map(([id]) => id), i = ids.indexOf(from.dataset.tab);
  const to = {ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: ids.length - 1}[event.key];
  if (to === undefined) return;
  event.preventDefault();
  selectTab(ids[(to + ids.length) % ids.length]);
  $(`tab-${tab}`).focus();
});

addEventListener("hashchange", () => show(location.hash.slice(1)));
addEventListener("popstate", () => show(location.hash.slice(1)));
setInterval(tick, 1000);
render();
refresh();

// All seller and Claude text is inserted with textContent only.
const $ = (id) => document.getElementById(id);
const history = [];
let spec = null, results = [], tab = "MATCH", sortKey = "verdict", sortDir = 1;

function code() { try { return sessionStorage.getItem("code") || ""; } catch { return ""; } }
async function api(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Access-Code": code()}, body: JSON.stringify(body)});
  if (r.status === 401) { $("gate").hidden = false; throw new Error("Enter the access code, then resend."); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Request failed");
  return r.json();
}
function bubble(role, text) {
  const d = document.createElement("div"); d.className = "msg " + role; d.textContent = text;
  $("log").appendChild(d); d.scrollIntoView({block: "end"});
}
$("code").addEventListener("change", () => { try { sessionStorage.setItem("code", $("code").value); } catch {} });

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("box").value.trim(); if (!text) return;
  $("box").value = ""; bubble("user", text); history.push({role: "user", content: text});
  $("form").querySelector("button").disabled = true;
  try {
    const r = await api("/api/chat", {messages: history});
    history.push({role: "assistant", content: r.reply}); bubble("assistant", r.reply);
    if (r.spec) showSpec(r.spec);
  } catch (err) { bubble("assistant", err.message); history.pop(); }
  $("form").querySelector("button").disabled = false; $("box").focus();
});

function showSpec(s) {
  spec = s; $("spec").hidden = false; $("spectitle").textContent = "Searching for: " + s.product;
  const ul = $("speclist"); ul.textContent = "";
  const items = [
    `Budget: up to $${s.max_total} total` + (s.flex.price_stretch ? ` (up to $${s.flex.price_stretch} over if negotiable)` : ""),
    s.must_have.length ? "Must have: " + s.must_have.join(", ") : null,
    s.deal_breakers.length ? "Deal breakers: " + s.deal_breakers.join(", ") : null,
    "Auctions: " + (s.flex.allow_auctions ? "ok" : "no"),
    "Minor issues: " + (s.flex.ok_with_minor_issues ? "ok" : "no"),
    "Unstated specs: " + (s.flex.ok_with_unknown_specs ? "keep as possible" : "reject"),
  ].filter(Boolean);
  for (const t of items) { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); }
}

$("go").addEventListener("click", async () => {
  $("go").disabled = true; $("go").textContent = "Searching and judging…";
  try {
    const r = await api("/api/search", spec);
    results = r.results; $("out").hidden = false;
    $("notes").textContent = r.notes.join(" ") + ` Found ${r.count} listings.`;
    render();
  } catch (err) { $("notes").textContent = err.message; $("out").hidden = false; }
  $("go").disabled = false; $("go").textContent = "Find listings";
});

const COLS = [["verdict", "Verdict"], ["title", "Listing"], ["total", "Total"], ["source", "Source"]];
const val = (j, k) => k === "verdict" ? ["MATCH", "POSSIBLE", "REJECT"].indexOf(j.verdict) : k === "total" ? j.listing.price + j.listing.shipping : j.listing[k];
function render() {
  const tabs = $("tabs"); tabs.textContent = "";
  for (const t of ["MATCH", "POSSIBLE", "REJECT"]) {
    const b = document.createElement("button"); b.className = t === tab ? "on" : "";
    b.textContent = `${t[0] + t.slice(1).toLowerCase()} (${results.filter((j) => j.verdict === t).length})`;
    b.onclick = () => { tab = t; render(); }; tabs.appendChild(b);
  }
  const head = $("head"); head.textContent = "";
  for (const [k, label] of COLS) {
    const th = document.createElement("th"); th.textContent = label + (sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : "");
    th.onclick = () => { sortDir = sortKey === k ? -sortDir : 1; sortKey = k; render(); }; head.appendChild(th);
  }
  const rows = results.filter((j) => j.verdict === tab).sort((a, b) => {
    const x = val(a, sortKey), y = val(b, sortKey); return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
  });
  const body = $("rows"); body.textContent = "";
  for (const j of rows) {
    const tr = document.createElement("tr");
    const c = (n) => tr.appendChild(document.createElement("td"));
    const v = c(); v.className = "v " + j.verdict; v.textContent = j.verdict;
    const t = c(); const a = document.createElement("a");
    a.textContent = j.listing.title; a.href = /^https?:\/\//.test(j.listing.url) ? j.listing.url : "#";
    a.target = "_blank"; a.rel = "noopener noreferrer"; t.appendChild(a);
    for (const line of [...j.reasons, ...j.ask_seller.map((q) => "Ask: " + q)]) {
      const s = document.createElement("small"); s.textContent = line; t.appendChild(s);
    }
    c().textContent = "$" + (j.listing.price + j.listing.shipping).toFixed(0);
    c().textContent = j.listing.source;
    body.appendChild(tr);
  }
}
bubble("assistant", "What are you looking to buy?");

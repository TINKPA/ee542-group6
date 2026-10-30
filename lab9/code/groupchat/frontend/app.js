const $ = (id) => document.getElementById(id);

const authPanel = $("auth");
const chatPanel = $("chat");
const messagesDiv = $("messages");
const usernameInput = $("username");
const passwordInput = $("password");
const authMsg = $("authMsg");

const signupBtn = $("signupBtn");
const loginBtn = $("loginBtn");
const logoutBtn = $("logoutBtn");
const chatInput = $("chatInput");
const sendBtn = $("sendBtn");

const API = location.origin + "/api";
let token = localStorage.getItem("token") || "";
let ws;

function showAuth() {
  authPanel.classList.remove("hidden");
  chatPanel.classList.add("hidden");
}

function showChat() {
  authPanel.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  // Messages were added while the panel was hidden (scrollHeight 0), so
  // scroll to the newest one only now that it is laid out.
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function callAPI(path, method = "GET", body) {
  const headers = {"Content-Type": "application/json"};
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) {
    // FastAPI sends a string for our own errors but a list of
    // {loc, msg} objects for validation errors (e.g. an empty password).
    const d = (await res.json().catch(() => ({}))).detail;
    const msg = Array.isArray(d) ? d.map((e) => `${e.loc?.at(-1) ?? "input"}: ${e.msg}`).join("; ") : d;
    throw new Error(msg || ("HTTP " + res.status));
  }
  return res.json();
}

// Text with clickable links, built from DOM nodes (never innerHTML) so a chat
// message cannot inject markup. The bot's "Sources:" list becomes links.
const URL_RE = /https?:\/\/[^\s<>"]+/g;
function renderText(el, text) {
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    el.appendChild(document.createTextNode(text.slice(last, m.index)));
    const a = document.createElement("a");
    a.href = m[0]; a.textContent = m[0].replace(/^https?:\/\//, "").slice(0, 70) + (m[0].length > 78 ? "…" : "");
    a.target = "_blank"; a.rel = "noopener noreferrer";
    el.appendChild(a);
    last = m.index + m[0].length;
  }
  el.appendChild(document.createTextNode(text.slice(last)));
}

function addMessage(m) {
  const el = document.createElement("div");
  el.className = "message" + (m.is_bot ? " bot" : "");
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${m.username || "unknown"} • ${new Date(m.created_at).toLocaleString()}`;
  const body = document.createElement("div");
  body.className = "body";
  renderText(body, m.content);
  el.appendChild(meta);
  el.appendChild(body);
  messagesDiv.appendChild(el);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function loadMessages() {
  const data = await callAPI("/messages");
  messagesDiv.innerHTML = "";
  for (const m of data.messages) addMessage(m);
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === "message") addMessage(data.message);
    } catch (e) {}
  };
  ws.onclose = () => {
    // try to reconnect after a delay
    setTimeout(connectWS, 2000);
  };
}

signupBtn.onclick = async () => {
  try {
    const out = await callAPI("/signup", "POST", {
      username: usernameInput.value.trim(),
      password: passwordInput.value
    });
    token = out.token;
    localStorage.setItem("token", token);
    await loadMessages();
    connectWS();
    showChat();
  } catch (e) {
    authMsg.textContent = e.message;
  }
};

loginBtn.onclick = async () => {
  try {
    const out = await callAPI("/login", "POST", {
      username: usernameInput.value.trim(),
      password: passwordInput.value
    });
    token = out.token;
    localStorage.setItem("token", token);
    await loadMessages();
    connectWS();
    showChat();
  } catch (e) {
    authMsg.textContent = e.message;
  }
};

logoutBtn.onclick = () => {
  token = "";
  localStorage.removeItem("token");
  showAuth();
};

sendBtn.onclick = async () => {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  await callAPI("/messages", "POST", {content: text});
};

// Suggested questions: one click asks the bot.
document.querySelectorAll("#suggest .chip").forEach((b) => {
  b.onclick = () => { chatInput.value = b.textContent; sendBtn.click(); };
});

// Enter sends (the template only wired the Send button).
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); sendBtn.click(); }
});

if (token) {
  loadMessages().then(()=>{
    connectWS();
    showChat();
  }).catch(()=>showAuth());
} else {
  showAuth();
}

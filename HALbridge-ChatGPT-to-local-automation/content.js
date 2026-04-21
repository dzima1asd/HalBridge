// content.js – HalBridge-integrated

const SERVER_URL = "http://192.168.100.12:5000"; const TOKEN = localStorage.getItem("halbridge_token") || "bardzo_sekretny_token"; const AUTO_RUN = localStorage.getItem("halbridge_auto_run") === "true"; const DEBUG = true;

function log(...args) { if (DEBUG) console.log("[HalBridge Extension]", ...args); }

function sendToServer(endpoint, data, callback) { fetch(${SERVER_URL}${endpoint}, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": Bearer ${TOKEN} }, body: JSON.stringify(data) }) .then(res => res.json()) .then(callback) .catch(err => log("Błąd połączenia z serwerem:", err)); }

function processMessage(node) { const text = node.innerText; if (!text) return;

// === Komenda systemowa ===
const cmdMatch = text.match(/###(.*?)###/);
if (cmdMatch) {
    const command = cmdMatch[1].trim();
    if (AUTO_RUN) {
        sendToServer("/run-command", { command }, res => log("Wynik:", res.result));
    } else {
        addButton(node, "Wykonaj", () => {
            sendToServer("/run-command", { command }, res => log("Wynik:", res.result));
        });
    }
}

// === Prompt AI Plan B ===
const promptMatch = text.match(/\$&\$(.*?)\$&\$/s);
if (promptMatch) {
    const prompt = promptMatch[1].trim();
    if (AUTO_RUN) {
        sendToServer("/ai-prompt", { prompt }, res => insertReply(res.result));
    } else {
        addButton(node, "Wyślij do agenta", () => {
            sendToServer("/ai-prompt", { prompt }, res => insertReply(res.result));
        });
    }
}

// === Obsługa odpowiedzi zwrotnych @#@...@#@ ===
if (text.includes("@#@")) {
    const responseMatch = text.match(/@#@(.*?)@#@/s);
    if (responseMatch) {
        insertReply(responseMatch[1].trim());
    }
}

}

function addButton(node, label, onClick) { const btn = document.createElement("button"); btn.textContent = [${label}]; btn.style.marginLeft = "10px"; btn.onclick = onClick; node.appendChild(btn); }

function insertReply(text) { const textarea = document.querySelector("textarea"); if (textarea) { textarea.value = text; textarea.dispatchEvent(new Event("input", { bubbles: true })); } }

// === MutationObserver === const observer = new MutationObserver(mutations => { for (const mutation of mutations) { for (const node of mutation.addedNodes) { if (node.nodeType === 1 && node.innerText) { processMessage(node); } } } });

observer.observe(document.body, { childList: true, subtree: true });

log("Rozszerzenie HalBridge aktywne.");


// background.js – HalBridge-kompatybilny

chrome.runtime.onInstalled.addListener(() => { console.log("[HalBridge] Rozszerzenie zainstalowane"); chrome.storage.local.set({ halbridge_token: "bardzo_sekretny_token", halbridge_auto_run: false, halbridge_debug: true }); });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => { if (msg.type === "setConfig") { chrome.storage.local.set(msg.data, () => sendResponse({ success: true })); return true; // async } if (msg.type === "getConfig") { chrome.storage.local.get(null, config => sendResponse(config)); return true; } });

chrome.runtime.onStartup.addListener(() => { console.log("[HalBridge] Rozszerzenie uruchomione"); });


// popup.js – zarządzanie konfiguracją rozszerzenia HalBridge

document.addEventListener("DOMContentLoaded", () => {
  const tokenInput = document.getElementById("token");
  const autoRunCheckbox = document.getElementById("autoRun");
  const debugCheckbox = document.getElementById("debug");

  // Wczytaj istniejące ustawienia z chrome.storage.local
  chrome.storage.local.get(
    ["halbridge_token", "halbridge_auto_run", "halbridge_debug"],
    (data) => {
      tokenInput.value = data.halbridge_token || "";
      autoRunCheckbox.checked = data.halbridge_auto_run || false;
      debugCheckbox.checked = data.halbridge_debug || false;
    }
  );

  // Zapisz ustawienia po kliknięciu przycisku
  document.getElementById("saveBtn").addEventListener("click", () => {
    const newToken = tokenInput.value.trim();
    const newAutoRun = autoRunCheckbox.checked;
    const newDebug = debugCheckbox.checked;

    chrome.storage.local.set(
      {
        halbridge_token: newToken,
        halbridge_auto_run: newAutoRun,
        halbridge_debug: newDebug,
      },
      () => {
        alert("✅ Zapisano ustawienia.");
      }
    );
  });
});

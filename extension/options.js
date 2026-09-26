const HOST_NAME = "com.liveplayer.host";

const $ = (id) => document.getElementById(id);

async function load() {
  const stored = await chrome.storage.sync.get({ defaultQuality: "best" });
  $("defaultQuality").value = stored.defaultQuality || "best";
}

$("defaultQuality").addEventListener("change", () => {
  chrome.storage.sync.set({ defaultQuality: $("defaultQuality").value });
  $("status").textContent = "已保存默认画质。";
});

$("check").addEventListener("click", () => {
  $("status").textContent = "检查中…";
  chrome.runtime.sendNativeMessage(HOST_NAME, { action: "health" }, (resp) => {
    const err = chrome.runtime.lastError;
    if (err) {
      $("status").textContent = "连接失败：" + err.message;
      return;
    }
    $("status").textContent = JSON.stringify(resp, null, 2);
  });
});

load();

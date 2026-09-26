const HOST_NAME = "com.liveplayer.host";
const PLATFORM_LABEL = {
  bilibili_live: "B站直播",
  bilibili_video: "B站视频",
  douyu: "斗鱼直播",
  huya: "虎牙直播",
};

const $ = (id) => document.getElementById(id);
let currentUrl = "";
let currentTarget = null;

function detect(rawUrl) {
  const url = (rawUrl || "").trim();
  const low = url.toLowerCase();
  if (!/^https?:/i.test(low)) return null;
  if (/bilibili\.com/.test(low)) {
    if (/\/(video|bangumi)\//.test(low) || /(BV[0-9A-Za-z]{8,}|av\d+)/.test(url)) {
      return { platform: "bilibili_video", kind: "video" };
    }
    return { platform: "bilibili_live", kind: "live" };
  }
  if (/douyu\.com/.test(low)) return { platform: "douyu", kind: "live" };
  if (/huya\.com/.test(low)) return { platform: "huya", kind: "live" };
  return null;
}

function send(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

function setResult(text, cls) {
  const el = $("result");
  el.textContent = text || "";
  el.className = "result" + (cls ? " " + cls : "");
}

function qualityText(q) {
  if (!q) return "?";
  return `${q.label}${q.height ? " (" + q.height + "p)" : ""}`;
}

async function init() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  currentUrl = (tab && tab.url) || "";
  currentTarget = detect(currentUrl);

  if (!currentTarget) {
    $("page-info").textContent = "当前页面不是支持的直播/视频页面。";
    $("play").disabled = true;
    $("list").disabled = true;
    $("copy").disabled = true;
  } else {
    $("page-info").innerHTML =
      `当前：<b>${PLATFORM_LABEL[currentTarget.platform] || currentTarget.platform}</b><br><span style="color:#9aa0aa">${currentUrl}</span>`;
  }

  const stored = await chrome.storage.sync.get({ defaultQuality: "best" });
  $("quality").value = stored.defaultQuality || "best";

  const status = await send({ type: "status" });
  if (status && status.ok) {
    $("helper-status").textContent = status.potplayer ? "助手就绪" : "助手就绪（未找到 PotPlayer）";
  } else {
    $("helper-status").textContent = "助手未就绪";
    setResult((status && status.error) || "无法连接本地助手，请先运行注册脚本并确认 host.exe 存在。", "error");
  }
}

$("quality").addEventListener("change", () => {
  chrome.storage.sync.set({ defaultQuality: $("quality").value });
});

$("play").addEventListener("click", async () => {
  if (!currentTarget) return;
  setResult("正在解析并启动 PotPlayer…");
  $("play").disabled = true;
  const resp = await send({ type: "play", url: currentUrl, quality: $("quality").value });
  $("play").disabled = false;
  if (resp && resp.ok) {
    setResult(`已用 PotPlayer 播放：${qualityText(resp.selected)}`, "ok");
  } else {
    setResult((resp && resp.error) || "播放失败", "error");
  }
});

$("list").addEventListener("click", async () => {
  if (!currentTarget) return;
  setResult("正在获取画质…");
  const resp = await send({ type: "parse", url: currentUrl, quality: $("quality").value });
  if (resp && resp.ok) {
    const list = (resp.qualities || []).map((q) => qualityText(q)).join("，");
    setResult(`可选画质：${list}\n已选：${qualityText(resp.selected)}`, "ok");
  } else {
    setResult((resp && resp.error) || "获取失败", "error");
  }
});

$("copy").addEventListener("click", async () => {
  if (!currentTarget) return;
  setResult("正在获取直链…");
  const resp = await send({ type: "parse", url: currentUrl, quality: $("quality").value });
  if (resp && resp.ok && resp.url) {
    try {
      await navigator.clipboard.writeText(resp.url);
      setResult("直链已复制到剪贴板。", "ok");
    } catch (e) {
      setResult(resp.url, "ok");
    }
  } else {
    setResult((resp && resp.error) || "获取失败", "error");
  }
});

$("open-options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

init();

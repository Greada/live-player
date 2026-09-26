// LivePlayer Service Worker：识别平台、读取登录 Cookie、调用本地 Host。
const HOST_NAME = "com.liveplayer.host";

const PLATFORM_LABEL = {
  bilibili_live: "B站直播",
  bilibili_video: "B站视频",
  douyu: "斗鱼直播",
  huya: "虎牙直播",
};

function detect(rawUrl) {
  const url = (rawUrl || "").trim();
  const low = url.toLowerCase();
  if (!url) return null;
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

async function buildCookieHeader(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    return "";
  }
}

function callHost(message) {
  return chrome.runtime.sendNativeMessage(HOST_NAME, message);
}

async function runPlay(url, quality) {
  const cookies = await buildCookieHeader(url);
  return await callHost({ action: "play", url, cookies, quality: quality || "" });
}

async function runParse(url, quality) {
  const cookies = await buildCookieHeader(url);
  return await callHost({ action: "parse", url, cookies, quality: quality || "" });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "lp-play",
    title: "用 PotPlayer 播放",
    contexts: ["page", "link", "video"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "lp-play") return;
  const url = info.linkUrl || info.pageUrl || (tab && tab.url) || "";
  try {
    await runPlay(url, "");
  } catch (e) {
    console.warn("LivePlayer 播放失败:", e);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "status") {
        sendResponse(await callHost({ action: "health" }));
      } else if (msg.type === "play") {
        sendResponse(await runPlay(msg.url, msg.quality));
      } else if (msg.type === "parse") {
        sendResponse(await runParse(msg.url, msg.quality));
      } else {
        sendResponse({ ok: false, error: "未知消息类型" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: (e && e.message) || String(e) });
    }
  })();
  return true;
});

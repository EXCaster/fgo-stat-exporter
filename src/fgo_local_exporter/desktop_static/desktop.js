/* 本机窗口桥；只调用已绑定当前回环页面会话的本机方法。 */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const explanations = {
    RESOURCE_DOWNLOAD_FAILED:"公开资源下载失败，可重试；不需要连接统计网站。",
    RESOURCE_VERSION_CHANGED:"上游资源已变化，未使用未验证的版本。请更新程序或选择已核验资源。",
    RESOURCE_PREPARE_FAILED:"资源未准备完整，请重试或选择已有资源目录。",
    EXPORT_PATH_EXISTS:"所选文件已经存在，请换一个文件名保存。",
    EXPORT_EXTENSION_INVALID:"请保留文件的 JSON 或 JPG 扩展名。",
    LOCAL_OPERATION_FAILED:"本机操作未完成，请重试。"
  };
  let connected = false, updating = false;
  const documents = document.createElement("button");
  documents.id = "desktop-documents";
  documents.type = "button";
  documents.className = "button light";
  documents.textContent = "使用说明与许可";
  $("desktop-open-folder").insertAdjacentElement("afterend", documents);
  documents.addEventListener("click", async () => {
    try { await command("open_documents"); }
    catch (error) { notice(error.message); }
  });
  function notice(text) { $("desktop-notice").textContent = text; }
  function failed(value) {
    if (!value?.ok) throw new Error((explanations[value?.error] || "操作未完成") + ` (${value?.error || "LOCAL_OPERATION_FAILED"})`);
    return value;
  }
  async function command(name, ...args) {
    if (!connected) throw new Error("桌面窗口尚未就绪，请稍候。");
    return failed(await window.pywebview.api[name](...args));
  }
  async function refresh() {
    if (!connected || updating) return;
    updating = true;
    try {
      const value = await command("status");
      window.renderResourceStatus(value.resources, value.dictionary_directory);
      $("desktop-open-folder").hidden = !value.can_open_folder;
    } catch (error) { notice(error.message); }
    finally { updating = false; }
  }
  for (const [id, name] of [["desktop-open-dictionary","open_dictionary_folder"],["desktop-prepare","prepare_resources"],["desktop-existing","choose_resources"],["desktop-open-folder","open_folder"]]) {
    $(id).addEventListener("click", async () => {
      const button = $(id);
      button.disabled = true;
      if (name === "prepare_resources") notice("已开始查询上游资源版本，进度和结果会显示在下方。");
      try { await command(name); await refresh(); }
      catch (error) { notice(error.message); button.disabled = false; }
    });
  }
  $("download-json").addEventListener("click", async event => {
    event.preventDefault();
    try {
      const result = await command("save_json");
      notice(result.saved ? `统计 JSON 已保存：${result.name}` : "已取消保存，没有写入文件。");
      await refresh();
    } catch (error) { notice(error.message); }
  });
  window.fgoDesktopSave = async (dataUrl, name, version) => {
    const result = await command("save_image", dataUrl, name, version);
    notice(result.saved ? `统计图片已保存：${result.name}` : "图片已在本机生成；已取消保存，没有写入文件。");
    await refresh();
  };
  async function ready() {
    try {
      const csrf = document.querySelector('meta[name="fgo-csrf"]').content;
      const initial = failed(await window.pywebview.api.connect(csrf));
      connected = true;
      if (!initial.resources.ready) await command("prepare_resources");
      await refresh();
      window.setInterval(refresh, 400);
    } catch (error) { notice(error.message); }
  }
  if (window.pywebview?.api) ready();
  else window.addEventListener("pywebviewready", ready, {once:true});
})();

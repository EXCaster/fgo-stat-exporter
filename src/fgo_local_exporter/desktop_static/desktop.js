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
    LOCAL_OPERATION_FAILED:"操作未完成，请重试。",
    DATA_DIRECTORY_UNAVAILABLE:"所选目录无法写入，请选择固定磁盘上的其他文件夹。",
    DATA_SETTINGS_UNAVAILABLE:"无法记住数据目录，请检查 Windows 用户权限后重试。"
  };
  let connected = false, updating = false;
  const storageRow = document.createElement("div");
  storageRow.className = "desktop-directory";
  storageRow.innerHTML = '<label for="desktop-data-directory">数据保存位置</label><input id="desktop-data-directory" readonly aria-label="数据保存位置"><button id="desktop-change-data" class="button light" type="button">更换数据目录</button>';
  $("desktop-dictionary-directory").closest(".desktop-directory").insertAdjacentElement("beforebegin", storageRow);
  const storageHint = document.createElement("p");
  storageHint.className = "desktop-secondary";
  storageHint.id = "desktop-storage-hint";
  storageRow.insertAdjacentElement("afterend", storageHint);
  $("desktop-change-data").addEventListener("click", async () => {
    const button = $("desktop-change-data");
    button.disabled = true;
    try {
      const result = await command("choose_data_directory");
      if (result.changed) notice(result.restart_required ? "数据目录已设置，重启应用后生效。原目录的文件会保留。" : "已继续使用当前数据目录。");
      await refresh();
    } catch (error) { notice(error.message); }
    finally { button.disabled = false; }
  });
  const openData = document.createElement("button");
  openData.id = "desktop-open-data";
  openData.type = "button";
  openData.className = "button light";
  openData.textContent = "打开数据目录";
  $("desktop-existing").insertAdjacentElement("afterend", openData);
  openData.addEventListener("click", async () => {
    try { await command("open_data_folder"); }
    catch (error) { notice(error.message); }
  });
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
      $("desktop-data-directory").value = value.data_directory;
      storageHint.textContent = value.pending_data_directory ? `重启后使用：${value.pending_data_directory}。原目录的文件会保留。` : "字典、图片缓存和浏览器数据保存在此目录。";
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
    notice(result.saved ? `统计图片已保存：${result.name}` : "已取消保存，没有写入文件。");
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

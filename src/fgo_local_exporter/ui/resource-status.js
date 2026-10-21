/* 桌面和安卓共用资源状态，版本检查失败时明确保留旧版。 */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const busyPhases = new Set(["discovering", "checking", "downloading", "validating", "activating"]);
  const phases = {discovering:"查询上游版本", checking:"校验资源", downloading:"下载更新", validating:"核验完整版本", activating:"启用新资源"};
  const errors = {
    RESOURCE_DOWNLOAD_FAILED:"无法连接公开资源源站，请检查网络后重试。",
    RESOURCE_VERSION_CHANGED:"源站在下载期间更新了数据，请重新检查。",
    RESOURCE_FORMAT_UNSUPPORTED:"新版数据格式暂不兼容，需更新应用后重试。",
    RESOURCE_CATALOG_INCOMPLETE:"源站资源清单尚不完整，请稍后重试。",
    RESOURCE_MANIFEST_INVALID:"资源清单未通过校验，请稍后重试。",
    RESOURCE_SIZE_LIMIT:"资源超出当前应用的读取限额。"
  };
  function megabytes(value) { return `${(Math.max(0, value || 0) / 1048576).toFixed(1)} MB`; }
  window.renderResourceStatus = (resource, directory) => {
    const busy = busyPhases.has(resource.phase), failed = resource.phase === "error";
    const checked = resource.last_checked_at > 0;
    $("desktop-resource-state").textContent = busy ? "更新检查中" : failed ? "检查未完成" : resource.ready ? "已就绪" : "缺少资源";
    $("desktop-resource-state").dataset.state = busy ? "busy" : failed || !resource.ready ? "error" : "ready";
    $("desktop-dictionary-directory").value = directory || "资源准备后显示保存位置";
    $("desktop-open-dictionary").disabled = !directory;
    $("desktop-dictionary-meta").textContent = `当前字典：${resource.version}`;
    $("desktop-images-meta").textContent = `已缓存图片 ${resource.public_images} 张 · 助战组件 ${resource.native_images} 张 · ${megabytes(resource.image_bytes)}`;
    let text;
    if (busy) text = resource.phase === "discovering" ? "正在检查从者、礼装、卡池、关卡及名称字典的最新版本…" : `${phases[resource.phase]}：${resource.current_file || "请稍候"}`;
    else if (failed) text = `${errors[resource.error] || "更新未完成，请重试。"}（${resource.error}）${resource.ready ? "现有字典仍可使用。" : ""}`;
    else if (checked) text = resource.result === "updated" ? `已启用新版本，本次下载 ${resource.repaired} 个字典文件。新版图片将在生成统计图时按需下载。` : `已检查上游，当前为最新版本；${resource.completed} 个文件通过校验，本次修复 ${resource.repaired} 个。`;
    else text = resource.ready ? "本机资源可用；检查更新后，新图片会在出图时按需下载并缓存。" : "正在准备统计资源…";
    $("desktop-resources").textContent = text;
    $("desktop-progress-area").hidden = !(busy || checked || failed);
    $("desktop-progress-label").textContent = busy ? phases[resource.phase] : failed ? "检查未完成" : "检查完成";
    $("desktop-progress-number").textContent = resource.phase === "discovering" ? "连接源站…" : `${resource.completed} / ${resource.total}`;
    $("desktop-progress").max = Math.max(1, resource.total_bytes || resource.total);
    $("desktop-progress").value = Math.min(resource.total_bytes, resource.checked_bytes + resource.current_bytes);
    $("desktop-progress-detail").textContent = checked ? `已核验 ${megabytes(resource.checked_bytes)}；${new Date(resource.last_checked_at * 1000).toLocaleTimeString()} 完成。已有统计图可点击“重新生成统计图”使用新资源。` : resource.phase === "discovering" ? "每次检查都会直接查询公开源站，无需重新扫码。" : `${resource.current_file || "等待检查"} · ${megabytes(resource.checked_bytes + resource.current_bytes)} / ${megabytes(resource.total_bytes)}`;
    $("desktop-prepare").disabled = $("desktop-existing").disabled = busy;
    $("desktop-prepare").textContent = busy ? "正在检查资源更新…" : "检查资源更新";
    return busy;
  };
})();

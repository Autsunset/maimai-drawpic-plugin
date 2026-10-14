(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, buttonAction, toast } = U;
  let timer;
  async function original(taskId, index, button) {
    let offset = 0,
      info,
      parts = [];
    do {
      info = await call("query", "original", {
        task_id: taskId,
        index,
        offset,
      });
      const decoded = atob(info.data);
      const bytes = Uint8Array.from(decoded, (ch) => ch.charCodeAt(0));
      parts.push(bytes);
      offset = info.next_offset;
      button.textContent = `读取原图 ${Math.round((offset / info.size) * 100)}%`;
    } while (!info.done);
    const url = URL.createObjectURL(new Blob(parts, { type: info.mime }));
    const node = U.modal(
      "原图预览",
      `<img class="detail-image" src="${e(url)}" alt="生成的原图"><p class="hint">${e(info.filename)} · ${(info.size / 1024 / 1024).toFixed(2)} MiB · 原文件保存在当前实例的数据目录。</p>`,
      () => URL.revokeObjectURL(url),
    );
    node.scrollTop = 0;
  }
  async function openTask(taskId, index = 0) {
    const data = await call("query", "task", { task_id: taskId });
    const node = U.modal(
      "绘图任务详情",
      `<div class="toolbar"><div class="actions"><span class="pill ${e(data.status)}">${e(U.statusLabel(data.status))}</span><span class="pill">${e(data.model)}</span></div><button id="detail-refresh" class="button secondary compact">${icon("refresh")}刷新</button></div><div id="detail-preview">${data.images.length ? '<div class="loading"><span class="spinner"></span>加载图片…</div>' : U.empty("暂无图片结果", data.status === "completed" ? "图片已清理或此历史任务未保存结果。新图片可在保留期内预览。" : data.message)}</div><div class="image-selector">${data.images.map((image, i) => `<button class="button ${i === index ? "" : "secondary"} compact" data-image-index="${i}">第 ${i + 1} 张</button>`).join("")}</div><div class="actions" style="margin-top:15px">${data.images.length ? `<button id="view-original" class="button secondary compact">${icon("eye")}查看原图</button>` : ""}${["pending", "running"].includes(data.status) ? '<button id="cancel-task" class="button danger compact">取消任务</button>' : ""}<button id="task-log" class="button ghost compact">查看任务日志</button></div><p class="hint" style="margin-top:20px">${e(data.message)}<br>任务 ${e(taskId)} · ${e(U.date(data.created_at))}</p>${data.prompt ? `<details style="margin-top:15px"><summary class="muted">本次提示词</summary><p class="hint" style="white-space:pre-wrap">${e(data.prompt)}</p></details>` : ""}`,
    );
    $("#detail-refresh", node).onclick = () =>
      openTask(taskId, index).catch(U.error);
    node.querySelectorAll("[data-image-index]").forEach((button) => {
      button.onclick = () =>
        openTask(taskId, Number(button.dataset.imageIndex)).catch(U.error);
    });
    $("#task-log", node).onclick = () => {
      state.logTask = taskId;
      U.closeModal();
      U.navigate("logs").catch(U.error);
    };
    if ($("#cancel-task", node))
      $("#cancel-task", node).onclick = (event) =>
        buttonAction(event.currentTarget, async () => {
          await call("action", "cancel", { task_id: taskId });
          toast("已取消任务");
          await openTask(taskId, index);
        });
    if (data.images.length) {
      const image = await call("query", "image", { task_id: taskId, index });
      if (!node.isConnected || !$("#detail-preview", node)) return;
      $("#detail-preview", node).innerHTML =
        `<img class="detail-image" src="${e(image.data_url)}" alt="任务生成图片 ${index + 1}"><p class="hint">${image.width} × ${image.height} · ${(image.size / 1024 / 1024).toFixed(2)} MiB · 页面先显示压缩预览，原文件独立保存。</p>`;
      $("#view-original", node).onclick = (event) =>
        buttonAction(event.currentTarget, () =>
          original(taskId, index, event.currentTarget),
        );
    }
  }
  async function renderTasks() {
    clearTimeout(timer);
    const result = await call("query", "tasks", {
      page: state.taskPage,
      status: state.taskStatus,
      search: state.taskSearch,
    });
    if (state.view !== "tasks") return;
    const active = result.counts.pending + result.counts.running;
    $("#active-count").hidden = !active;
    $("#active-count").textContent = active;
    $("#workspace-content").innerHTML =
      `<div class="stat-row"><div class="stat"><div class="stat-label">全部任务</div><div class="stat-value">${Object.values(result.counts).reduce((a, b) => a + b, 0)}</div></div><div class="stat"><div class="stat-label">进行中</div><div class="stat-value">${active}</div></div><div class="stat"><div class="stat-label">已完成</div><div class="stat-value">${result.counts.completed}</div></div><div class="stat"><div class="stat-label">失败 / 未通过</div><div class="stat-value">${result.counts.failed + result.counts.rejected}</div></div></div><form id="task-search" class="toolbar"><div class="actions"><select id="task-status" class="search-input" aria-label="筛选任务状态">${[
        ["", "全部状态"],
        ["pending", "等待执行"],
        ["running", "正在绘图"],
        ["completed", "已完成"],
        ["failed", "失败"],
        ["rejected", "审核未通过"],
      ]
        .map(
          ([value, label]) =>
            `<option value="${value}" ${value === state.taskStatus ? "selected" : ""}>${label}</option>`,
        )
        .join(
          "",
        )}</select><input id="task-search-text" class="search-input" value="${e(state.taskSearch)}" placeholder="搜索模型、任务 ID 或失败原因" aria-label="搜索任务"><button type="submit" class="button secondary">搜索</button></div><span class="hint">${active ? "任务进行中，每 5 秒刷新" : "最近保留 500 个任务记录"}</span></form>${result.items.length ? `<div class="card-grid">${result.items.map((item) => `<button class="panel task-card" data-task="${e(item.task_id)}" aria-label="查看 ${e(item.model)} 任务详情">${item.thumbnail ? `<img class="task-art" src="${e(item.thumbnail)}" alt="绘图任务缩略图">` : `<div class="task-no-image">${icon(["pending", "running"].includes(item.status) ? "clock" : "images")}<span>${e(U.statusLabel(item.status))}</span></div>`}<div class="task-body"><span class="pill ${e(item.status)}">${e(U.statusLabel(item.status))}</span><h3>${e(item.model)}</h3><p class="task-message">${e(item.message)}</p><div class="task-bottom"><span>${{ webui: "网页创作", plugin: "插件联动", chat: "聊天绘图" }[item.origin] || "绘图任务"} · ${item.image_count} 张</span><span>${e(U.date(item.created_at))}</span></div></div></button>`).join("")}</div>` : U.empty("这里还没有任务", "开始一幅新的作品，或者调整搜索和筛选条件。")}<div class="actions pagination"><button id="previous-page" class="button secondary compact" ${state.taskPage <= 1 ? "disabled" : ""}>上一页</button><span class="muted">${state.taskPage} / ${Math.max(1, Math.ceil(result.total / result.page_size))}</span><button id="next-page" class="button secondary compact" ${state.taskPage * result.page_size >= result.total ? "disabled" : ""}>下一页</button></div>`;
    document.querySelectorAll("[data-task]").forEach((button) => {
      button.onclick = () => openTask(button.dataset.task).catch(U.error);
    });
    U.bindSubmit($("#task-search"));
    $("#task-search").onsubmit = (event) => {
      event.preventDefault();
      state.taskSearch = $("#task-search-text").value;
      state.taskStatus = $("#task-status").value;
      state.taskPage = 1;
      renderTasks().catch(U.error);
    };
    $("#task-status").onchange = () => U.submitForm($("#task-search"));
    $("#previous-page").onclick = () => {
      state.taskPage--;
      renderTasks().catch(U.error);
    };
    $("#next-page").onclick = () => {
      state.taskPage++;
      renderTasks().catch(U.error);
    };
    if (active) {
      const poll = () => {
        if (state.view !== "tasks") return;
        if (document.hidden || $("#modal").open || state.busy) {
          timer = setTimeout(poll, 5000);
          return;
        }
        renderTasks().catch(U.error);
      };
      timer = setTimeout(poll, 5000);
    }
  }
  U.views.tasks = renderTasks;
  U.openTask = openTask;
})();

(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, buttonAction } = U;
  let timer,
    debounce,
    generation = 0;
  U.views.logs = async () => {
    clearTimeout(timer);
    clearTimeout(debounce);
    const token = ++generation;
    let cursor = "",
      loading = false;
    $("#workspace-content").innerHTML =
      `<form id="log-filter" class="toolbar"><div class="actions"><input id="log-task" class="search-input" value="${e(state.logTask || "")}" maxlength="12" placeholder="任务 ID，留空查看全部" aria-label="筛选日志任务"><select id="log-level" class="search-input" aria-label="筛选日志级别"><option value="">全部级别</option>${["INFO", "WARNING", "ERROR", "DEBUG"].map((value) => `<option value="${value}" ${state.logLevel === value ? "selected" : ""}>${value}</option>`).join("")}</select><button type="submit" class="button secondary">${icon("refresh")}查询</button></div></form><div class="toolbar log-controls"><label class="actions"><input type="checkbox" id="log-auto" checked>自动刷新</label><span id="log-status" class="hint" role="status">正在读取…</span></div><section class="panel log-panel"><pre class="log-output" id="log-output" role="log" aria-label="插件日志">正在读取…</pre></section>`;
    function schedule() {
      clearTimeout(timer);
      if (state.view !== "logs" || token !== generation) return;
      timer = setTimeout(async () => {
        if (!document.hidden && $("#log-auto")?.checked && !state.busy) {
          try {
            await load();
          } catch (error) {
            U.error(error);
          }
        }
        schedule();
      }, 5000);
    }
    async function load(reset = false) {
      if (loading || state.view !== "logs" || token !== generation) return;
      loading = true;
      if (reset) cursor = "";
      $("#log-status").textContent = "正在查询…";
      try {
        state.logTask = $("#log-task").value.trim();
        state.logLevel = $("#log-level").value;
        const result = await call("query", "logs", {
          task_id: state.logTask,
          level: state.logLevel,
          limit: 120,
          cursor,
        });
        if (state.view !== "logs" || token !== generation) return;
        const output = $("#log-output");
        if (!result.unchanged) {
          const follow =
            output.scrollTop + output.clientHeight >= output.scrollHeight - 40;
          output.textContent =
            result.lines.join("\n") ||
            "暂无符合条件的日志。新日志会在这里显示。";
          if (follow || reset) output.scrollTop = output.scrollHeight;
        }
        cursor = result.cursor;
        $("#log-status").textContent =
          `最近 120 条 · ${new Date().toLocaleTimeString("zh-CN")} · ${result.unchanged ? "暂无新增" : "已更新"}`;
      } catch (error) {
        if (state.view === "logs" && token === generation)
          $("#log-status").textContent = "查询失败，可点击查询重试";
        throw error;
      } finally {
        loading = false;
      }
    }
    const form = $("#log-filter");
    U.bindSubmit(form);
    form.onsubmit = (event) => {
      event.preventDefault();
      buttonAction($("button", form), () => load(true));
    };
    $("#log-task").oninput = () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => load(true).catch(U.error), 300);
    };
    $("#log-level").onchange = () => load(true).catch(U.error);
    await load();
    schedule();
  };
})();

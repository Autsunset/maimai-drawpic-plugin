(() => {
  "use strict";
  const paths = {
    sparkles:
      '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/><path d="m20 2 .7 1.3L22 4l-1.3.7L20 6l-.7-1.3L18 4l1.3-.7Z"/>',
    images:
      '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1.5"/><path d="m5 18 5-5 3 3 3-4 4 5"/>',
    layers:
      '<path d="m12 3 10 5-10 5L2 8l10-5Z"/><path d="m2 12 10 5 10-5M2 16l10 5 10-5"/>',
    sliders:
      '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="2" fill="currentColor"/><circle cx="16" cy="17" r="2" fill="currentColor"/>',
    terminal:
      '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
    refresh: '<path d="M20 8a8 8 0 1 0 1 6M20 3v5h-5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v4h16v-4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  };
  const state = {
    view: "studio",
    data: null,
    dirty: false,
    busy: 0,
    taskPage: 1,
    taskStatus: "",
    taskSearch: "",
    sources: [],
    lastTask: null,
    requestId: null,
  };
  const views = {};
  const titles = {
    studio: ["开始创作", "从一个想法开始，剩下的交给画笔。"],
    tasks: ["绘图任务", "每一次创作，都可以在这里找到。"],
    platforms: ["绘图平台", "用到哪个，就添加哪个。让每个模型各展所长。"],
    settings: ["偏好与预设", "把常用的选择，变成顺手的习惯。"],
    logs: ["运行日志", "沿着任务链路，找到问题发生的位置。"],
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const e = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (ch) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[ch],
    );
  const icon = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.plus}</svg>`;
  const uid = () =>
    Array.from(crypto.getRandomValues(new Uint8Array(12)), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
  let queue = Promise.resolve(),
    toastTimer,
    modalCleanup;
  async function call(kind, name, args = {}, file = null, options = {}) {
    const operation = queue.then(async () => {
      state.busy++;
      try {
        if (!window.maibot)
          throw new Error("请在 MaiBot 的插件扩展页面打开工作台");
        await window.maibot.ready;
        const result =
          kind === "upload"
            ? await window.maibot.upload(name, file, args, options)
            : await window.maibot[kind](name, args);
        if (typeof result?.__workspace_error__ === "string")
          throw new Error(result.__workspace_error__);
        return result;
      } finally {
        state.busy--;
      }
    });
    queue = operation.catch(() => {});
    return operation;
  }
  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      node.hidden = true;
    }, 4500);
  }
  function error(error) {
    toast(error.message || String(error));
  }
  async function buttonAction(button, operation) {
    button.disabled = true;
    try {
      return await operation();
    } catch (err) {
      error(err);
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  }
  function modal(title, html, cleanup = null) {
    if (modalCleanup) modalCleanup();
    modalCleanup = cleanup;
    $("#modal-title").textContent = title;
    $("#modal-content").innerHTML = html;
    if (!$("#modal").open) $("#modal").showModal();
    return $("#modal-content");
  }
  function closeModal() {
    $("#modal").close();
  }
  $("#modal").addEventListener("close", () => {
    if ($("#provider-form")) state.dirty = false;
    if (modalCleanup) modalCleanup();
    modalCleanup = null;
  });
  $("#modal-close").onclick = closeModal;
  async function bootstrap() {
    state.data = await call("query", "bootstrap");
    $("#connection").textContent = "已连接当前实例";
    $("#load-error").hidden = true;
    return state.data;
  }
  async function render() {
    const [title, description] = titles[state.view];
    $("#page-title").textContent = title;
    $("#page-description").textContent = description;
    document.querySelectorAll("[data-view]").forEach((node) => {
      node.classList.toggle("active", node.dataset.view === state.view);
      node.setAttribute(
        "aria-current",
        node.dataset.view === state.view ? "page" : "false",
      );
    });
    updateNavigationIndicator();
    await views[state.view]();
  }
  function updateNavigationIndicator() {
    const nav = $("#navigation"),
      active = $("[data-view].active", nav);
    if (!active) return;
    let indicator = $("#navigation-indicator", nav);
    if (!indicator) {
      indicator = document.createElement("span");
      indicator.id = "navigation-indicator";
      indicator.setAttribute("aria-hidden", "true");
      nav.prepend(indicator);
      indicator.style.transition = "none";
      requestAnimationFrame(() => {
        indicator.style.transition = "";
      });
    }
    indicator.style.width = active.offsetWidth + "px";
    indicator.style.height = active.offsetHeight + "px";
    indicator.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
    nav.classList.add("navigation-ready");
  }
  new ResizeObserver(updateNavigationIndicator).observe($("#navigation"));
  async function navigate(view) {
    if (state.dirty) {
      const node = modal(
        "离开未保存的配置？",
        '<p class="muted">这次编辑还没有保存。离开后需要重新填写。</p><div class="modal-footer"><button class="button secondary" id="keep-editing">继续编辑</button><button class="button" id="discard-editing">离开</button></div>',
      );
      $("#keep-editing", node).onclick = closeModal;
      $("#discard-editing", node).onclick = () => {
        state.dirty = false;
        closeModal();
        navigate(view);
      };
      return;
    }
    state.view = view;
    window.location.hash = view;
    await render();
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function empty(title, description, button = "") {
    return `<div class="panel empty">${icon("sparkles")}<h3>${e(title)}</h3><p>${e(description)}</p>${button}</div>`;
  }
  function statusLabel(status) {
    return (
      {
        pending: "等待执行",
        running: "正在绘图",
        completed: "已完成",
        failed: "执行失败",
        rejected: "审核未通过",
      }[status] || status
    );
  }
  function date(value) {
    return value
      ? new Date(value).toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";
  }
  function bindDirty(root) {
    root.addEventListener("input", () => {
      state.dirty = true;
      const n = $("[data-unsaved]", root);
      if (n) n.hidden = false;
    });
  }
  function submitForm(form) {
    if (form.reportValidity()) {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    }
  }
  function bindSubmit(form) {
    // 宿主 sandbox 没有 allow-forms：使用受校验的事件处理，不进行原生表单导航。
    form.querySelectorAll('[type="submit"]').forEach((button) => {
      button.onclick = (event) => {
        event.preventDefault();
        submitForm(form);
      };
    });
    form.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.tagName === "INPUT") {
        event.preventDefault();
        submitForm(form);
      }
    });
  }
  window.DrawpicUI = {
    state,
    views,
    $,
    e,
    icon,
    uid,
    call,
    toast,
    error,
    buttonAction,
    modal,
    closeModal,
    bootstrap,
    render,
    navigate,
    empty,
    statusLabel,
    date,
    bindDirty,
    bindSubmit,
    submitForm,
  };
  document.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
  document.querySelectorAll("[data-view]").forEach((node) => {
    node.onclick = () => navigate(node.dataset.view).catch(error);
  });
  $(".brand").onclick = (event) => {
    event.preventDefault();
    navigate("studio").catch(error);
  };
  $("#refresh").onclick = () => {
    const refresh = () =>
      buttonAction($("#refresh"), async () => {
        await bootstrap();
        state.dirty = false;
        closeModal();
        await render();
        toast("已刷新");
      });
    if (!state.dirty) return refresh();
    const node = modal(
      "放弃未保存的修改？",
      '<p class="muted">刷新会重新读取已保存的配置。</p><div class="modal-footer"><button id="refresh-keep" class="button secondary">继续编辑</button><button id="refresh-discard" class="button">放弃并刷新</button></div>',
    );
    $("#refresh-keep", node).onclick = closeModal;
    $("#refresh-discard", node).onclick = refresh;
  };
})();

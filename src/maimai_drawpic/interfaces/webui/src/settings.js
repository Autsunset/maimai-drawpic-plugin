(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, buttonAction, toast } = U;
  const sections = {
    general: "通用与审核",
    style: "风格预设",
  };
  U.views.settings = async (reset = false) => {
    const selected = sections[state.settingsSection]
      ? state.settingsSection
      : "general";
    const schema = state.data.schema.sections[selected];
    const values = structuredClone(
      reset ? state.data.defaults[selected] : state.data.settings[selected],
    );
    if (reset) state.dirty = true;
    $("#workspace-content").innerHTML =
      `<div class="settings-layout"><div class="settings-tabs" role="tablist" aria-label="配置分类">${Object.entries(
        sections,
      )
        .map(
          ([name, title]) =>
            `<button class="settings-tab ${selected === name ? "active" : ""}" data-section="${name}" role="tab" aria-selected="${selected === name}">${title}</button>`,
        )
        .join(
          "",
        )}</div><section class="panel"><div class="panel-header"><div><h2>${e(sections[selected])}</h2><p class="hint">${selected === "style" ? "把常用风格保存为可复用的提示词模板，所有平台都可以使用。" : "绘图通用参数与预设由插件独立保存；网络代理和插件开关在 MaiBot 插件配置页管理。"}</p></div><button type="button" id="reset-settings" class="button secondary compact">恢复本页默认</button></div><form id="settings-form">${U.forms.html(schema.fields, values)}<datalist id="workspace-models">${state.data.models.map((model) => `<option value="${e(model.name)}"></option>`).join("")}</datalist><div class="sticky-save"><span data-unsaved class="unsaved" hidden>有未保存的修改</span><button class="button" type="submit">${icon("check")}保存设置</button></div></form></section></div>`;
    const form = $("#settings-form"),
      read = U.forms.bind(form, schema.fields, values);
    document.querySelectorAll("[data-section]").forEach((button) => {
      button.onclick = () => {
        if (state.dirty) {
          toast("请先保存当前修改，或使用刷新放弃本次编辑");
          return;
        }
        state.settingsSection = button.dataset.section;
        U.render().catch(U.error);
      };
    });
    $("#reset-settings").onclick = () =>
      U.views
        .settings(true)
        .then(() => toast("已恢复本页默认值，保存后生效"))
        .catch(U.error);
    if (reset) $("[data-unsaved]", form).hidden = false;
    U.bindSubmit(form);
    form.onsubmit = (event) => {
      event.preventDefault();
      buttonAction($("[type=submit]", form), async () => {
        const all = structuredClone(state.data.settings);
        all[selected] = read();
        await call("action", "settings_save", {
          config_json: JSON.stringify(all),
          revision: state.data.revision,
        });
        state.dirty = false;
        await U.bootstrap();
        await U.render();
        toast("设置已保存");
      });
    };
  };
})();

# AGENTS.md

## 本插件开发注意事项

- 本目录是独立插件仓库；提交、状态检查和 diff 优先使用 `git -C plugins/maimai-drawpic-plugin ...`。
- 不要修改 MaiBot 主程序代码来绕过插件问题；确实需要主程序改动时先说明原因并请求许可。
- 配置变更只改插件配置模板与配置模型；新增配置字段时同步提升 `config_version`。
- `src/maimai_drawpic/domain/models/` 只存放模型能力、任务约束与参数构造等纯定义；`src/maimai_drawpic/infrastructure/providers/` 只存放平台鉴权、传输、轮询、响应解析和图片下载适配器，不要把模型注册表放入平台适配器目录。
- 强制绘图命令必须严格区分模式：`/绘图 文生图` 检测到同条消息或引用消息中有真实图片时要提示改用图生图；`/绘图 图生图` 找不到真实源图时要提示补充图片，不能降级为文生图。
- 后台任务提交层也必须校验图生图能力；不支持图生图的平台或模型要在创建 task 与扣额度前拒绝，并返回明确原因。
- 文生图/图生图能力判断统一走 `ProviderRouter` 的模型任务能力接口；不要在各入口散写 `provider != ...` 之类的分支。
- 某些平台整体不支持图生图时在路由层内置原因；具体模型优先自动识别，也允许通过 `[general].image_edit_unsupported_models` 与 `[general].text_to_image_unsupported_models` 人工覆盖，不要等上游接口报错。
- 日志要能定位任务链路：提交、开始执行、能力拒绝、审核失败、平台失败、发送成功至少包含 `task_id`、`task_type`、`provider`、`model`、`source_image_count` 等关键字段。
- 日志严禁输出 API Key、Authorization、完整 Base64、带查询参数的签名 URL；上游错误应保留 HTTP 状态、业务错误码、脱敏 URL、request_id 与耗时。
- 源图处理必须校验真实图片 Base64，同时保留适配器给出的原始 HTTP(S) URL；不要把图片描述文本当作源图传入。
- 智谱图片接口默认模型为 `glm-image`；请求必填字段为 `model`、`prompt`，可选字段为 `quality`、`size`、`watermark_enabled`、`user_id`，并保留 `extra_parameters` 供用户自定义。不要重新加入当前官方接口未声明的 `response_format` 或旧 `user` 字段。
- 智谱当前模型列表没有 Z-Image；插件中的 `z-image-turbo` 属于阿里百炼平台。维护智谱适配时不要误删或混用阿里百炼的 Z-Image 模型及参数。
- 阿里云支持范围为 Qwen Image、Z-Image、可灵图像和 Vidu 图像；当前明确不接入万象、创意工具、图像翻译与视频生成。变更范围时应同步更新模型注册表、能力测试和 README。
- 阿里云 `base_url` 必须来自配置且以 `/api/v1` 结尾；不要硬编码用户工作空间地址。可灵/Vidu 图生图必须使用适配器原图 URL，Qwen 默认保持 Base64。
- 文档与 README 要同步用户可见行为，尤其是命令语义、配置项、版本号和不支持图生图时的处理方式。
- OpenAI 的 `rinkoai` 模式针对 `api.rinko.ai` 的 NAI 系列，替代已删除的 `novelai_images_api` 模式（旧值作为别名读取）。`chat_completions` 是独立的 New API 标准聊天绘图模式；源图使用 `messages[].content[].image_url`，不得混发 Gemini 原生 `contents`。自动模式优先参考模型端点信息，其次按模型系列排序；只允许在明确的端点不支持错误后切换格式，鉴权、配额、审核、模型错误以及成功响应解析/下载失败不得触发重绘。图生图表单重试只处理明确的 size/image 参数错误，不能静默丢掉源图。RinkoAI NAI 图生图仍在路由层提前拒绝，未经验证的参数或源图支持不得宣称生效。
- `src/maimai_drawpic/domain/configuration/` 新增或重命名配置节、配置字段时，必须同步维护 `src/maimai_drawpic/domain/configuration/localization.py` 的英语、日语和韩语 Schema 文案，并运行配置 i18n 覆盖测试；简体中文保留为默认文案和回退语言。
- 提交前运行受影响的测试、源码编译与 `git diff --check`。优先 `uv`，在 MaiBot 工作区验证可用 `uv run --project ../.. --no-sync python -m pytest tests -q`；不要为插件改动全量测试或构建宿主。

## 工程结构

- 根目录 `plugin.py` 只组合组件和导出 `create_plugin()`；`_manifest.json`、`webui.json` 是宿主声明，不放业务逻辑。
- 所有运行代码集中在 `src/maimai_drawpic/`，插件内部使用显式相对导入，不导入 MaiBot 主程序的 `src.*`。
- `domain/`：配置模型、平台模型能力、参数与风格规则；纯定义不依赖 SDK 运行上下文或网络。
- `application/`：生命周期组合、绘图审核/计划/执行、路由、聊天发送、会话偏好/额度和工作台服务。按职责分子包，避免新增大型单文件或无意义转发层。
- `infrastructure/`：平台传输适配器、HTTP、媒体校验、原子持久化与数据迁移。数据路径由 SDK 的 `ctx.paths` 注入，`paths.py` 只定位源码资源。
- `interfaces/`：聊天命令/工具/Hook、WebUI 私有 API、实例内公开 API、页面源码及生成产物。
- `assets/` 保留图片和字体资源；`docs/` 保存用户平台说明与联动指南；`tests/` 保存隔离验证；`tools/` 只放工程构建脚本。不要在根目录重新建立 core、providers、api 等平行源码目录。

## 工作台与配置所有权

- 平台实例按需添加，保存到标准数据目录的 `platforms.json`；未添加的平台明确禁用。不要重新在宿主默认配置页展示所有平台。
- `config.toml` 只保留 plugin/proxy，由 MaiBot 插件配置页管理；general/style 迁到 workspace_settings.json，由工作台管理，页面不展示代理或插件开关。完整配置模型用于兼容 Runner 归一化时保留旧配置；不得在迁移前丢弃旧平台字段。
- 旧 TOML 先按字节备份，再迁移平台并移除平台节；旧数据冲突必须报错，不覆盖。迁移、图片处理、日志和文件 IO 放到工作线程。
- 密钥不回传，留空保留，清除必须显式选择；配置保存带修订号，过期修改拒绝。不得把含密钥的 Pydantic 输入原样写入日志或返回页面。
- 当前 Host 自定义页面协议为 schema_version=2。源码位于 `interfaces/webui/src/`，用 `uv run --project ../.. --no-sync python tools/build_webui.py` 生成同目录上层 `index.html`；保持产物与源码一致。插件页面不需要构建宿主 dashboard。
- 大功能或广泛重构进行桌面/窄屏预览；细节小修不新建重复测试或重复 build。独立预览服务固定 7999 端口，测试模拟桥接不得进入生产页面。
- 遵循宿主 iframe 隔离权限，只提供原图预览，不通过修改宿主 sandbox 开启下载。用户已要求保持宿主不变。

## 插件联动

- 仅使用 SDK `@API(public=True)` 与当前 Host 的 `ctx.api.call`。不增加令牌、HTTP 监听、跨实例调用或联动配置项。
- 公开 API 只覆盖模型能力、任务提交/查询/取消、图片读取、风格预设管理。平台密钥、通用配置写入和日志查询不公开给其他插件。
- 所有入口复用同一绘图、审核、模型能力与存储服务。图片参数不接受任意文件路径；分页、并发、文件归属、源图大小及原图读取分块必须校验。
- API 契约变更同步 `docs/integration.md`；界面和数据行为同步 README；用户可见功能写 `changelog.md`，不写 changelog.dev。版本号仅在明确发布需求时修改。
- 验证使用临时配置和数据目录、模拟平台，不调用真实收费服务或向真实聊天发送消息。不得把用户 config.toml、platforms.json、迁移备份、运行日志和测试截图提交进 Git。

## 实例、重试和资源边界

- 所有平台类型允许多个命名实例，名称全局不重复；InstanceProviderRouter 为实例创建独立路由及适配器缓存，绝不能按平台类型覆盖其他实例。模型以实例名 / 模型名标识；短名多匹配时拒绝。
- 备选模型使用有序列表，默认重试次数为 0；仅 ProviderError 明确允许时重试/切换，不根据普通异常字符串猜测。审核拒绝终止为 rejected；结果解析/下载失败与远端受理状态不确定不得重新生成。旧 fallback_model 自动迁入列表，不新增重复的可见配置入口。
- 默认模型、默认风格使用实际已启用对象的下拉框。平台和工作台分类支持恢复参数默认，但只在保存时持久化，保留已有密钥。
- 页面切换不得整块淡入或位移造成闪烁；只保留侧栏选中背景、模式滑块的移动，并遵循减少动态效果。PC 任务筛选保持一行，移动端适当换行，导航入口全部可见。
- 图片、日志、上传容量放在宿主管理的 plugin 配置节，默认分别为 300 MB、10 MB、256 MB，工作台不展示；减少上限立即在线程清理。生成原图及 WebP 预览写入 ctx.paths.runtime_dir/results，旧 data_dir/results 兼容读取且共用配额。inputs/uploads 另限制 24 小时、100 文件；results 另限制 30 天、500 任务；日志总配额包含当前文件及 3 个备份。不能把缓存容量不足当作上游生成失败或触发重绘，不删除用户工作流、持久配置或迁移备份。
- 页面品牌使用 assets/icon.png，通过构建脚本内嵌，避免 iframe 相对资源地址与联网权限问题。依赖维护 requirements.txt 与 manifest，不创建 pyproject.toml。
- 日志查询从文件尾部有界读取，游标一致时返回 unchanged；滚动位置不因自动刷新跳走。轮转和读取共享文件锁。
- WebUI 旧页面可能带回 plugin/proxy 字段，保存时只提取 general/style，既不修改宿主字段，也不因旧字段阻止绘图设置保存。必须保留此回归验证。
- 提供商结果图片统一走 infrastructure/media/downloads.py，逐跳验证 HTTP(S)、地址范围及 DNS，并固定实际连接 IP；仅管理员配置的同源服务地址可访问内网。不允许恢复任意 session.get(url) 或自动跟随跳转。
- 任意结构的提供商诊断在交给宿主 logger 前脱敏；运行期 SecretRedactor 保留所有实例和已轮换密钥，任务消息在持久化前处理，不能只在公开查询时修补。
- 上传校验、容量清理和原子接管由 ArtifactRetention.claim_input 在同一个线程锁中执行；所有定时清理复用此锁。迁移冲突检查必须先于任何配置写入、备份清理或移除旧 TOML 节。
- 活动任务刷新不得替换正在编辑的筛选表单；搜索草稿与已提交筛选分开。hash 历史、未保存确认、原图分块读取取消均保持页面状态一致。

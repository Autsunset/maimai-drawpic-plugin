<div align="center">

<img src="assets/icon.png" alt="麦麦绘图插件图标" width="128" height="128">

# 🎨 麦麦绘图

![Plugin Version](https://img.shields.io/badge/Plugin-1.12.6-informational.svg)
![MaiBot](https://img.shields.io/badge/MaiBot-%3E%3D1.2.0-blue.svg)
![MaiBot Plugin SDK](https://img.shields.io/badge/Plugin%20SDK-%3E%3D2.7.1-blueviolet.svg)
![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)

为 MaiBot 提供图片生成、图片编辑与多模型管理能力。

[问题反馈](https://github.com/WhiteCloudOL/maimai-drawpic-plugin/issues) · [插件仓库](https://github.com/WhiteCloudOL/maimai-drawpic-plugin)

</div>

## 功能

- 支持文生图，以及编辑附带或引用的真实图片。
- 支持 OpenAI、Google Gemini、智谱、阿里百炼、火山引擎、硅基流动、NovelAI 和 ComfyUI。
- 支持全局默认模型、会话模型、失败时使用的备选模型，以及多个 OpenAI 兼容服务实例。
- 支持全平台风格模板；NovelAI 另有 Anime、Furry、Background 模式与会话画师标签。
- 所有绘图在独立后台任务中执行，多人可同时使用，并可查询自己的任务状态。
- 支持提示词与生成图片审核、群聊和私聊独立额度、管理员权限及失败原因通知。
- 支持 HTTP/HTTPS 代理与系统代理；WebUI 配置支持简体中文、英语、日语和韩语。

## 图片平台

| 平台 | 文生图 | 图生图 | 说明 |
| --- | --- | --- | --- |
| OpenAI 及兼容接口 | ✅ | ✅ | 支持 Images API、New API Chat Completion 绘图和多实例模型映射；RinkoAI NAI 暂不支持图生图 |
| Google Gemini | ✅ | ✅ | 支持 Gemini 图片模型，可设置宽高比与分辨率档位 |
| 智谱 | ✅ | ❌ | 支持 GLM-Image 与 CogView 图片模型，适合中文提示词 |
| 阿里百炼 | ✅ | ✅ | 支持 Qwen Image、Z-Image、可灵图像与 Vidu 图像模型，任务类型以具体模型为准 |
| 火山引擎 | ✅ | ✅ | 支持 Seedream 5.0 flash/pro/lite、4.5、4.0 与旧版图片模型，统一使用一个模型列表 |
| 硅基流动 | ✅ | ✅ | 支持平台开放的图片模型，包括 Kolors、Qwen Image 与 Qwen Image Edit |
| NovelAI / NovelAPI | ✅ | ✅ | 支持 V3、V4、V4.5、V5 与兼容网关，可设置模式、画师及正反向提示词 |
| ComfyUI | ✅ | ✅ | 使用本地或局域网 ComfyUI 的 API 格式工作流，图生图需要单独配置工作流 |

表中的支持情况表示插件具备对应能力，不代表该平台的每个模型都支持两种任务。模型必须已在账号或服务中开通；插件只提供图片功能，不支持视频生成。

## 安装

运行要求：MaiBot `>=1.2.0`、MaiBot Plugin SDK `>=2.7.1`。低于此版本时，请先升级 MaiBot 和 Plugin SDK。

### 插件市场

在 MaiBot WebUI 的插件市场中搜索“麦麦绘图”并安装。

### maibot CLI

```bash
maibot plugin install WhiteCloudOL/maimai-drawpic-plugin
```

### 手动安装

```bash
cd plugins
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin.git maimai-drawpic
```

安装后重启 MaiBot，在 WebUI 的插件配置页填写密钥与模型。

## 快速配置

1. 找到准备使用的平台，开启该平台，填写 API Key 和账号可用的图片模型；不使用的平台可以关闭。
2. 在“通用配置”中把“默认首选模型”设为该平台模型列表中的一个名称。
3. 按需配置备选模型、超时时间和管理员 ID，保存配置。
4. 在聊天中发送 `/绘图 模型` 检查模型列表，再用文生图命令开始绘图。

下面是使用 OpenAI 的最小示例：

```toml
[general]
default_model = "gpt-image-2"
fallback_model = ""
request_timeout_seconds = 150
failure_reason_enabled = true

[openai]
enabled = true
base_url = "https://api.openai.com/v1"
api_key = "你的 API Key"
models = ["gpt-image-2"]
default_openai_compatibility_mode = "auto"
```

```text
/绘图 文生图 一只坐在窗边的橘猫，温暖的午后阳光
```

推荐直接在 WebUI 中修改配置。本文的 TOML 示例也可用于插件 `config.toml` 的相应配置节：请替换密钥、地址和模型，合并到已有配置中，不要重复添加同名配置节。切换默认平台时，也要同步修改 `general.default_model`。

### 通用配置

以下选项位于 `[general]`：

| 配置项 | 作用与填写方式 |
| --- | --- |
| `default_model` | 未设置会话模型时使用的首选模型，必须在已启用平台的模型列表中 |
| `fallback_model` | 首选模型失败时使用的备选模型，留空关闭；也必须已配置并支持当前任务 |
| `request_timeout_seconds` | 单次图片请求超时，单位秒，通常可设为 120～300 |
| `command_reply_mode` | 指令回复形式，可选 `图片` 或 `文本` |
| `failure_reason_enabled` | 开启后直接通知简要失败原因；关闭后不主动发送失败消息 |
| `permission_enabled` | 开启后，模型、兼容模式、NAI 模式/画师与额度管理指令仅管理员可用 |
| `admin_user_ids` | 管理员用户 ID 列表；OneBot 填 QQ 号，QQ 官方适配器填用户 OpenID |
| `image_edit_unsupported_models` | 不支持图生图的模型名单，按模型显示名称填写 |
| `text_to_image_unsupported_models` | 不支持文生图的模型名单，按模型显示名称填写 |
| `prompt_review_enabled` | 生成前审核提示词，使用 MaiBot 的 replyer 模型 |
| `image_review_enabled` | 发送前审核生成图片，使用 MaiBot 的 vlm 模型 |

`/绘图 模型 <模型名>` 修改当前会话的首选模型，不会改动其他会话。没有会话设置时跟随 `default_model`；风格绘图同样沿用当前会话模型。

## 平台配置

### OpenAI 及兼容接口

必填项为 `base_url`、`api_key` 和 `models`。BaseURL 填完整 API 根地址，例如 `https://api.openai.com/v1`；兼容服务按其要求保留 `/v1`、`/api/v3` 等版本路径，不要填写某个具体绘图接口的地址。

```toml
[openai]
enabled = true
base_url = "https://api.openai.com/v1"
api_key = "你的 OpenAI API Key"
models = ["gpt-image-2"]
default_openai_compatibility_mode = "auto"
default_size = "1024x1024"
quality = ""
output_format = ""
```

`quality`、`output_format`、`background`、`moderation` 等均为可选项。不确定兼容服务是否支持时先留空；使用透明背景时选择 PNG 或 WebP，不要选择 JPEG。不同模型可以通过 `model_size_overrides` 分别设置尺寸。

#### 如何选择兼容模式

| 模式 | 适用服务 | 使用说明 |
| --- | --- | --- |
| `auto` | 大多数 OpenAI 兼容服务、New API | 根据服务提供的模型信息和模型系列选择绘图方式，推荐先使用此模式 |
| `images_api` | OpenAI 官方及提供标准图片接口的服务 | 使用标准图片生成/编辑能力，服务必须支持相应任务 |
| `chat_completions` | New API 等支持聊天绘图的服务 | 用于通过聊天接口输出图片的模型，例如网关上的 Gemini 图片模型 |
| `rinkoai` | `api.rinko.ai` 的 NAI 系列 | 用于 RinkoAI NAI 文生图；不用于独立 NovelAI 平台 |

可以在配置中设置默认模式，也可以通过 `/绘图 兼容模式 <模式>` 为当前会话切换。地址、密钥或模型权限错误不能靠切换兼容模式解决。

#### New API

在 New API 控制台启用图片模型与对应渠道后，将 New API 的 API 根地址和令牌填入插件：

```toml
[openai]
enabled = true
base_url = "https://你的-newapi-地址/v1"
api_key = "你的 New API 令牌"
models = ["gpt-image-2", "gemini-3.1-flash-image"]
default_openai_compatibility_mode = "auto"
```

模型名称以该 New API 实例实际开放的名称为准。若服务明确要求聊天绘图，可将默认模式设为 `chat_completions`。普通聊天模型不一定能生成图片；图生图还要求模型和渠道都支持图片编辑。

聊天绘图不会自动套用标准图片接口的尺寸、质量和输出格式设置。需要这些选项时，请按所用服务的说明填写“额外参数”。

#### RinkoAI 的 NAI 系列

```toml
[openai]
enabled = true
base_url = "https://api.rinko.ai/v1"
api_key = "你的 RinkoAI 密钥"
models = ["nai-diffusion-5-full"]
default_openai_compatibility_mode = "auto"
```

`auto` 可以识别此服务的 NAI 系列，也可以手动选择 `rinkoai`。该兼容模式目前仅支持 NAI 文生图，不支持 NAI 图生图；如需 NAI 图生图、数据集模式或会话画师设置，请使用下方独立 NovelAI 平台。

RinkoAI 的其他图片模型按普通兼容服务处理。尺寸、质量等是否可设置，以该服务实际支持的功能为准。

#### 多个兼容服务与同名模型

“额外 OpenAI 兼容实例”可以同时接入多个服务，每个实例单独填写名称、地址、密钥、模型和兼容模式。关闭主 `openai.enabled` 不会关闭额外实例。

```toml
[openai]
enabled = false

[[openai.instances]]
enabled = true
name = "New API"
base_url = "https://你的-newapi-地址/v1"
api_key = "你的 New API 令牌"
models = "newapi-gpt=gpt-image-2, newapi-gemini=gemini-3.1-flash-image"
default_openai_compatibility_mode = "auto"

[[openai.instances]]
enabled = true
name = "备用服务"
base_url = "https://api.example.com/v1"
api_key = "你的备用服务密钥"
models = "relay-gpt=gpt-image-2"
default_openai_compatibility_mode = "images_api"
```

主配置的 `models` 是列表；额外实例的 `models` 是文本，多个模型用逗号或分号分隔。`显示名=上游模型名` 用来区分同名模型，例如 `newapi-gpt` 和 `relay-gpt` 都使用上游的 `gpt-image-2`，但分别走不同服务。

在默认模型、备选模型和指令中使用显示名：

```text
/绘图 模型 newapi-gpt
/绘图 文生图 夕阳下的城市街道
```

### Google Gemini

使用 Google Gemini 原生图片服务时，启用 `google` 并填写 Gemini API Key；通过 New API 等 OpenAI 兼容网关使用 Gemini 时，配置在 `openai`，不要混用两种地址和密钥。

```toml
[google]
enabled = true
base_url = "https://generativelanguage.googleapis.com"
api_key = "你的 Gemini API Key"
models = ["gemini-3.1-flash-image", "gemini-3-pro-image"]
aspect_ratio = "16:9"
image_size = "2K"
negative_prompt = ""
```

- `aspect_ratio` 可设置 `1:1`、`3:4`、`4:3`、`9:16`、`16:9` 等；留空不强制比例。
- `image_size` 可设置 `1K`、`2K`、`4K`，Gemini 3.1 Flash 还支持 `512`；`K` 必须大写。Gemini 2.5 图片模型需留空。
- 反向提示词会并入普通提示词，不会被丢弃。
- 当前 Google 配置使用 Gemini 图片模型，不再支持已下线的 Gemini API Imagen 模型。

模型名与可用分辨率以账号实际开放的能力为准，兼容网关也应使用其提供的 Gemini 服务地址。

### 智谱

智谱当前仅支持文生图。填写 API Key 和已开通的 GLM-Image 或 CogView 模型：

```toml
[zhipu]
enabled = true
api_key = "你的智谱 API Key"
models = ["glm-image"]
quality = "hd"
size = "1280x1280"
watermark_enabled = true
```

`quality`、`size` 均可留空，使用模型默认设置；GLM-Image 的质量使用 `hd`。不要用智谱模型执行图生图，也不要把百炼的 `z-image-turbo` 填到智谱模型列表。

### 阿里百炼

必填项为 DashScope `base_url`、同地域/工作空间的 API Key 和 `models`。BaseURL 需包含 `/api/v1`，不要使用 `compatible-mode` 地址。使用工作空间专属域名时，复制该工作空间的 DashScope 地址。

```toml
[aliyun]
enabled = true
base_url = "https://dashscope.aliyuncs.com/api/v1"
api_key = "你的百炼 API Key"
models = [
  "qwen-image-3.0-pro",
  "qwen-image-3.0",
  "qwen-image-2.0-pro",
  "qwen-image-2.0",
  "z-image-turbo",
  "kling/kling-v3-image-generation",
  "kling/kling-v3-omni-image-generation",
  "vidu/vidu-image_reference2image",
  "vidu/vidu-image-pro_reference2image",
  "vidu/vidu-image-lite_reference2image",
  "vidu/viduq3-fast_reference2image",
]
default_size = "2048*2048"
image_input_mode = "auto"
```

默认只保留常用模型，旧模型或日期快照可按需手动加入；升级不会替换已有用户的模型列表。

| 模型系列 | 文生图 | 图生图 | 使用提示 |
| --- | --- | --- | --- |
| Qwen Image 3.0 / 2.0 / 2.1 | ✅ | ✅ | 2.1 系列可手动添加；尺寸按模型支持范围填写 |
| 早期 Qwen Image / Max / Plus | ✅ | ❌ | 使用该系列生成新图片 |
| Qwen Image Edit | ❌ | ✅ | 必须提供源图 |
| Z-Image | ✅ | ❌ | 提示词扩写可单独开启，可能产生额外费用 |
| 可灵图像 V3 / Omni | ✅ | ✅ | 可配置宽高比、分辨率和独立图片/连续组图 |
| Vidu 图像 | ✅ | ✅ | 图生图需要平台可访问的原始图片 URL |

图生图建议保持 `image_input_mode = "auto"`。千问可直接使用聊天图片；可灵和 Vidu 需要适配器提供可访问的原始图片 URL，只有本地图片或 Base64 时不能使用这两类模型编辑，可换用千问。

常用可选项包括 `negative_prompt`、`prompt_extend`、`seed` 和 `watermark`。模型不支持独立反向提示词时，会将反向内容合并到普通提示词。可灵可设置 `kling_aspect_ratio`、`kling_resolution`、`kling_result_type` 和 `kling_series_amount`；不同模型的专属选项在 WebUI 中分别配置。

本插件不接入百炼视频、万象、创意工具或图像翻译功能。

### 火山引擎方舟

使用 Seedream 图片模型，填写与账号/套餐对应的 BaseURL 和 API Key。普通方舟、Token 额度包和 Agent Plan 共用同一组配置，不需要分别设置两套密钥。

```toml
[volcengine]
enabled = true
api_key = "你的方舟 API Key"
base_url = "https://ark.cn-beijing.volces.com/api/v3"
models = [
  "doubao-seedream-5-0-flash-260915",
  "doubao-seedream-5-0-pro-260628",
  "doubao-seedream-5-0-260128",
]
default_size = "2K"
output_format = "png"
watermark = true
```

| 使用方式 | BaseURL | 密钥 |
| --- | --- | --- |
| 普通按量调用 / Token 额度包 | `https://ark.cn-beijing.volces.com/api/v3` | 对应普通方舟 API Key |
| Agent Plan | `https://ark.cn-beijing.volces.com/api/plan/v3` | 对应套餐的 API Key |
| 兼容网关 | 网关提供的图片服务根地址 | 网关密钥 |

密钥和地址必须配套，套餐是否包含目标图片模型以控制台权益为准。使用方舟原生 Seedream 图生图时，请配置在火山引擎平台。

- `models` 统一填写 Model ID 或 Endpoint ID；没有单独的文生图/图生图模型列表。
- 旧模型名称带 `t2i` 标记时仅支持文生图，带 `i2i` 标记时仅支持图生图；也可通过通用配置的两份模型名单手动限制任务类型。
- 尺寸可用分辨率档位或 `宽x高`；5.0 pro/flash 通常使用 `1K`、`1.5K`、`2K`，其他模型按其支持范围设置。
- 5.0 lite、4.5、4.0 可开启 `sequential_image_generation = "auto"` 生成组图，并用 `max_images` 限制数量；5.0 pro/flash 不支持普通组图。
- 5.0 pro/flash 图生图可选透明背景或图层拆分。透明背景需一张带透明通道的源图并选择 PNG；图层拆分也只接受一张源图。
- Seedance 属于视频模型，不在支持范围内。

通常只需配置密钥、地址、模型和尺寸。提示词优化、联网搜索等选项可按需在 WebUI 中开启，不需要复制额外接口参数。

### 硅基流动

填写 API Key 和模型广场中可用的图片模型。下面示例同时配置 Kolors 与 Qwen Image：

```toml
[siliconflow]
enabled = true
api_key = "你的硅基流动 API Key"
models = ["Kwai-Kolors/Kolors", "Qwen/Qwen-Image", "Qwen/Qwen-Image-Edit-2509"]
image_size = "1024x1024"
num_inference_steps = 20
guidance_scale = 7.5
cfg = 4.0
negative_prompt = ""
```

`guidance_scale` 用于 Kolors，`cfg` 用于 Qwen Image。Qwen Image Edit 需要源图，输出尺寸跟随模型，不使用 `image_size`；`Qwen/Qwen-Image-Edit-2509` 最多接受三张源图，其他已接入单图接口不要提供多张。

每次请求生成一张图片；不要再设置已停用的 `batch_size`。需要多张图片时，分别创建绘图任务。

### NovelAI / NovelAPI

官方服务使用 `https://image.novelai.net` 与 NovelAI Bearer Token；兼容网关按其要求填写根地址和密钥。

```toml
[novelai]
enabled = true
base_url = "https://image.novelai.net"
api_key = "你的 NovelAI Token"
models = ["nai-diffusion-5-full", "nai-diffusion-5-curated"]
default_mode = "anime"
default_artist_tags = ""
positive_prompt = ""
negative_prompt = "low quality, blurry, bad anatomy"
width = 832
height = 1216
sampler = "k_euler_ancestral"
steps = 28
scale = 5.0
seed = -1
quality_toggle = true
img2img_strength = 0.7
img2img_noise = 0.0
rewrite_prompt_to_english = true
```

“官方模型列表”可以选择 V5、V4.5、V4 和 V3 的 Full/Curated/Furry 模型；网关自定义名称填入 `custom_models`，例如 `custom_models = ["你的网关模型名"]`。

| 常用选项 | 使用说明 |
| --- | --- |
| `default_mode` | `anime` 为普通模式；`furry` 为兽人模式；`background` 为背景模式 |
| `default_artist_tags` | 默认画师标签，填写原始标签，如 `artist:name`，多个标签用英文逗号分隔 |
| `positive_prompt` / `negative_prompt` | 平台默认正反向提示词，分别与本次用户正向/反向提示词合并 |
| `width` / `height` | 默认输出尺寸；可用 `model_size_overrides` 对不同模型分别设置 |
| `sampler` / `steps` / `scale` | 采样器、步数和提示词引导强度，不确定时保留默认值 |
| `seed` | `-1` 随机，非负整数固定种子 |
| `quality_toggle` | 自动添加对应模型的质量增强标签 |
| `img2img_strength` | 重绘强度，越低越接近源图，越高允许的改动越大 |
| `img2img_noise` | 图生图噪声，通常可先保留 `0` |

NovelAI 图生图只接受一张源图。Background 模式需要 V4.5 或 V5；V3 的 Furry 模式需要同时启用 `nai-diffusion-furry-3`。普通绘图、风格绘图和 NAI 专属指令只要选中 NovelAI，都会使用同一套平台参数、会话模式、画师与正反向提示词设置。

### ComfyUI

先在 ComfyUI 中导出“API 格式”工作流，将文生图与图生图文件分别放到插件的 `data/workflows/t2i.json`、`data/workflows/i2i.json`。普通画布工作流不能直接使用。

下面节点 ID 仅为示例，需替换为自己 API 工作流里的 ID：

```toml
[comfyui]
enabled = true
base_url = "http://127.0.0.1:8188"
t2i_workflow_path = "data/workflows/t2i.json"
i2i_workflow_path = "data/workflows/i2i.json"

t2i_prompt_mode = "positive_negative"
t2i_positive_prompt_node_id = "6"
t2i_negative_prompt_node_id = "7"
t2i_negative_prompt = "low quality, blurry"

i2i_prompt_mode = "positive_negative"
i2i_positive_prompt_node_id = "6"
i2i_negative_prompt_node_id = "7"
i2i_negative_prompt = "low quality, blurry"
i2i_image_node_id = "10"

prompt_input_name = "text"
image_input_name = "image"
seed = -1
```

- 相对工作流路径以插件目录为基准，也可以填写绝对路径。Windows 路径建议使用 `D:/ComfyUI/workflow.json` 这样的写法。
- 正反向分开的工作流选 `positive_negative`，填写对应提示词节点 ID；只有一个提示词节点时选 `single_prompt`，填写 `t2i_prompt_node_id` 或 `i2i_prompt_node_id`。
- 图生图必须配置源图节点，当前只向一个源图节点写入一张图片。
- 标准提示词节点的输入名为 `text`，LoadImage 的输入名为 `image`；自定义节点按实际字段填写。
- 种子节点唯一时可自动识别；有多个种子节点时填写 `t2i_seed_node_id` / `i2i_seed_node_id`。
- 启用后用 `/绘图 模型 comfyui` 选择该平台。不使用图生图时可将 `i2i_workflow_path` 留空。
- ComfyUI 必须能被 MaiBot 所在机器访问；`127.0.0.1` 指的是 MaiBot 所在机器，不是浏览器所在机器。

## 绘图与风格使用

### 普通绘图

```text
/绘图 文生图 夜晚的海边灯塔，水彩插画
/绘图 文生图 一座雪山 --反向 模糊，水印，文字
```

图生图需要在发送图片时附上命令，或回复包含图片的消息：

```text
/绘图 图生图 保留人物和构图，把背景改成樱花树林
```

`文生图` 指令带图片时会提示改用图生图；`图生图` 找不到真实图片时不会改成文生图。源图只读取当前聊天，单条消息最多收集 8 张，单张上限为 25 MiB；模型的参考图上限更小时，以模型限制为准。

也可以直接在聊天中让麦麦画图或改图，由模型调用插件工具。绘图开始后在后台执行，不必等待完成才能继续聊天；用 `/绘图 状态` 查询自己的最近任务。

### 全平台风格模板

“绘图风格配置”位于通用配置之后。风格是提示词模板，适用于所有平台，**与 NovelAI 的数据集模式是两回事**，不会替你切换模型或 NAI 模式。

```toml
[style]
default_style = "水彩"

[[style.presets]]
enabled = true
name = "水彩"
description = "柔和的透明水彩质感，适合风景和插画"
positive_prompt_template = "watercolor, soft colors, {prompt}"
negative_prompt_template = "3d render, oil painting, {negative_prompt}"

[[style.presets]]
enabled = true
name = "赛博朋克"
description = "高对比霓虹光，适合未来都市和人像"
positive_prompt_template = "cyberpunk, neon lights, cinematic lighting, {prompt}"
negative_prompt_template = "flat lighting, low contrast, {negative_prompt}"
```

`{prompt}` 和 `{negative_prompt}` 分别放入用户的正向、反向提示词；未填写占位符时会自动追加。支持独立反向字段的平台会分别使用两类提示词，其余平台合并到一个提示词中。

```text
/绘图 风格
/绘图 风格 水彩 一座被森林环绕的小木屋
/绘图 风格 默认 雨后的城市
```

附带或引用图片时自动进行图生图。`默认` 使用 `default_style`；默认风格留空时不套用模板。风格描述可以帮助模型理解每种风格的效果，模型会先通过风格列表工具了解名称与描述，再调用风格绘图工具。

### NAI 会话模式与画师

```text
/绘图 nai 模式 furry
/绘图 nai 画师 artist:example_name
/绘图 nai 文生图 一只在森林中散步的狐狸
/绘图 nai 图生图 保留角色，换成冬季服装
/绘图 nai 参数
```

`/绘图 nai 模式 跟随` 和 `/绘图 nai 画师 跟随` 恢复插件默认设置。只改变本次模式时，可以用 `/绘图 nai furry <提示词>`，`anime`、`background` 同理。

会话画师标签替代默认画师标签，用户的本次提示词仍会与默认正向词合并。不需要默认画师时，在配置中将 `default_artist_tags` 留空。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/绘图` | 查看帮助 |
| `/绘图 状态` | 查看当前模型、额度与自己的最近任务 |
| `/绘图 模型` | 查看可用模型 |
| `/绘图 模型 <模型名>` | 设置当前会话模型 |
| `/绘图 兼容模式` | 查看当前 OpenAI 兼容模式 |
| `/绘图 兼容模式 <模式>` | 设置 `auto`、`images_api`、`chat_completions` 或 `rinkoai` |
| `/绘图 文生图 <提示词> [--反向 <提示词>]` | 创建文生图任务 |
| `/绘图 图生图 <提示词> [--反向 <提示词>]` | 编辑附带或引用的图片 |
| `/绘图 风格` | 查看可用风格 |
| `/绘图 风格 <风格名> <提示词> [--反向 <提示词>]` | 使用全平台模板绘图，带源图时自动图生图 |
| `/绘图 nai` | 查看 NAI 设置与用法 |
| `/绘图 nai 模式 <anime/furry/background/跟随>` | 设置会话 NAI 模式 |
| `/绘图 nai 画师 <画师标签/跟随>` | 设置会话画师标签或恢复默认设置 |
| `/绘图 nai 模型 <模型名>` | 设置会话 NAI 模型 |
| `/绘图 nai 参数` | 查看 NAI 绘图参数 |
| `/绘图 nai 文生图 <提示词> [--反向 <提示词>]` | 使用 NAI 文生图 |
| `/绘图 nai 图生图 <提示词> [--反向 <提示词>]` | 使用 NAI 图生图 |
| `/绘图 nai furry <提示词>` | 本次使用 Furry 模式，Anime、Background 同理 |
| `/绘图 设置 群聊/用户 <ID> <次数>` | 管理员设置额度 |
| `/绘图 增加 群聊/用户 <ID> <次数>` | 管理员增加额度 |
| `/绘图 减少 群聊/用户 <ID> <次数>` | 管理员减少额度 |

英文入口为 `/drawpic`，常用子命令支持 `status`、`model`、`compatible-mode`、`draw`、`edit` 和 `times`。

模型可使用的绘图工具包括 `draw`（文生图）、`edit_image`（图生图）、`draw_styles`（查看风格）、`styled_draw`（风格绘图）和 `draw_status`（查询任务）。

## 权限、额度与审核

```toml
[general]
permission_enabled = true
admin_user_ids = ["你的管理员用户ID"]

group_quota_enabled = true
group_quota_period = "daily"
group_default_quota = 5

private_quota_enabled = true
private_quota_period = "daily"
private_default_quota = 5

prompt_review_enabled = false
image_review_enabled = false
```

群聊和私聊额度独立，周期支持 `daily`（每日）、`weekly`（每周）、`monthly`（每月）、`once`（一次性，不自动重置）。管理员不受额度限制，并可通过指令调整额度。任务失败、超时、取消或审核拒绝后，会退回预留的次数。

OneBot 使用 QQ 号/群号；QQ 官方适配器使用用户 OpenID/群 OpenID。更改权限配置前，请先确认自己的管理员 ID。

提示词审核使用 replyer，图片审核使用 vlm；开启前确认 MaiBot 已配置对应模型。审核提示词可在 WebUI 的通用配置中分别修改。

### 失败通知

开启 `failure_reason_enabled` 后，工具和指令的绘图失败都会由插件直接发送简要状态、任务 ID 与截断、脱敏后的原因，不通过 LLM 生成错误文案。

关闭后不主动发送失败通知，只保留日志、任务状态和工具结果；可使用 `/绘图 状态` 查询。此开关不关闭指令帮助、缺少提示词等输入检查提示。

## 代理

```toml
[proxy]
enabled = true
use_system_proxy = false
scheme = "http"
host = "127.0.0.1"
port = 7890
username = ""
password = ""
bypass_china_providers = true
```

`use_system_proxy = true` 时读取 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`，无需填写手动代理。`bypass_china_providers = true` 时，阿里百炼、火山引擎、硅基流动直连，其他平台按全局代理设置请求。

## 常见问题

- **没有可用模型**：检查平台是否启用、API Key 是否填写，以及默认模型是否在该平台的模型列表中。
- **兼容服务只能画图、不能改图**：确认服务和模型确实支持图片编辑；RinkoAI NAI 当前仅支持文生图，智谱也不支持图生图。
- **找不到源图**：发送图片时附上图生图命令，或回复当前聊天中包含图片的消息；不要把图片描述当成真实图片。
- **百炼可灵/Vidu 提示缺少原图 URL**：这两类模型需要可访问的原始图片链接，可更换能提供原图 URL 的适配器或使用千问。
- **提示参考图片过多**：减少图片数量，或切换到支持多张参考图的模型；NAI、ComfyUI 的当前图生图流程只接收一张。
- **绘图超时**：适当增加 `request_timeout_seconds`，并检查图片服务、代理和网络；慢任务可通过状态指令查询。
- **权限不足**：将当前用户 ID 加入 `admin_user_ids`，或按需关闭权限限制。
- **ComfyUI 工作流无法使用**：确认是 API 格式，路径、提示词节点、图片节点和种子节点都正确。
- **中文提示词效果不佳**：使用 NovelAI、Stable Diffusion 类模型时可开启对应平台的 `rewrite_prompt_to_english`；该功能会使用 MaiBot 的 replyer 模型。

升级或备份时，请保留插件的 `config.toml` 和 `data/`。

## 问题反馈

通过 [GitHub Issues](https://github.com/WhiteCloudOL/maimai-drawpic-plugin/issues/new/choose) 反馈问题，附上插件与 MaiBot 版本、平台与模型、复现步骤和错误日志。提交前请隐藏 API Key、Token 等敏感信息。

交流 QQ 群：637174573。

## License

[GNU Affero General Public License v3.0](LICENSE)

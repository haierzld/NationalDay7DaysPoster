# 出图指南

两种引擎：**API**（有 Key 时用，稳定可批量）与**本地浏览器**（复用豆包 / 千问 / 即梦的登录态，无需 Key）。

## 1. API 引擎

```powershell
python scripts/nd7.py gen --all --engine api --provider siliconflow --out-dir outputs
```

| provider | 默认模型 | 默认尺寸 | Key 环境变量 |
| --- | --- | --- | --- |
| `siliconflow` | `Kwai-Kolors/Kolors` | 1080x1920 | `SILICONFLOW_API_KEY` |
| `dashscope`（通义万相） | `wanx2.1-t2i-turbo` | 1080*1920 | `DASHSCOPE_API_KEY` |
| `openai`（兼容接口） | `gpt-image-1` | 1024x1536 | `OPENAI_API_KEY` |

- 也可以用 `--api-key`、`--model`、`--base-url` 显式指定；`--provider auto` 时按环境变量自动选择
- 通用变量：`IMAGE_API_KEY`、`IMAGE_BASE_URL`、`IMAGE_PROVIDER`
- 本技能不内置任何密钥；不要把 Key 写进仓库文件，用环境变量或 `--api-key` 传入

## 2. 浏览器引擎（复用登录态）

```powershell
pip install playwright                       # 只需一次，不需要下载浏览器
python scripts/nd7.py browsers               # 探测本机 Chrome / Edge
python scripts/nd7.py gen --day 1 --engine browser --platform doubao
python scripts/nd7.py gen --all --engine browser --platform qianwen --timeout 240
```

平台：`doubao`（豆包）、`qianwen`（通义千问 / 通义万相）、`jimeng`（即梦），用 `--platform` 指定。

工作方式：

1. 按 **Chrome → Edge** 顺序查找本机浏览器与其用户数据目录
2. 把用户数据**复制成登录态副本**放到临时目录（跳过缓存目录，7 秒左右；再次运行增量复用），再用 Playwright 持久化上下文加载副本 → **自带已登录账号**
   - 之所以不用原目录：Chrome 136+ 禁止在默认用户数据目录上开启远程调试（`DevTools remote debugging requires a non-default data directory`）
3. 自动关闭遮罩层、尝试进入「图像生成」模式，定位输入框后写入提示词并回车发送
4. 轮询页面，把新出现的大图下载到 `outputs/`；定位失败时把提示词复制到剪贴板（或存为 `outputs/_prompt_dayN.txt`），提示手动粘贴发送，脚本继续等待并自动下载

常用参数：

- `--platform doubao|qianwen|jimeng`：平台
- `--browser Chrome|Edge`：指定浏览器
- `--headless`：无头模式。登录态异常或平台风控时请去掉，用有头模式人工过一次验证
- `--live-profile`：直接使用真实用户数据目录（仅在浏览器未运行且远程调试未被拒时可用）
- `--prompt-prefix`：提交前加的引导语，默认“请严格按照以下提示词生成一张 9:16 竖版图片…”，传空串可关闭
- `--dry-run`：只打印将提交的文本，不启动浏览器
- `--timeout`：等待单张出图的秒数，默认 180

## 3. 故障排查

| 现象 | 处理 |
| --- | --- |
| `DevTools remote debugging requires a non-default data directory` | 默认已自动改用登录态副本；若手动用了 `--live-profile`，去掉该参数 |
| 副本里没有登录态 | 先在原浏览器登录豆包 / 千问 / 即梦，再重新运行（副本会自动更新） |
| 提示未登录 | 在打开的窗口中登录完成后按回车继续 |
| 点击被遮罩拦截 / 弹窗 | 脚本会自动移除 `dialog-overlay` 并改用 `fill()` 直接写入，一般无需人工干预 |
| 找不到输入框 | 脚本已把提示词放到剪贴板，手动粘贴发送即可，脚本会自动下载 |
| 下载到 0 字节 | 图片可能是 blob 链接，脚本会尝试用页面内 fetch 兜底；仍失败可手动右键保存 |
| 平台风控 / 需验证码 | 用有头模式，首次人工完成验证 |
| API 返回 401/403 | 检查 Key 与 provider 是否匹配、余额与额度 |
| 竖版比例不对 | 在提示词末尾补一句“严格 9:16 竖版构图”，或在支持尺寸参数的 provider 上确认 size |

## 4. 二维码与机构署名

AI 画二维码通常是扫不出来的乱码，所以流程是：**提示词预留留白 + 出图后叠加**。

```powershell
python scripts/nd7.py plan --subject 中国 --qr --org "某某集团" --out outputs/prompts.md
python scripts/nd7.py gen --all --engine api --out-dir outputs
python scripts/nd7.py overlay --image "outputs/day*.png" --qr "https://example.com" --org "某某集团" --date 2026.10.01
```

`overlay` 参数：`--position bottom-right|bottom-left|bottom-center`、`--scale`（二维码边长占画面宽度比例，默认 0.12）、`--slogan`、`--out`。

二维码库缺失时脚本会尝试安装 `segno`（纯 Python）；也可手动 `pip install qrcode` 或 `pip install segno`。

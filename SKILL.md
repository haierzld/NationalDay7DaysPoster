---
name: national-day-7days-poster
description: 国庆 7 天连更海报生成（10.1-10.7 每日一张 9:16 红金国风竖版海报）。用户输入“中国 / 中国福州 / 某某大学 / 某某集团 / 公司+二维码”等主体时使用；主体为国家时用内置重大工程与科技素材库，为城市、学校、企业时先联网检索公开素材再生成。栏目数 = 日期号，7 号为三角交错特殊版式，画框内禁止任何文字。
---

# 国庆 7 天连更海报生成器（NationalDay7DaysPoster）

把“主体 + 日期”转成一套可直接出图的 9:16 竖版红金国风国庆海报提示词，并支持出图与后期叠加。

- 年份：2026（中华人民共和国成立 77 周年）
- 主标题：默认 `辉煌七十七载·扬帆再出发`，可**按天**换（素材库 `title` 字段，如 10.1 用 `盛世华章·祖国万岁`）；副标题固定 `国庆祝福`
- 每日栏目数 = 日期号（1 号 1 栏 → 6 号 6 栏）；形状版式每天有多种可选（Day7 默认三角交错，还可用五角星 / 七竖条 / 北斗七星等，见 `config/frames.json`）
- 落款可按天配两行（如 10.1：`2026.10.01` + `庆祝中华人民共和国成立77周年`）
- 出图两条路：**模型生成**（`gen`，参考实景照片出图）与**实景照片直排**（`compose`，网图评分合格就直接排进画框，不再让模型参考生成）
- 作品示例见 `examples/`：`national/`（国家）· `shanghai/`（城市）· `cqu/`（高校）· `quanzhou/`（城市·世遗，模型版）· `quanzhou-photo/`（同主体，照片直排版）
- 输出统一归档到 `outputs/<主体>/`：`day1..7.png` + `prompts.md` 放在同一个目录；照片直排版在同目录的 `compose/` 子目录

## 一、输入参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `day_num` | 否 | 1-7；不填表示一次生成 7 天 |
| `subject` | 否 | 主体：`中国`（默认）/ `中国福州` 等城市 / `某某大学` / `某某集团` |
| `custom_title` | 否 | 覆盖主标题 |
| `custom_events` | 否 | 覆盖当日事件列表（长度应与 `day_num` 一致） |
| `qr` | 否 | 是否加二维码，默认 **不加** |
| `org` | 否 | 画面里的机构/公司署名，默认 **不加** |

## 二、执行流程

### 1. 解析主体（先跑脚本，不要凭感觉猜）

```powershell
python scripts/nd7.py subject "中国福州"
```

返回 `type`：`nation` / `city` / `school` / `company`，以及 `needs_research`、`topics`、`notes`。

### 2. nation：直接用内置素材库

`config/events_national.json` 已内置 28 个条目（1+2+…+7），题材为 2026 国内重大工程与科技事件（平陆运河、可复用火箭、天问二号、C919、深海一号、航母编队等）。无需检索，直接进入第 5 步。

### 3. city / school / company：先检索，再落地素材库

对非国家主体**必须**先联网检索，不得凭记忆编造：

- 按 `scripts/nd7.py subject` 输出的 7 大主题逐个检索，凑齐 28 个条目（Day1 需 1 条，Day7 需 7 条）
- 名称、地点、建成/启用时间至少**两处独立来源**交叉核对；无法核实的条目换同类备选
- 只使用官网、官方公众号、年报、权威媒体报道的公开信息
- 结果写入 `config/subjects/<slug>.json`（格式见 `reference/subject-playbook.md`），然后用 `--subject <主体名>` 或 `--events-file` 调用

学校主题优先用：校门与标志性建筑、校园风景、课堂、实验室、体育社团、校史荣誉（不出现人物）、国际交流。也可以直接用校园风景 7 幅。

#### 3.1 实景优先：先抓真实照片，再按照片出图

地标类题材（古建筑、景区、校园、厂区）**不得纯凭提示词臆造**。流程：

1. 采集真实照片（`refs` 子命令，公开网络检索，结果落在 `assets/<主体>/<slug>/`，来源记入 `assets/<主体>/_refs.json`）
2. 出图时把照片上传给平台作参考（`--ref` / `--ref-auto`），提示词追加「严格参照照片的建筑造型、屋顶形式、色调与视角，不引入照片之外的地标」
3. 复检：若成图与照片的地标轮廓明显不符，更换参考图重出

```powershell
# 单个题材
python scripts/nd7.py refs --query "安溪清水岩 帝字形 主殿 蓬莱山" --slug qingshuiyan --limit 8
# 批量（config/refs_<主体>.json 里列出 7 天题材的检索词）
python scripts/nd7.py refs --config config/refs_安溪.json
# 手动补一张指定图片
python scripts/nd7.py refs --url "https://.../wenmiao.jpg" --slug wenmiao --note "来源：安溪县人民政府网"

# 出图时带上照片（图生图，耗时约 2-3 分钟/张，超时给到 300s）
python scripts/nd7.py gen --day 1 --subject 安溪 --engine browser --platform doubao `
  --ref "assets/安溪/wenmiao/01_xxx.jpg" --ref "assets/安溪/wenmiao/05_xxx.jpg" --timeout 300
# 或按当天题材自动匹配已采集照片
python scripts/nd7.py gen --day 2 --subject 安溪 --engine browser --platform doubao --ref-auto --timeout 300
```

检索词写法：`地点 + 标志性特征`（如「帝字形 主殿」「燕尾脊 大成殿」「寺庙群 绿道」），命中率远高于只写地名。
合规：只抓公开可检索的图片并记录来源；对外发布前需自行确认版权与肖像权，禁用无人机禁飞区与涉密场所照片。

#### 3.2 网图够好就直接用：评分选拔 + 照片直排

抓到照片后先打分（`scripts/score_refs.py` 可看体检报告：分数分布、最弱题材、实际会被选中的分数）：

- 评分维度：题材贴合（图片标题为主证，检索词只算参考）> 分辨率 > 构图 > 来源可信度；图库水印站与「效果图/素材/插画」类重罚
- 硬门槛：低于 **4.0** 分不进模型（宁可不给参考，也不把模型往错误地标上带）；采集时题材最高分低于 4.5 会自动换检索词重采一轮
- 某个栏目抓到**评分优秀（≥9 分）**的实景图时，可以不走模型，直接用 `compose` 把它排进画框：

```powershell
# 看某个主体每天有哪些形状版式可选
python scripts/nd7.py compose --list-layouts

# 7 天照片直排（≥9 分会在日志里标注“优秀·直接采用”，未达 --min-score 的栏目画金色留空框）
python scripts/nd7.py compose --subject 泉州 --all
python scripts/nd7.py compose --subject 泉州 --day 5 --layout five-star        # 五角星阵
python scripts/nd7.py compose --subject 泉州 --day 6 --layout six-petal         # 六瓣花
python scripts/nd7.py compose --subject 泉州 --day 7 --layout seven-dipper      # 北斗七星
python scripts/nd7.py compose --subject 泉州 --day 7 --layout seven-tri-quad --min-score 5
```

产物落在 `outputs/<主体>/compose/dayN.png`，与模型出的图分开放，方便对比挑用。

#### 3.3 形状版式库（`config/frames.json`）

每天 1-4 种有规律的形状版式，同一份定义**两种用法**：`slots` 给 `compose` 精确落位，`desc` 给模型出图时用文字描述。当前枚举：

| 天数 | 可用版式 |
| --- | --- |
| Day1 | 单框拱门 |
| Day2 | 双框并立 / 上下双层 |
| Day3 | 三框拱起 / 宝塔三角（一正两倒） |
| Day4 | 四联拱 / 四菱方阵 |
| Day5 | 五联扇形 / **五角星阵** / **五边形错列** |
| Day6 | 二三网格 / **六瓣花** / **六边形蜂巢环** |
| Day7 | 三角交错（上三倒下四正）/ **七竖条天际线** / **三倒三角 + 四菱形** / **北斗七星** |

模型出图也可以用这些形状：`python scripts/nd7.py gen --day 5 --subject 泉州 --layout five-star --engine browser --platform doubao`。

注意事项：
- 画布 1520×2720（比例 0.5588），圆/星/多边形类形状必须满足 `h ≈ 0.559 × w`，等边三角形 `h ≈ 0.484 × w`，否则会被纵向拉长
- 形状带旋转时（六花瓣）遮罩要画在更大的画布上再旋转，不能旋转后裁回原框，否则会被切掉
- 新增版式只需在 `frames.json` 里加一组 `slots` + `desc`，两条出图链路同时生效

### 4. 主动提醒可选项（每次首次使用只问一次）

默认**不加**二维码与机构署名。生成前必须提醒用户：

> 需要加二维码或机构/公司署名吗？（默认不加；二维码用后期叠加真实可扫描的图案，不会让 AI 画乱码方块）

用户确认后传 `--qr` 与 `--org`，脚本会在提示词里预留右下角留白，出图后用 `overlay` 叠加。

### 5. 生成提示词

```powershell
# 单日
python scripts/nd7.py prompt --day 7
# 7 天全量（默认写入 outputs/<主体>/prompts.md，与该主体的成品图同一个目录；--out 可改路径）
python scripts/nd7.py plan --subject 中国
# 自定义主体 + 二维码 + 署名
python scripts/nd7.py plan --subject 某某集团 --qr --org "某某集团"
```

### 6. 出图（二选一）

```powershell
# A. API
python scripts/nd7.py gen --day 1 --engine api --provider siliconflow
python scripts/nd7.py gen --all --engine api --provider dashscope --out-dir outputs

# B. 本地浏览器（复用豆包 / 千问 / 即梦登录态，先 Chrome 后 Edge）
python scripts/nd7.py gen --day 1 --engine browser --platform doubao
python scripts/nd7.py browsers   # 探测本地浏览器
python scripts/nd7.py gen --day 1 --engine browser --dry-run   # 只看将提交的文本
```

> **前置（最容易卡住的一步）**：运行前必须先用**本机 Chrome 或 Edge** 打开豆包（千问 / 即梦同理）**登录一次**，然后**完全退出该浏览器**。脚本用**登录态副本**运行（Chrome 136+ 禁止在默认用户数据目录开启远程调试），首次复制约数十秒、之后增量复用；若日志提示未登录，回到原浏览器登录一次再重跑。

浏览器引擎按 Chrome → Edge 查找本地浏览器，前提是原浏览器已登录豆包 / 千问 / 即梦。细节与故障排查见 `reference/generation-guide.md`。

### 7. 清除平台角标水印

豆包 / 即梦等平台会在成图右下角固定位置加「xx AI 生成」角标。浏览器引擎出图后**默认自动清除**（`--no-clean` 可关闭）：在四角外缘检测浅色小字连通块 → 生成掩码 → `cv2.inpaint` 用邻域背景重建。

```powershell
# 单独处理（支持通配符）；--detect 只看候选区域，--dump-dir 导出裁剪图肉眼确认
python scripts/nd7.py wm --image "outputs/day?_安溪.png" --detect
python scripts/nd7.py wm --image "outputs/day*_中国.png"            # 输出 *_clean.png
python scripts/nd7.py wm --image "outputs/day?.png" --inplace      # 就地覆盖
python scripts/nd7.py wm --image "outputs/day1.png" --force --default-box 0.80,0.962,0.20,0.036 --inplace
```

- 默认清理区域为内置经验值 `0.80,0.962,0.20,0.036`（右下角最底部一条，覆盖「豆包 AI 生成」整条 6 字；只清右半会留下「豆」字），并与自动检测结果合并
- 框给宽只会更保险：默认只把「比背景亮的像素」判为水印（`--block` 才整块 inpaint），不会糊掉红绸背景
- 角标位置随平台/版本可能变化：先 `--detect` 确认，再用 `--box x,y,w,h`（相对比例）精确清除

### 8. 后期叠加

```powershell
python scripts/nd7.py overlay --image "outputs/day*_中国.png" --qr "https://example.com" --org "某某集团" --date 2026.10.01
```

## 三、视觉与版式规格

- 全局基底：9:16 竖版，巨大飘扬五星红旗背景 + 金色星光粒子放射；顶部金色书法主标题与白色副标题；底部流动红绸波浪；暖金色光影、烟花祥云；8K 商业级精修、干净无水印
- 画框：竖弧形（拱形顶）金色浮雕细边框，框内写实摄影质感实景；day7 为金色细边三角形
- 版式：Day1 居中 1 大框；Day2-6 等宽并排，中间高两侧略低形成微拱（Day6 分左右两组各 3 个）；Day7 上排 3 个倒三角 + 下排 4 个正三角交错咬合，居中对称、边界清晰不重叠
- 以上为默认版式；5/6/7 栏还有五角星、五边形、六花瓣、蜂巢环、七竖条、倒三角+菱形、北斗七星等可选形状（同一套定义同时供模型出图与照片直排使用，见 `config/frames.json`）
- 落款：底部居中极小金色文字（10.01 用 `2026.10.01 庆祝中华人民共和国成立77周年`，其余用 `10.0X 祝福祖国`）

详细版式参数见 `reference/layout-spec.md`。

## 四、画框内文字禁令

正面提示词里只描述“画什么”，画框内部**不得**生成任何文字标签、图注、汉字、编号；物体表面不得乱生成文字。允许的画外文字只有：主标题、副标题、落款、用户确认后的机构署名。

## 五、合规红线

- 国旗庄重完整，不破损、不倒置、不做商业变形与恶搞
- 学校/企业主题：不出现可识别的真实人物肖像，不精确复刻校徽、商标与品牌 logo，不编造排名、人数、升学率、专利号、财务数据等未公开信息
- 照片直排（`compose`）同样守这条：素材库里标了 `"people": true` 的人物场景题材（非遗表演、市井人等）默认不采用实拍网图（可用 `--allow-people` 打开），能检测到的人脸做高斯模糊
- 不使用“第一”“最强”“唯一”等绝对化用语；不输出地图边界与国界线等敏感元素
- 素材事实以官方最新公告为准；交叉核验只降低错误率，不保证绝对准确

## 六、交付规范

- 默认交付：图片 + 简短说明（主体、日期、栏目数、是否加二维码/署名）
- 用户明确索要时才输出完整提示词
- 没有生图工具时如实说明无法出图，不谎称已生成；联网不可用时说明未核验，不用记忆编造事实
- 结尾附：

> 免责声明：海报内容与文字仅供艺术创作与庆祝宣传参考，不构成官方史料、统计口径或商业宣传依据。素材事实、肖像、商标与版权请在使用前自行复核并以官方最新公布为准。

# 香港主体开户材料信息提取工具

本地运行的香港主体（CI / BR / NNC1·NAR1）材料信息提取工具。上传三类 PDF，
自动提取企业信息、企业代表（董事）与 UBO（最终受益人，持股 ≥25%），前端
逐字段复核编辑后导出 JSON / CSV。详见 `PRD_HK_主体材料提取.md`（产品需求）。

## 目录结构

```
app/
  main.py                FastAPI 服务：静态页面 + POST /api/extract
  extraction/
    schema.py             字段对象（value/source/status/raw）
    normalize.py           日期归一化、地址推断国家等工具函数
    pdf_text.py             文字层提取（pdfplumber 逐词坐标重建版面）+ OCR fallback（pdf2image/pytesseract）
    ci.py / br.py / nnc1.py 各文件类型的正则/关键词锚定规则
    romanize.py              中文姓名转拼音兜底（普通话拼音 / 粤语拼音建议）
    merge.py                跨文件合并、默认值、派生字段、冲突检测
static/
  index.html               前端页面（基于 hk_extract_ui.html 原型改造，接入真实后端）
requirements.txt
```

## 环境依赖

- Python 3.10+
- 系统层：`tesseract-ocr`（含繁体中文语言包 `chi_tra`）、`poppler-utils`（供
  `pdf2image` 使用），仅扫描件走 OCR 时才需要。

Ubuntu/Debian 安装系统依赖：

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-tra poppler-utils
```

macOS（Homebrew）：

```bash
brew install tesseract tesseract-lang poppler
```

## 安装与运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开浏览器访问 `http://localhost:8000`，三栏上传 CI / BR / NNC1·NAR1 PDF，
点击「开始提取」。

## 说明与已知限制

- **提取规则为启发式实现**：CI/BR/NNC1/NAR1 的官方表格版式在不同年份、不同
  申请渠道下略有差异，`app/extraction/ci.py`、`br.py`、`nnc1.py` 中的正则
  基于公开表格的常见字段标签编写，尚未用真实样本校准（对应 PRD 第 10.5
  条待确认项）。建议用脱敏真实样本跑一遍，按需调整锚点正则。
- **证件字段（证件签发国/出生日期/完整证件号）** 在 NNC1/NAR1 中常缺失或被
  遮蔽，本期未提供独立的证件上传窗口（对应 PRD 第 10.1 条待确认项），因此
  这些字段命中率较低，需人工补录，前端会以「缺失待补」红色高亮。
- **企业代表字段范围**：本期不提取/展示职位、性别、国籍、居住国家（这些字
  段在 NNC1/NAR1 中经常缺失或需要额外证件比对，暂不纳入）。居住地址与证件
  信息均从 NNC1/NAR1 董事个人资料区块中提取。
- **PI-NNC1 董事详情页解析**：董事的中文姓名、英文姓氏/名字、证件号码（香
  港身份证为空/NIL/「無」时改取护照完整号码 + 签发国家/地区）、通常住址
  （Flat/Floor/Block、Building、Street、District/City/Province、Country 五
  个分栏按顺序拼接）均按此页实际版式的字段标签定位取值。取值前会用一份标
  签黑名单校验，避免捕获到空白栏位旁边的标签文字本身（如"Surname"
  "Building""PI-NNC1"页眉等）——命中黑名单一律按缺失处理，不会用标签文字
  填充。标签匹配限定在每行开头附近，避免匹配到页面上"请于本页申报首任董
  事的香港身分证或护照的完整号码及通常住址"这类说明性文字中间偶然出现的
  同名短语。半角/全角斜杠（"/" 与 "／"）、"身份"/"身分"两种写法均可识别，
  以兼容官方表格实际使用的全角标点与无「亻」字旁写法。此逻辑已用真实用户
  提供的 NNC1 原件（含空白 Flat/Building 分栏、拆行的英文说明标签等版式）
  校验过。
- **英文姓名拼音兜底**：若原件英文姓名（Surname / Other Names）留空但有中
  文姓名，会按该董事证件类型自动填充拼音建议：证件为中国大陆身份证/护照
  （签发国 China）时，用 `pypinyin` 转普通话拼音，标记为「推断值」；证件为
  香港身份证时，用 `pycantonese` 的粤拼再套用一份近似的"香港身份证英文拼
  法"映射表生成建议值，标记为「建议值·待确认」（不是「推断值」）——因为香
  港身份证英文姓名并无统一转换标准，只能作为待人工核对的建议，不可当作确
  认值使用。两种拼音都会在导出的 JSON/CSV 中带上明确的 source/status，方便
  区分。
- **UBO（最终受益人）计算方式**：不直接找现成的持股比例文字，而是分别定位
  NNC1 第 5 节「Share Capital and Initial Shareholdings」Total 行的股份总数
  （分母）与「創辦成員 / Founder Members」股东名单里各股东的认购股数
  （分子），相除算出百分比，仅保留 ≥25% 的股东列入 `ubos`。法人股东（公司）
  只登记公司名称与持股比例，不追溯其背后自然人。股东名单区块通常不重复
  证件/地址信息，若该股东同时也是董事，会自动从董事记录回填。无法定位股份
  总数时，相关股东仍会列出但持股比例标记「缺失待补」，不会静默丢弃潜在
  UBO。此逻辑同样是启发式实现，未经真实 NNC1/NAR1 样本校准。
- **文字层版面重建**：`pdf_text.py` 不使用 pdfplumber 默认的 `extract_text()`
  （其阅读顺序基于 PDF 内容流的字符绘制顺序，在 PI-NNC1 这类多栏表单上会把
  标签与填写值错位穿插），而是用 `page.extract_words()` 取得每个词的
  x0/x1/top 坐标，按 `top` 聚类成行、行内按 `x0` 从左到右排序，行间用换行、
  同行跨列之间用加宽空白拼接，使"标签 → 右侧/下方值"的空间对应关系保留到
  输出文本里。OCR 分支同理，用 `pytesseract.image_to_data`（`--psm 6`）取
  词级坐标做同样的重建（坐标按 OCR_DPI 换算像素->点）。
- **叠印文字层去重**：部分翻印/扫描后重新生成的 BR/CI PDF 会把同一段文字
  的文字层原样重复嵌入两次、坐标完全重合，导致 pdfplumber 交替读出两层字
  符，每个字符看起来都重复了一遍（如"FLAT"→"FFLLAATT"）。`pdf_text.py` 在
  逐词重建版面前，先用 pdfplumber 内置的 `page.dedupe_chars()` 按坐标（而
  非纯文本模式）合并同文字、同字体字号、位置相差在 1pt 以内的重复字符，只
  保留一份——本来就该有的双字母词（如"KOMM"）因为不在同一坐标上，不会被
  误伤。
- **OCR 依赖系统二进制**：若未安装 `tesseract-ocr` / `poppler`，扫描件文件
  会在结果中带上警告文案，字段按未识别处理，不会导致整个请求失败。
- 前端所有字段值可编辑；用户手动填写过的「缺失/遮蔽」字段会标记为「人工
  填写」徽章，一并写入导出的 JSON / CSV。

# 香港主体开户材料信息提取工具

本地运行的香港主体（CI / BR / NNC1·NAR1）材料信息提取工具。上传三类 PDF，
自动提取企业信息与企业代表（董事）信息，前端逐字段复核编辑后导出 JSON /
CSV。详见 `PRD_HK_主体材料提取.md`（产品需求）。

## 目录结构

```
app/
  main.py                FastAPI 服务：静态页面 + POST /api/extract
  extraction/
    schema.py             字段对象（value/source/status/raw）
    normalize.py           日期归一化、地址推断国家等工具函数
    pdf_text.py             文字层提取（pdfplumber）+ OCR fallback（pdf2image/pytesseract）
    ci.py / br.py / nnc1.py 各文件类型的正则/关键词锚定规则
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
- **OCR 依赖系统二进制**：若未安装 `tesseract-ocr` / `poppler`，扫描件文件
  会在结果中带上警告文案，字段按未识别处理，不会导致整个请求失败。
- 前端所有字段值可编辑；用户手动填写过的「缺失/遮蔽」字段会标记为「人工
  填写」徽章，一并写入导出的 JSON / CSV。

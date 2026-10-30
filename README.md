# 数据结构智练

面向大学《数据结构》课程的轻量 Web 刷题应用。Python + Streamlit + SQLite，支持题库解析、OpenAI Chat 兼容 API 和自行部署的 LoRA 模型三种辅导方式。

## 当前交付状态

- 60 道自编单选题，覆盖线性表、栈与队列、树与二叉树、图、查找、排序。
- 章节/难度/关键词筛选、作答状态导航、跳过已练题、标准答案判分。
- 提示与讲解按题目和模型缓存，支持带有限上下文的连续追问。
- 提交答案后保持当前题目；追问使用醒目的多行输入框，位于助手回复上方，答题后即可使用。
- 错题自动收录、连续复习、复习状态、章节统计、记录导出。
- 紧凑练习工作台、答后自动收起选项、助手独立滚动、手机尺寸适配，见 `docs/界面优化验收.md`。
- 144 条训练、48 条验证、48 条测试辅导样本，对应 36/12/12 道不同题目。
- LoRA / QLoRA 训练、真实结果评测、OpenAI Chat 兼容推理服务脚本。
- 本机网页及自动化功能测试已执行，记录见 `docs/验收记录.md`。
- **云端 API 与幕僚云公网部署已完成，GPU 微调尚未执行。** 入口为 <http://140.210.92.250:17078>，需要网站访问口令；手机流量能打开登录页已由用户确认。部署、二维码和验收证据见 `docs/幕僚云部署说明.md` 与 `docs/幕僚云部署验收.md`。
- 题库模式的文字为预设内容，页面不会把它标作模型生成。此前本机 API 验收见 `docs/API接入验收.md`。

## 在本机打开

Windows 双击 `启动应用.cmd`，然后访问 <http://127.0.0.1:8501>。

仓库不包含虚拟环境。一键入口会在需要时创建环境并安装依赖。Windows 建议 Python 3.11～3.13。

手动运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

首次无需 API 密钥，可使用题库解析。连接模型时，将 `.env.example` 复制为 `.env`，填写服务商提供的地址、模型名和密钥，展开侧栏“辅导设置”，点击“重新读取模型配置”，选择“云端 API”。配置齐全时，新会话默认选择云端模式；点击生成提示、讲解或发送追问时才调用模型。密钥保存在运行应用的机器上，不要提交到源码仓库。

## 工程结构

```text
app.py                       Web 页面和交互
ds_tutor/                    题库、判分、持久化、提示词、模型客户端
assets/style.css             页面样式
data/questions.json          60 道题库数据
data/training/               JSONL 数据集与划分清单
training/prepare_data.py     生成数据并按题族划分
training/train_lora.py       单 GPU LoRA / QLoRA 训练
training/evaluate.py         基础模型与适配器公平对比
training/serve.py            受密钥保护的模型推理服务
scripts/build_bank.py        题库原始定义
scripts/package_project.py   生成不含密钥和个人记录的源码包
tests/                      核心逻辑与 Streamlit 交互测试
docs/                       部署、微调、展示与验收资料
runtime/                    本机学习记录（忽略、不打包）
outputs/                    训练和评测真实产物（训练后才生成）
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

本机 `requirements-lock.txt` 保存实际安装版本，便于复现 Web 环境；跨平台优先使用 `requirements.txt`。GPU 环境独立使用 `training/requirements.txt`。

2026-10-30 本地 18 项测试通过；云服务器还使用独立测试数据库和模拟模型，验证了非首题提交、切页返回、连续错题复习与多行追问。最新修复验收见 `docs/答题与追问修复验收.md`。本轮没有额外发起收费模型请求。

## 接下来

1. 可直接访问幕僚云部署的 API 版网页，保持云实例运行，并保存自己的学习码。
2. 人工核对数据，上传源码包到单卡云 GPU，先运行 5 个优化步的试跑。
3. 正式训练并评测，下载适配器、训练日志和评测文件。
4. 根据 `docs/使用与部署说明.md` 接入微调模型，补拍真实模型截图。
5. 收到教师模板后，将真实实验结果整理到不少于 3000 字的正式报告中。

本项目已经提供可运行应用、云端 API 接入和公网部署。真实微调实验、系统性评测及按教师模板编排的正式报告仍待完成。

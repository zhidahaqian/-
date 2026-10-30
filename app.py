import hmac
import json
import os
import re
import time
import uuid

import pandas as pd
import streamlit as st

from ds_tutor.bank import CHAPTERS, ROOT, load_questions
from ds_tutor.llm import ModelError, complete, reload_model_settings, settings_for
from ds_tutor.prompts import make_messages, reference_reply
from ds_tutor.practice import open_question, render_practice
from ds_tutor.storage import Store, local_learner, summarize

st.set_page_config(page_title="数据结构智练 · 每一道题，都学明白", page_icon="🌱", layout="wide")
st.markdown(f"<style>{(ROOT / 'assets/style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

access_code = os.getenv("APP_ACCESS_CODE", "")
if access_code and not st.session_state.get("authorized"):
    st.title("进入数据结构智练")
    with st.form("access"):
        code = st.text_input("访问口令", type="password")
        entered = st.form_submit_button("进入")
    if entered:
        if hmac.compare_digest(code.encode("utf-8"), access_code.encode("utf-8")):
            st.session_state.authorized = True
            st.rerun()
        st.error("访问口令不正确。")
    st.stop()

questions = load_questions()
by_id = {q["id"]: q for q in questions}
store = Store()
shared = os.getenv("APP_SHARED_MODE", "false").lower() == "true"
if "learner" not in st.session_state:
    st.session_state.learner = uuid.uuid4().hex if shared else local_learner()
st.session_state.setdefault("ui", {})
st.session_state.setdefault("page", "章节练习")
st.session_state.setdefault("api_calls", 0)
st.session_state.setdefault("mode", "云端 API" if settings_for("云端 API").ready else "题库解析")


def request_answer(q, task, answer=None, followup="", history=None):
    if mode == "题库解析":
        return {"content": reference_reply(q, task), "model": "题库预设内容 · 非模型生成"}
    if st.session_state.api_calls >= 80:
        raise ModelError("本会话已达到 80 次模型调用上限，请先查看服务商用量。")
    if time.monotonic() - st.session_state.get("last_call", 0) < 2:
        raise ModelError("请稍等两秒再发起下一次请求。")
    st.session_state.last_call = time.monotonic()
    st.session_state.api_calls += 1
    return complete(make_messages(q, task, answer, followup, history=history), settings_for(mode))


records = store.records(st.session_state.learner)
stats = summarize(records)

with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">知</div><div><div class="brand-name">数据结构智练</div><div class="brand-subtitle">理解，从练习开始</div></div></div>', unsafe_allow_html=True)
    st.radio("学习空间", ["章节练习", "我的错题", "学习概览", "模型实验室", "使用说明"], key="page", width="stretch")
    st.divider()
    with st.expander("辅导设置", icon=":material/tune:"):
        mode = st.selectbox("选择讲解来源", ["题库解析", "云端 API", "自训练模型"], key="mode")
        st.button("重新读取模型配置", on_click=reload_model_settings, help="读取本机 .env 中的模型设置；不会显示密钥。", width="stretch")
        if mode == "题库解析":
            st.caption("预设提示与解析，不调用模型。")
        elif settings_for(mode).ready:
            st.caption(f"已配置：{settings_for(mode).model}。")
        else:
            st.warning("模型尚未配置。填写 .env 后点击“重新读取模型配置”。")
    st.divider()
    st.caption("题库进度（已作答题目数）")
    st.progress(stats["unique"] / len(questions))
    st.caption(f"{stats['unique']} / {len(questions)} 题 · 6 个章节")
    if shared:
        with st.expander("保存 / 恢复我的学习码"):
            st.caption("学习码用于恢复个人记录，请自行保存，不要分享给他人。")
            st.code(st.session_state.learner, language=None)
            with st.form("restore_profile"):
                recovery = st.text_input("输入已有学习码", type="password")
                if st.form_submit_button("恢复记录"):
                    if re.fullmatch(r"[0-9a-f]{32}", recovery):
                        st.session_state.learner = recovery
                        st.session_state.ui = {}
                        st.rerun()
                    st.error("学习码应为 32 位小写十六进制字符。")
    else:
        st.caption("本机个人学习空间 · 记录保存在本地")

page = st.session_state.page
titles = {"章节练习": ("专注练习，逐题掌握。", "先独立思考，再和学习助手一起把问题弄明白。"),
          "我的错题": ("把薄弱的地方，再练一遍。", "答错自动收录，重新答对后标记为已复习。"),
          "学习概览": ("每一点进步，都有迹可循。", "从真实作答记录中，找到下一步的学习方向。"),
          "模型实验室": ("模型实验室", "查看真实实验数据，比较微调前后的辅导效果。"),
          "使用说明": ("使用指南", "了解练习流程、模型连接与数据保存方式。")}
title, subtitle = titles[page]
accuracy = f"{stats['correct']/stats['attempts']:.0%}" if stats["attempts"] else "—"
st.markdown(f'<div class="workspace-header"><div><div class="eyebrow">学习工作台 / {page}</div><h1>{title}</h1><p>{subtitle}</p></div><div class="header-stats"><span>已练 <b>{stats["unique"]}</b> / 60</span><span>正确率 <b>{accuracy}</b></span><span>待复习 <b>{len(stats["pending"])}</b></span></div></div>', unsafe_allow_html=True)

if page == "章节练习":
    render_practice(questions, stats, store, mode, request_answer)

elif page == "我的错题":
    selection = st.radio("复习范围", ["待复习", "全部错题", "已复习"], horizontal=True)
    target = stats["pending"] if selection == "待复习" else stats["ever_wrong"]
    if selection == "已复习":
        target = stats["ever_wrong"] - stats["pending"]
    st.caption(f"{len(target)} 道题 · 最近一次重新作答正确，才会标记为已复习。")
    if not target:
        st.info("这里暂时没有题目。练习中的错误会自动记录到这里。")
    ordered_target = [q["id"] for q in questions if q["id"] in target]
    if ordered_target:
        st.button("开始连续复习", type="primary", on_click=open_question, args=(ordered_target[0], ordered_target))
    for q in questions:
        if q["id"] not in target:
            continue
        with st.container(border=True):
            a, b = st.columns([5, 1])
            a.markdown(f"**{q['id']} · {q['topic']}**")
            a.write(q["stem"])
            a.caption(f"{q['chapter']} · {'待复习' if q['id'] in stats['pending'] else '已复习'}")
            b.button("重新练习", key=f"review_{q['id']}", on_click=open_question, args=(q["id"], ordered_target))

elif page == "学习概览":
    metrics = st.columns(4)
    metrics[0].metric("累计作答", stats["attempts"])
    metrics[1].metric("练习题目", stats["unique"])
    metrics[2].metric("作答正确率", f"{stats['correct']/stats['attempts']:.0%}" if stats["attempts"] else "—")
    metrics[3].metric("待复习错题", len(stats["pending"]))
    st.caption("正确率按所有提交次数计算，包含重复练习；题目进度按不同题目计算。")
    rows = []
    for chapter in CHAPTERS:
        ids = {q["id"] for q in questions if q["chapter"] == chapter}
        attempts = [r for r in records if r["qid"] in ids]
        rows.append({"章节": chapter, "已练题目": len(ids & stats["latest"].keys()), "总题数": len(ids),
                     "提交次数": len(attempts), "正确次数": sum(r["correct"] for r in attempts),
                     "待复习": len(ids & stats["pending"])})
    st.subheader("章节进度")
    st.bar_chart(pd.DataFrame(rows).set_index("章节")[["已练题目"]], color="#358976")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    pending_chapters = sorted(rows, key=lambda row: row["待复习"], reverse=True)
    if pending_chapters[0]["待复习"]:
        st.info(f"建议先复习「{pending_chapters[0]['章节']}」：目前有 {pending_chapters[0]['待复习']} 道待复习题。此建议按错题数量生成。")
    st.download_button("导出我的答题记录", store.export(st.session_state.learner), "study_records.json", "application/json")

elif page == "模型实验室":
    st.info("微调尚未执行时，本页不会展示训练曲线或虚构提升数据。云端 API 与自训练模型的比较，也不等同于微调前后比较。")
    manifest_path = ROOT / "data/training/manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cols = st.columns(3)
        for col, name, label in zip(cols, ["train", "validation", "test"], ["训练集", "验证集", "测试集"]):
            col.metric(label, f"{manifest['splits'][name]['samples']} 条")
            col.caption(f"来自 {manifest['splits'][name]['questions']} 道题")
        st.caption("同一道题的提示、正确作答解析、错误作答解析、知识点追问固定分在同一集合。样本由题库模板构造，尚需人工复核。")
    st.subheader("同题查看微调前后回答")
    st.caption("先运行 training/evaluate.py，将真实结果保存为 outputs/evaluation/results.jsonl。")
    results_path = ROOT / "outputs/evaluation/results.jsonl"
    if results_path.exists():
        try:
            results = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if results:
                index = st.selectbox("评测样本", range(len(results)), format_func=lambda i: f"{results[i]['question_id']} · {results[i]['task']}")
                row = results[index]
                st.write(by_id.get(row["question_id"], {}).get("stem", row["question_id"]))
                base, tuned = st.columns(2)
                with base:
                    st.markdown("**基础模型**")
                    st.write(row["base_response"])
                with tuned:
                    st.markdown("**微调模型**")
                    st.write(row["tuned_response"])
                st.caption("请人工评价事实正确性、提示是否泄露答案，以及讲解是否清晰；训练损失下降不代表这些指标必然改善。")
        except (ValueError, KeyError):
            st.error("评测文件格式不正确，请重新运行评测脚本。")
    else:
        st.caption("当前没有已完成的微调评测。训练、推理、评测脚本已随项目提供。")
    with st.expander("运行路径"):
        st.code("python training/prepare_data.py\npython training/train_lora.py --output-dir outputs/lora\npython training/evaluate.py --adapter outputs/lora\npython training/serve.py --adapter outputs/lora", language="bash")

else:
    st.markdown("""**开始练习**

选择章节 → 独立作答或请求提示 → 提交答案并查看解析 → 下一道未练。难度筛选、搜索和题目跳转位于“筛选与跳题”。作答后的选项默认收起，可以重新展开核对。错题本支持“开始连续复习”。

**三种辅导方式**

- **题库解析**：显示题库预设提示与解析，完全离线可用，不生成新的回答。
- **云端 API**：由已配置的服务商模型生成讲解；仅在点击辅导按钮时调用。
- **自训练模型**：连接自行部署的微调模型服务；必须实际训练并启动服务后才能使用。

**连接模型**

在项目根目录将 `.env.example` 复制为 `.env`，填写服务端地址、模型名称和密钥，然后展开侧栏“辅导设置”，点击“重新读取模型配置”。配置齐全时，新会话默认选择云端模式。同题同模型的提示与讲解会缓存，连续追问会带上有限的近期上下文。密钥不要写入源码或上传到公开仓库。接口配置步骤见 `docs/使用与部署说明.md`。

**学习记录**

本机模式将记录保存在 `runtime/study.db`，重启后保留。共享部署需启用 `APP_SHARED_MODE=true`，每位访客使用独立学习码，并配备持久磁盘。学习码用于找回记录，不是完整的用户认证系统。

**项目边界**

本项目面向课程复习。题库为自编教学材料，尚待教师复核；客观题按标准答案判分，模型讲解作为辅助。当前没有拍照识题、自动代码执行或正式考试功能。
""")
    with st.expander("当前连接配置（不显示密钥）"):
        for name in ["云端 API", "自训练模型"]:
            settings = settings_for(name)
            st.write(f"{name}：{settings.model} · {'配置齐全，待实际请求验证' if settings.ready else '未配置完成'}")
    st.caption("项目资料：README.md · docs/使用与部署说明.md · docs/微调技术说明.md")

st.markdown('<div class="footer"><span>数据结构智练</span><span>循序渐进 · 学以致用</span></div>', unsafe_allow_html=True)

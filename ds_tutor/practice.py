"""刷题工作台：紧凑导航、连续复习，以及按题目和模型隔离的辅导对话。"""
import hashlib
import html
import uuid

import streamlit as st

from ds_tutor.bank import CHAPTERS, filter_questions, grade
from ds_tutor.llm import ModelError, settings_for


def move_question(qid):
    st.session_state.current_question_id = qid


def remember_question():
    st.session_state.current_question_id = st.session_state.practice_select


def reset_question(qid):
    st.session_state.ui.pop(qid, None)


def clear_filters():
    st.session_state.chapter = "全部章节"
    st.session_state.difficulty = "全部难度"
    st.session_state.search = ""


def open_question(qid, queue=None):
    st.session_state.page = "章节练习"
    clear_filters()
    st.session_state.review_queue = list(queue or [])
    st.session_state.current_question_id = qid
    for target in queue or [qid]:
        st.session_state.ui.pop(target, None)


def leave_review():
    st.session_state.review_queue = []
    clear_filters()


def next_target(ids, current, eligible):
    """从当前题之后按顺序查找，末尾回绕；不返回当前题。"""
    if not ids or current not in ids:
        return None
    pivot = ids.index(current)
    return next((qid for qid in ids[pivot+1:] + ids[:pivot] if qid in eligible), None)


def source_key(mode):
    settings = settings_for(mode) if mode != "题库解析" else None
    source = mode if settings is None else f"{mode}|{settings.base_url}|{settings.model}"
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def conversation(state, mode):
    return state.setdefault("conversations", {}).setdefault(source_key(mode),
        {"hint": None, "explain": None, "chat": [], "error": None})


def reply(result):
    st.markdown(result["content"])
    meta = f"来源：{result['model']}"
    if "seconds" in result:
        meta += f" · {result['seconds']:.2f} 秒"
    st.caption(meta)


def render_followup(q, state, tutor, mode, request_answer):
    if mode == "题库解析":
        return
    answered = state["answer"] is not None
    with st.container(key="tutor_composer"):
        with st.form(f"followup_{state['event']}_{source_key(mode)}", clear_on_submit=True, border=False):
            followup = st.text_area("继续追问", height=110, max_chars=800,
                placeholder="例如：为什么这样计算？\n能用一个具体例子再解释一下吗？",
                disabled=not answered)
            st.caption("围绕这道题，哪里没理解都可以问。" if answered else "提交答案后，可在这里输入问题；现在可以先获取提示。")
            send = st.form_submit_button("发送追问", type="primary", icon=":material/send:",
                                         width="stretch", disabled=not answered)
        if send:
            if not followup.strip():
                st.warning("先写下你的问题，再发送。")
                return
            history = [("请讲解这道题。", tutor["explain"]["content"])] if tutor["explain"] else []
            history += [(prompt, result["content"]) for prompt, result in tutor["chat"]]
            try:
                with st.spinner("正在回答…"):
                    result = request_answer(q, "followup", state["answer"], followup, history=history[-3:])
                    tutor["chat"].append((followup, result))
                    tutor["error"] = None
            except ModelError as error:
                tutor["error"] = str(error)
            st.rerun()


def render_practice(questions, stats, store, mode, request_answer):
    by_id = {q["id"]: q for q in questions}
    queue = [qid for qid in st.session_state.get("review_queue", []) if qid in by_id]
    reviewing = bool(queue)
    if reviewing:
        left, right = st.columns([4, 1], vertical_alignment="center")
        remaining = len(set(queue) & stats["pending"])
        left.info(f"错题复习中 · 本轮 {len(queue)} 题，还剩 {remaining} 题待巩固")
        right.button("结束复习", on_click=leave_review, width="stretch")
        if not remaining:
            st.success("本轮错题已全部答对，完成一轮巩固！")
    with st.container(key="practice_toolbar"):
        chapter_col, filter_col = st.columns([1.5, 1], vertical_alignment="bottom")
        chapter = chapter_col.selectbox("章节", ["全部章节"] + CHAPTERS, key="chapter", disabled=reviewing)
        with filter_col.popover("筛选与跳题", width="stretch"):
            st.markdown("**找到你想练的题**")
            difficulty = st.selectbox("难度", ["全部难度", "基础", "进阶"], key="difficulty", disabled=reviewing)
            search = st.text_input("搜索题目或知识点", placeholder="例如：二分查找", key="search", disabled=reviewing)
            filtered = [by_id[qid] for qid in queue] if reviewing else filter_questions(questions, chapter, difficulty, search)
            ids = [q["id"] for q in filtered]
            if ids:
                current = st.session_state.get("current_question_id", st.session_state.get("practice_select"))
                if current not in ids:
                    current = ids[0]
                st.session_state.current_question_id = current
                # 作答状态会改变选项文案，导致 Streamlit 重建 selectbox。
                # 用独立的题号状态恢复控件，不能依赖控件自身的默认首项。
                st.session_state.practice_select = current
                def option_label(qid):
                    latest = stats["latest"].get(qid)
                    status = "未练" if latest is None else "已答对" if latest["correct"] else "待复习"
                    return f"{qid} · {by_id[qid]['topic']} · {status}"
                st.selectbox("当前练习", ids, key="practice_select", format_func=option_label,
                             on_change=remember_question)
            st.button("清除筛选", on_click=clear_filters, disabled=reviewing, width="stretch")
    if not ids:
        with st.container(border=True):
            st.subheader("暂时没有匹配的题目")
            st.write("试试缩短关键词，或恢复全部章节和难度。")
            st.button("恢复全部题目", on_click=clear_filters, type="primary")
        return
    qid = st.session_state.practice_select
    q = by_id[qid]
    position = ids.index(qid)
    done = len(set(ids) & stats["latest"].keys())
    st.markdown(f'<div class="practice-meta"><span>{html.escape(q["chapter"])} <span class="meta-separator">/</span> {html.escape(q["topic"])}</span><span>第 <b>{position+1:02d}</b> / {len(ids):02d} 题 · 已练 {done} 题</span></div>', unsafe_allow_html=True)
    state = st.session_state.ui.setdefault(qid, {"event": uuid.uuid4().hex, "answer": None})
    tutor = conversation(state, mode)
    task = "explain" if state["answer"] else "hint"
    eligible = (set(ids) & stats["pending"]) if reviewing else (set(ids) - stats["latest"].keys())
    next_fresh = next_target(ids, qid, eligible)
    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        with st.container(border=True, key="question_card"):
            st.markdown(f'<div class="question-meta"><span class="tag">{html.escape(q["difficulty"])}</span><span class="question-kind">单项选择</span><span class="question-id">{qid}</span></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="question-title">{html.escape(q["stem"])}</div>', unsafe_allow_html=True)
            submitted = False
            if state["answer"] is None:
                with st.form(f"question_{state['event']}", border=False):
                    choice = st.radio("选择你的答案", list(q["options"]), index=None,
                        format_func=lambda value: f"{value}　{q['options'][value]}",
                        key=f"choice_{state['event']}", label_visibility="collapsed", width="stretch")
                    submitted = st.form_submit_button("提交答案", type="primary", width="stretch")
            else:
                with st.expander("查看选项与我的作答"):
                    for option, text in q["options"].items():
                        marks = []
                        if option == q["answer"]:
                            marks.append("正确答案")
                        if option == state["answer"]:
                            marks.append("你的选择")
                        suffix = " · " + " / ".join(marks) if marks else ""
                        st.write(f"**{option}**　{text}{suffix}")
            if submitted:
                if choice is None:
                    st.warning("先选择一个选项，再提交答案。")
                else:
                    state["answer"] = choice
                    store.record(st.session_state.learner, qid, choice, grade(q, choice), state["event"])
                    st.rerun()
            if state["answer"]:
                correct = grade(q, state["answer"])
                style = "correct" if correct else "incorrect"
                heading = "回答正确，继续保持。" if correct else f"正确答案是 {q['answer']}，再理解一次。"
                detail = f"你选择了 {state['answer']}" + (" · 已加入错题本" if not correct else " · 本题已巩固")
                st.markdown(f'<div class="answer-feedback {style}"><b>{heading}</b><span>{detail}</span></div>', unsafe_allow_html=True)
                st.markdown("**解题思路**")
                st.write(q["explanation"])
                with st.expander("容易混淆的地方"):
                    st.write(q["misconception"])
                st.button("再练一次", on_click=reset_question, args=(qid,), type="tertiary")
            else:
                st.caption("先独立思考；需要帮助时，可以向学习助手要一个提示。")
        with st.container(key="question_navigation"):
            prev, following = st.columns(2)
            prev.button("← 上一题", disabled=position == 0, on_click=move_question,
                        args=(ids[max(0, position-1)],), width="stretch")
            following.button("下一题 →", disabled=position == len(ids)-1, on_click=move_question,
                             args=(ids[min(position+1, len(ids)-1)],), type="primary" if state["answer"] else "secondary", width="stretch")
        st.button("下一道待复习" if reviewing else "下一道未练", disabled=next_fresh is None,
                  on_click=move_question, args=(next_fresh,), width="stretch", type="tertiary")
        if not eligible and not reviewing:
            st.caption("这个范围的题目都已练过，可以切换章节或到错题本巩固。")
    with right:
        with st.container(border=True, key="tutor_panel"):
            model_name = "题库解析" if mode == "题库解析" else settings_for(mode).model
            st.markdown(f'<div class="tutor-heading"><div class="tutor-icon">✦</div><div><strong>学习助手</strong><span>{html.escape(mode)} · {html.escape(model_name) if mode != "题库解析" else "预设提示与解析"}</span></div></div>', unsafe_allow_html=True)
            label = "讲解我的作答" if state["answer"] else "给我一点提示"
            cached = tutor[task] is not None
            if st.button(label if not cached else ("讲解已生成" if task == "explain" else "提示已显示"),
                         key="tutor_button", disabled=cached, width="stretch", icon=":material/auto_awesome:"):
                try:
                    with st.spinner("正在思考…" if mode != "题库解析" else "正在读取解析…"):
                        tutor[task] = request_answer(q, task, state["answer"])
                        tutor["error"] = None
                except ModelError as error:
                    tutor["error"] = str(error)
                # 立即切换按钮状态，避免用户连续重复调用相同提示。
                st.rerun()
            if tutor["error"]:
                st.error(tutor["error"])
            render_followup(q, state, tutor, mode, request_answer)
            content_exists = tutor[task] is not None or bool(tutor["chat"])
            with st.container(height=370 if content_exists else 225, border=False, key="tutor_output"):
                if tutor["chat"]:
                    with st.expander(f"之前的对话 · {len(tutor['chat'])} 次追问"):
                        if tutor[task]:
                            reply(tutor[task])
                        for prompt, result in tutor["chat"][-4:-1]:
                            st.markdown(f"**你：** {prompt}")
                            reply(result)
                elif tutor[task]:
                    reply(tutor[task])
                elif not tutor["chat"]:
                    empty_title = "答案之外，再多理解一步" if state["answer"] else "卡住时，从一个提示开始"
                    empty_text = "我会先给你一个思考方向。提交答案后，再一起梳理解题过程。"
                    if state["answer"]:
                        empty_text = "点击上方按钮，查看题库中的解题步骤与易错提醒。" if mode == "题库解析" else "点击上方按钮，让助手结合你的选择讲解。也可以在上方的“继续追问”输入框中提出疑问。"
                    st.markdown(f'<div class="tutor-empty"><div>✧</div><strong>{empty_title}</strong><p>{empty_text}</p></div>', unsafe_allow_html=True)
                for prompt, result in tutor["chat"][-1:]:
                    with st.chat_message("user"):
                        st.write(prompt)
                    with st.chat_message("assistant"):
                        reply(result)
            if mode == "题库解析":
                st.caption("提交答案后，可以继续追问。" if not state["answer"] else "在侧栏选择云端 API 后，可以继续追问。")
            if state["answer"] and tutor["hint"]:
                with st.expander("回看作答前的提示"):
                    reply(tutor["hint"])
            st.caption("生成内容仅供辅助，请结合题库解析核对。")

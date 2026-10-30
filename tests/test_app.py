from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from ds_tutor.bank import load_questions
from ds_tutor.storage import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_models(monkeypatch):
    # UI tests must never consume the user's real API quota.
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('LOCAL_API_KEY', '')


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_practice_wrongbook_review_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'app.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    assert not at.exception
    button(at, '提交答案').click().run()
    assert any('先选择' in x.value for x in at.warning)
    button(at, '给我一点提示').click().run()
    assert any('非模型生成' in x.value for x in at.caption)
    choice = next(x for x in at.radio if x.label == '选择你的答案')
    choice.set_value('B')
    button(at, '提交答案').click().run()
    assert not at.exception
    assert any('已加入错题本' in x.value for x in at.markdown)
    at.sidebar.radio[0].set_value('我的错题').run()
    assert not at.exception
    assert any('1 道题' in x.value for x in at.caption)
    button(at, '重新练习').click().run()
    choice = next(x for x in at.radio if x.label == '选择你的答案')
    choice.set_value('A')
    button(at, '提交答案').click().run()
    assert any('回答正确' in x.value for x in at.markdown)
    at.sidebar.radio[0].set_value('我的错题').run()
    assert any('暂时没有题目' in x.value for x in at.info)
    at.sidebar.radio[0].set_value('学习概览').run()
    assert not at.exception
    assert [x.value for x in at.metric] == ['2', '1', '50%', '0']
    at.sidebar.radio[0].set_value('模型实验室').run()
    assert not at.exception
    assert [x.value for x in at.metric] == ['144 条', '48 条', '48 条']
    at.sidebar.radio[0].set_value('使用说明').run()
    assert not at.exception


def test_filters_and_unconfigured_model(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'filters.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    next(x for x in at.selectbox if x.label == '章节').set_value('栈与队列').run()
    assert len(next(x for x in at.selectbox if x.label == '当前练习').options) == 10
    at.sidebar.selectbox[0].set_value('云端 API').run()
    button(at, '给我一点提示').click().run()
    assert any('尚未配置模型连接' in x.value for x in at.error)
    assert not at.exception


def test_access_gate_supports_chinese_passphrase(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'access.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.setenv('APP_ACCESS_CODE', '课堂展示口令')
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    at.text_input[0].set_value('wrong')
    button(at, '进入').click().run()
    assert any('不正确' in x.value for x in at.error)
    at.text_input[0].set_value('课堂展示口令')
    button(at, '进入').click().run()
    assert not at.exception
    assert len(at.sidebar.radio) == 1


def test_continuous_review_resets_old_answers_and_keeps_queue(tmp_path, monkeypatch):
    db = tmp_path / 'review.db'
    monkeypatch.setenv('APP_DB_PATH', str(db))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    bank = load_questions()
    for q in bank[:2]:
        choice = next(x for x in at.radio if x.label == '选择你的答案')
        choice.set_value(next(a for a in q['options'] if a != q['answer']))
        button(at, '提交答案').click().run()
        if q == bank[0]:
            button(at, '下一题 →').click().run()
    at.sidebar.radio[0].set_value('我的错题').run()
    button(at, '开始连续复习').click().run()
    for index, q in enumerate(bank[:2]):
        choice = next(x for x in at.radio if x.label == '选择你的答案')
        assert not choice.disabled
        choice.set_value(q['answer'])
        button(at, '提交答案').click().run()
        assert at.session_state['review_queue'] == ['DS001', 'DS002']
        if index == 0:
            button(at, '下一道待复习').click().run()
    assert any('本轮错题已全部答对' in x.value for x in at.success)
    assert len(Store(db).records(at.session_state['learner'])) == 4
    button(at, '结束复习').click().run()
    assert not at.exception
    assert at.session_state['review_queue'] == []


def test_skip_unanswered_and_recover_empty_search(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'navigation.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    next(x for x in at.radio if x.label == '选择你的答案').set_value('A')
    button(at, '提交答案').click().run()
    button(at, '下一道未练').click().run()
    assert at.session_state['practice_select'] == 'DS002'
    next(x for x in at.text_input if x.label == '搜索题目或知识点').set_value('不存在的关键词').run()
    assert any('暂时没有匹配' in x.value for x in at.subheader)
    button(at, '恢复全部题目').click().run()
    assert not at.exception
    assert len(next(x for x in at.selectbox if x.label == '当前练习').options) == 60


def test_submitting_later_question_keeps_current_question(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'stay-on-question.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    next(x for x in at.selectbox if x.label == '当前练习').set_value('DS003').run()
    next(x for x in at.radio if x.label == '选择你的答案').set_value('B')
    button(at, '提交答案').click().run()
    assert not at.exception
    assert at.session_state['practice_select'] == 'DS003'
    assert any('DS003' in x.value and 'question-id' in x.value for x in at.markdown)
    assert any('回答正确' in x.value for x in at.markdown)
    button(at, '下一题 →').click().run()
    assert at.session_state['practice_select'] == 'DS004'
    next(x for x in at.radio if x.label == '选择你的答案').set_value('A')
    button(at, '提交答案').click().run()
    assert at.session_state['practice_select'] == 'DS004'
    at.sidebar.radio[0].set_value('学习概览').run()
    at.sidebar.radio[0].set_value('章节练习').run()
    assert at.session_state['practice_select'] == 'DS004'


def test_tutor_cache_source_isolation_and_followup_context(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB_PATH', str(tmp_path / 'tutor.db'))
    monkeypatch.setenv('APP_SHARED_MODE', 'true')
    monkeypatch.setenv('LLM_API_KEY', 'unit-test-placeholder')
    monkeypatch.delenv('APP_ACCESS_CODE', raising=False)
    calls = []
    def fake_complete(messages, settings):
        calls.append(messages)
        return {'content': f'测试回答 {len(calls)}', 'model': 'test-model', 'seconds': 0.1}
    monkeypatch.setattr('ds_tutor.llm.complete', fake_complete)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    assert at.session_state['mode'] == '云端 API'
    assert next(x for x in at.text_area if x.label == '继续追问').disabled
    assert button(at, '发送追问').disabled
    button(at, '给我一点提示').click().run()
    assert button(at, '提示已显示').disabled
    at.run()
    assert len(calls) == 1
    at.sidebar.selectbox[0].set_value('题库解析').run()
    assert not button(at, '给我一点提示').disabled
    assert not any('测试回答 1' in x.value for x in at.markdown)
    at.sidebar.selectbox[0].set_value('云端 API').run()
    assert button(at, '提示已显示').disabled
    next(x for x in at.radio if x.label == '选择你的答案').set_value('A')
    button(at, '提交答案').click().run()
    assert not next(x for x in at.text_area if x.label == '继续追问').disabled
    assert not button(at, '发送追问').disabled
    button(at, '发送追问').click().run()
    assert any('先写下你的问题' in x.value for x in at.warning)
    assert len(calls) == 1
    at.session_state['last_call'] = 0
    button(at, '讲解我的作答').click().run()
    for prompt in ['为什么是这个复杂度？', '用更小的例子解释一下。']:
        at.session_state['last_call'] = 0
        next(x for x in at.text_area if x.label == '继续追问').set_value(prompt)
        button(at, '发送追问').click().run()
    assert not at.exception
    assert len(calls) == 4
    assert any(m['role'] == 'assistant' and m['content'] == '测试回答 2' for m in calls[-1])
    assert any(m['role'] == 'user' and m['content'] == '为什么是这个复杂度？' for m in calls[-1])
    assert any('测试回答 4' in x.value for x in at.markdown)

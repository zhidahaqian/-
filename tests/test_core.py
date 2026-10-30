import json
from unittest.mock import Mock

import pytest
import requests

from ds_tutor.bank import CHAPTERS, ROOT, filter_questions, grade, load_questions
from ds_tutor.llm import ModelError, Settings, complete, reload_model_settings, settings_for
from ds_tutor.prompts import make_messages
from ds_tutor.storage import Store, summarize
from training.data_utils import encode_sample, read_jsonl, verify_disjoint
from training.prepare_data import build_splits


def test_bank_integrity():
    bank = load_questions()
    assert len(bank) == 60
    assert {q['chapter'] for q in bank} == set(CHAPTERS)
    for question in bank:
        assert set(question['options']) == set('ABCD')
        assert len(set(question['options'].values())) == 4
        assert len(question['explanation']) >= 20
        for answer in question['options']:
            assert grade(question, answer) == (answer == question['answer'])
    assert len(filter_questions(bank, chapter='图')) == 10
    assert filter_questions(bank, search='不存在的知识点') == []


def test_calculated_answers():
    bank = {q['topic']: q for q in load_questions()}
    values = {'循环队列长度': (2-6+8)%8, '叶子计数': 7+1, '满二叉树结点数': 2**4-1,
              '二叉树层容量': 2**3, '无向图度数': 2*7, '生成树边数': 9-1, '后缀表达式': (3+4)*2,
              '装填因子': 12/20}
    for topic, value in values.items():
        question = bank[topic]
        assert float(question['options'][question['answer']]) == value
    numbers = [5, 1, 4, 2]
    for i in range(len(numbers)-1):
        if numbers[i] > numbers[i+1]:
            numbers[i], numbers[i+1] = numbers[i+1], numbers[i]
    q = bank['冒泡一趟']
    assert json.loads(q['options'][q['answer']]) == numbers


def test_wrong_book_persistence_isolation_and_idempotency(tmp_path):
    path = tmp_path / 'study.db'
    store = Store(path)
    store.record('alice', 'DS001', 'B', False, 'event1')
    store.record('alice', 'DS001', 'B', False, 'event1')
    store.record('bob', 'DS002', 'A', False, 'event2')
    assert len(Store(path).records('alice')) == 1
    assert summarize(store.records('alice'))['pending'] == {'DS001'}
    store.record('alice', 'DS001', 'A', True, 'event3')
    stats = summarize(Store(path).records('alice'))
    assert stats['pending'] == set()
    assert stats['ever_wrong'] == {'DS001'}
    assert stats['attempts'] == 2
    assert 'bob' not in store.export('alice')
    assert 'learner' not in json.loads(store.export('alice'))[0]


def test_training_split_no_leakage():
    splits = build_splits(load_questions())
    assert splits == build_splits(load_questions())
    verify_disjoint(*splits.values())
    assert [len(splits[k]) for k in splits] == [144, 48, 48]
    for key, rows in splits.items():
        assert rows == read_jsonl(ROOT / f'data/training/{key}.jsonl')
        assert all(r['messages'][-1]['role'] == 'assistant' for r in rows)
    with pytest.raises(ValueError):
        verify_disjoint(splits['train'], splits['train'])


def test_hint_prompt_does_not_include_reference_answer():
    q = load_questions()[0]
    content = make_messages(q, 'hint')[-1]['content']
    assert '标准答案' not in content
    assert '标准解析' not in content
    assert q['explanation'] not in content
    assert '可用提示' in content


def test_followup_context_is_bounded_and_never_added_to_hint():
    q = load_questions()[0]
    history = [(f'问题{i}' + '问' * 900, f'回答{i}' + '答' * 4000) for i in range(5)]
    messages = make_messages(q, 'followup', 'A', '再举个例子', history=history)
    assert len(messages) == 8
    assert messages[1]['content'].startswith('问题2')
    assert len(messages[1]['content']) == 800
    assert len(messages[2]['content']) == 3000
    hint = make_messages(q, 'hint', history=history)
    assert len(hint) == 2
    assert '标准答案' not in hint[-1]['content']


class FakeTokenizer:
    eos_token = '!'
    def apply_chat_template(self, *args, **kwargs):
        return 'PROMPT'
    def __call__(self, text, **kwargs):
        return {'input_ids': [ord(c) for c in text]}


def test_only_assistant_tokens_receive_loss():
    row = {'id': 'one', 'messages': [{'role': 'user', 'content': 'ask'}, {'role': 'assistant', 'content': 'OK'}]}
    encoded = encode_sample(row, FakeTokenizer(), 20)
    assert encoded['labels'] == [-100]*6 + [ord('O'), ord('K'), ord('!')]
    assert len(encoded['input_ids']) == len(encoded['attention_mask']) == len(encoded['labels'])
    with pytest.raises(ValueError, match='不会静默截断'):
        encode_sample(row, FakeTokenizer(), 7)


def test_api_request_shape_and_errors(monkeypatch):
    settings = Settings('https://example.test/v1', 'test-secret', 'qwen-plus', send_thinking=True)
    response = Mock(status_code=200)
    response.json.return_value = {'choices': [{'message': {'content': '真实接口返回的讲解'}}], 'model': 'qwen-plus'}
    post = Mock(return_value=response)
    monkeypatch.setattr('ds_tutor.llm.requests.post', post)
    result = complete(make_messages(load_questions()[0], 'hint'), settings)
    assert result['model'] == 'qwen-plus'
    assert post.call_args.kwargs['json']['enable_thinking'] is False
    assert post.call_args.args[0] == 'https://example.test/v1/chat/completions'
    response.status_code = 401
    with pytest.raises(ModelError) as error:
        complete([], settings)
    assert 'test-secret' not in str(error.value)
    assert '401' in str(error.value)
    post.side_effect = requests.Timeout()
    with pytest.raises(ModelError, match='超时'):
        complete([], settings)


def test_api_missing_configuration_and_insecure_remote():
    with pytest.raises(ModelError, match='尚未配置'):
        complete([], Settings('https://example.test/v1', '', 'model'))
    with pytest.raises(ModelError, match='HTTPS'):
        complete([], Settings('http://example.test/v1', 'secret', 'model'))


def test_reload_only_changes_model_settings(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('LLM_MODEL', 'old-model')
    monkeypatch.setenv('APP_ACCESS_CODE', 'keep-existing-access')
    monkeypatch.setattr('ds_tutor.llm.dotenv_values', lambda path: {
        'LLM_API_KEY': 'unit-test-secret', 'LLM_MODEL': 'updated-model',
        'APP_ACCESS_CODE': 'must-not-replace', 'PATH': 'must-not-replace'})
    reload_model_settings()
    assert settings_for('云端 API').api_key == 'unit-test-secret'
    assert settings_for('云端 API').model == 'updated-model'
    assert __import__('os').environ['APP_ACCESS_CODE'] == 'keep-existing-access'

from fastapi.testclient import TestClient

from training.serve import create_app


def test_compatible_service_auth_limits_and_adapter_switch(monkeypatch):
    observed = []

    def fake_generate(model, tokenizer, messages, max_tokens, use_adapter):
        observed.append(use_adapter)
        return {'content': '测试桩响应，不是真实模型生成', 'input_tokens': 20, 'output_tokens': 10}

    monkeypatch.setattr('training.serve.generate', fake_generate)
    client = TestClient(create_app(object(), object(), 'unit-test-secret-only'))
    payload = {'model': 'ds-tutor-lora', 'messages': [{'role': 'user', 'content': '解释栈'}], 'max_tokens': 100}
    auth = {'Authorization': 'Bearer unit-test-secret-only'}
    assert client.get('/health').json()['adapter_loaded'] is True
    assert client.post('/v1/chat/completions', json=payload).status_code == 403
    assert client.post('/v1/chat/completions', json=payload, headers={'Authorization':'Bearer wrong'}).status_code == 401
    response = client.post('/v1/chat/completions', json=payload, headers=auth)
    assert response.status_code == 200
    assert response.json()['model'] == 'ds-tutor-lora'
    assert response.json()['usage']['total_tokens'] == 30
    assert observed == [True]
    payload['model'] = 'ds-tutor-base'
    assert client.post('/v1/chat/completions', json=payload, headers=auth).status_code == 200
    assert observed[-1] is False
    payload['model'] = 'not-a-model'
    assert client.post('/v1/chat/completions', json=payload, headers=auth).status_code == 404
    payload['model'] = 'ds-tutor-lora'
    payload['max_tokens'] = 999999
    assert client.post('/v1/chat/completions', json=payload, headers=auth).status_code == 422
    payload['max_tokens'] = 100
    payload['stream'] = True
    assert client.post('/v1/chat/completions', json=payload, headers=auth).status_code == 400

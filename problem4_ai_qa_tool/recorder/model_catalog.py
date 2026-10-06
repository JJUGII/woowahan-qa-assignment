"""Small task-based menu, intersected with API discovery; no access guarantees.

Reviewed 2026-10-06 against the official OpenAI model pages:
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/models/gpt-6.1-sol
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://developers.openai.com/api/docs/models/gpt-4o-mini
Task suitability is our starting hypothesis, not measured Recorder performance.
"""
OPENAI_RECORDER_MODELS = {
    'gpt-6-luna': '기본 추천 ,  반복적인 Selector, Assertion 추천과 Step 설명 작성',
    'gpt-6.1-sol': '품질 중심 ,  복잡한 테스트 의도와 검증 설명 검토',
    'gpt-4.1-mini': '경량 대안 ,  지시사항에 맞춘 텍스트, JSON 처리',
    'gpt-4o-mini': '간단한 작업 ,  짧은 요소 설명과 후보 추천',
}


def recorder_models(service, available):
    """Exact aliases only; snapshots/fine-tunes/specialized models stay in full view."""
    if service != 'OpenAI':
        return list(available)
    found = set(available)
    return [model for model in OPENAI_RECORDER_MODELS if model in found]


def model_description(service, model):
    if service == 'OpenAI' and model in OPENAI_RECORDER_MODELS:
        return OPENAI_RECORDER_MODELS[model] + '\nJSON 추천 지원과 실제 결과는 연결 테스트, 녹화에서 확인하세요.'
    if not model:
        return ''
    return ('현재 모델은 대표 추천 목록 밖의 모델입니다. ' if service == 'OpenAI' else '') + 'JSON 추천 지원을 연결 테스트로 확인하세요.'

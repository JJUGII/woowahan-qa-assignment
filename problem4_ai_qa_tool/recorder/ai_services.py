"""Service presets and a single adapter factory for future API integrations."""
from recorder.ai_recommender import CompatibleLLMProvider, RecommendationError

CUSTOM_SERVICE = '기타 호환 API'
SERVICE_PRESETS = {
    'OpenAI': 'https://api.openai.com/v1',
    'Google Gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
}
SERVICE_NAMES = [*SERVICE_PRESETS, CUSTOM_SERVICE]


def service_for_url(base_url):
    address = base_url.strip().rstrip('/')
    if not address:
        return 'OpenAI'
    return next((name for name, url in SERVICE_PRESETS.items() if url == address), CUSTOM_SERVICE)


def create_provider(*, service=None, base_url=None, model=None, api_key=None, timeout=40, require_model=True):
    # Keeping selection separate from transport makes native API adapters addable here.
    service = service or service_for_url(base_url or '')
    if service not in SERVICE_NAMES:
        raise RecommendationError('지원하는 AI 서비스를 선택하세요.')
    if service in SERVICE_PRESETS:
        base_url = SERVICE_PRESETS[service]
        if not api_key or not api_key.strip():
            raise RecommendationError(f'{service} API Key를 입력하세요.')
    provider = CompatibleLLMProvider(base_url=base_url, model=model, api_key=api_key,
                                     timeout=timeout, require_model=require_model)
    provider.name = service + ' API' if service != CUSTOM_SERVICE else 'LLM (호환 API)'
    return provider

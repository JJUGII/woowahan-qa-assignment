"""Run a user-selected startup hook with the Recorder's existing device session."""
import ast
import importlib.util
import inspect
import logging
from pathlib import Path
import sys
import tokenize
import uuid

logger = logging.getLogger(__name__)


def validate_pre_script(path):
    script = Path(path).expanduser().resolve()
    if not script.is_file() or script.suffix.lower() != '.py':
        raise ValueError('사전 실행 스크립트는 존재하는 Python(.py) 파일이어야 합니다.')
    with tokenize.open(script) as source:
        tree = ast.parse(source.read(), filename=str(script))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not ({script.stem, 'run'} & functions):
        raise ValueError(f'사전 스크립트에 def {script.stem}(device_info) 또는 def run(device_info)가 필요합니다.')
    return script


def run_pre_script(path, device_info):
    script = validate_pre_script(path)
    module_name = '_recorder_startup_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(module_name, script)
    module = importlib.util.module_from_spec(spec)
    previous_path = sys.path.copy()
    try:
        sys.path.insert(0, str(script.parent))
        sys.modules[module_name] = module
        logger.info('[사전 스크립트] 실행: %s', script)
        # Read the selected source each time; same-size edits within a second must not use stale pyc.
        with tokenize.open(script) as source:
            exec(compile(source.read(), str(script), 'exec'), module.__dict__)
        entry = getattr(module, script.stem, None) or getattr(module, 'run', None)
        if not callable(entry) or inspect.iscoroutinefunction(entry):
            raise ValueError('사전 실행 함수는 동기 함수여야 합니다.')
        inspect.signature(entry).bind(device_info)
        if entry(device_info) is False:
            raise RuntimeError('사전 실행 함수가 실패(False)를 반환했습니다.')
        logger.info('[사전 스크립트] 완료: %s', script.name)
    except Exception as exc:
        raise RuntimeError(f'사전 스크립트 {script.name} 실행 실패: {exc}') from exc
    finally:
        sys.path[:] = previous_path
        sys.modules.pop(module_name, None)

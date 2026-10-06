"""제출용 진입점. 기존 Android Script Studio를 실행한다."""
from pathlib import Path
import os,runpy
if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    os.chdir(root)
    runpy.run_path(str(root / "main_recorder.py"), run_name="__main__")

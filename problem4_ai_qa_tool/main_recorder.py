import os
import logging
import sys

# 모듈 경로 설정을 위해 루트 디렉토리 명시
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# exe(PyInstaller)로 실행된 경우 작업 디렉토리를 exe 위치로 고정한다.
# LOG/, generated_scripts/, resources/, device_config.json 이 모두 상대 경로 기준이라
# 바로가기 등으로 실행하면 엉뚱한 위치에 파일이 생성되는 것을 막기 위함.
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from recorder.portable_runtime import configure_portable_runtime


def initialize_directories():
    """프로젝트 실행에 필요한 필수 폴더 생성"""
    directories = [
        "LOG",
        "generated_scripts",
        os.path.join("resources", "images")
    ]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)


if __name__ == "__main__":
    try:
        configure_portable_runtime()
    except (OSError, ValueError, RuntimeError) as exc:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('배포본 준비 오류', str(exc) + '\n쓰기 가능한 폴더에 압축을 해제했는지 확인하세요.')
        root.destroy()
        sys.exit(1)
    if '--self-test' in sys.argv:
        from recorder.portable_runtime import self_test
        index = sys.argv.index('--self-test')
        sys.exit(self_test(sys.argv[index + 1] if len(sys.argv) > index + 1 else None))
    from recorder.writer_gui import ScriptWriterGUI
    initialize_directories()
    # Keep the selected launch method and Python traceback available after the popup closes.
    file_handler = logging.FileHandler(os.path.join('LOG', 'Recorder.log'), encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logging.getLogger().addHandler(file_handler)
    logging.getLogger(__name__).info('Recorder 소스: %s', os.path.abspath(__file__))
    logging.getLogger(__name__).info('Python 실행 파일: %s', sys.executable)

    # GUI 실행
    app = ScriptWriterGUI()
    app.mainloop()

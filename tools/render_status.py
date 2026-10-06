import argparse
import json
from pathlib import Path
from test_report import write_report

p=argparse.ArgumentParser(); p.add_argument('folder',type=Path); a=p.parse_args()
d=json.loads((a.folder/'status.json').read_text(encoding='utf-8-sig'))
write_report(a.folder,d['title'],d['scope'],d['rows'],d['exit_code'],d.get('environment'))

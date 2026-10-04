"""Persist startup failures for packaged builds before GUI imports run."""
import json
import sys
import traceback
from pathlib import Path

def report_exception(kind, value, tb):
    try:
        if '--self-test' in sys.argv:
            path=Path(sys.argv[sys.argv.index('--self-test')+1])
            path.write_text(json.dumps({'passed':False,'error':''.join(traceback.format_exception(kind,value,tb))},ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            path=Path(sys.executable).parent/'QA_data'/'startup_error.txt'
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(''.join(traceback.format_exception(kind,value,tb)),encoding='utf-8')
    finally:
        # No hidden modal dialog during unattended verification.
        if '--self-test' not in sys.argv:
            sys.__excepthook__(kind,value,tb)

sys.excepthook=report_exception

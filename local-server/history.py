"""Local task history. Credentials and audio URLs never enter this store."""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from settings import DATA_DIR
DIRECTORY = DATA_DIR / 'history'
LOCK = threading.RLock()

def path_for(task_id):
    return DIRECTORY / (str(UUID(task_id)) + '.json')

def read(task_id):
    with LOCK:
        path = path_for(task_id)
        return json.loads(path.read_text('utf-8')) if path.exists() else None

def update(task_id, **changes):
    allowed = {'name', 'state', 'result', 'text'}
    with LOCK:
        DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
        now = datetime.now(timezone.utc).isoformat()
        record = read(task_id) or {'id': str(UUID(task_id)), 'name': '恢复的录音', 'created_at': now}
        record.update({k: v for k, v in changes.items() if k in allowed})
        record['updated_at'] = now
        target = path_for(task_id)
        temp = target.with_suffix('.' + uuid4().hex + '.tmp')
        try:
            with temp.open('x', encoding='utf-8') as f:
                os.chmod(temp, 0o600)
                json.dump(record, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return record

def listing():
    with LOCK:
        records = []
        for path in DIRECTORY.glob('*.json'):
            r = json.loads(path.read_text('utf-8'))
            records.append({k:r.get(k) for k in ('id','name','state','created_at','updated_at')} | {'preview':r.get('text','')[:100], 'characters':len(r.get('text',''))})
        return sorted(records, key=lambda r:r['created_at'], reverse=True)

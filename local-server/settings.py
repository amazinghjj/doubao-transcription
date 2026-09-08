# 文件用途：读取和原子保存本地配置，校验字段并提供页面配置回填数据。
"""Portable local configuration for the authenticated loopback settings UI."""
import json
import os
import tempfile
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get('ASR_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'data'))).expanduser().resolve()
CONFIG_PATH = DATA_DIR / 'config.json'
LOCK = threading.RLock()
FIELDS = ('key', 'ak', 'sk', 'bucket', 'region')

class SettingsError(Exception):
    pass

def load():
    with LOCK:
        try:
            if not CONFIG_PATH.exists():
                return {}
            value = json.loads(CONFIG_PATH.read_text('utf-8'))
            if not isinstance(value, dict) or any(not isinstance(v, str) for k, v in value.items() if k in FIELDS):
                raise ValueError('Invalid configuration')
            return {k: v for k, v in value.items() if k in FIELDS}
        except (OSError, ValueError):
            raise SettingsError('无法读取本地配置，请检查 data/config.json 的格式和读取权限。') from None

def save(changes):
    if not isinstance(changes, dict):
        raise SettingsError('配置内容格式不正确。')
    with LOCK:
        old = load()
        new = dict(old)
        for k in FIELDS:
            v = changes.get(k)
            if v is not None and not isinstance(v, str):
                raise SettingsError('配置内容格式不正确。')
            if isinstance(v, str) and v.strip():
                if len(v)>1024 or '\r' in v or '\n' in v:
                    raise SettingsError('配置内容格式不正确，请重新填写。')
                new[k] = v.strip()
        if new == old:
            return new
        temp = None
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(prefix='.config-', suffix='.tmp', dir=CONFIG_PATH.parent)
            temp = Path(name)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                os.fchmod(f.fileno(), 0o600)
                json.dump(new, f, ensure_ascii=False, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, CONFIG_PATH)
            return new
        except OSError:
            raise SettingsError('配置保存失败，请检查本地数据目录的写入权限和磁盘空间。') from None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

def public(value):
    return {'has_key':bool(value.get('key')), 'has_ak':bool(value.get('ak')), 'has_sk':bool(value.get('sk')), 'bucket':value.get('bucket',''), 'region':value.get('region','cn-beijing'), 'key':value.get('key',''), 'ak':value.get('ak',''), 'sk':value.get('sk','')}

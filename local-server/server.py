import os, re, secrets, tempfile, subprocess, uuid, shutil
from pathlib import Path
from urllib.parse import urlsplit
import requests
import tos
import history
import settings
from flask import Flask, request, jsonify, send_from_directory, abort

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)
BASE = 'https://openspeech.bytedance.com/api/v3/auc/bigmodel'
PORT = int(os.getenv('ASR_PORT', '8765'))

@app.before_request
def protect():
    if request.host not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
        abort(403)
    if request.method == 'POST':
        if request.headers.get('X-Local-Token') != TOKEN:
            abort(403)
        origin = request.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            abort(403)

@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.errorhandler(413)
def too_large(e):
    return jsonify(error='文件过大，请使用小于 500 MB 的录音。'), 413

@app.get('/api/session')
def session():
    return jsonify(token=TOKEN, app='local-asr')

@app.post('/api/upload')
def upload():
    f = request.files.get('file')
    c = dict(request.form)
    c = settings.save(c)
    if not f or not all(c.get(k, '').strip() for k in ('ak', 'sk', 'bucket', 'region')):
        return jsonify(error='请选择文件，并填写完整的 TOS 配置。'), 400
    region = c['region'].strip()
    bucket = c['bucket'].strip()
    if not re.fullmatch(r'[a-z]{2}-[a-z]+(?:-\d+)?', region) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
        return jsonify(error='地域或存储桶名称格式不正确。'), 400
    ext = Path(f.filename or '').suffix.lower()
    if ext not in ('.mp3', '.wav', '.ogg', '.m4a', '.aac'):
        return jsonify(error='支持 MP3、WAV、OGG、M4A、AAC 文件。'), 400
    try:
        with tempfile.TemporaryDirectory(prefix='local-asr-') as d:
            source = Path(d) / ('audio' + ext)
            f.save(source)
            if source.stat().st_size == 0:
                return jsonify(error='音频文件为空。'), 400
            if ext in ('.m4a', '.aac'):
                target = Path(d) / 'audio.wav'
                try:
                    ffmpeg = shutil.which('ffmpeg')
                    if not ffmpeg:
                        return jsonify(error='转换 M4A / AAC 需要安装 FFmpeg 并加入 PATH，或先转为 MP3 / WAV 上传。'), 400
                    cmd = [ffmpeg, '-nostdin', '-v', 'error', '-i', str(source), '-vn', '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(target)]
                    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
                except (OSError, subprocess.SubprocessError):
                    return jsonify(error='音频转换失败，请先将录音导出为 MP3 或 WAV。'), 400
                source, ext = target, '.wav'
            if source.stat().st_size >= 500 * 1024 * 1024:
                return jsonify(error='转换后的文件超过 500 MB，请分段或使用 MP3。'), 400
            client = tos.TosClientV2(c['ak'].strip(), c['sk'].strip(), 'https://tos-' + region + '.volces.com', region)
            key = 'local-asr/' + str(uuid.uuid4()) + ext
            with source.open('rb') as content:
                client.put_object(bucket, key, content=content, acl=tos.ACLType.ACL_Private)
            signed = client.pre_signed_url(tos.HttpMethodType.Http_Method_Get, bucket, key, expires=86400)
            return jsonify(url=signed.signed_url, format=ext[1:], object=key)
    except Exception:
        # SDK exceptions can contain signed URLs; never return or log their text.
        return jsonify(error='TOS 上传失败：请检查网络、地域、存储桶及 AK/SK 的上传和读取权限。若上传已完成，文件会保留在 local-asr/ 目录。'), 502

def call_asr(action, data, task_id, body):
    key = (data.get('key') or settings.load().get('key', '')).strip()
    if not key or len(key) > 512 or '\n' in key or '\r' in key:
        return jsonify(error='请填写有效的豆包语音 API Key。'), 400
    headers = {'X-Api-Key': key, 'X-Api-Resource-Id': 'volc.seedasr.auc', 'X-Api-Request-Id': task_id}
    if action == 'submit':
        headers['X-Api-Sequence'] = '-1'
    try:
        r = requests.post(BASE + '/' + action, headers=headers, json=body, timeout=(10, 60), allow_redirects=False)
        code = r.headers.get('X-Api-Status-Code', '')
        logid = r.headers.get('X-Tt-Logid', '')
        if code in ('20000001', '20000002') and action == 'query':
            history.update(task_id, state='queued' if code == '20000002' else 'running')
            return jsonify(id=task_id, state='queued' if code == '20000002' else 'running')
        if r.ok and code == '20000000':
            if action == 'submit':
                history.update(task_id, state='submitted')
                return jsonify(id=task_id, state='submitted')
            result = r.json()
            previous = history.read(task_id) or {}
            history.update(task_id, state='done', result=result, text=previous['text'] if previous.get('result') else result.get('result', {}).get('text', ''))
            return jsonify(id=task_id, state='done', data=result)
        messages = {'20000003': '没有检测到人声。', '45000001': '参数不正确或任务重复，请检查音频直链和格式。', '45000002': '音频为空。', '45000151': '音频格式不正确。', '45000132': '音频超过大小限制。', '55000031': '服务繁忙，请稍后继续查询。'}
        msg = messages.get(code, '调用失败，请检查 API Key、2.0 服务开通状态、余额和音频链接。')
        history.update(task_id, state='interrupted')
        return jsonify(error=msg, code=code or str(r.status_code), logid=logid, id=task_id), 502
    except (requests.RequestException, ValueError):
        history.update(task_id, state='interrupted')
        return jsonify(error='网络连接中断或返回异常。请使用当前任务编号继续查询，避免重复提交。', id=task_id), 502

@app.post('/api/submit')
def submit():
    d = request.get_json(silent=True) or {}
    task_id = d.get('id', '')
    try:
        uuid.UUID(task_id)
    except (ValueError, TypeError):
        return jsonify(error='任务编号无效。'), 400
    url = d.get('url', '')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
        return jsonify(error='请填写 HTTP 或 HTTPS 音频直链。'), 400
    if d.get('format') not in ('mp3', 'wav', 'ogg'):
        return jsonify(error='请选择正确的音频格式。'), 400
    body = {'user': {'uid': 'local-asr'}, 'audio': {'url': url, 'format': d['format']}, 'request': {'model_name': 'bigmodel', 'enable_itn': True, 'enable_punc': True, 'enable_ddc': d.get('smooth') is True, 'enable_speaker_info': d.get('speaker') is True, 'show_utterances': True}}
    if not history.read(task_id):
        history.update(task_id, name=str(d.get('name') or '链接录音')[:240], state='submitting')
    if d.get('key'): settings.save({'key':d['key']})
    return call_asr('submit', d, task_id, body)

@app.post('/api/query')
def query():
    d = request.get_json(silent=True) or {}
    try:
        uuid.UUID(d.get('id', ''))
    except (ValueError, TypeError):
        return jsonify(error='任务编号无效。'), 400
    if d.get('key'): settings.save({'key':d['key']})
    return call_asr('query', d, d['id'], {})

@app.errorhandler(settings.SettingsError)
def settings_error(e):
    return jsonify(error=str(e)), 400

@app.post('/api/settings/read')
def settings_read():
    return jsonify(settings.public(settings.load()))

@app.post('/api/settings/save')
def settings_save():
    d = request.get_json(silent=True) or {}
    return jsonify(settings.public(settings.save(d)))

@app.post('/api/history/list')
def history_list():
    return jsonify(items=history.listing())

@app.post('/api/history/read')
def history_read():
    d = request.get_json(silent=True) or {}
    try:
        record = history.read(d.get('id', ''))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='任务编号无效。'), 400
    if record is None:
        return jsonify(error='找不到这条历史记录。'), 404
    return jsonify(record=record)

@app.post('/api/history/edit')
def history_edit():
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get('text'), str) or len(d['text']) > 5000000:
        return jsonify(error='文字格式不正确或超过长度限制。'), 400
    try:
        record = history.read(d.get('id', ''))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='任务编号无效。'), 400
    if not record or not record.get('result'):
        return jsonify(error='该记录尚无识别结果。'), 400
    return jsonify(record=history.update(d['id'], text=d['text']))

@app.errorhandler(OSError)
def storage_error(e):
    return jsonify(error='本机历史记录保存失败，请检查磁盘空间及文件夹权限；保留任务编号后可继续查询。'), 500

@app.get('/')
def index():
    return send_from_directory(ROOT / 'dist/client', 'index.html')

@app.get('/<path:path>')
def assets(path):
    return send_from_directory(ROOT / 'dist/client', path)

if __name__ == '__main__':
    print(f'录音转文字：http://127.0.0.1:{PORT}', flush=True)
    if os.getenv('ASR_OPEN_BROWSER') == '1':
        import threading, webbrowser, socket
        probe = socket.socket()
        if probe.connect_ex(('127.0.0.1', PORT)) == 0:
            probe.close()
            try:
                local = requests.Session()
                local.trust_env = False
                if local.get(f'http://127.0.0.1:{PORT}/api/session', timeout=2).json().get('app') == 'local-asr':
                    webbrowser.open(f'http://127.0.0.1:{PORT}')
                    raise SystemExit(0)
            except requests.RequestException:
                pass
            print('端口已被其他程序使用，请关闭该程序后重试。')
            raise SystemExit(1)
        probe.close()
        threading.Timer(1.0, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)

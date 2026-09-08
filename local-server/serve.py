# 文件用途：使用单进程多线程 WSGI 服务运行容器，保持请求令牌和文件锁在同一进程。
from waitress import serve
from server import app, HOST, PORT

if __name__ == '__main__':
    print(f'录音转文字服务已启动：{HOST}:{PORT}，支持本机及局域网 IPv4 访问。', flush=True)
    serve(
        app,
        host=HOST,
        port=PORT,
        threads=4,
        max_request_body_size=app.config['MAX_CONTENT_LENGTH'],
        channel_timeout=600,
        clear_untrusted_proxy_headers=True,
    )

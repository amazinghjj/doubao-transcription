# 文件用途：分阶段构建网页及 Python 依赖，生成包含 FFmpeg 的精简运行镜像。
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app ./app
COPY components ./components
COPY lib ./lib
COPY public ./public
COPY next.config.ts vite.config.ts tsconfig.json ./
RUN npm run build

FROM python:3.12-alpine3.22 AS python-deps
WORKDIR /build
RUN apk add --no-cache build-base
COPY local-server/requirements*.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements-container.txt

FROM python:3.12-alpine3.22 AS audio-build
WORKDIR /build
RUN apk add --no-cache build-base curl xz
# 固定官方源码版本及校验和，只编译 M4A/AAC 解码和 WAV 输出所需模块。
RUN curl -fsSL --retry 3 https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz -o ffmpeg.tar.xz \
    && echo "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c  ffmpeg.tar.xz" | sha256sum -c - \
    && tar -xJf ffmpeg.tar.xz --strip-components=1 \
    && ./configure --prefix=/opt/ffmpeg \
       --disable-everything --disable-autodetect --disable-network \
       --disable-doc --disable-debug --disable-x86asm --enable-small \
       --disable-ffplay --disable-ffprobe --enable-ffmpeg \
       --enable-protocol=file,pipe --enable-demuxer=mov,aac,wav \
       --enable-parser=aac --enable-decoder=aac,alac,pcm_s16le \
       --enable-encoder=pcm_s16le --enable-muxer=wav \
       --enable-filter=aresample,aformat,anull --extra-ldflags=-static \
    && make -j2 \
    && make install

FROM python:3.12-alpine3.22 AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASR_HOST=0.0.0.0 \
    ASR_PORT=8765 \
    ASR_DATA_DIR=/app/data
WORKDIR /app
RUN addgroup -g 10001 app \
    && adduser -D -H -u 10001 -G app app \
    && mkdir /app/data \
    && chown app:app /app/data \
    && chmod 700 /app/data
COPY --from=python-deps /opt/venv /opt/venv
COPY --from=audio-build /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=audio-build /build/COPYING.LGPLv2.1 /usr/share/licenses/ffmpeg/COPYING.LGPLv2.1
COPY --from=frontend /build/dist/client ./dist/client
COPY local-server/*.py ./local-server/
USER 10001:10001
EXPOSE 8765
CMD ["python", "local-server/serve.py"]

/* 文件用途：配置 Vinext 构建、样式处理、开发文件监听和本地接口代理。 */
import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig } from 'vite';
export default defineConfig({css:{postcss:{plugins:[tailwindcss()]}},plugins:[vinext()],server:{host:'127.0.0.1',watch:{usePolling:true},proxy:{'/api':'http://127.0.0.1:8765'}}});

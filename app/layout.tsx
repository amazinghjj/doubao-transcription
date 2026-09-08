import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'听写工作台 · 录音转文字',icons:{icon:'/favicon.svg'},description:'本地豆包录音文件识别 2.0 工具'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="zh-CN"><body>{children}</body></html>;}

/* 文件用途：封装从底层组件库导出文字布局方向上下文，供页面复用；组件是否实际使用取决于页面引用。 */
'use client';

export {
  DirectionProvider,
  useDirection,
} from '@base-ui/react/direction-provider';

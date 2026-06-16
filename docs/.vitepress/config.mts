import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'QQ Sticker Sync',
  description: 'QQ 表情同步插件 — KiraAI 插件文档',
  lang: 'zh-CN',
  themeConfig: {
    logo: false,
    nav: [
      { text: '指南', link: '/guide/overview' },
      { text: '配置', link: '/config/options' },
      { text: '开发', link: '/dev/architecture' },
    ],
    sidebar: {
      '/guide/': [
        { text: '概述', link: '/guide/overview' },
        { text: '安装与配置', link: '/guide/setup' },
        { text: '工作流程', link: '/guide/workflow' },
      ],
      '/config/': [
        { text: '配置选项', link: '/config/options' },
      ],
      '/dev/': [
        { text: '架构设计', link: '/dev/architecture' },
        { text: '核心流程', link: '/dev/flows' },
        { text: '自定义与扩展', link: '/dev/customization' },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/CelestNya/kira-plugin-qq-sticker-sync' },
    ],
  },
})

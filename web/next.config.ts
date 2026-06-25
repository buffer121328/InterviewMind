import type { NextConfig } from "next";

// NEXT_OUTPUT=standalone  → Docker/Node.js 部署（.next/standalone）
// 其他 / 未设置           → 静态导出（output: 'export'），用于 Cloudflare Pages 等
const isStandalone = process.env.NEXT_OUTPUT === "standalone";

const nextConfig: NextConfig = {
  output: isStandalone ? "standalone" : "export",
  reactCompiler: true,
  // 静态导出需要禁用图片优化；standalone 模式由 Next.js 内置处理
  images: {
    unoptimized: !isStandalone,
  },
};

export default nextConfig;


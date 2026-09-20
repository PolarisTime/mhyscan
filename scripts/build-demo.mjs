// 将 tauri-app/ui 打包成单文件 demo.html（内联 CSS/JS，无外部依赖）
// 用法: node scripts/build-demo.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const ui = join(root, "tauri-app", "ui");

const html = readFileSync(join(ui, "index.html"), "utf8");
const js = readFileSync(join(ui, "main.js"), "utf8");

const out = html.replace(
  /<script type="module" src="\.\/main\.js"><\/script>/,
  `<script type="module">\n${js}\n</script>`
);

const target = join(ui, "demo.html");
writeFileSync(target, out);
console.log(`demo.html 生成完成: ${target} (${(out.length / 1024).toFixed(1)} KB)`);

/**
 * Phase T1 — Cleanup: remove unused TextInput from react-native imports (v3).
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function findFiles(dir, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (["node_modules", "__tests__", ".expo"].includes(entry.name)) continue;
      findFiles(full, results);
    } else if (/\.(tsx|ts)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

let cleaned = 0;
const files = [
  ...findFiles(path.join(ROOT, "src")),
  ...findFiles(path.join(ROOT, "app")),
];

for (const filepath of files) {
  const rel = path.relative(ROOT, filepath);
  if (rel.includes("AppTextInput.tsx")) continue;

  let content = fs.readFileSync(filepath, "utf8");
  if (!/\bTextInput\b/.test(content)) continue;

  // Strip imports, comments, and strings to see if TextInput is used in code
  let stripped = content;
  // Remove import blocks
  stripped = stripped.replace(/import\s+[\s\S]*?from\s+["'][^"']+["'];?/g, "");
  // Remove single-line comments
  stripped = stripped.replace(/\/\/.*$/gm, "");
  // Remove multi-line comments
  stripped = stripped.replace(/\/\*[\s\S]*?\*\//g, "");
  // Remove string literals
  stripped = stripped.replace(/"[^"]*"|'[^']*'|`[^`]*`/g, "");
  
  if (/\bTextInput\b/.test(stripped)) {
    // Still used in code (as type ref, etc.) — keep import
    continue;
  }

  // Remove TextInput from the react-native import
  const rnImportRegex = /(import\s*\{)([\s\S]*?)(\}\s*from\s*["']react-native["'];?)/g;
  let updated = content.replace(rnImportRegex, (match, prefix, items, suffix) => {
    const parts = items.split(",").map(s => s.trim()).filter(s => s && s !== "TextInput");
    if (parts.length === 0) return "";
    return prefix + " " + parts.join(", ") + " " + suffix;
  });

  if (updated !== content) {
    fs.writeFileSync(filepath, updated);
    cleaned++;
  }
}

console.log(`Cleaned ${cleaned} files.`);

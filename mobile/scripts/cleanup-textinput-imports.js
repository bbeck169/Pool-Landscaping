/**
 * Phase T1 — Cleanup: remove unused TextInput from react-native imports.
 * 
 * Runs AFTER batch-replace-textinput.js has replaced all JSX usages.
 * Only removes TextInput from import if it's not used as a type ref.
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
  
  // Check if file still references TextInput (in import)
  if (!/\bTextInput\b/.test(content)) continue;
  
  // Check if TextInput is used outside imports (as a type ref)
  const withoutImports = content.replace(/^\s*import\s[\s\S]*?from\s+["'][^"']+["'];?\s*$/gm, "");
  const usedAsType = /\bTextInput\b/.test(withoutImports);
  
  if (usedAsType) {
    // Keep TextInput import — it's used as a type
    continue;
  }
  
  // Remove TextInput from react-native import
  // Pattern: may appear on the same line or as a standalone line in multi-line import
  let updated = content;
  
  // Handle: TextInput on its own line in multi-line import (with optional comma)
  updated = updated.replace(/^\s*TextInput,?\s*\n/gm, "");
  
  // Handle: TextInput in single-line import  
  // " TextInput," or ", TextInput," or ", TextInput " or " TextInput }"
  updated = updated.replace(
    /(import\s*\{[^}]*)(\bTextInput\b\s*,?\s*|\s*,\s*\bTextInput\b)([^}]*\}\s*from\s*["']react-native["'])/g,
    (match, before, textinput, after) => {
      let result = before + after;
      // Clean up commas
      result = result.replace(/,\s*,/g, ",");
      result = result.replace(/\{\s*,/g, "{ ");
      result = result.replace(/,\s*\}/g, " }");
      return result;
    }
  );
  
  if (updated !== content) {
    fs.writeFileSync(filepath, updated);
    cleaned++;
  }
}

console.log(`Cleaned unused TextInput imports from ${cleaned} files.`);

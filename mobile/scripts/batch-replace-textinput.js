/**
 * Phase T1 — Batch replace TextInput → AppTextInput across mobile codebase.
 *
 * For every .tsx/.ts file under src/ and app/ that contains <TextInput:
 *  1. Add `import AppTextInput from "@/src/components/ui/AppTextInput";`
 *  2. Replace `<TextInput` → `<AppTextInput` in JSX
 *  3. Keep TextInput in react-native import if used as a type ref
 *  4. Remove TextInput from react-native import if only used in JSX
 *
 * Run: node scripts/batch-replace-textinput.js
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function findFiles(dir, pattern, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "__tests__" || entry.name === ".expo") continue;
      findFiles(full, pattern, results);
    } else if (pattern.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

// Skip the wrapper file itself and test files
const SKIP = [
  "src/components/ui/AppTextInput.tsx",
];

let changed = 0;
let skipped = 0;

const files = [
  ...findFiles(path.join(ROOT, "src"), /\.(tsx|ts)$/),
  ...findFiles(path.join(ROOT, "app"), /\.(tsx|ts)$/),
];

for (const filepath of files) {
  const rel = path.relative(ROOT, filepath);
  if (SKIP.some((s) => rel.includes(s))) continue;

  let content = fs.readFileSync(filepath, "utf8");
  if (!content.includes("<TextInput")) continue;

  // 1) Replace <TextInput in JSX → <AppTextInput
  let updated = content.replace(/<TextInput\b/g, "<AppTextInput");

  // 2) Add import if not already present
  if (!updated.includes("AppTextInput") || !updated.includes('import AppTextInput')) {
    // Find last import line to insert after
    const lines = updated.split("\n");
    let lastImportLine = -1;
    for (let i = 0; i < lines.length; i++) {
      if (/^\s*(import |} from )/.test(lines[i]) || /^\s*from\s+["']/.test(lines[i])) {
        // Check if this line or nearby lines complete an import statement
        if (lines[i].includes(" from ") || lines[i].includes("} from")) {
          lastImportLine = i;
        }
      }
    }
    // Also handle multi-line imports: find the last line that contains `from "` or `from '`
    for (let i = 0; i < lines.length; i++) {
      if (/from\s+["']/.test(lines[i]) && /;\s*$/.test(lines[i].trim())) {
        lastImportLine = i;
      } else if (/from\s+["']/.test(lines[i])) {
        lastImportLine = i;
      }
    }

    if (lastImportLine >= 0) {
      lines.splice(lastImportLine + 1, 0, 'import AppTextInput from "@/src/components/ui/AppTextInput";');
      updated = lines.join("\n");
    }
  }

  // 3) Check if TextInput is still needed in the react-native import (type refs)
  //    Count non-import, non-JSX occurrences of bare TextInput
  const withoutImportsAndJSX = updated
    .replace(/import\s[\s\S]*?from\s+["'][^"']+["'];?/g, "")  // remove imports
    .replace(/<AppTextInput\b/g, "");  // remove JSX usages (already renamed)

  const stillUsesTextInputType = /\bTextInput\b/.test(withoutImportsAndJSX);

  if (!stillUsesTextInputType) {
    // Remove TextInput from react-native import
    // Handle both single-line and multi-line imports
    // Single-line: import { View, Text, TextInput } from "react-native";
    updated = updated.replace(
      /(import\s*\{[^}]*)\bTextInput\b,?\s*([^}]*\}\s*from\s*["']react-native["'])/g,
      (match, before, after) => {
        let result = before + after;
        // Clean up double commas or trailing commas before }
        result = result.replace(/,\s*,/g, ",");
        result = result.replace(/,\s*\}/g, " }");
        result = result.replace(/\{\s*,/g, "{ ");
        return result;
      }
    );

    // Also handle multi-line where TextInput is on its own line
    updated = updated.replace(/^\s*TextInput,?\s*\n/gm, "");
  }

  if (updated !== content) {
    fs.writeFileSync(filepath, updated);
    changed++;
    console.log(`✓ ${rel}`);
  } else {
    skipped++;
  }
}

console.log(`\nDone: ${changed} files updated, ${skipped} files skipped.`);

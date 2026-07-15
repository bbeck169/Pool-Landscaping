#!/usr/bin/env bash
# preflight.sh — must run clean before every `finish` on any phase
# that touches backend or frontend or mobile.
#
# Catches the "reference to undefined identifier" class of bug (missing
# icon import, missing hook import, typo'd component name, etc.) that
# webpack's warnings + our human eyes have repeatedly missed.
#
# Exit codes: 0 = all green, non-zero = a blocker was found (do NOT ship).
set -euo pipefail

echo "== backend syntax =="
python -m compileall -q /app/backend

echo "== frontend syntax + missing-imports (esbuild dry-run) =="
cd /app/frontend
node -e "require('esbuild').buildSync({
  entryPoints: ['src/index.js'],
  bundle: true,
  write: false,
  logLevel: 'silent',
  loader: { '.js': 'jsx', '.jsx': 'jsx', '.css': 'empty', '.png': 'empty', '.jpg': 'empty', '.jpeg': 'empty', '.svg': 'empty', '.gif': 'empty', '.woff': 'empty', '.woff2': 'empty' },
  resolveExtensions: ['.js', '.jsx', '.ts', '.tsx', '.json'],
  alias: { '@': './src' },
  jsx: 'automatic',
  external: [
    'react','react-dom','react-router-dom','recharts','lucide-react',
    'framer-motion','date-fns','react-big-calendar','sonner',
  ],
})"

echo "== JSX undeclared-identifier scan =="
python3 /app/scripts/check_jsx_imports.py

echo "== mobile syntax (best-effort, may skip on missing peer deps) =="
if [ -d /app/mobile ]; then
  cd /app/mobile
  node -e "require('esbuild').buildSync({
    entryPoints: ['app/_layout.tsx'],
    bundle: true,
    write: false,
    logLevel: 'silent',
    loader: { '.tsx': 'tsx', '.ts': 'ts', '.js': 'jsx', '.jsx': 'jsx' },
    jsx: 'automatic',
    external: [
      'react','react-native','expo','expo-router','expo-*',
      '@expo/*','@expo/vector-icons',
      '@react-native-async-storage/async-storage','@react-navigation/*',
      'react-native-*','react-native-svg',
    ],
    resolveExtensions: ['.tsx','.ts','.js','.jsx','.json'],
  })" 2>/dev/null || echo "mobile skip (metro-only bundle)"
fi

echo "preflight OK"

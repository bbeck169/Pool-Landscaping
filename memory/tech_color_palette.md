# Canonical Technician Color Palette (v1)

Shared source-of-truth for the `technician.color` FALLBACK — used when the
tech directory doesn't carry a `display_color_hex` / `color` value. Web
implements this in `frontend/src/components/maps/TeardropPin.jsx`
(`colorFromId` + `_SAFE_PALETTE`). Mobile MUST produce byte-identical
output for the same input id so LiveTech pins agree across surfaces.

Any change to the palette or hash MUST bump `version` and be
coordinated with mobile.

```json
{
  "version": 1,
  "palette": [
    "#EF4444",
    "#F97316",
    "#EAB308",
    "#22C55E",
    "#10B981",
    "#06B6D4",
    "#0EA5E9",
    "#3B82F6",
    "#6366F1",
    "#8B5CF6",
    "#EC4899",
    "#14B8A6"
  ],
  "hash_algorithm": "Java-style String.hashCode: start hash=0, for each UTF-16 code unit c of the raw input string do hash = ((hash * 31) + c) with 32-bit signed integer overflow (i.e. after each step apply |0 in JavaScript or int32 cast in other languages). Final index = Math.abs(hash) % palette.length. Absolute value of INT32_MIN must wrap to 0 (i.e. treat -2147483648 as 0 before the modulo, or equivalently do (Math.abs(hash) >>> 0) % palette.length).",
  "input_normalization": "raw — the id is passed to String() verbatim; NO trim, NO lowercase, NO Unicode normalisation. Empty string, null, and undefined all short-circuit to palette[0] before any hashing.",
  "notes": "Iterate UTF-16 code units (JavaScript charCodeAt / Java charAt). For surrogate-pair characters this hashes each half separately — matches Java. If a language iterates by Unicode code points (Python ord over string, Swift Character), pre-split into UTF-16 first (Python: for c in id.encode('utf-16-le') read pairs; Swift: id.utf16). Tie-breaker: none needed — the modulo is deterministic across all 12 buckets. Empty-input tie-breaker: palette[0] (= #EF4444)."
}
```

## Reference implementation (JavaScript)

```js
export function colorFromId(id) {
  if (!id) return "#EF4444";           // palette[0]
  const s = String(id);
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    hash = ((hash * 31) + s.charCodeAt(i)) | 0;    // int32 wrap
  }
  const idx = Math.abs(hash) % 12;
  return PALETTE[idx];
}
```

## Parity test vectors (add to any port)

| input id | expected color |
|---|---|
| `""` / `null` / `undefined` | `#EF4444` |
| `"tech-jenny"` | run the reference once and pin |
| `"tech-1"` | run the reference once and pin |
| `"u-alice"` | run the reference once and pin |

*Mobile must snapshot the same table from the reference JS impl and lock it as a unit test so a hash-regression fails loud.*

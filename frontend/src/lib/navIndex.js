/**
 * Feb-2026 · N1 · PageHeader navigable-search route index.
 *
 * Flattens the sidebar single-source-of-truth (``ADMIN_NAV_V2``
 * from ``nav/adminNav.js``) into a flat array of
 * ``{path, title, aliases}`` records the ``<PageHeader>`` search
 * uses.  Aliases come from a new optional ``aliases: [..]`` field
 * added directly to select entries in ``adminNav.js`` — see the
 * top-frequency rows (Invoices, Payments, PDF Import, Vendor
 * Bills, Check Writer, Dunning Queue, Schedule, Customers,
 * Reports Hub, AI CFO) for the shorthand map.
 *
 * Public API
 * ──────────
 *   getNavIndex()             — snapshot of every {path, title,
 *                                aliases[]} record.
 *   searchNavIndex(query, opts?) — case-insensitive matcher.
 *                                Returns up to ``limit`` (default
 *                                8) records ranked as:
 *                                  rank 0 · exact title match
 *                                  rank 1 · title prefix
 *                                  rank 2 · title substring
 *                                  rank 3 · alias match (any)
 *                                Ties broken by title A→Z.
 *
 * The index is scoped to the admin sidebar per the S1 ruling
 * (Feb-2026 · Cmd+K nav-search sub-phase).  Top-nav-only
 * shortcuts that are not also present in the sidebar
 * (Dashboard "/", Estimates "/estimates", Settings "/settings")
 * are intentionally omitted — folding them in is a separate
 * N-follow-up.
 */
import { ADMIN_NAV_V2 } from "@/nav/adminNav";


// Rank buckets — keep as bare integers so the sort key is
// unambiguous and consumers can filter on ``rank <= N``.
export const RANK_EXACT = 0;
export const RANK_PREFIX = 1;
export const RANK_SUBSTRING = 2;
export const RANK_ALIAS = 3;

const DEFAULT_LIMIT = 8;


/** Flatten every ``entries[]`` under every category into a single
 *  array of ``{path, title, aliases}``.  Skips rows without a
 *  ``to`` / ``label`` pair; every real navigable row must have
 *  both. */
export function getNavIndex() {
  const out = [];
  const seen = new Set();  // dedupe by path — legacy aliases + relocations
                            // occasionally point two labels at the same path.
  for (const group of ADMIN_NAV_V2 || []) {
    for (const entry of group?.entries || []) {
      const path = entry?.to;
      const title = entry?.label;
      if (!path || !title) continue;
      if (seen.has(path)) continue;
      seen.add(path);
      const aliases = Array.isArray(entry.aliases)
        ? entry.aliases.filter((a) => typeof a === "string" && a.length > 0)
        : [];
      out.push({ path, title, aliases });
    }
  }
  return out;
}


/** Case-insensitive scoring pass over the flattened index. */
export function searchNavIndex(query, opts = {}) {
  const limit = typeof opts.limit === "number" && opts.limit > 0
    ? opts.limit
    : DEFAULT_LIMIT;
  const q = (query || "").trim().toLowerCase();
  if (!q) return [];

  const index = opts.index || getNavIndex();

  const scored = [];
  for (const rec of index) {
    const titleLc = (rec.title || "").toLowerCase();
    let rank = null;
    if (titleLc === q) {
      rank = RANK_EXACT;
    } else if (titleLc.startsWith(q)) {
      rank = RANK_PREFIX;
    } else if (titleLc.includes(q)) {
      rank = RANK_SUBSTRING;
    } else {
      // Alias match — any alias hit falls to RANK_ALIAS.
      for (const a of rec.aliases || []) {
        const al = a.toLowerCase();
        if (al === q || al.includes(q)) {
          rank = RANK_ALIAS;
          break;
        }
      }
    }
    if (rank !== null) {
      scored.push({ ...rec, rank });
    }
  }

  scored.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return a.title.localeCompare(b.title);
  });

  return scored.slice(0, limit);
}

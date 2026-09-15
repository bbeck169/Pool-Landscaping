/**
 * Phase CHEM3 — ChemicalDropdownStack body-type filter + WaterBodyPanel adapter.
 *
 * Tests:
 *  1. Read adapter: body.chemicals_used with product_slug maps to slug for stack
 *  2. Write adapter: stack onChange slug maps back to product_slug
 *  3. Filter: spa body hides pool-only chemicals (salt, phosphate_remover)
 *  4. Filter: pool body shows salt
 *  5. No regression on non-cyanuric read/write
 */
import { CHEMICALS_CATALOG } from "../src/config/chemicalsCatalog";
import { CHEMICAL_ALLOWLIST } from "../src/lib/waterBodies";

// ── Replicate adapter logic from WaterBodyPanel ──────────────────────

function toStackFormat(chemicals_used: any[]) {
  return (chemicals_used || []).map((c: any) => ({
    ...c,
    slug: c.product_slug || c.slug,
  }));
}

function fromStackFormat(chemicals_added: any[]) {
  return chemicals_added.map((c: any) => {
    const { slug, ...rest } = c;
    return { ...rest, product_slug: slug || c.product_slug };
  });
}

// ── Replicate filter logic from ChemicalDropdownStack ────────────────

function filteredCatalog(bodyType?: string) {
  if (!bodyType) return CHEMICALS_CATALOG;
  const allowed = new Set(CHEMICAL_ALLOWLIST[bodyType] || CHEMICAL_ALLOWLIST.pool);
  return CHEMICALS_CATALOG.filter((c) => allowed.has(c.slug));
}

// ── Tests ─────────────────────────────────────────────────────────────

describe("Phase CHEM3 — ChemicalDropdownStack + WaterBodyPanel adapter", () => {

  it("read adapter maps product_slug → slug", () => {
    const input = [
      { product_slug: "cal-hypo", quantity: 2, unit: "oz" },
    ];
    const adapted = toStackFormat(input);
    expect(adapted).toHaveLength(1);
    expect(adapted[0].slug).toBe("cal-hypo");
    // original field preserved
    expect(adapted[0].product_slug).toBe("cal-hypo");
    expect(adapted[0].quantity).toBe(2);
  });

  it("write adapter maps slug → product_slug", () => {
    const stackOutput = [
      { slug: "trichlor-tabs", quantity: 3, unit: "tabs" },
    ];
    const persisted = fromStackFormat(stackOutput);
    expect(persisted).toHaveLength(1);
    expect(persisted[0].product_slug).toBe("trichlor-tabs");
    // slug stripped from persisted object
    expect(persisted[0]).not.toHaveProperty("slug");
    expect(persisted[0].quantity).toBe(3);
  });

  it("spa body filters out salt and phosphate_remover", () => {
    const spaList = filteredCatalog("spa");
    const slugs = new Set(spaList.map((c) => c.slug));
    expect(slugs.has("salt")).toBe(false);
    expect(slugs.has("phosphate_remover")).toBe(false);
  });

  it("pool body includes salt", () => {
    const poolList = filteredCatalog("pool");
    const slugs = new Set(poolList.map((c) => c.slug));
    expect(slugs.has("salt")).toBe(true);
  });

  it("filter preserves all fields on catalog entries", () => {
    const poolList = filteredCatalog("pool");
    for (const entry of poolList) {
      expect(entry).toHaveProperty("slug");
      expect(entry).toHaveProperty("name");
      expect(entry).toHaveProperty("unit");
    }
  });

  it("round-trip: product_slug survives read → write", () => {
    const original = [
      { product_slug: "muriatic-acid", quantity: 16, unit: "oz", note: "pH down" },
    ];
    const adapted = toStackFormat(original);
    const written = fromStackFormat(adapted);
    expect(written[0].product_slug).toBe("muriatic-acid");
    expect(written[0].quantity).toBe(16);
    expect(written[0].note).toBe("pH down");
  });
});

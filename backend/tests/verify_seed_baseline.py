"""Ad-hoc verification of seed baseline & 3 demo logins after teardown."""
import os, sys, requests, json

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pool-app-mobile.preview.emergentagent.com").rstrip("/")

def login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

def main():
    creds = [("admin@aquaterra.com", "password123"),
             ("mike@aquaterra.com", "password123"),
             ("customer@aquaterra.com", "password123")]
    for email, pw in creds:
        try:
            tok = login(email, pw)
            print(f"LOGIN OK: {email} -> token[{len(tok)}]")
        except Exception as e:
            print(f"LOGIN FAIL: {email}: {e}")
            sys.exit(1)

    admin_h = {"Authorization": f"Bearer {login('admin@aquaterra.com','password123')}"}

    endpoints = {
        "jobs": "/api/jobs",
        "leads": "/api/leads",
        "customers": "/api/customers",
        "forms": "/api/forms",
        "automations": "/api/automations",
        "campaigns": "/api/campaigns",
        "reviews": "/api/reviews",
        "billing-plans": "/api/billing-plans",
        "repairs": "/api/repairs",
    }

    baseline = {"jobs":5,"leads":3,"customers":4,"forms":2,"automations":3,
                "campaigns":2,"reviews":3,"billing-plans":3,"repairs":3}

    results = {}
    contaminated = {}
    for k, path in endpoints.items():
        r = requests.get(f"{BASE}{path}", headers=admin_h, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            # try common wrapping keys
            for wrap_k in ["items","results","data",k]:
                if wrap_k in data and isinstance(data[wrap_k], list):
                    data = data[wrap_k]; break
        assert isinstance(data, list), f"{path} not list: {type(data)}"
        results[k] = len(data)
        # Detect any TEST_ residue and 'X Request' titled jobs
        residue = []
        for item in data:
            for field in ("title","name","subject","customer_name","text","equipment","issue","service","email"):
                val = item.get(field) if isinstance(item, dict) else None
                if isinstance(val, str):
                    if val.startswith("TEST_"):
                        residue.append({field: val, "id": item.get("id")})
                        break
                    if k == "jobs" and field == "title" and val.strip().endswith(" Request"):
                        # e.g., "Green Pool Request" auto-generated titles
                        residue.append({field: val, "id": item.get("id")})
                        break
                    if k == "customers" and field == "email" and val.endswith("@example.com"):
                        residue.append({field: val, "id": item.get("id")})
                        break
        if residue:
            contaminated[k] = residue

    print("\nSEED COUNTS (actual vs expected):")
    ok = True
    for k, exp in baseline.items():
        act = results.get(k, "MISSING")
        marker = "OK" if act == exp else ("ACCEPT" if isinstance(act,int) and abs(act-exp) <= 1 else "DIFF")
        if marker == "DIFF": ok = False
        print(f"  {k}: actual={act}  expected={exp}  [{marker}]")

    # Verify no billing_plan_id invoices remain
    inv_r = requests.get(f"{BASE}/api/quotes?type=invoice", headers=admin_h, timeout=15)
    inv_r.raise_for_status()
    invs = inv_r.json()
    if isinstance(invs, dict):
        for wk in ("items","results","data","quotes"):
            if wk in invs and isinstance(invs[wk], list): invs = invs[wk]; break
    bp_invs = [i for i in invs if isinstance(i,dict) and i.get("billing_plan_id")]
    print(f"\nINVOICES with billing_plan_id (should be 0): {len(bp_invs)}")

    # Verify @example.com users are gone
    if contaminated:
        print("\nRESIDUE FOUND:")
        for k,v in contaminated.items():
            print(f"  {k}: {v[:5]}  (total {len(v)})")
    else:
        print("\nNO TEST_ RESIDUE FOUND in any monitored collection.")

    # Verify specific seed presence
    seed_reviews_expected = {"Jennifer Carson","Robert Sterling","Maria Rodriguez"}
    r_r = requests.get(f"{BASE}/api/reviews", headers=admin_h, timeout=15).json()
    if isinstance(r_r, dict):
        for wk in ("items","reviews","data"):
            if wk in r_r and isinstance(r_r[wk], list): r_r = r_r[wk]; break
    r_names = {x.get("customer_name") for x in r_r if isinstance(x, dict)}
    seed_reviews_present = seed_reviews_expected.issubset(r_names)
    print(f"Seed reviews present (Jennifer/Robert/Maria): {seed_reviews_present}  actual_names={sorted(r_names)}")

    seed_leads_expected = {"Tom Harker","Diana Cruz","Kevin Lee"}
    l_r = requests.get(f"{BASE}/api/leads", headers=admin_h, timeout=15).json()
    if isinstance(l_r, dict):
        for wk in ("items","leads","data"):
            if wk in l_r and isinstance(l_r[wk], list): l_r = l_r[wk]; break
    l_names = {x.get("name") for x in l_r if isinstance(x, dict)}
    seed_leads_present = seed_leads_expected.issubset(l_names)
    print(f"Seed leads present (Tom/Diana/Kevin): {seed_leads_present}  actual_names={sorted(l_names)}")

    print("\nOK" if (ok and not contaminated and not bp_invs and seed_reviews_present and seed_leads_present) else "\nDISCREPANCY")

if __name__ == "__main__":
    main()

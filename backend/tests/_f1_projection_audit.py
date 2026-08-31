"""Static audit: every is_tech_authorized_on_job call site must be fed a
job doc whose projection includes crew_id (else crew membership silently
fails closed → 403).
"""
import re, pathlib

FILES = ["routers/jobs.py", "routers/workstream_job_detail.py",
         "routers/job_media_line_items.py", "routers/maintenance.py",
         "routers/service_reports.py"]

for f in FILES:
    src = pathlib.Path("/app/backend", f).read_text().splitlines()
    for i, line in enumerate(src):
        if "is_tech_authorized_on_job(" in line and "import" not in line and "``" not in line:
            # walk backwards to nearest db.jobs.find_one(
            start = max(0, i - 60)
            window = "\n".join(src[start:i])
            m = list(re.finditer(r"db\.jobs\.find_one\(", window))
            if not m:
                print(f"{f}:{i+1}  [no local find_one in 60 lines]")
                continue
            seg = window[m[-1].start():]
            has_proj = '"_id": 0' in seg or "'_id': 0" in seg
            has_crew = "crew_id" in seg
            if has_proj and not has_crew and '{"_id": 0}' not in seg:
                print(f"!! {f}:{i+1}  projection MISSING crew_id -> {seg[:200]!r}")

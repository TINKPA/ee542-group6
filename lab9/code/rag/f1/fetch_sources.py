#!/usr/bin/env python3
"""EE542 Lab 9 Part 4: collect the F-1 / OPT / CPT knowledge base.

  python f1/fetch_sources.py              # fetch everything not fetched yet
  python f1/fetch_sources.py --refresh    # fetch again (pages change; the manifest keeps dates)

Curation rule: official sources only, F-1 students only (no J-1, scholars or
M-1 pages), so the corpus has one consistent view - the government's rules
plus USC's own procedures for applying them:

  eCFR      8 CFR 214.2(f), the F-1 regulation itself (cut out of section 214.2)
  USCIS     OPT / STEM OPT / cap-gap pages and the Form I-765 instructions
  SEVP      Study in the States (DHS): STEM OPT Hub and student pages
  ICE       SEVP practical-training page
  USC OIS   USC Office of International Services F-1 pages

Output: data/f1/raw/<id>.<ext> plus data/f1/manifest.json (id, title, agency,
url, fetched_at, sha256, bytes). The raw pages are not redistributed (the data
folder is git-ignored); the manifest lets anyone rebuild the corpus.
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent.parent / "data" / "f1"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
SITS = "https://studyinthestates.dhs.gov"
OIS = "https://ois.usc.edu"
USCIS_SEV = "https://www.uscis.gov/working-in-the-united-states/students-and-exchange-visitors"

# (id, agency, title, url)
SOURCES = [
    ("ecfr_8cfr214_2f", "eCFR", "8 CFR 214.2(f) - F-1 students (regulation text)", "ecfr:8:214.2:f"),
    # USCIS
    ("uscis_opt", "USCIS", "Optional Practical Training (OPT) for F-1 Students", f"{USCIS_SEV}/optional-practical-training-opt-for-f-1-students"),
    ("uscis_stem_opt", "USCIS", "OPT Extension for STEM Students (STEM OPT)", f"{USCIS_SEV}/optional-practical-training-extension-for-stem-students-stem-opt"),
    ("uscis_students_employment", "USCIS", "Students and Employment", f"{USCIS_SEV}/students-and-employment"),
    # (USCIS's own cap-gap page 404s as of 2026-10-19; SEVP and USC OIS cover cap-gap.)
    ("uscis_i765_instructions", "USCIS", "Form I-765 Instructions (Application for Employment Authorization)",
     "https://www.uscis.gov/sites/default/files/document/forms/i-765instr.pdf"),
    # SEVP / Study in the States
    ("sevp_stem_overview", "SEVP", "STEM OPT Extension Overview", f"{SITS}/stem-opt-hub/stem-opt-extension-overview"),
    ("sevp_stem_faq", "SEVP", "STEM OPT Frequently Asked Questions", f"{SITS}/stem-opt-hub/stem-opt-frequently-asked-questions"),
    ("sevp_stem_eligibility", "SEVP", "Students: Determining STEM OPT Extension Eligibility", f"{SITS}/stem-opt-hub/students-determining-stem-opt-extension-eligibility"),
    ("sevp_stem_reporting", "SEVP", "Students: STEM OPT Reporting Requirements", f"{SITS}/stem-opt-hub/students-stem-opt-reporting-requirements"),
    ("sevp_stem_cip", "SEVP", "Eligible CIP Codes for the STEM OPT Extension", f"{SITS}/stem-opt-hub/eligible-cip-codes-for-the-stem-opt-extension"),
    ("sevp_i983", "SEVP", "Students and the Form I-983", f"{SITS}/students/students-and-the-form-i-983"),
    ("sevp_i983_overview", "SEVP", "Form I-983 Overview", f"{SITS}/students/form-i-983-overview"),
    ("sevp_working", "SEVP", "Working in the United States (F and M students)", f"{SITS}/students/work/working-in-the-united-states"),
    ("sevp_applying_pt", "SEVP", "Applying for Practical Training", f"{SITS}/students/work/applying-for-practical-training"),
    ("sevp_training", "SEVP", "Training Opportunities in the United States", f"{SITS}/students/training-opportunities-in-the-united-states"),
    ("sevp_cap_gap", "SEVP", "H-1B Status and the Cap-Gap Extension", f"{SITS}/students/h-1b-status-and-the-cap-gap-extension"),
    ("sevp_ssn", "SEVP", "Obtaining a Social Security Number", f"{SITS}/students/work/obtaining-a-social-security-number"),
    ("sevp_everify", "SEVP", "Understanding E-Verify", f"{SITS}/students/work/understanding-e-verify"),
    ("sevp_maintaining", "SEVP", "Maintaining Status", f"{SITS}/students/maintaining-status"),
    ("sevp_full_course", "SEVP", "Full Course of Study", f"{SITS}/students/study/full-course-of-study"),
    ("sevp_travel", "SEVP", "Traveling as an F or M Student", f"{SITS}/students/study/traveling-as-an-f-or-m-student"),
    ("sevp_transfer", "SEVP", "Transferring to Another School", f"{SITS}/students/study/transferring-to-another-school"),
    ("sevp_transfer_f1", "SEVP", "Instructions for Transferring to Another School as an F-1 Student",
     f"{SITS}/students/study/instructions-for-transferring-to-another-school-as-an-f-1-student"),
    ("sevp_change_status", "SEVP", "Change of Status", f"{SITS}/students/change-of-status"),
    ("sevp_i20", "SEVP", "Students and the Form I-20", f"{SITS}/students/prepare/students-and-the-form-i-20"),
    ("sevp_i901", "SEVP", "Paying the I-901 SEVIS Fee", f"{SITS}/students/prepare/paying-the-i-901-sevis-fee"),
    ("sevp_lifecycle", "SEVP", "International Student Life Cycle", f"{SITS}/students/international-student-life-cycle"),
    ("sevp_emergency", "SEVP", "Maintain F and M Status in Emergency Events", f"{SITS}/students/study/maintain-f-and-m-status-in-emergency-events"),
    ("sevp_i515a", "SEVP", "Form I-515A Overview", f"{SITS}/students/travel/form-i-515a-overview"),
    ("sevp_secondary", "SEVP", "What Is Secondary Inspection?", f"{SITS}/students/travel/what-is-secondary-inspection"),
    # ICE
    ("ice_practical_training", "ICE", "SEVP Practical Training", "https://www.ice.gov/sevis/practical-training"),
    # USC Office of International Services
    ("usc_f1_employment", "USC OIS", "F-1 Student Employment", f"{OIS}/employment/f1-student-employment/"),
    ("usc_on_campus", "USC OIS", "On-Campus Employment", f"{OIS}/employment/on-campus-employment/"),
    ("usc_offsite", "USC OIS", "Offsite (Non-USC) Employment", f"{OIS}/employment/offsite-non-usc-employment/"),
    ("usc_other_employment", "USC OIS", "Additional Forms of Employment", f"{OIS}/employment/additional-forms-of-employment/"),
    ("usc_cpt", "USC OIS", "Curricular Practical Training (CPT)", f"{OIS}/employment/curricular-practical-training-cpt/"),
    ("usc_opt", "USC OIS", "Optional Practical Training (OPT)", f"{OIS}/employment/optional-practical-training-opt/"),
    ("usc_pre_opt", "USC OIS", "Pre-Completion OPT", f"{OIS}/employment/pre-completion-opt/"),
    ("usc_post_opt", "USC OIS", "Post-Completion OPT", f"{OIS}/employment/post-completion-opt/"),
    ("usc_stem_opt", "USC OIS", "STEM OPT Extension", f"{OIS}/employment/stem-opt-extension/"),
    ("usc_stem_prior", "USC OIS", "STEM OPT Extension Based on a Prior Degree", f"{OIS}/employment/stem-opt-extension-prior-degree/"),
    ("usc_cap_gap", "USC OIS", "Cap-Gap Extension", f"{OIS}/employment/cap-gap-extension/"),
    ("usc_maintaining", "USC OIS", "Guidelines for Maintaining Status", f"{OIS}/maintaining-status/guidelines-maintaining-status/"),
    ("usc_rcl", "USC OIS", "Reduced Course Load", f"{OIS}/maintaining-status/reduced-course-load/"),
    ("usc_loa", "USC OIS", "Leave of Absence", f"{OIS}/maintaining-status/leave-of-absence/"),
    ("usc_extend", "USC OIS", "Extending Your Program (Students)", f"{OIS}/maintaining-status/extending-program-students/"),
    ("usc_completion", "USC OIS", "Program Completion (Students)", f"{OIS}/maintaining-status/program-completion-students/"),
    ("usc_other_school", "USC OIS", "Attending Another Institution", f"{OIS}/maintaining-status/attending-another-institution/"),
    ("usc_change_status", "USC OIS", "Change of Status to F-1", f"{OIS}/maintaining-status/change-of-status-f1/"),
    ("usc_progressive", "USC OIS", "Progressive Degree Program", f"{OIS}/maintaining-status/progressive-degree-program/"),
    ("usc_reentry", "USC OIS", "Requirements for Reentry", f"{OIS}/travel/requirements-for-reentry/"),
    ("usc_entering", "USC OIS", "Entering the United States", f"{OIS}/travel/entering-united-states/"),
    ("usc_renew_visa", "USC OIS", "Renewing Your Passport or F-1/J-1 Visa", f"{OIS}/travel/renewing-passport-f1-j1-visa/"),
    ("usc_auto_reval", "USC OIS", "Automatic Revalidation", f"{OIS}/travel/automatic-revalidation/"),
    ("usc_visa_types", "USC OIS", "Student Visa Types", f"{OIS}/getting-started/student-visa-types/"),
    ("usc_transfer_in", "USC OIS", "Transferring to USC", f"{OIS}/getting-started/transferring-to-usc/"),
    ("usc_apply_visa", "USC OIS", "Applying for a Visa (Students)", f"{OIS}/getting-started/applying-for-visa-students/"),
    ("usc_duration_status", "USC OIS", "Duration of Status Rule Change (news)", f"{OIS}/duration-status-rule-change/"),
    ("usc_opt_fees", "USC OIS", "Update Regarding Proposed OPT Fees (news)", f"{OIS}/update-regarding-proposed-opt-fees/"),
]


def get(url: str, accept: str = "*/*") -> bytes:
    # eCFR's bulk endpoints refuse (406) any request that does not allow gzip.
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        return gzip.decompress(data) if r.headers.get("Content-Encoding") == "gzip" else data


def ecfr_paragraph(title: int, section: str, para: str) -> tuple[bytes, str]:
    """Cut one top-level paragraph, e.g. (f), out of an eCFR section, as text."""
    meta = json.loads(get("https://www.ecfr.gov/api/versioner/v1/titles.json", "application/json"))
    date = next(t["latest_issue_date"] for t in meta["titles"] if t["number"] == title)
    part = section.split(".")[0]
    xml = get(f"https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}&section={section}",
              "application/xml")
    root = ET.fromstring(xml)
    lines, inside = [], False
    nxt = f"({chr(ord(para) + 1)})"
    for el in root.iter():
        if el.tag not in ("P", "HD", "FP"):
            continue
        text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        if text.startswith(f"({para})"):
            inside = True
        elif inside and text.startswith(nxt):
            break
        if inside and text:
            lines.append(text)
    body = (f"8 CFR {section}({para}) as published in the eCFR, current as of {date}.\n"
            f"https://www.ecfr.gov/current/title-{title}/section-{section}#p-{section}({para})\n\n" + "\n".join(lines))
    return body.encode(), f"https://www.ecfr.gov/current/title-{title}/section-{section}#p-{section}({para})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    mpath = OUT / "manifest.json"
    manifest = {m["id"]: m for m in json.loads(mpath.read_text())} if mpath.exists() else {}
    for sid, agency, title, url in SOURCES:
        if sid in manifest and not a.refresh and (raw / manifest[sid]["file"]).exists():
            continue
        try:
            if url.startswith("ecfr:"):
                _, t, sec, p = url.split(":")
                data, url = ecfr_paragraph(int(t), sec, p)
                ext = "txt"
            else:
                data = get(url)
                ext = "pdf" if data[:4] == b"%PDF" else "html"
        except Exception as e:  # keep going; report at the end
            print(f"FAIL {sid}: {e}", file=sys.stderr)
            continue
        (raw / f"{sid}.{ext}").write_bytes(data)
        manifest[sid] = {"id": sid, "agency": agency, "title": title, "url": url, "file": f"{sid}.{ext}",
                         "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        print(f"ok   {sid:<26} {len(data):>8,} B  {agency}: {title}")
        time.sleep(1.0)   # be polite to the servers
    order = [s[0] for s in SOURCES]
    mpath.write_text(json.dumps([manifest[i] for i in order if i in manifest], indent=1))
    missing = [s[0] for s in SOURCES if s[0] not in manifest]
    print(f"\n{len(manifest)}/{len(SOURCES)} sources in {mpath}" + (f"; missing: {missing}" if missing else ""))


if __name__ == "__main__":
    main()

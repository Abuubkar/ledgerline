"""Turn a pytest JUnit XML file into a short Markdown summary (CI appends it to the run's summary page).

  uv run python scripts/junit_summary.py "Integration tests" build/junit.xml >> "$GITHUB_STEP_SUMMARY"
"""

import sys
import xml.etree.ElementTree as ET

title, path = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
suites = [root] if root.tag == "testsuite" else list(root)
total = sum(int(s.get("tests", 0)) for s in suites)
failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
skipped = sum(int(s.get("skipped", 0)) for s in suites)
seconds = sum(float(s.get("time", 0)) for s in suites)
print(f"### {title}\n\n{total - failed - skipped} passed, {failed} failed, {skipped} skipped in {seconds:.0f} s\n")
for case in root.iter("testcase"):
    problem = case.find("failure") if case.find("failure") is not None else case.find("error")
    if problem is not None:
        message = (problem.get("message") or "").splitlines()[0][:200] if problem.get("message") else ""
        print(f"- ❌ `{case.get('classname')}.{case.get('name')}`: {message}")

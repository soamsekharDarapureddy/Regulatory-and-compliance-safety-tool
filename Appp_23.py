import streamlit as st
import pandas as pd
import pdfplumber
import openpyxl
import re

# ============= Regulatory/Standards Knowledge (as before) ============
STANDARDS_KNOWLEDGE_BASE = {
    "IP Rating": "IEC 60529",
    "Short Circuit Protection": "AIS-156 / IEC 62133",
    "Overcharge Protection": "AIS-156 / ISO 12405-4",
    "Over-discharge Protection": "AIS-156 / ISO 12405-4",
    "Cell Balancing": "AIS-156",
    "Temperature Protection": "AIS-156 / ISO 12405-4",
    "Communication Interface (CAN)": "ISO 11898",
    "Vibration Test": "IEC 60068-2-6 / AIS-048",
    "Thermal Runaway Test": "AIS-156 Amendment 3",
    "Frame Fatigue Test": "ISO 4210-6",
    "Braking Performance Test": "EN 15194 / ISO 4210-2",
    "EMC Test": "IEC 61000 / EN 15194",
    "Salt Spray Test": "ASTM B117",
    "Efficiency Test": "EN 15194",
    "Insulation Resistance Test": "IEC 60364-6",
    "Dielectric Withstand (Hipot) Test": "IEC 60335-1"
}

ALL_STANDARD_TESTS = [k for k in STANDARDS_KNOWLEDGE_BASE.keys()]

TEST_CASE_KNOWLEDGE_BASE = {
    "ip rating": {"requirement": "Test for ingress protection against dust and water per class (e.g., IP65).", "equipment": ["Dust Chamber", "Jet Water"]},
    "short circuit": {"requirement": "Check DUT withstands short-circuit without unsafe operation.", "equipment": ["High-Current Supply", "Oscilloscope"]},
    "overcharge": {"requirement": "Verify no damage/fault with overcharge for set time.", "equipment": ["Power Supply", "Logger"]},
    "over-discharge": {"requirement": "DUT resists faults/damage under over-discharge.", "equipment": ["Load Bank", "Logger"]},
    "cell balancing": {"requirement": "Cell voltages deviation within permitted mV.", "equipment": ["Cell Logger"]},
    "temp protection": {"requirement": "Activate protection at high/low temp per spec.", "equipment": ["Thermal Chamber", "Sensors"]},
    "thermal runaway": {"requirement": "Prevent runaway propagation on cell event.", "equipment": ["Heater", "Logger"]},
    "frame fatigue": {"requirement": "Frame resists stress cycles as per ISO 4210.", "equipment": ["Fatigue Rig"]},
    "braking": {"requirement": "Braking distance per spec (wet & dry).", "equipment": ["Brake Tester", "Speed Logger"]},
    "efficiency": {"requirement": "Efficiency exceeds regulatory minimum.", "equipment": ["Power Meter", "Dyno"]},
    "salt spray": {"requirement": "Metal parts resist corrosion for standard time.", "equipment": ["Salt Spray Chamber"]},
    "emc": {"requirement": "No excessive emissions/susceptibility failures.", "equipment": ["EMI Chamber", "EMI Receiver"]}
}
for name in list(TEST_CASE_KNOWLEDGE_BASE):
    TEST_CASE_KNOWLEDGE_BASE[name + " test"] = TEST_CASE_KNOWLEDGE_BASE[name]

COMPONENT_KNOWLEDGE_BASE = {
    "bq76952": {"manufacturer": "Texas Instruments", "function": "Battery Monitor IC", "voltage": "Up to 80V", "package": "TQFP-48"},
    "irfb4110": {"manufacturer": "Infineon", "function": "N-MOSFET", "voltage": "100V", "current": "180A", "package": "TO-220AB"},
    "1n4007": {"manufacturer": "Generic", "function": "Rectifier Diode", "voltage": "1000V", "current": "1A", "package": "DO-41"},
    "crcw120610k0fkea": {"manufacturer": "Vishay", "function": "Thick Film Chip Resistor", "value": "10 kΩ", "tolerance": "±1%", "package": "1206"},
}

# ==================== Flexible Test Report Parser ====================
def extract_tests_from_text(text):
    lines = text.split('\n')
    report_tests, current = [], None
    buffer_paragraph = ""
    def flush_current():
        nonlocal current, buffer_paragraph
        if current and current["Test Name"]:
            current["Paragraph"] = buffer_paragraph.strip()
            report_tests.append(current)
        buffer_paragraph = ""
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            flush_current()
            current = None
            continue
        matched_test = None
        for stdtest in ALL_STANDARD_TESTS:
            key = stdtest.lower().replace(' ', '')
            if (key in line_strip.lower().replace(" ", "")) or (stdtest.lower() in line_strip.lower()):
                matched_test = stdtest
                break
        if matched_test:
            flush_current()
            current = {"Test Name": matched_test,
                       "Standard": STANDARDS_KNOWLEDGE_BASE.get(matched_test,"N/A"),
                       "Result": "N/A", "Expected": "N/A", "Actual": "N/A", "Paragraph": ""}
        if current:
            if "pass" in line_strip.lower() or "fail" in line_strip.lower():
                m = re.search(r"(pass|fail)", line_strip, re.I)
                if m: current["Result"] = m.group(1).upper()
            m = re.search(r"(Requirement|Expected|Limit)[:\s]+([^\n\r]+)", line_strip, re.I)
            if m: current["Expected"] = m.group(2)
            m = re.search(r"(Actual|Measured|Observed|Value|Triggered at|Cut-off at|Deviation)[:\s]+([^\n\r]+)", line_strip, re.I)
            if m: current["Actual"] = m.group(2)
            buffer_paragraph += line_strip + " "
    flush_current()
    return report_tests

def parse_report(uploaded_file):
    if not uploaded_file: return []
    try:
        if uploaded_file.type == "application/pdf":
            pd_text = ""
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    pd_text += page.extract_text() + "\n"
            return extract_tests_from_text(pd_text)
        elif uploaded_file.type in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"):
            import docx
            doc = docx.Document(uploaded_file)
            doc_text = '\n'.join([p.text for p in doc.paragraphs])
            return extract_tests_from_text(doc_text)
        elif uploaded_file.type in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"):
            df = pd.read_excel(uploaded_file)
            return df.to_dict("records")
    except Exception as e:
        st.error("Parsing error: " + str(e))
        return []

def verify_report(parsed_tests):
    return [f"Test Failed: {t['Test Name']}" for t in parsed_tests if "FAIL" in t.get("Result", "").upper()]

def generate_requirements(test_cases):
    reqs, default_info = [], {"requirement": "Generic requirement.", "equipment": ["Not specified."]}
    for i, user_input_line in enumerate(test_cases):
        matches = []
        for known_test in TEST_CASE_KNOWLEDGE_BASE:
            if known_test.replace(" test", "") in user_input_line.lower():
                matches.append(known_test)
        if matches:
            for m in matches:
                d = TEST_CASE_KNOWLEDGE_BASE[m]
                reqs.append({"Test Case": m.title(), "Requirement ID": f"REQ_{i+1:03d}", "Requirement Description": d["requirement"], "Required Equipment": ", ".join(d["equipment"])})
        else:
            reqs.append({"Test Case": user_input_line, "Requirement ID": f"REQ_{i+1:03d}", **default_info, "external_search": user_input_line})
    return reqs

# ===================== Stylish UI & Experience =====================
st.set_page_config(page_title="Regulatory Compliance & Safety Checker", layout="wide")
st.markdown("""
    <style>
    .banner {background:#0056b3;padding:1em 2em 0.7em 2em;border-radius:14px;margin-bottom:18px;}
    .banner h1 {color:#fff;font-size:2em;margin-bottom:0;}
    .banner p {color:#f2f6fa;font-size:1.15em;font-weight:500;}
    .gem-panel {background:#f0f6fa;border-radius:16px;padding:1.35em 1em 1.1em 1em;
                box-shadow:0 2px 16px #cde8fa;}
    </style>
""", unsafe_allow_html=True)

st.markdown('''
<div class="banner" style="margin-bottom:22px;">
  <h1>🛡️ E-Bike Regulatory Compliance & Safety Checking Tool 🛡️</h1>
  <p>For use by engineers, auditors, and manufacturers for end-to-end regulatory validation of any electric vehicle project. Upload reports, verify compliance, generate requirements, and track critical component safety—all visually and intuitively.</p>
</div>
''', unsafe_allow_html=True)

option = st.sidebar.radio("Select Module", (
    "🗂️ Test Report Verification", "✅ Test Requirement Generation", "🔎 Component Lookup & Database", "📊 Dashboard & Analytics"))

if option == "🗂️ Test Report Verification":
    st.markdown('<div class="gem-panel">', unsafe_allow_html=True)
    st.subheader("Step 1: Verify Official Test Report Against Regulatory Standards")
    st.info("Upload a test report (PDF, Word, Excel) from your compliance lab, supplier, or project. This page extracts safety/compliance results and checks for failures.")
    uploaded_file = st.file_uploader("Upload a test report (.pdf, .docx, .xlsx)", type=['pdf', 'docx', 'xlsx'])
    if uploaded_file:
        parsed_tests = parse_report(uploaded_file)
        if parsed_tests:
            st.subheader("Extracted Compliance & Safety Result Summary")
            for idx, t in enumerate(parsed_tests):
                result_color = "#27ae60" if 'PASS' in t.get('Result', '').upper() else "#c0392b" if 'FAIL' in t.get('Result','').upper() else "#999"
                st.markdown(
                    f"<div style='background:#fff;border-radius:9px;padding:11px 17px 5px 17px;margin-bottom:10px;border-left:8px solid {result_color};'>"
                    f"<b>Regulatory Test:</b> {t['Test Name']}<br>"
                    f"<b>Standard:</b> {t['Standard']}<br>"
                    f"<b>Result:</b> <span style='color:{result_color};font-weight:bold'>{t['Result']}</span><br>"
                    f"<b>Expected:</b> {t['Expected']}<br>"
                    f"<b>Actual:</b> {t['Actual']}<br>"
                    f"<div style='font-size:0.97em;color:#888;'>{t['Paragraph'][:350]}{'...' if len(t['Paragraph'])>350 else ''}</div></div>",
                    unsafe_allow_html=True)
        else:
            st.warning("No recognized tests found. Check your report’s format and content.")
        if parsed_tests and st.button("Run Compliance Check"):
            issues = verify_report(parsed_tests)
            if issues:
                st.error(f"❌ COMPLIANCE FAILED: {len(issues)} issues.")
                for i in issues: st.write(f"- {i}")
            else:
                st.success("✔️ COMPLIANCE PASSED: No failures detected for official standards.")
    st.markdown('</div>', unsafe_allow_html=True)

elif option == "✅ Test Requirement Generation":
    st.markdown('<div class="gem-panel">', unsafe_allow_html=True)
    st.subheader("Step 2: Generate Regulatory Requirements for Any Test")
    st.info("Enter every safety, electrical, mechanical, or regulatory compliance test you require—one per line. This tool matches any known method and gives you clear requirements. If the test is new, you get a research link.")
    default_test_cases = "\n".join([
        "IP rating", "short circuit", "frame fatigue test", "insulation resistance", "braking", "emc test"
    ])
    test_case_text = st.text_area("Enter test cases, one per line", default_test_cases, height=150)
    if st.button("Generate Requirements"):
        test_cases = [line.strip() for line in test_case_text.split('\n') if line.strip()]
        requirements = generate_requirements(test_cases)
        st.subheader("Proposed Requirements & Industry Equipment")
        for req in requirements:
            st.markdown(
                f"<div style='background:#fafdff;border-radius:9px;padding:10px 16px 8px 16px;margin-bottom:9px;border-left:6px solid #28b7b7;'>"
                f"📝 <b>Test Case:</b> {req['Test Case']}<br>"
                f"🆔 <b>Requirement ID:</b> {req['Requirement ID']}<br>"
                f"📋 <b>Description:</b> <span style='color:#393bac'>{req['Requirement Description']}</span><br>"
                f"🛠️ <b>Equipment:</b> {req['Required Equipment']}", unsafe_allow_html=True)
            if "external_search" in req:
                search = req["external_search"]
                st.markdown(
                    f'<small style="color:#888;">Test not found in internal industry database. Quick research: '
                    f'<a href="https://en.wikipedia.org/w/index.php?search={search}" target="_blank">Wikipedia</a> | '
                    f'<a href="https://www.google.com/search?q={search}+test+standard" target="_blank">Google</a></small>',
                    unsafe_allow_html=True)
            st.markdown("---")
        if requirements:
            csv = pd.DataFrame(requirements).drop(columns=["external_search"], errors='ignore').to_csv(index=False).encode('utf-8')
            st.download_button("Download Requirements (CSV)", data=csv, file_name="requirements.csv", mime="text/csv")
    st.markdown('</div>', unsafe_allow_html=True)

elif option == "🔎 Component Lookup & Database":
    st.markdown('<div class="gem-panel">', unsafe_allow_html=True)
    st.subheader("Step 3: Component Regulatory Datasheet & Spec Lookup")
    st.info("Type any IC, MOSFET, diode, or passive component part number. If not in the internal database, click a web link below to find official parameters and copy them back here.")
    part_number_to_find = st.text_input("Enter Component Part Number", help="Partial match allowed.").lower().strip()
    if st.button("Find Component Info"):
        found_info, found_key = None, None
        for key in COMPONENT_KNOWLEDGE_BASE:
            if key in part_number_to_find:
                found_key, found_info = key, COMPONENT_KNOWLEDGE_BASE[key]
                break
        if found_info:
            st.session_state.found_component = found_info
            st.session_state.found_component['part_number'] = part_number_to_find.upper()
            st.success(f"Found industry data: {found_key}")
        else:
            st.session_state.found_component = {}
            st.warning("Not in internal database. Use these links to research official datasheet/spec:")
            if part_number_to_find:
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.markdown(f"[Octopart](https://octopart.com/search?q={part_number_to_find})", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"[Digi-Key](https://www.digikey.com/en/products/result?s={part_number_to_find})", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"[Mouser](https://www.mouser.com/Search/Refine?Keyword={part_number_to_find})", unsafe_allow_html=True)
                with c4:
                    st.markdown(f"[Wikipedia](https://en.wikipedia.org/wiki/Special:Search?search={part_number_to_find})", unsafe_allow_html=True)
                st.info("Copy key parameters you find into the fields below.")
    st.markdown("---")
    st.subheader("Add or Record Key Component")
    d = st.session_state.get('found_component', {})
    with st.form("component_form", clear_on_submit=True):
        pn = st.text_input("Part Number", value=d.get("part_number", ""))
        mfg = st.text_input("Manufacturer", value=d.get("manufacturer", ""))
        func = st.text_input("Function", value=d.get("function", ""))
        p1_label = "Value" if "resistor" in func.lower() or "capacitor" in func.lower() else "Voltage"
        p1_val = d.get("value", d.get("voltage", ""))
        p1 = st.text_input(p1_label, value=p1_val)
        p2_label = "Package" if "resistor" in func.lower() or "capacitor" in func.lower() else "Current"
        p2_val = d.get("package", d.get("current", ""))
        p2 = st.text_input(p2_label, value=p2_val)
        if st.form_submit_button("Add Component"):
            if pn:
                if 'project_db' not in st.session_state: st.session_state.project_db = pd.DataFrame()
                new_row = pd.DataFrame([{
                    "Part Number": pn, "Manufacturer": mfg, "Function": func, p1_label: p1, p2_label: p2
                }])
                st.session_state.project_db = pd.concat([st.session_state.project_db, new_row], ignore_index=True)
                st.success(f"Component '{pn}' added.")
    if 'project_db' in st.session_state and not st.session_state.project_db.empty:
        st.markdown("---")
        st.subheader("Project Component Compliance Database")
        st.dataframe(st.session_state.project_db.astype(str))
    st.markdown('</div>', unsafe_allow_html=True)

else:
    st.markdown('<div class="gem-panel">', unsafe_allow_html=True)
    st.subheader("Regulatory Compliance Dashboard & Analytics")
    st.write("Compliance and safety progress at a glance.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Reports Verified", "0")
    col2.metric("Requirements Generated", "0")
    col3.metric("Components in DB", len(st.session_state.get('project_db', [])))
    st.markdown('''
    <br>
    <span style="color:#0496ff;font-size:1.1em;"><b>
      Remember: This application helps you achieve and document regulatory compliance. All analytics and reports can be exported for your audit trail.
    </b></span>
    ''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

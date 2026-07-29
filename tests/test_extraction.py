"""Sanity checks for the rule extractors against synthetic document text.

No real HK CI/BR/NNC1 samples are available in this environment (PRD 第
10.5 条 explicitly flags this), so these tests exercise the regex/keyword
logic directly against representative text drawn from the public HK
Companies Registry form wording, plus an end-to-end smoke test through the
FastAPI endpoint using generated PDFs.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import br as br_rules
from app.extraction import ci as ci_rules
from app.extraction import nnc1 as nnc1_rules
from app.extraction.merge import NNC1Source, merge
from app.extraction.normalize import normalize_date

CI_TEXT = """
CERTIFICATE OF INCORPORATION
No. 3012345
I hereby certify that
GWEN INTERNATIONAL LIMITED
is incorporated in Hong Kong under the Companies Ordinance (Chapter 622)
as a Private Company with Limited Liability, on this date of 15 March 2023.
"""

BR_TEXT = """
BUSINESS REGISTRATION CERTIFICATE
Business Registration Number: 30123456-000-01-23-1
Name of Business: GWEN INTL
Nature of Business: IMPORT AND EXPORT TRADING
Business Address: 88 QUEEN'S ROAD CENTRAL, HONG KONG
Date of Commencement: 15/03/2023
"""

NNC1_TEXT = """
FORM NNC1
INCORPORATION FORM
Registered Office:
FLAT B, 12/F, ABC BUILDING, 88 DES VOEUX ROAD CENTRAL, HONG KONG

Founder Member / Director 1
Surname or Company Name: CHAN
Forename(s): TAI MAN
Chinese Name: 陳大文
Capacity: Director
Nationality: Chinese
Usual Residential Address: ROOM 5, 10/F, XYZ MANSION, KOWLOON, HONG KONG
Identification: P1234567(HK)
Date of Birth: 01/01/1980

Surname or Company Name: WONG
Forename(s): MEI LING
Chinese Name: 黃美玲
Capacity: Director
Nationality: British
Usual Residential Address: 20 BAKER STREET, LONDON, UNITED KINGDOM
Identification: K98****
"""


def test_ci():
    r = ci_rules.extract_ci(CI_TEXT)
    assert r["name_en"]["value"] == "GWEN INTERNATIONAL LIMITED", r["name_en"]
    assert r["crn"]["value"] == "3012345", r["crn"]
    assert r["incorp_date"]["value"] == "2023-03-15", r["incorp_date"]
    print("test_ci OK", r)


def test_ci_issued_on():
    text = """
    CERTIFICATE OF INCORPORATION
    No. 3298765
    I hereby certify that
    SAMPLE TRADING LIMITED
    is incorporated in Hong Kong under the Companies Ordinance.
    Issued on 16 October 2025
    """
    r = ci_rules.extract_ci(text)
    assert r["incorp_date"]["value"] == "2025-10-16", r["incorp_date"]
    assert r["incorp_date"]["raw"] == "16 October 2025", r["incorp_date"]
    print("test_ci_issued_on OK", r["incorp_date"])


def test_br():
    r = br_rules.extract_br(BR_TEXT)
    assert r["trading_name"]["value"] == "GWEN INTL", r["trading_name"]
    assert r["br_number"]["value"].startswith("30123456"), r["br_number"]
    assert "QUEEN'S ROAD" in r["business_address"]["value"], r["business_address"]
    assert r["effective_date"]["value"] == "2023-03-15", r["effective_date"]
    print("test_br OK", r)


def test_br_bilingual_multiline_address():
    text = """
    BUSINESS REGISTRATION CERTIFICATE
    Business Registration Number: 65432109-000-08-24-6
    Name of Business: CLOUD NINE TRADING

    Address / 地址
    RM 509, 5/F
    THE CLOUD
    111 TUNG CHAU ST
    TAI KOK TSUI
    HONG KONG

    Nature of Business: WHOLESALE
    Date of Commencement: 01/09/2024
    """
    r = br_rules.extract_br(text)
    assert r["business_address"]["value"] == (
        "RM 509, 5/F THE CLOUD 111 TUNG CHAU ST TAI KOK TSUI HONG KONG"
    ), r["business_address"]
    print("test_br_bilingual_multiline_address OK", r["business_address"])


def test_br_official_form2_stacked_address_label():
    """Real HK Form 2 (BR certificate) layout: 地址/Address stacked on two
    lines, each on its own row, with no bilingual slash on one line."""
    text = """
    表格 2   FORM 2
    BUSINESS REGISTRATION ORDINANCE (Chapter 310)

    業務 / 法團所用名稱
    Name of Business/Corporation
    NOVAUNB LIMITED

    地 址
    Address
    RM 509, 5/F THE CLOUD 111
    TUNG CHAU ST TAI KOK TSUI
    HONG KONG

    業務性質
    Nature of Business
    CORP

    生效日期
    Date of Commencement
    16/10/2025
    """
    r = br_rules.extract_br(text)
    assert r["business_address"]["value"] == (
        "RM 509, 5/F THE CLOUD 111 TUNG CHAU ST TAI KOK TSUI HONG KONG"
    ), r["business_address"]
    assert r["business_address"]["status"] == "extracted"
    print("test_br_official_form2_stacked_address_label OK", r["business_address"])


def test_br_address_fills_both_reg_and_op_address():
    """When no NNC1/NAR1 is uploaded, the BR address should populate both
    enterprise.reg_address and enterprise.op_address, both as 'extracted'."""
    br = br_rules.extract_br(
        "Address / 地址\nRM 509, 5/F THE CLOUD 111\nTUNG CHAU ST TAI KOK TSUI\nHONG KONG\n"
        "Nature of Business: CORP"
    )
    result = merge(ci_files=[], br_files=[("BR.pdf", br)], nnc1_sources=[])
    ent = result["enterprise"]
    expected = "RM 509, 5/F THE CLOUD 111 TUNG CHAU ST TAI KOK TSUI HONG KONG"
    assert ent["reg_address"]["value"] == expected, ent["reg_address"]
    assert ent["reg_address"]["status"] == "extracted", ent["reg_address"]
    assert ent["op_address"]["value"] == expected, ent["op_address"]
    assert ent["op_address"]["status"] == "extracted", ent["op_address"]
    print("test_br_address_fills_both_reg_and_op_address OK", ent["reg_address"], ent["op_address"])


def test_nnc1():
    r = nnc1_rules.extract_nnc1(NNC1_TEXT, source="NNC1")
    assert "DES VOEUX ROAD" in r["registered_address"]["value"], r["registered_address"]
    assert len(r["directors"]) == 2, r["directors"]

    d1 = r["directors"][0]
    assert d1["surname_en"]["value"] == "CHAN", d1["surname_en"]
    assert d1["given_en"]["value"] == "TAI MAN", d1["given_en"]
    assert d1["surname_cn"]["value"] == "陳", d1["surname_cn"]
    assert d1["given_cn"]["value"] == "大文", d1["given_cn"]
    assert d1["residential_address"]["value"] == (
        "ROOM 5, 10/F, XYZ MANSION, KOWLOON, HONG KONG"
    ), d1["residential_address"]
    assert d1["id_info"]["value"] == "P1234567(HK)", d1["id_info"]
    assert d1["id_info"]["status"] == "extracted", d1["id_info"]
    assert d1["dob"]["value"] == "1980-01-01", d1["dob"]
    for removed_key in ("position", "gender", "nationality", "residing_country", "same_nationality"):
        assert removed_key not in d1, f"{removed_key} should no longer be extracted"

    d2 = r["directors"][1]
    assert d2["surname_en"]["value"] == "WONG", d2["surname_en"]
    assert d2["id_info"]["value"] == "K98****", d2["id_info"]
    assert d2["id_info"]["status"] == "masked", d2["id_info"]
    print("test_nnc1 OK", r)


def test_normalize_date_variants():
    assert normalize_date("15 March 2023")[0] == "2023-03-15"
    assert normalize_date("2023-03-15")[0] == "2023-03-15"
    assert normalize_date("15/03/2023")[0] == "2023-03-15"
    assert normalize_date("2023年3月15日")[0] == "2023-03-15"
    print("test_normalize_date_variants OK")


def test_merge():
    ci = ci_rules.extract_ci(CI_TEXT)
    br = br_rules.extract_br(BR_TEXT)
    nnc1 = nnc1_rules.extract_nnc1(NNC1_TEXT, source="NNC1")

    result = merge(
        ci_files=[("CI.pdf", ci)],
        br_files=[("BR.pdf", br)],
        nnc1_sources=[NNC1Source(filename="NNC1.pdf", doc_kind="NNC1", data=nnc1, recency_key="0000-00-00")],
    )
    ent = result["enterprise"]
    assert ent["name_en"]["value"] == "GWEN INTERNATIONAL LIMITED"
    assert ent["crn"]["value"] == "3012345"
    assert ent["reg_country"]["status"] == "default"
    assert ent["reg_address"]["value"] == nnc1["registered_address"]["value"]
    assert ent["op_address"]["value"] == br["business_address"]["value"]
    assert len(result["representatives"]) == 2
    assert result["files"] == ["CI.pdf", "BR.pdf", "NNC1.pdf"]
    print("test_merge OK", ent)


def test_endpoint_smoke():
    """End-to-end smoke test: build tiny PDFs with reportlab and hit /api/extract."""
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        print("test_endpoint_smoke SKIPPED (reportlab not installed)")
        return

    from fastapi.testclient import TestClient
    from app.main import app

    def make_pdf(text: str) -> bytes:
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        y = 800
        for line in text.strip("\n").split("\n"):
            c.drawString(40, y, line)
            y -= 16
        c.save()
        return buf.getvalue()

    client = TestClient(app)
    files = [
        ("ci_files", ("CI.pdf", make_pdf(CI_TEXT), "application/pdf")),
        ("br_files", ("BR.pdf", make_pdf(BR_TEXT), "application/pdf")),
        ("nnc1_files", ("NNC1.pdf", make_pdf(NNC1_TEXT), "application/pdf")),
    ]
    resp = client.post("/api/extract", files=files)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["enterprise"]["crn"]["value"] == "3012345", data["enterprise"]
    assert len(data["representatives"]) == 2
    print("test_endpoint_smoke OK", data["enterprise"]["name_en"], data["enterprise"]["crn"])


if __name__ == "__main__":
    test_ci()
    test_ci_issued_on()
    test_br()
    test_br_bilingual_multiline_address()
    test_br_official_form2_stacked_address_label()
    test_br_address_fills_both_reg_and_op_address()
    test_nnc1()
    test_normalize_date_variants()
    test_merge()
    test_endpoint_smoke()
    print("\nALL TESTS PASSED")

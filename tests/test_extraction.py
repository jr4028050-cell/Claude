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

Particulars of Founder Members and Shares Taken
Surname or Company Name: CHAN
Forename(s): TAI MAN
Number of Shares Taken: 6000

Surname or Company Name: WONG
Forename(s): MEI LING
Number of Shares Taken: 2500

Surname or Company Name: LI
Forename(s): SIU MING
Number of Shares Taken: 1500

Name of Corporation: SMALLCO HOLDINGS LIMITED
Number of Shares Taken: 0

Share Capital and Initial Shareholdings
Total Number of Shares Proposed to be Issued: 10000
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


# Verbatim pdfplumber.extract_text() output from a real HK Form 2 (BR
# certificate) sample. Note the label line carries the first fragment of
# the value inline ("地 址 RM 509, 5/F THE CLOUD 111"), the English label
# repeats on the next line with the second fragment ("Address TUNG CHAU ST
# TAI KOK TSUI"), and the header above is full of "ORDINANCE"/"FORM 2"/
# "REGULATION" boilerplate that a naive first-match-of-"address" regex
# will latch onto instead of the real field.
REAL_FORM2_TEXT = (
    "請沿虛線剪下並將有效的商業/分行登記證展示在營業地點。\n"
    "Please cut along the dotted line and display the valid business/branch "
    "registration certificate at business address.\n"
    "以\n正 本 表格 2 FORM 2 [第5條]\n"
    "ORIGINAL 《商業登記條例》（第310章） [regulation 5 ]\n"
    "BUSINESS REGISTRATION ORDINANCE (Chapter 310)\n"
    "《商業登記規例》\n複 本 BUSINESS REGISTRATION REGULATIONS\nDUPLICATE\n"
    "商業 / 分行登記證 Business / Branch Registration Certificate\n"
    "業務 / 法團所用名稱 NOVAUNB LIMITED\nName of Business/\nCorporation\n"
    "業務 / 分行名稱 " + "* " * 24 + "\nBusiness/\nBranch Name\n" + "* " * 24 + "\n"
    "地 址 RM 509, 5/F THE CLOUD 111\n"
    "Address TUNG CHAU ST TAI KOK TSUI\n"
    "HONG KONG\n"
    "業務性質 CORP\nNature of Business\n"
    "法律地位\nBODY CORPORATE\nStatus\n"
)


def test_br_real_form2_address_ignores_header_boilerplate():
    r = br_rules.extract_br(REAL_FORM2_TEXT)
    assert r["business_address"]["value"] == (
        "RM 509, 5/F THE CLOUD 111 TUNG CHAU ST TAI KOK TSUI HONG KONG"
    ), r["business_address"]
    assert r["business_address"]["status"] == "extracted"
    for noise in ("ORDINANCE", "FORM 2", "regulation", "ORIGINAL", "DUPLICATE"):
        assert noise.upper() not in r["business_address"]["value"].upper(), r["business_address"]
    print("test_br_real_form2_address_ignores_header_boilerplate OK", r["business_address"])


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
    assert ent["reg_country"]["value"] == "Hong Kong / 中国香港", ent["reg_country"]
    assert ent["op_country"]["value"] == "Hong Kong / 中国香港", ent["op_country"]
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
    for removed_key in (
        "position", "gender", "nationality", "residing_country", "same_nationality", "dob",
    ):
        assert removed_key not in d1, f"{removed_key} should no longer be extracted"

    d2 = r["directors"][1]
    assert d2["surname_en"]["value"] == "WONG", d2["surname_en"]
    assert d2["id_info"]["value"] == "K98****", d2["id_info"]
    assert d2["id_info"]["status"] == "masked", d2["id_info"]
    print("test_nnc1 OK directors", r["directors"])

    # UBOs: CHAN 6000/10000=60% and WONG 2500/10000=25% qualify (>=25%);
    # LI 1500/10000=15% and the 0-share corporate holder do not.
    assert len(r["ubos"]) == 2, r["ubos"]
    ubo_by_name = {u["surname_en"]["value"]: u for u in r["ubos"]}
    assert ubo_by_name["CHAN"]["shareholding_pct"]["value"] == "60.00%", ubo_by_name["CHAN"]
    assert ubo_by_name["CHAN"]["residential_address"]["value"] == (
        "ROOM 5, 10/F, XYZ MANSION, KOWLOON, HONG KONG"
    ), ubo_by_name["CHAN"]  # backfilled from the director record
    assert ubo_by_name["CHAN"]["id_info"]["value"] == "P1234567(HK)", ubo_by_name["CHAN"]
    assert ubo_by_name["WONG"]["shareholding_pct"]["value"] == "25.00%", ubo_by_name["WONG"]
    assert ubo_by_name["WONG"]["id_info"]["status"] == "masked", ubo_by_name["WONG"]
    print("test_nnc1 OK ubos", r["ubos"])


def test_nnc1_corporate_ubo():
    text = """
    Registered Office:
    FLAT B, HONG KONG

    Particulars of Founder Members and Shares Taken
    Name of Corporation: BIG HOLDINGS LIMITED
    Number of Shares Taken: 4000

    Surname or Company Name: LEE
    Forename(s): KA WING
    Number of Shares Taken: 500

    Share Capital
    Total Number of Shares Proposed to be Issued: 10000
    """
    r = nnc1_rules.extract_nnc1(text, source="NNC1")
    assert len(r["ubos"]) == 1, r["ubos"]  # LEE at 5% is below threshold
    ubo = r["ubos"][0]
    assert ubo["is_corporate"] is True, ubo
    assert ubo["company_name"]["value"] == "BIG HOLDINGS LIMITED", ubo
    assert ubo["shareholding_pct"]["value"] == "40.00%", ubo
    assert ubo["id_info"]["status"] == "na", ubo
    assert ubo["residential_address"]["status"] == "na", ubo
    assert ubo["surname_en"]["status"] == "na", ubo
    print("test_nnc1_corporate_ubo OK", ubo)


def test_nnc1_ubo_unknown_total_flags_missing_pct():
    """No total-shares figure in the document -> can't compute the ratio,
    so shareholders are still surfaced (not silently dropped) but with
    shareholding_pct marked 'missing' for manual completion."""
    text = """
    Registered Office:
    FLAT B, HONG KONG

    Particulars of Founder Members and Shares Taken
    Surname or Company Name: LEE
    Forename(s): KA WING
    Number of Shares Taken: 500
    """
    r = nnc1_rules.extract_nnc1(text, source="NNC1")
    assert len(r["ubos"]) == 1, r["ubos"]
    assert r["ubos"][0]["shareholding_pct"]["status"] == "missing", r["ubos"][0]
    print("test_nnc1_ubo_unknown_total_flags_missing_pct OK", r["ubos"][0])


# Best-effort reconstruction of a real "PI-NNC1" director particulars page
# (首任公司秘書／董事(自然人)- 受保護資料 / First Company Secretary /
# Director (Individual) - Protected Information), based on the exact field
# labels/order/example values supplied against a real bug report: the
# previous extractor was grabbing label text ("Surname", "Building", the
# page heading, ...) instead of the filled-in values next to them.
PI_NNC1_CHINA_ID_TEXT = """
PI-NNC1
首任公司秘書／董事(自然人)- 受保護資料
First Company Secretary / Director (Individual) - Protected Information

中文姓名 / Name in Chinese
邱漢城

英文姓名 / Name in English
姓氏
Surname

名字
Other Names

身分識別 / Identification
香港身份證號碼
Hong Kong Identity Card No.
NIL

護照
Passport
完整號碼
Full Number
440304199501252615
簽發國家/地區
Issuing Country
China

董事的通常住址 / Usual Residential Address of Director
室/樓/座
Flat/Floor/Block
D2205
大廈
Building
TIANRENJU DISTRICT 1
街道
Street
NO. 1 JINGTIAN NORTH STREET
地區/市/省
District/City/Province
FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE
國家
Country
China
"""


def test_pi_nnc1_no_label_text_leaks_into_values():
    """Core bug: none of the extracted field values should ever equal a
    field label (中文姓名/Surname/Other Names/身分識別/PI-NNC1/etc)."""
    r = nnc1_rules.extract_nnc1(PI_NNC1_CHINA_ID_TEXT, source="NNC1")
    assert len(r["directors"]) == 1, r["directors"]
    d = r["directors"][0]

    label_like = {
        "surname", "other names", "othernames", "identification", "身分識別",
        "hong kong identity card no.", "pi-nnc1", "building", "street", "country",
        "flat/floor/block", "usual residential address of director",
    }
    for key, f in d.items():
        assert f["value"].strip().lower() not in label_like, (key, f)

    print("test_pi_nnc1_no_label_text_leaks_into_values OK", d)


def test_pi_nnc1_exact_field_values():
    """Exact expected values from the real-world bug report example."""
    r = nnc1_rules.extract_nnc1(PI_NNC1_CHINA_ID_TEXT, source="NNC1")
    d = r["directors"][0]

    assert d["surname_cn"]["value"] == "邱", d["surname_cn"]
    assert d["given_cn"]["value"] == "漢城", d["given_cn"]
    assert d["id_info"]["value"] == "440304199501252615", d["id_info"]
    assert d["id_issuing_country"]["value"] == "China", d["id_issuing_country"]
    assert d["residential_address"]["value"] == (
        "D2205, TIANRENJU DISTRICT 1, NO. 1 JINGTIAN NORTH STREET, "
        "FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE, China"
    ), d["residential_address"]
    print("test_pi_nnc1_exact_field_values OK", d)


def test_pi_nnc1_mandarin_pinyin_fallback_when_english_name_blank():
    """China ID on file + blank English name -> Mandarin Hanyu Pinyin,
    marked 'inferred' (a deterministic, standardised transliteration)."""
    r = nnc1_rules.extract_nnc1(PI_NNC1_CHINA_ID_TEXT, source="NNC1")
    d = r["directors"][0]
    assert d["surname_en"]["value"] == "Qiu", d["surname_en"]
    assert d["surname_en"]["status"] == "inferred", d["surname_en"]
    assert d["given_en"]["value"] == "Hancheng", d["given_en"]
    assert d["given_en"]["status"] == "inferred", d["given_en"]
    print("test_pi_nnc1_mandarin_pinyin_fallback_when_english_name_blank OK", d["surname_en"], d["given_en"])


def test_pi_nnc1_cantonese_suggestion_when_hkid_and_english_name_blank():
    """HKID on file (not NIL) + blank English name -> a Cantonese/HK-ID-
    style romanization *suggestion*, marked 'suggested' (never 'inferred')
    since there's no reliable standard scheme to compute it from."""
    text = PI_NNC1_CHINA_ID_TEXT.replace(
        "香港身份證號碼\nHong Kong Identity Card No.\nNIL",
        "香港身份證號碼\nHong Kong Identity Card No.\nA1234567",
    ).replace(
        "完整號碼\nFull Number\n440304199501252615\n簽發國家/地區\nIssuing Country\nChina",
        "完整號碼\nFull Number\n\n簽發國家/地區\nIssuing Country\n",
    )
    r = nnc1_rules.extract_nnc1(text, source="NNC1")
    d = r["directors"][0]
    assert d["id_info"]["value"] == "A1234567", d["id_info"]
    assert d["id_issuing_country"]["value"] == "Hong Kong", d["id_issuing_country"]
    assert d["surname_en"]["value"] == "Yau", d["surname_en"]
    assert d["surname_en"]["status"] == "suggested", d["surname_en"]
    assert d["given_en"]["value"] == "Hon Shing", d["given_en"]
    assert d["given_en"]["status"] == "suggested", d["given_en"]
    print("test_pi_nnc1_cantonese_suggestion_when_hkid_and_english_name_blank OK", d["surname_en"], d["given_en"])


def test_pi_nnc1_filled_english_name_is_used_as_is_no_romanization():
    text = PI_NNC1_CHINA_ID_TEXT.replace(
        "姓氏\nSurname\n\n名字\nOther Names",
        "姓氏\nSurname\nCHOW\n\n名字\nOther Names\nHON SHING",
    )
    r = nnc1_rules.extract_nnc1(text, source="NNC1")
    d = r["directors"][0]
    assert d["surname_en"]["value"] == "CHOW", d["surname_en"]
    assert d["surname_en"]["status"] == "extracted", d["surname_en"]
    assert d["given_en"]["value"] == "HON SHING", d["given_en"]
    assert d["given_en"]["status"] == "extracted", d["given_en"]
    print("test_pi_nnc1_filled_english_name_is_used_as_is_no_romanization OK", d["surname_en"], d["given_en"])


def test_pi_nnc1_does_not_regress_simple_single_line_address_format():
    """Guard against the regression this rewrite introduced and fixed:
    the PI-NNC1 component-address grab must not fire on a plain single-
    line "Residential Address: value" block just because the value text
    happens to contain a word like "Street"."""
    d = nnc1_rules.extract_nnc1(NNC1_TEXT, source="NNC1")["directors"][1]
    assert d["surname_en"]["value"] == "WONG", d["surname_en"]
    assert d["residential_address"]["value"] == "20 BAKER STREET, LONDON, UNITED KINGDOM", (
        d["residential_address"]
    )
    print("test_pi_nnc1_does_not_regress_simple_single_line_address_format OK", d["residential_address"])


def test_pi_nnc1_ignores_unrelated_sections_and_instructional_notes():
    """Real bug report: block splitting previously scanned the whole
    document for bare "Surname"/"姓氏" occurrences, so an unrelated
    "Proposed Company English or Chinese Name" field (which also contains
    "或 OR" bilingual text) got mistaken for a second, fake director, and
    the real director's fields picked up stray label fragments ("前用姓名"
    Former Name, an "(...)"" instructional note before the address
    sub-fields). Scoping each director to its own PI-NNC1 page fixes both:
    exactly one real director, with clean field values."""
    text = """
    FORM NNC1
    INCORPORATION FORM

    1. Company Name
    建議採用的公司英文或中文名稱
    Proposed Company English or Chinese Name
    NOVAUNB LIMITED 或 OR 諾凡股份有限公司

    2. Registered Office
    FLAT B, 12/F, ABC BUILDING, 88 DES VOEUX ROAD CENTRAL, HONG KONG

    3. Particulars of Person(s) Who Are Founder Member(s)/First Director(s)

    PI-NNC1
    首任公司秘書／董事(自然人)- 受保護資料
    First Company Secretary / Director (Individual) - Protected Information

    中文姓名 / Name in Chinese
    邱漢城

    英文姓名 / Name in English
    姓氏
    Surname

    名字
    Other Names

    前用姓名 / Former Name(s)


    身分識別 / Identification
    香港身份證號碼
    Hong Kong Identity Card No.
    NIL

    護照
    Passport
    完整號碼
    Full Number
    440304199501252615
    簽發國家/地區
    Issuing Country
    China

    董事的通常住址 / Usual Residential Address of Director
    (Please state the full address in Hong Kong or elsewhere)
    室/樓/座
    Flat/Floor/Block
    D2205
    大廈
    Building
    TIANRENJU DISTRICT 1
    街道
    Street
    NO. 1 JINGTIAN NORTH STREET
    地區/市/省
    District/City/Province
    FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE
    國家
    Country
    China

    4. Share Capital and Initial Shareholdings
    Total Number of Shares Proposed to be Issued: 10000
    """
    r = nnc1_rules.extract_nnc1(text, source="NNC1")
    assert len(r["directors"]) == 1, r["directors"]  # not 2 (no fake director from the company-name section)
    d = r["directors"][0]
    assert d["surname_cn"]["value"] == "邱", d["surname_cn"]
    assert d["given_cn"]["value"] == "漢城", d["given_cn"]
    assert d["id_info"]["value"] == "440304199501252615", d["id_info"]  # not "NIL"
    assert d["id_issuing_country"]["value"] == "China", d["id_issuing_country"]
    assert d["residential_address"]["value"] == (
        "D2205, TIANRENJU DISTRICT 1, NO. 1 JINGTIAN NORTH STREET, "
        "FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE, China"
    ), d["residential_address"]
    print("test_pi_nnc1_ignores_unrelated_sections_and_instructional_notes OK", d)


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
    # BR's Address field is authoritative for reg_address even when NNC1/NAR1
    # was also uploaded and disagrees; the disagreement is still logged.
    assert ent["reg_address"]["value"] == br["business_address"]["value"]
    assert ent["reg_address"]["source"] == "BR"
    assert ent["reg_address"]["status"] == "extracted"
    assert ent["op_address"]["value"] == br["business_address"]["value"]
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["field"] == "enterprise.reg_address"
    assert len(result["directors"]) == 2
    assert len(result["ubos"]) == 2
    assert result["files"] == ["CI.pdf", "BR.pdf", "NNC1.pdf"]
    print("test_merge OK", ent, result["conflicts"])


def test_merge_ubo_dedup_across_nnc1_and_nar1():
    """Same UBO listed in both an NNC1 and a later NAR1 should be merged
    into one entry, preferring the newer NAR1 on ties/completeness."""
    nnc1_text = """
    Registered Office:
    FLAT B, HONG KONG

    Particulars of Founder Members and Shares Taken
    Surname or Company Name: CHAN
    Forename(s): TAI MAN
    Number of Shares Taken: 6000

    Share Capital
    Total Number of Shares Proposed to be Issued: 10000
    """
    nar1_text = """
    Annual Return
    made up to 15 March 2025
    Registered Office:
    FLAT B, HONG KONG

    Particulars of Founder Members and Shares Taken
    Surname or Company Name: CHAN
    Forename(s): TAI MAN
    Usual Residential Address: ROOM 5, KOWLOON, HONG KONG
    Identification: P1234567(HK)
    Number of Shares Taken: 6000

    Share Capital
    Total Number of Shares Proposed to be Issued: 10000
    """
    nnc1_data = nnc1_rules.extract_nnc1(nnc1_text, source="NNC1")
    nar1_data = nnc1_rules.extract_nnc1(nar1_text, source="NAR1")
    result = merge(
        ci_files=[],
        br_files=[],
        nnc1_sources=[
            NNC1Source(filename="NNC1.pdf", doc_kind="NNC1", data=nnc1_data, recency_key="0000-00-00"),
            NNC1Source(filename="NAR1.pdf", doc_kind="NAR1", data=nar1_data, recency_key="2025-03-15"),
        ],
    )
    assert len(result["ubos"]) == 1, result["ubos"]
    ubo = result["ubos"][0]
    assert ubo["shareholding_pct"]["value"] == "60.00%", ubo
    assert ubo["residential_address"]["value"] == "ROOM 5, KOWLOON, HONG KONG", ubo
    print("test_merge_ubo_dedup_across_nnc1_and_nar1 OK", ubo)


_WQY_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def test_pdf_text_layout_reconstruction_real_pdf():
    """Full-pipeline validation with an actually-rendered two-column PDF
    (real glyph positions, not just sequential text fixtures): a naive
    label/value regex over pdfplumber's default extract_text() is what
    produced label text as "director data" in the original bug report.
    Renders a PI-NNC1-style page with a genuine bilingual (Chinese+English)
    two-column layout using a real CJK font, runs it through
    app.extraction.pdf_text.extract_document_text (the rewritten
    row/column reconstruction) and then app.extraction.nnc1.extract_nnc1
    unchanged, and checks the three fields called out in the bug report:
    Chinese name 邱漢城, passport number 440304199501252615 (HKID cell is
    NIL), and the fully-assembled residential address.
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        print("test_pdf_text_layout_reconstruction_real_pdf SKIPPED (reportlab not installed)")
        return
    import os
    if not os.path.exists(_WQY_FONT_PATH):
        print("test_pdf_text_layout_reconstruction_real_pdf SKIPPED (no CJK font at", _WQY_FONT_PATH, ")")
        return

    from app.extraction.pdf_text import extract_document_text

    pdfmetrics.registerFont(TTFont("WQY", _WQY_FONT_PATH))
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("WQY", 10)
    LEFT, RIGHT = 40, 320

    def row(y, left_text="", right_text=""):
        if left_text:
            c.drawString(LEFT, y, left_text)
        if right_text:
            c.drawString(RIGHT, y, right_text)

    y = 760
    row(y, "PI-NNC1"); y -= 20
    row(y, "首任公司秘書／董事(自然人)- 受保護資料",
        "First Company Secretary / Director (Individual) - Protected Information"); y -= 30
    row(y, "中文姓名", "Name in Chinese"); y -= 18
    row(y, "邱漢城"); y -= 30
    row(y, "英文姓名", "Name in English"); y -= 18
    row(y, "姓氏", "Surname"); y -= 18
    y -= 18  # Surname value left blank
    row(y, "名字", "Other Names"); y -= 18
    y -= 30  # Other Names value left blank
    row(y, "身分識別", "Identification"); y -= 18
    row(y, "香港身份證號碼", "Hong Kong Identity Card No."); y -= 18
    row(y, "NIL"); y -= 24
    row(y, "護照", "Passport"); y -= 18
    row(y, "完整號碼", "Full Number"); y -= 18
    row(y, "440304199501252615"); y -= 18
    row(y, "簽發國家/地區", "Issuing Country"); y -= 18
    row(y, "China"); y -= 30
    row(y, "董事的通常住址", "Usual Residential Address of Director"); y -= 18
    row(y, "室/樓/座", "Flat/Floor/Block"); y -= 18
    row(y, "D2205"); y -= 18
    row(y, "大廈", "Building"); y -= 18
    row(y, "TIANRENJU DISTRICT 1"); y -= 18
    row(y, "街道", "Street"); y -= 18
    row(y, "NO. 1 JINGTIAN NORTH STREET"); y -= 18
    row(y, "地區/市/省", "District/City/Province"); y -= 18
    row(y, "FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE"); y -= 18
    row(y, "國家", "Country"); y -= 18
    row(y, "China")
    c.save()

    doc = extract_document_text("PI_NNC1.pdf", buf.getvalue())
    result = nnc1_rules.extract_nnc1(doc.full_text, source="NNC1")
    assert len(result["directors"]) == 1, result["directors"]
    d = result["directors"][0]

    assert d["surname_cn"]["value"] == "邱", d["surname_cn"]
    assert d["given_cn"]["value"] == "漢城", d["given_cn"]
    assert d["id_info"]["value"] == "440304199501252615", d["id_info"]  # not "NIL"
    assert d["id_issuing_country"]["value"] == "China", d["id_issuing_country"]
    assert d["residential_address"]["value"] == (
        "D2205, TIANRENJU DISTRICT 1, NO. 1 JINGTIAN NORTH STREET, "
        "FUTIAN DISTRICT, SHENZHEN CITY, GUANGDONG PROVINCE, China"
    ), d["residential_address"]
    # both English name fields genuinely blank -> Mandarin pinyin fallback
    # (China passport), proving no stray label text leaked in as a value
    assert d["surname_en"]["value"] == "Qiu" and d["surname_en"]["status"] == "inferred", d["surname_en"]
    assert d["given_en"]["value"] == "Hancheng", d["given_en"]

    print("test_pdf_text_layout_reconstruction_real_pdf OK", d)


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
    assert len(data["directors"]) == 2
    assert len(data["ubos"]) == 2
    print("test_endpoint_smoke OK", data["enterprise"]["name_en"], data["enterprise"]["crn"])


if __name__ == "__main__":
    test_ci()
    test_ci_issued_on()
    test_br()
    test_br_bilingual_multiline_address()
    test_br_official_form2_stacked_address_label()
    test_br_real_form2_address_ignores_header_boilerplate()
    test_br_address_fills_both_reg_and_op_address()
    test_nnc1()
    test_nnc1_corporate_ubo()
    test_nnc1_ubo_unknown_total_flags_missing_pct()
    test_pi_nnc1_no_label_text_leaks_into_values()
    test_pi_nnc1_exact_field_values()
    test_pi_nnc1_mandarin_pinyin_fallback_when_english_name_blank()
    test_pi_nnc1_cantonese_suggestion_when_hkid_and_english_name_blank()
    test_pi_nnc1_filled_english_name_is_used_as_is_no_romanization()
    test_pi_nnc1_does_not_regress_simple_single_line_address_format()
    test_pi_nnc1_ignores_unrelated_sections_and_instructional_notes()
    test_normalize_date_variants()
    test_merge()
    test_merge_ubo_dedup_across_nnc1_and_nar1()
    test_pdf_text_layout_reconstruction_real_pdf()
    test_endpoint_smoke()
    print("\nALL TESTS PASSED")

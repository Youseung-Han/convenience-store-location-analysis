"""Read and audit versioned source files before constructing model inputs."""

from datetime import date
from hashlib import file_digest
from io import BytesIO
from pathlib import Path
import re
from urllib.request import urlopen
from zipfile import ZipFile

import pandas as pd


CUTOFF = date(2024, 4, 30)
ENDPOINT = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do"
STORE_FIELDS = {
    "유사업종점포수": "stores", "개업점포수": "opened", "폐업점포수": "closed",
    "개업율": "opening_rate", "폐업률": "closing_rate", "프랜차이즈점포수": "franchise",
}
IDENTITY = {
    "상권코드": "area", "상권코드명": "name", "상권구분코드": "type",
    "서비스업종코드": "industry", "서비스업종코드명": "industry_name",
}
KEY = ["quarter", "area"]


def source_url(entry):
    return f"{ENDPOINT}?infId={entry['id']}&seq={entry['seq']}&infSeq=3"


def download(raw, manifest):
    raw.mkdir(parents=True, exist_ok=True)
    for entry in manifest.values():
        if "seq" not in entry:
            continue
        path = raw / entry["path"]
        if path.exists():
            continue
        with urlopen(source_url(entry), timeout=60) as response:
            content = response.read()
        if not content.startswith(b"PK"):
            raise ValueError(f"{path.name}: expected ZIP, use the manual download route")
        path.write_bytes(content)


def audit_source(raw, entry, *, allow_revised=False):
    path = raw / entry["path"]
    report = {"file": path.name, "portal_modified": entry.get("portal_modified")}
    if not path.is_file():
        return report | {"eligible": False, "reason": "file missing"}
    with path.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    report["sha256"] = digest
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            report["zip_member_dates"] = sorted({
                date(*member.date_time[:3]).isoformat() for member in members
            })
    if digest != entry.get("sha256"):
        return report | {"eligible": False, "reason": "SHA-256 mismatch"}
    verified = entry.get("version_date")
    evidence = entry.get("version_evidence")
    late_members = any(stamp > CUTOFF.isoformat() for stamp in report.get("zip_member_dates", []))
    if late_members or not verified or not evidence or date.fromisoformat(verified) > CUTOFF:
        if allow_revised:
            return report | {"eligible": True, "version_policy": "historical_observations_in_revised_snapshot"}
        reason = "ZIP member timestamp after cutoff" if late_members else "pre-cutoff version evidence missing"
        return report | {"eligible": False, "reason": reason}
    return report | {"eligible": True, "version_date": verified, "version_evidence": evidence}


def read_csv(path):
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"{path.name}: expected one CSV member")
            content = archive.read(members[0])
    else:
        content = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(BytesIO(content), encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: unrecognized encoding")


def require_unique(frame, key):
    if frame[key].isna().any(axis=None):
        raise ValueError(f"missing join key in {key}")
    duplicated = frame.duplicated(key, keep=False)
    if duplicated.any():
        raise ValueError(f"{int(duplicated.sum())} rows have duplicate keys in {key}")


def read_quarters(path, kind, year, sales_unit=None):
    frame = read_csv(path)
    frame.columns = [re.sub(r"[\s_]", "", name) for name in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError(f"{path.name}: ambiguous normalized column names")
    if "기준년분기코드" in frame:
        quarter = frame["기준년분기코드"]
    else:
        quarter = frame["기준년코드"] + frame["기준분기코드"]
    if not quarter.str.fullmatch(f"{year}[1-4]", na=False).all():
        raise ValueError(f"{path.name}: invalid or out-of-year quarter")
    quarter = pd.PeriodIndex(quarter.str[:4] + "Q" + quarter.str[-1], freq="Q")
    if set(quarter) != set(pd.period_range(f"{year}Q1", periods=4, freq="Q")):
        raise ValueError(f"{path.name}: incomplete observation year")

    if kind == "population":
        fields = {"상권코드": "area", "총유동인구수": "weight"}
        numeric = ["weight"]
    elif kind == "stores":
        fields = IDENTITY | STORE_FIELDS | {"점포수": "regular_stores"}
        numeric = [*STORE_FIELDS.values(), "regular_stores"]
    else:
        sales = {
            "quarter_total": ("분기당매출금액", "분기당매출건수"),
            "monthly_average": ("당월매출금액", "당월매출건수"),
        }
        amount, transactions = sales[sales_unit]
        fields = IDENTITY | {amount: "sales", transactions: "transactions"}
        numeric = ["sales", "transactions"]
    result = frame[list(fields)].rename(columns=fields).apply(
        lambda column: column.str.strip().replace("", pd.NA)
    )
    result["quarter"] = quarter
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="raise")
        if (result[column].dropna() < 0).any():
            raise ValueError(f"{path.name}: negative {column}")
    if kind == "stores":
        counts = result[["stores", "regular_stores", "franchise"]].dropna()
        if not counts["stores"].eq(counts["regular_stores"] + counts["franchise"]).all():
            raise ValueError(f"{path.name}: total store definition requires verification")
    if kind == "population":
        require_unique(result, KEY)
    else:
        require_unique(result, KEY + ["industry"])
        by_name = result["industry_name"].eq("편의점")
        by_code = result["industry"].eq("CS300002")
        if not by_name.any() or not by_name.equals(by_code):
            raise ValueError(f"{path.name}: 편의점 and CS300002 do not match")
    return result

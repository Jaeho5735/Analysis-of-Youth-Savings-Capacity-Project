"""
행정동 신뢰도 등급 산출

표면주거비 배정 신뢰도 검증 결과를 서비스에서 쓸 등급으로 정리한다.
근거는 docs/표면주거비_배정_신뢰도.md 참고.

등급
    no_data          표면주거비 미산출 (결측 7개 동)
    unreliable       검증 정확도 0% (배정이 체계적으로 이웃 동으로 샘)
    low_confidence   정확도 하위 / 교통비 커버리지 부족 / 소표본
    ok               나머지

산출
    docs/행정동_신뢰도.csv
    sql/dim_dong_reliability.sql   (DDL + 시드 + QC)

사용법
    python src/analysis/build_dong_reliability.py
    python src/analysis/build_dong_reliability.py C:\\MULTICAM_PROJECT
"""

import sys
from pathlib import Path

import pandas as pd

ENCODINGS = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]

# ── 임계값 (조정하려면 여기만 고친다) ────────────────────────
TH_UNRELIABLE_ACC = 0.001   # 검증 정확도가 사실상 0
TH_UNRELIABLE_N = 50        # 그 판정을 내리기 위한 최소 검증표본
TH_LOWCONF_ACC = 0.50       # 정확도 50% 미만
TH_LOWCONF_N = 30           # 그 판정을 내리기 위한 최소 검증표본
TH_COVERAGE = 0.70          # 교통비 산출포함률 하한
TH_SMALL_TX = 30            # 거래 30건 미만은 소표본


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 68)
    log(t)
    log("=" * 68)


def read_csv_any(path, **kw):
    last = None
    for enc in ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError as e:
            last = e
        except Exception as e:
            last = e
            break
    raise RuntimeError(f"{Path(path).name} 읽기 실패: {last}")


def find_one(root, pattern):
    hits = [p for p in root.rglob(pattern) if p.is_file()
            and not any(x in {".git", "__pycache__", "web", "flask_sample"} for x in p.parts)]
    hits.sort(key=lambda p: len(str(p)))
    return hits[0] if hits else None


def col_of(df, *keywords, exclude=()):
    """키워드를 모두 포함하고 exclude 를 하나도 포함하지 않는 컬럼. 없으면 None."""
    for c in df.columns:
        s = str(c)
        if all(k in s for k in keywords) and not any(x in s for x in exclude):
            return c
    return None


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    log(f"프로젝트 루트: {root.resolve()}")

    section("[1단계] 입력 파일")
    p_cov = find_one(root, "*행정동_소스별_커버리지*.csv")
    p_acc = find_one(root, "*도로명근사_정확도_동별*.csv")
    p_bur = find_one(root, "*주거통근_통합부담_행정동별*.csv")
    p_asg = find_one(root, "*표면주거비_배정방식_동별_보정*.csv")

    for lb, p in [("커버리지", p_cov), ("정확도", p_acc), ("통합부담", p_bur), ("배정방식", p_asg)]:
        log(f"  {lb:8s} : {p if p else '(없음)'}")
    if not p_cov:
        log("\n  커버리지 파일이 없으면 진행할 수 없다.")
        return

    # ── 기준 427개 동 ──
    cov = read_csv_any(p_cov, dtype=str)
    c_code = col_of(cov, "행정동코드")
    c_name = col_of(cov, "행정동명")
    c_gu = col_of(cov, "자치구")
    c_flag = col_of(cov, "표면주거비")
    if not all([c_code, c_name, c_flag]):
        log(f"  컬럼 확인 필요: {list(cov.columns)}")
        return

    df = pd.DataFrame({
        "dong_code": cov[c_code].astype(str).str.strip().str[:8],
        "dong_name": cov[c_name].astype(str).str.strip(),
        "gu": cov[c_gu].astype(str).str.strip() if c_gu else "",
        "has_rent": cov[c_flag].astype(str).str.strip().str.lower().isin(["true", "1", "y", "yes"]),
    })
    log(f"\n  기준 행정동 {len(df)}개 / 표면주거비 산출 {int(df['has_rent'].sum())}개")

    df["status"] = "ok"
    df["reasons"] = [[] for _ in range(len(df))]

    def mark(mask, status, reason):
        n = int(mask.sum())
        if n:
            df.loc[mask, "reasons"] = df.loc[mask, "reasons"].map(lambda r: r + [reason])
            # 등급은 강한 쪽이 이긴다
            rank = {"ok": 0, "low_confidence": 1, "unreliable": 2, "no_data": 3}
            cur = df.loc[mask, "status"].map(rank)
            new = rank[status]
            df.loc[mask & (cur < new).reindex(df.index, fill_value=False), "status"] = status
        log(f"    {reason:34s} {n:>4d}개")

    section("[2단계] 등급 판정")

    # no_data
    mark(~df["has_rent"], "no_data", "표면주거비 미산출")

    # unreliable / low_confidence : 도로명 근사 정확도
    if p_acc:
        acc = read_csv_any(p_acc, dtype=str)
        a_code = col_of(acc, "행정동코드")
        a_acc = col_of(acc, "정확도")
        a_n = col_of(acc, "검증표본")
        if a_code and a_acc and a_n:
            acc["_c"] = acc[a_code].astype(str).str.strip().str[:8]
            acc["_a"] = pd.to_numeric(acc[a_acc], errors="coerce")
            acc["_n"] = pd.to_numeric(acc[a_n], errors="coerce")
            m = df.merge(acc[["_c", "_a", "_n"]].rename(columns={"_c": "dong_code"}),
                         on="dong_code", how="left")
            df["road_acc"] = m["_a"].values
            df["road_n"] = m["_n"].values
            mark((df["road_n"] >= TH_UNRELIABLE_N) & (df["road_acc"] <= TH_UNRELIABLE_ACC),
                 "unreliable", "도로명 배정 검증 정확도 0%")
            mark((df["road_n"] >= TH_LOWCONF_N) & (df["road_acc"] < TH_LOWCONF_ACC)
                 & (df["road_acc"] > TH_UNRELIABLE_ACC),
                 "low_confidence", f"도로명 배정 정확도 {TH_LOWCONF_ACC:.0%} 미만")
        else:
            log(f"    [건너뜀] 정확도 파일 컬럼 확인 필요: {list(acc.columns)}")

    # low_confidence : 교통비 커버리지
    if p_bur:
        bur = read_csv_any(p_bur, dtype=str)
        b_code = col_of(bur, "행정동코드")
        # '교통비'로 먼저 찾으면 월교통비_실지출_원 같은 금액 컬럼이 먼저 잡힌다.
        # 커버리지 성격의 단어로 직접 찾는다.
        b_cov = (col_of(bur, "포함률", exclude=("부족", "여부", "flag"))
                 or col_of(bur, "커버리지", exclude=("부족", "여부", "flag"))
                 or col_of(bur, "커버율", exclude=("부족", "여부", "flag")))
        if b_code and b_cov:
            log(f"    교통비 커버리지 컬럼 = '{b_cov}'")
            bur["_c"] = bur[b_code].astype(str).str.strip().str[:8]
            bur["_v"] = pd.to_numeric(bur[b_cov], errors="coerce")
            m = df.merge(bur[["_c", "_v"]].rename(columns={"_c": "dong_code"}),
                         on="dong_code", how="left")
            df["fare_coverage"] = m["_v"].values
            mark(df["fare_coverage"] < TH_COVERAGE,
                 "low_confidence", f"교통비 커버리지 {TH_COVERAGE:.0%} 미만")
        else:
            log("    [건너뜀] 교통비 커버리지 컬럼을 특정하지 못함. 전체 컬럼:")
            for c in bur.columns:
                log(f"        {c}")

    # low_confidence : 소표본
    if p_asg:
        asg = read_csv_any(p_asg, dtype=str)
        g_code = col_of(asg, "행정동코드")
        g_n = col_of(asg, "총거래수") or col_of(asg, "거래")
        if g_code and g_n:
            asg["_c"] = asg[g_code].astype(str).str.strip().str[:8]
            asg["_n"] = pd.to_numeric(asg[g_n], errors="coerce")
            m = df.merge(asg[["_c", "_n"]].rename(columns={"_c": "dong_code"}),
                         on="dong_code", how="left")
            df["tx_count"] = m["_n"].values
            mark(df["tx_count"] < TH_SMALL_TX,
                 "low_confidence", f"거래 {TH_SMALL_TX}건 미만")
        else:
            log(f"    [건너뜀] 배정방식 파일 컬럼 확인 필요: {list(asg.columns)}")

    section("[3단계] 결과")
    log(df["status"].value_counts().to_string())
    log()
    for st in ["no_data", "unreliable", "low_confidence"]:
        sub = df[df["status"] == st]
        if not len(sub):
            continue
        log(f"  ── {st} ({len(sub)}개) ──")
        for _, r in sub.iterrows():
            log(f"    {r['dong_name']:14s} {r['gu']:8s} {' / '.join(r['reasons'])}")
        log()

    df["reason"] = df["reasons"].map(lambda r: " / ".join(r))
    out_cols = ["dong_code", "dong_name", "gu", "status", "reason"]
    for c in ["road_acc", "road_n", "fare_coverage", "tx_count"]:
        if c in df.columns:
            out_cols.append(c)

    out_csv = root / "docs" / "행정동_신뢰도.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df[out_cols].sort_values(["status", "dong_code"]).to_csv(out_csv, index=False, encoding="utf-8-sig")
    log(f"  저장: {out_csv}")

    # ── SQL 생성 ──
    lines = [
        "-- 자동 생성: src/analysis/build_dong_reliability.py",
        "-- 근거: docs/표면주거비_배정_신뢰도.md",
        "",
        "USE multicam;",
        "",
        "DROP TABLE IF EXISTS dim_dong_reliability;",
        "",
        "CREATE TABLE dim_dong_reliability (",
        "    dong_code8 CHAR(8) NOT NULL COMMENT '행정동코드8',",
        "    status ENUM('ok','low_confidence','unreliable','no_data') NOT NULL,",
        "    reason VARCHAR(200) NULL COMMENT '판정 사유(복수면 / 로 구분)',",
        "    road_accuracy DECIMAL(5,4) NULL COMMENT '도로명 배정 검증 정확도',",
        "    road_sample_n INT NULL COMMENT '검증표본 수',",
        "    fare_coverage DECIMAL(5,4) NULL COMMENT '교통비 산출포함률',",
        "    tx_count INT NULL COMMENT '표면주거비 산출 거래 수',",
        "    PRIMARY KEY (dong_code8),",
        "    CONSTRAINT fk_ddr_region FOREIGN KEY (dong_code8) REFERENCES dim_region (dong_code8)",
        ") COMMENT = '행정동별 표면주거비 신뢰도 등급';",
        "",
        "INSERT INTO dim_dong_reliability",
        "    (dong_code8, status, reason, road_accuracy, road_sample_n, fare_coverage, tx_count)",
        "VALUES",
    ]

    def sql_num(v, as_int=False):
        if pd.isna(v):
            return "NULL"
        return f"{int(v)}" if as_int else f"{v}"

    rows = []
    for _, r in df.sort_values("dong_code").iterrows():
        reason = r["reason"].replace("'", "''") if r["reason"] else None
        rows.append(
            f"('{r['dong_code']}', '{r['status']}', "
            f"{'NULL' if not reason else repr(reason).replace(chr(34), chr(39))}, "
            f"{sql_num(r.get('road_acc', float('nan')))}, "
            f"{sql_num(r.get('road_n', float('nan')), as_int=True)}, "
            f"{sql_num(r.get('fare_coverage', float('nan')))}, "
            f"{sql_num(r.get('tx_count', float('nan')), as_int=True)})"
        )
    lines.append(",\n".join(rows) + ";")
    lines += [
        "",
        "-- QC1 등급 분포",
        "SELECT status, COUNT(*) FROM dim_dong_reliability GROUP BY status;",
        "",
        "-- QC2 전체 행정동이 빠짐없이 들어갔는가",
        "SELECT COUNT(*) FROM dim_region r",
        "LEFT JOIN dim_dong_reliability d ON d.dong_code8 = r.dong_code8",
        "WHERE d.dong_code8 IS NULL;  -- 기대 0",
        "",
        "-- QC3 no_data 인데 표면주거비가 있는 경우",
        "SELECT d.dong_code8 FROM dim_dong_reliability d",
        "JOIN fact_dong_burden b ON b.dong_code8 = d.dong_code8",
        "WHERE d.status = 'no_data';  -- 기대 0행",
    ]

    out_sql = root / "sql" / "dim_dong_reliability.sql"
    out_sql.parent.mkdir(parents=True, exist_ok=True)
    out_sql.write_text("\n".join(lines), encoding="utf-8")
    log(f"  저장: {out_sql}")

    section("완료")
    log("  임계값을 바꾸려면 스크립트 상단 TH_ 상수만 고치고 다시 실행하면 된다.")


if __name__ == "__main__":
    main()
import pandas as pd
from io import BytesIO


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------
def fmt_num_ru(x) -> str:
    """
    Формат чисел:
    - без пробелов
    - дробная часть отделяется запятой
    - если целое -> без ",0"
    """
    if x is None:
        return "0"
    try:
        v = float(x)
    except Exception:
        return str(x)

    if abs(v - int(v)) < 1e-9:
        return str(int(v))

    s = f"{v:.10f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _norm_addr(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()


# ------------------------------------------------------------
# Single wallet report
# ------------------------------------------------------------
def build_wallet_report(df: pd.DataFrame, wallet: str) -> dict:
    """
    df ожидается со столбцами:
    hash, from, to, amount, timestamp, token_symbol, token_address
    """
    if df.empty:
        return {
            "in_sum": 0.0,
            "out_sum": 0.0,
            "in_sum_fmt": "0",
            "out_sum_fmt": "0",
            "in_count": 0,
            "out_count": 0,
            "top5_pct": 0.0,
            "top5_pct_fmt": "0,00",
            "top10_df": pd.DataFrame(columns=["From", "Sum", "Share%"]),
        }

    df = df.copy()
    df["from"] = _norm_addr(df["from"])
    df["to"] = _norm_addr(df["to"])
    w = str(wallet).strip().lower()

    inbound = df[df["to"] == w].copy()
    outbound = df[df["from"] == w].copy()

    in_sum = float(inbound["amount"].sum())
    out_sum = float(outbound["amount"].sum())

    in_count = int(len(inbound))
    out_count = int(len(outbound))

    # Топ отправителей по входящим
    if inbound.empty:
        top10_df = pd.DataFrame(columns=["From", "Sum", "Share%"])
        top5_pct = 0.0
    else:
        grp = inbound.groupby("from", as_index=False)["amount"].sum()
        grp = grp.sort_values("amount", ascending=False)

        total_in = in_sum if in_sum != 0 else 1.0
        top5_sum = float(grp.head(5)["amount"].sum())
        top5_pct = (top5_sum / total_in) * 100.0

        top10 = grp.head(10).copy()
        top10["Share%"] = (top10["amount"] / total_in) * 100.0

        top10.rename(columns={"from": "From", "amount": "Sum"}, inplace=True)

        # форматирование
        top10["Sum"] = top10["Sum"].map(fmt_num_ru)
        top10["Share%"] = top10["Share%"].map(lambda x: f"{x:.4f}".replace(".", ","))

        top10_df = top10

    return {
        "df": df,

        "in_sum": in_sum,
        "out_sum": out_sum,
        "in_sum_fmt": fmt_num_ru(in_sum),
        "out_sum_fmt": fmt_num_ru(out_sum),

        "in_count": in_count,
        "out_count": out_count,

        "top5_pct": float(top5_pct),
        "top5_pct_fmt": f"{top5_pct:.2f}".replace(".", ","),

        "top10_df": top10_df,
    }


def build_excel_report(report: dict) -> bytes:
    """
    Excel для 1 кошелька:
    - Summary
    - Top10
    """
    out = BytesIO()

    summary = pd.DataFrame([{
        "Inbound Sum": report.get("in_sum", 0.0),
        "Inbound Count": report.get("in_count", 0),
        "Top5 Share %": report.get("top5_pct", 0.0),
        "Outbound Sum": report.get("out_sum", 0.0),
        "Outbound Count": report.get("out_count", 0),
    }])

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        report["top10_df"].to_excel(writer, sheet_name="Top10", index=False)

    out.seek(0)
    return out.read()


# ------------------------------------------------------------
# Compare 2 periods with 2 wallets (OLD wallet -> NEW wallet)
# ------------------------------------------------------------
def compare_periods_two_wallets(df_old: pd.DataFrame, df_new: pd.DataFrame, old_wallet: str, new_wallet: str) -> dict:
    """
    Сравнение отправителей (clients) между:
    - входящими на old_wallet за старый период
    - входящими на new_wallet за новый период
    """
    df_old = df_old.copy()
    df_new = df_new.copy()

    df_old["from"] = _norm_addr(df_old["from"])
    df_old["to"] = _norm_addr(df_old["to"])
    df_new["from"] = _norm_addr(df_new["from"])
    df_new["to"] = _norm_addr(df_new["to"])

    ow = str(old_wallet).strip().lower()
    nw = str(new_wallet).strip().lower()

    old_in = df_old[df_old["to"] == ow].copy()
    new_in = df_new[df_new["to"] == nw].copy()

    old_grp = old_in.groupby("from", as_index=False)["amount"].sum().rename(columns={"amount": "OldSum"})
    new_grp = new_in.groupby("from", as_index=False)["amount"].sum().rename(columns={"amount": "NewSum"})

    old_set = set(old_grp["from"].tolist())
    new_set = set(new_grp["from"].tolist())

    new_only = new_set - old_set
    lost_only = old_set - new_set
    both = old_set & new_set

    old_map = dict(zip(old_grp["from"], old_grp["OldSum"]))
    new_map = dict(zip(new_grp["from"], new_grp["NewSum"]))

    new_sum = float(sum(new_map.get(a, 0.0) for a in new_only))
    lost_sum = float(sum(old_map.get(a, 0.0) for a in lost_only))

    persistent_sum_old = float(sum(old_map.get(a, 0.0) for a in both))
    persistent_sum_new = float(sum(new_map.get(a, 0.0) for a in both))

    # таблицы
    new_df = pd.DataFrame(
        [{"From": a, "SumNEW": new_map.get(a, 0.0)} for a in new_only]
    ).sort_values("SumNEW", ascending=False)

    lost_df = pd.DataFrame(
        [{"From": a, "SumOLD": old_map.get(a, 0.0)} for a in lost_only]
    ).sort_values("SumOLD", ascending=False)

    persistent_df = pd.DataFrame([{
        "From": a,
        "SumOLD": old_map.get(a, 0.0),
        "SumNEW": new_map.get(a, 0.0),
        "DeltaNEW-OLD": new_map.get(a, 0.0) - old_map.get(a, 0.0),
    } for a in both]).sort_values("SumNEW", ascending=False)

    # форматирование для UI
    if not new_df.empty:
        new_df["SumNEW"] = new_df["SumNEW"].map(fmt_num_ru)
    if not lost_df.empty:
        lost_df["SumOLD"] = lost_df["SumOLD"].map(fmt_num_ru)
    if not persistent_df.empty:
        for c in ["SumOLD", "SumNEW", "DeltaNEW-OLD"]:
            persistent_df[c] = persistent_df[c].map(fmt_num_ru)

    return {
        "old_wallet": ow,
        "new_wallet": nw,

        "new_count": len(new_only),
        "persistent_count": len(both),
        "lost_count": len(lost_only),

        "new_sum": new_sum,
        "lost_sum": lost_sum,
        "persistent_sum_old": persistent_sum_old,
        "persistent_sum_new": persistent_sum_new,

        "new_sum_fmt": fmt_num_ru(new_sum),
        "lost_sum_fmt": fmt_num_ru(lost_sum),
        "persistent_sum_old_fmt": fmt_num_ru(persistent_sum_old),
        "persistent_sum_new_fmt": fmt_num_ru(persistent_sum_new),

        "new_df": new_df,
        "lost_df": lost_df,
        "persistent_df": persistent_df,
    }


def build_excel_compare_report(rep: dict) -> bytes:
    """
    Excel для сравнения:
    - Summary
    - New
    - Persistent
    - Lost
    """
    out = BytesIO()

    summary = pd.DataFrame([{
        "OldWallet": rep["old_wallet"],
        "NewWallet": rep["new_wallet"],

        "NewSendersCount": rep["new_count"],
        "PersistentSendersCount": rep["persistent_count"],
        "LostSendersCount": rep["lost_count"],

        "NewSum_NEWperiod": rep["new_sum"],
        "PersistentSum_OLDperiod": rep["persistent_sum_old"],
        "PersistentSum_NEWperiod": rep["persistent_sum_new"],
        "LostSum_OLDperiod": rep["lost_sum"],
    }])

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        rep["new_df"].to_excel(writer, sheet_name="New", index=False)
        rep["persistent_df"].to_excel(writer, sheet_name="Persistent", index=False)
        rep["lost_df"].to_excel(writer, sheet_name="Lost", index=False)

    out.seek(0)
    return out.read()
# ------------------------------------------------------------
# INTERSECTION REPORT
# ------------------------------------------------------------
def build_intersection_report(df_a: pd.DataFrame, df_b: pd.DataFrame, wallet_a: str, wallet_b: str) -> dict:

    df_a = df_a.copy()
    df_b = df_b.copy()

    df_a["from"] = _norm_addr(df_a["from"])
    df_a["to"] = _norm_addr(df_a["to"])
    df_b["from"] = _norm_addr(df_b["from"])
    df_b["to"] = _norm_addr(df_b["to"])

    wa = wallet_a.strip().lower()
    wb = wallet_b.strip().lower()

    in_a = df_a[df_a["to"] == wa].copy()
    in_b = df_b[df_b["to"] == wb].copy()

    grp_a = in_a.groupby("from", as_index=False)["amount"].sum().rename(columns={"amount": "SumA"})
    grp_b = in_b.groupby("from", as_index=False)["amount"].sum().rename(columns={"amount": "SumB"})

    set_a = set(grp_a["from"])
    set_b = set(grp_b["from"])
    inter = set_a & set_b

    map_a = dict(zip(grp_a["from"], grp_a["SumA"]))
    map_b = dict(zip(grp_b["from"], grp_b["SumB"]))

    # для быстрого доступа к хешам: первый hash на адрес
    hash_a_map = {}
    if not in_a.empty:
        tmp = in_a[["from", "hash"]].dropna()
        if not tmp.empty:
            hash_a_map = tmp.groupby("from")["hash"].first().to_dict()

    hash_b_map = {}
    if not in_b.empty:
        tmp = in_b[["from", "hash"]].dropna()
        if not tmp.empty:
            hash_b_map = tmp.groupby("from")["hash"].first().to_dict()

    rows = []
    for addr in inter:
        rows.append({
            "From": addr,
            "SumA": map_a.get(addr, 0.0),
            "SumB": map_b.get(addr, 0.0),
            "Total": map_a.get(addr, 0.0) + map_b.get(addr, 0.0),
            "ExampleHashA": hash_a_map.get(addr, ""),
            "ExampleHashB": hash_b_map.get(addr, ""),
        })

    inter_df = pd.DataFrame(rows).sort_values("Total", ascending=False)

    sum_a = float(sum(map_a.get(a, 0.0) for a in inter))
    sum_b = float(sum(map_b.get(a, 0.0) for a in inter))

    # форматирование для UI
    if not inter_df.empty:
        inter_df["SumA"] = inter_df["SumA"].map(fmt_num_ru)
        inter_df["SumB"] = inter_df["SumB"].map(fmt_num_ru)
        inter_df["Total"] = inter_df["Total"].map(fmt_num_ru)

    return {
        "intersection_count": len(inter),
        "sum_a": sum_a,
        "sum_b": sum_b,
        "sum_a_fmt": fmt_num_ru(sum_a),
        "sum_b_fmt": fmt_num_ru(sum_b),
        "intersection_df": inter_df
    }



def build_excel_intersection_report(rep: dict) -> bytes:

    out = BytesIO()

    with pd.ExcelWriter(out, engine="openpyxl") as writer:

        summary = pd.DataFrame([{
            "IntersectionCount": rep["intersection_count"],
            "SumOnWalletA": rep["sum_a"],
            "SumOnWalletB": rep["sum_b"],
        }])

        summary.to_excel(writer, sheet_name="Summary", index=False)
        rep["intersection_df"].to_excel(writer, sheet_name="Intersection", index=False)

    out.seek(0)
    return out.read()


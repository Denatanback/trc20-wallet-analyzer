import io
import re
import pandas as pd
import numpy as np


# -------------------------
# Helpers
# -------------------------
def normalize_wallet(x: str) -> str:
    if x is None:
        return ""
    s = str(x).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s


def fmt_num_ru(x) -> str:
    """
    Формат без пробелов, с запятой как десятичным разделителем.
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "0"
    try:
        v = float(x)
    except Exception:
        return str(x)
    # если целое — без .0
    if abs(v - int(v)) < 1e-9:
        return str(int(v))
    s = f"{v:.8f}".rstrip("0").rstrip(".")  # убираем хвост
    return s.replace(".", ",")


def to_number_series(s: pd.Series) -> pd.Series:
    """
    Превращает строковую сумму в float:
    - убирает пробелы
    - заменяет запятую на точку
    - убирает валютные символы
    """
    if s is None:
        return pd.Series(dtype=float)
    x = s.astype(str).str.replace(" ", "", regex=False)
    x = x.str.replace("\u00a0", "", regex=False)  # non-breaking space
    x = x.str.replace(",", ".", regex=False)
    # оставим цифры, точку, минус, экспоненту
    x = x.str.replace(r"[^0-9eE\.\-+]", "", regex=True)
    return pd.to_numeric(x, errors="coerce").fillna(0.0)


def load_csv_any(uploaded_file) -> pd.DataFrame:
    """
    Умеет читать CSV с разными разделителями.
    """
    raw = uploaded_file.read()
    # попробуем utf-8, если нет — latin-1
    for enc in ["utf-8", "utf-8-sig", "cp1251", "latin-1"]:
        try:
            text = raw.decode(enc)
            break
        except Exception:
            text = None
    if text is None:
        # fallback
        text = raw.decode("latin-1", errors="ignore")

    # Попробуем разные сепараторы
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep)
            if df.shape[1] >= 3:
                return df
        except Exception:
            pass

    # последний шанс (pandas сам определит)
    return pd.read_csv(io.StringIO(text))


def detect_columns(df: pd.DataFrame) -> dict:
    """
    Находит названия колонок по типовым вариантам.
    Возвращает dict: from,to,amount,hash
    """
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(candidates):
        for cand in candidates:
            for k, orig in cols.items():
                if k == cand:
                    return orig
        # contains match
        for cand in candidates:
            for k, orig in cols.items():
                if cand in k:
                    return orig
        return None

    from_col = pick(["from", "sender", "source", "address_from", "wallet_from", "from_address"])
    to_col = pick(["to", "receiver", "destination", "address_to", "wallet_to", "to_address"])
    amount_col = pick(["amount", "value", "sum", "quantity", "tokenvalue", "usd", "volume"])
    hash_col = pick(["hash", "txhash", "transactionhash", "tx_hash", "transaction_id", "txid", "id"])

    # если чего-то не нашли — попробуем эвристики
    if from_col is None:
        # первая колонка, где много похоже на адреса
        from_col = df.columns[0]
    if to_col is None:
        to_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    if amount_col is None:
        # первая числовая
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):
                amount_col = c
                break
        if amount_col is None and len(df.columns) > 2:
            amount_col = df.columns[2]
        elif amount_col is None:
            amount_col = df.columns[-1]
    if hash_col is None:
        hash_col = None  # не обязателен

    return {"from": from_col, "to": to_col, "amount": amount_col, "hash": hash_col}


def _prepare_df(df: pd.DataFrame, cols: dict, abs_amount: bool) -> pd.DataFrame:
    out = df.copy()

    out["_from"] = out[cols["from"]].astype(str).map(normalize_wallet)
    out["_to"] = out[cols["to"]].astype(str).map(normalize_wallet)

    # amount
    if pd.api.types.is_numeric_dtype(out[cols["amount"]]):
        amt = pd.to_numeric(out[cols["amount"]], errors="coerce").fillna(0.0)
    else:
        amt = to_number_series(out[cols["amount"]])

    if abs_amount:
        amt = amt.abs()

    out["_amount"] = amt

    if cols.get("hash") and cols["hash"] in out.columns:
        out["_hash"] = out[cols["hash"]].astype(str)
    else:
        out["_hash"] = ""

    return out


# -------------------------
# Reports
# -------------------------
def build_single_wallet_report(df: pd.DataFrame, wallet: str, cols: dict, include_fee: bool, abs_amount: bool) -> dict:
    w = normalize_wallet(wallet)
    t = _prepare_df(df, cols, abs_amount=abs_amount)

    inbound = t[t["_to"] == w].copy()
    outbound = t[t["_from"] == w].copy()

    # В этой версии fee отдельно не считаем, но оставили флаг на будущее.
    in_sum = float(inbound["_amount"].sum())
    out_sum = float(outbound["_amount"].sum())
    in_count = int(len(inbound))
    out_count = int(len(outbound))

    # Группировка по отправителям (вход)
    grp = inbound.groupby("_from", as_index=False)["_amount"].sum()
    grp = grp.sort_values("_amount", ascending=False)

    total_in = in_sum if in_sum != 0 else 1.0
    top5_sum = float(grp.head(5)["_amount"].sum()) if len(grp) else 0.0
    top5_pct = (top5_sum / total_in) * 100.0

    top10 = grp.head(10).copy()
    top10["SharePctOfInbound"] = (top10["_amount"] / total_in) * 100.0
    top10.rename(columns={"_from": "From", "_amount": "Sum"}, inplace=True)

    # форматирование
    top10["Sum"] = top10["Sum"].map(fmt_num_ru)
    top10["SharePctOfInbound"] = top10["SharePctOfInbound"].map(lambda x: f"{x:.4f}".replace(".", ","))

    notes = (
        f"- Уникальных отправителей (вход): {len(grp)}\n"
        f"- Total inbound для долей: {fmt_num_ru(in_sum)}\n"
        f"- Сравнение адресов: lower+trim, без пробелов.\n"
    )

    return {
        "in_sum": in_sum,
        "in_count": in_count,
        "top5_pct": top5_pct,
        "out_sum": out_sum,
        "out_count": out_count,
        "top10_df": top10,
        "notes": notes,
    }


def compare_periods_report(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    wallet: str,
    cols_old: dict,
    cols_new: dict,
    include_fee: bool,
    abs_amount: bool,
) -> dict:
    w = normalize_wallet(wallet)
    oldt = _prepare_df(df_old, cols_old, abs_amount=abs_amount)
    newt = _prepare_df(df_new, cols_new, abs_amount=abs_amount)

    old_in = oldt[oldt["_to"] == w].copy()
    new_in = newt[newt["_to"] == w].copy()

    old_grp = old_in.groupby("_from", as_index=False)["_amount"].sum().rename(columns={"_amount": "OldSum"})
    new_grp = new_in.groupby("_from", as_index=False)["_amount"].sum().rename(columns={"_amount": "NewSum"})

    old_set = set(old_grp["_from"].tolist())
    new_set = set(new_grp["_from"].tolist())

    new_only = new_set - old_set
    old_only = old_set - new_set
    both = old_set & new_set

    # суммы по группам
    old_map = dict(zip(old_grp["_from"], old_grp["OldSum"]))
    new_map = dict(zip(new_grp["_from"], new_grp["NewSum"]))

    new_sum = float(sum(new_map.get(a, 0.0) for a in new_only))
    lost_sum = float(sum(old_map.get(a, 0.0) for a in old_only))
    persistent_sum = float(sum(new_map.get(a, 0.0) for a in both))  # сумма в новом периоде для постоянных

    # таблицы
    new_df = pd.DataFrame(
        [{"From": a, "Sum": new_map.get(a, 0.0)} for a in new_only]
    ).sort_values("Sum", ascending=False)
    persistent_df = pd.DataFrame(
        [{"From": a, "OldSum": old_map.get(a, 0.0), "NewSum": new_map.get(a, 0.0)} for a in both]
    ).sort_values("NewSum", ascending=False)
    lost_df = pd.DataFrame(
        [{"From": a, "Sum": old_map.get(a, 0.0)} for a in old_only]
    ).sort_values("Sum", ascending=False)

    # форматирование
    if not new_df.empty:
        new_df["Sum"] = new_df["Sum"].map(fmt_num_ru)
    if not lost_df.empty:
        lost_df["Sum"] = lost_df["Sum"].map(fmt_num_ru)
    if not persistent_df.empty:
        persistent_df["OldSum"] = persistent_df["OldSum"].map(fmt_num_ru)
        persistent_df["NewSum"] = persistent_df["NewSum"].map(fmt_num_ru)

    notes = (
        f"- Новые: есть в новом, нет в старом.\n"
        f"- Ушедшие: есть в старом, нет в новом.\n"
        f"- Постоянные: есть в обоих; сумма показана в разрезе старый/новый.\n"
    )

    return {
        "new_count": len(new_only),
        "persistent_count": len(both),
        "lost_count": len(old_only),
        "new_sum": new_sum,
        "persistent_sum": persistent_sum,
        "lost_sum": lost_sum,
        "new_df": new_df,
        "persistent_df": persistent_df,
        "lost_df": lost_df,
        "notes": notes,
    }


def intersections_report(
    dfA: pd.DataFrame,
    dfB: pd.DataFrame,
    walletA: str,
    walletB: str,
    colsA: dict,
    colsB: dict,
    include_fee: bool,
    abs_amount: bool,
) -> dict:
    wA = normalize_wallet(walletA)
    wB = normalize_wallet(walletB)

    A = _prepare_df(dfA, colsA, abs_amount=abs_amount)
    B = _prepare_df(dfB, colsB, abs_amount=abs_amount)

    Ain = A[A["_to"] == wA].copy()
    Bin = B[B["_to"] == wB].copy()

    # суммы по отправителям + один пример hash
    def agg_with_hash(x: pd.DataFrame) -> pd.DataFrame:
        gsum = x.groupby("_from", as_index=False)["_amount"].sum().rename(columns={"_amount": "Sum"})
        # берём первый hash на отправителя
        h = x.groupby("_from", as_index=False)["_hash"].first().rename(columns={"_hash": "ExampleHash"})
        out = gsum.merge(h, on="_from", how="left")
        return out

    Aagg = agg_with_hash(Ain).rename(columns={"Sum": "SumA", "ExampleHash": "HashA"})
    Bagg = agg_with_hash(Bin).rename(columns={"Sum": "SumB", "ExampleHash": "HashB"})

    setA = set(Aagg["_from"].tolist())
    setB = set(Bagg["_from"].tolist())
    inter = setA & setB

    inter_df = Aagg[Aagg["_from"].isin(inter)].merge(
        Bagg[Bagg["_from"].isin(inter)], on="_from", how="inner"
    )

    inter_df["TotalSum"] = inter_df["SumA"].fillna(0.0) + inter_df["SumB"].fillna(0.0)

    # один hash "на 1 транзакцию" — покажем HashA, если пусто, то HashB
    inter_df["AnyExampleHash"] = inter_df["HashA"].where(inter_df["HashA"].astype(str).str.len() > 0, inter_df["HashB"])

    inter_df = inter_df.sort_values("TotalSum", ascending=False)
    inter_df.rename(columns={"_from": "From"}, inplace=True)

    # формат
    for c in ["SumA", "SumB", "TotalSum"]:
        if c in inter_df.columns:
            inter_df[c] = inter_df[c].map(fmt_num_ru)

    # порядок колонок
    keep = ["From", "SumA", "SumB", "TotalSum", "AnyExampleHash", "HashA", "HashB"]
    keep = [c for c in keep if c in inter_df.columns]
    inter_df = inter_df[keep]

    notes = (
        f"- Пересечение считается по отправителям (From), которые отправляли на To=кошелёк A в CSV#1 и на To=кошелёк B в CSV#2.\n"
        f"- AnyExampleHash: пример хеша одной транзакции (берём первый найденный).\n"
    )

    return {
        "intersection_count": int(len(inter_df)),
        "intersection_df": inter_df,
        "notes": notes,
    }

from io import BytesIO

def build_excel_bytes_multi(summary_df: pd.DataFrame, files, wallets, reports) -> bytes:
    """
    Делает Excel:
    - Sheet 'Summary'
    - Для каждого (файл+кошелёк): отдельный лист
    """
    out = BytesIO()

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        # Summary sheet
        s = summary_df.copy()
        # prettier formatting for excel (still store as numbers where possible)
        s.to_excel(writer, sheet_name="Summary", index=False)

        # Per wallet sheets
        for i in range(len(files)):
            fname = files[i].name
            wallet = wallets[i]
            rep = reports[i]

            # sheet name max 31 chars in Excel
            base = f"{i+1}_{fname}"
            sheet_name = re.sub(r"[\[\]\*\?/\\:]", "_", base)[:31]

            # KPI block
            kpi = pd.DataFrame([{
                "File": fname,
                "Wallet": wallet,
                "InboundSum": rep["in_sum"],
                "InboundCount": rep["in_count"],
                "Top5Pct": rep["top5_pct"],
                "OutboundSum": rep["out_sum"],
                "OutboundCount": rep["out_count"],
            }])

            # write KPI
            kpi.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)

            # write Top10 below
            top10 = rep["top10_df"].copy()

            # В top10 у нас строки уже форматированные. Для Excel лучше снова в числа:
            # попробуем восстановить числа из строк вида "123,45"
            def parse_ru_num(x):
                try:
                    return float(str(x).replace(" ", "").replace(",", "."))
                except:
                    return x

            if "Sum" in top10.columns:
                top10["Sum"] = top10["Sum"].map(parse_ru_num)
            if "SharePctOfInbound" in top10.columns:
                top10["SharePctOfInbound"] = top10["SharePctOfInbound"].map(parse_ru_num)

            top10.to_excel(writer, sheet_name=sheet_name, index=False, startrow=4)

        # auto-save
        writer.close()

    out.seek(0)
    return out.read()

import streamlit as st
from datetime import datetime
from tronscan_api import fetch_trc20_transfers
from report_builder import (
    build_wallet_report,
    build_excel_report,
    compare_periods_two_wallets,
    build_excel_compare_report,
)

st.set_page_config(page_title="TRC20 Wallet Analyzer", layout="wide")

st.title("TRC20 Wallet Analyzer (Tronscan API)")
st.caption("Источник: Tronscan → Transfers (TRC20)")

tabs = st.tabs([
    "📊 Отчёт по кошельку",
    "🔄 Сравнение периодов (OLD → NEW)",
    "🧩 Пересечение клиентов"
])


# =========================================================
# TAB 1
# =========================================================
with tabs[0]:

    wallet = st.text_input("Введите кошелек TRON")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Начало периода", key="t1_start")
    with col2:
        end_date = st.date_input("Конец периода", key="t1_end")

    api_key = st.text_input("Tronscan API Key (optional)", type="password", key="t1_api")

    if st.button("Получить отчет", type="primary"):

        if not wallet.strip():
            st.warning("Введите кошелек.")
            st.stop()

        start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp() * 1000)
        end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp() * 1000)

        with st.spinner("Загрузка TRC20 transfers..."):
            df = fetch_trc20_transfers(wallet, start_ts, end_ts, api_key)

        if df.empty:
            st.warning("Данные не найдены.")
            st.stop()

        report = build_wallet_report(df, wallet)

        st.success(f"Загружено {len(df)} transfers")

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Сумма входящих", report["in_sum_fmt"])
        k2.metric("Кол-во входящих", report["in_count"])
        k3.metric("% топ-5", report["top5_pct_fmt"])
        k4.metric("Сумма исходящих", report["out_sum_fmt"])
        k5.metric("Кол-во исходящих", report["out_count"])

        st.divider()
        st.subheader("Топ-10 отправителей (вход)")
        st.dataframe(report["top10_df"], use_container_width=True)

        st.divider()
        excel_bytes = build_excel_report(report)

        st.download_button(
            "Скачать Excel отчет",
            data=excel_bytes,
            file_name="trc20_wallet_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# =========================================================
# TAB 2
# =========================================================
with tabs[1]:

    col1, col2 = st.columns(2)
    with col1:
        old_wallet = st.text_input("OLD кошелек (старый период)", key="old_wallet")
    with col2:
        new_wallet = st.text_input("NEW кошелек (новый период)", key="new_wallet")

    c1, c2 = st.columns(2)
    with c1:
        old_start = st.date_input("Старый период: начало", key="old_start")
        old_end = st.date_input("Старый период: конец", key="old_end")
    with c2:
        new_start = st.date_input("Новый период: начало", key="new_start")
        new_end = st.date_input("Новый период: конец", key="new_end")

    api_key2 = st.text_input("Tronscan API Key (optional)", type="password", key="t2_api")

    if st.button("Сравнить периоды", type="primary"):

        if not old_wallet.strip() or not new_wallet.strip():
            st.warning("Введите оба кошелька.")
            st.stop()

        old_start_ts = int(datetime.combine(old_start, datetime.min.time()).timestamp() * 1000)
        old_end_ts   = int(datetime.combine(old_end, datetime.max.time()).timestamp() * 1000)
        new_start_ts = int(datetime.combine(new_start, datetime.min.time()).timestamp() * 1000)
        new_end_ts   = int(datetime.combine(new_end, datetime.max.time()).timestamp() * 1000)

        with st.spinner("Загрузка OLD периода..."):
            df_old = fetch_trc20_transfers(old_wallet, old_start_ts, old_end_ts, api_key2)

        with st.spinner("Загрузка NEW периода..."):
            df_new = fetch_trc20_transfers(new_wallet, new_start_ts, new_end_ts, api_key2)

        rep = compare_periods_two_wallets(df_old, df_new, old_wallet, new_wallet)

        a, b, c = st.columns(3)
        a.metric("Новые отправители", rep["new_count"])
        b.metric("Постоянные", rep["persistent_count"])
        c.metric("Ушедшие", rep["lost_count"])

        st.divider()
        s1, s2, s3 = st.columns(3)
        s1.metric("Сумма от новых (NEW)", rep["new_sum_fmt"])
        s2.metric("Сумма постоянных (NEW)", rep["persistent_sum_new_fmt"])
        s3.metric("Сумма ушедших (OLD)", rep["lost_sum_fmt"])

        st.divider()
        st.subheader("Новые")
        st.dataframe(rep["new_df"], use_container_width=True)

        st.subheader("Постоянные")
        st.dataframe(rep["persistent_df"], use_container_width=True)

        st.subheader("Ушедшие")
        st.dataframe(rep["lost_df"], use_container_width=True)

        st.divider()
        excel_bytes = build_excel_compare_report(rep)

        st.download_button(
            "Скачать Excel сравнение",
            data=excel_bytes,
            file_name="trc20_compare_old_new.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
# =========================================================
# TAB 3 — INTERSECTIONS
# =========================================================
with tabs[2]:

    st.subheader("Пересечение отправителей (клиентов)")

    col1, col2 = st.columns(2)
    with col1:
        wallet_a = st.text_input("Кошелёк A", key="int_wallet_a")
    with col2:
        wallet_b = st.text_input("Кошелёк B", key="int_wallet_b")

    c1, c2 = st.columns(2)
    with c1:
        start_a = st.date_input("Период A: начало", key="int_start_a")
        end_a = st.date_input("Период A: конец", key="int_end_a")
    with c2:
        start_b = st.date_input("Период B: начало", key="int_start_b")
        end_b = st.date_input("Период B: конец", key="int_end_b")

    api_key3 = st.text_input("Tronscan API Key (optional)", type="password", key="t3_api")

    if st.button("Проверить пересечение", type="primary"):

        if not wallet_a.strip() or not wallet_b.strip():
            st.warning("Введите оба кошелька.")
            st.stop()

        start_a_ts = int(datetime.combine(start_a, datetime.min.time()).timestamp() * 1000)
        end_a_ts   = int(datetime.combine(end_a,   datetime.max.time()).timestamp() * 1000)

        start_b_ts = int(datetime.combine(start_b, datetime.min.time()).timestamp() * 1000)
        end_b_ts   = int(datetime.combine(end_b,   datetime.max.time()).timestamp() * 1000)

        with st.spinner("Загрузка кошелька A..."):
            df_a = fetch_trc20_transfers(wallet_a, start_a_ts, end_a_ts, api_key3)

        with st.spinner("Загрузка кошелька B..."):
            df_b = fetch_trc20_transfers(wallet_b, start_b_ts, end_b_ts, api_key3)

        from report_builder import build_intersection_report, build_excel_intersection_report

        rep = build_intersection_report(df_a, df_b, wallet_a, wallet_b)

        st.success(f"Найдено пересечений: {rep['intersection_count']}")

        k1, k2 = st.columns(2)
        k1.metric("Сумма на A", rep["sum_a_fmt"])
        k2.metric("Сумма на B", rep["sum_b_fmt"])

        st.divider()
        st.dataframe(rep["intersection_df"], use_container_width=True)

        st.divider()
        excel_bytes = build_excel_intersection_report(rep)

        st.download_button(
            "Скачать Excel пересечения",
            data=excel_bytes,
            file_name="trc20_intersections.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

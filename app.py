import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from bs4 import BeautifulSoup
from supabase import create_client


st.set_page_config(
    page_title="旅伴帳本｜基礎測試版",
    page_icon="✳",
    layout="centered",
)

CURRENCIES = {
    "TWD": "新台幣",
    "JPY": "日圓",
    "KRW": "韓元",
    "USD": "美元",
    "CNY": "人民幣",
    "THB": "泰銖",
    "HKD": "港幣",
    "EUR": "歐元",
}

RATE_FIELDS = {
    "現金賣出": "本行現金賣出",
    "即期賣出": "本行即期賣出",
}


def get_supabase_client():
    """
    為目前 Streamlit 工作階段建立獨立 client。

    不使用全域快取，避免將登入 client 共用給不同使用者。
    """
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_PUBLISHABLE_KEY"],
    )


def taipei_now():
    return datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d %H:%M:%S")


def read_bot_rates():
    """
    讀取台灣銀行公開牌告網頁。

    網頁格式變更、服務暫停或連線失敗時可能無法解析。
    此函式不保證交易匯率，也不提供即時推播。
    """
    url = "https://rate.bot.com.tw/xrt?Lang=zh-TW"

    response = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "TravelLedgerPrototype/1.0"},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    rates = {}

    for row in soup.select("tr"):
        text = row.get_text(" ", strip=True)
        match = re.search(r"\b(USD|HKD|JPY|THB|EUR|KRW|CNY)\b", text)

        if not match:
            continue

        code = match.group(1)
        parsed = {}

        for label, attribute in RATE_FIELDS.items():
            cell = row.select_one(
                f'td[data-table="{attribute}"]'
            )

            if cell:
                value = cell.get_text(strip=True)

                try:
                    parsed[label] = Decimal(value)
                except InvalidOperation:
                    parsed[label] = None
            else:
                parsed[label] = None

        rates[code] = parsed

    if not rates:
        raise ValueError("未能解析銀行匯率資料。")

    time_element = soup.select_one("span.time")

    quote_time = (
        time_element.get_text(" ", strip=True)
        if time_element
        else "未能從網頁解析，請至台灣銀行網站確認"
    )

    return {
        "rates": rates,
        "quote_time": quote_time,
        "fetched_at": taipei_now(),
    }


def show_login():
    st.caption("TRAVEL TOGETHER")
    st.title("旅伴帳本")
    st.write("先建立您的旅程，讓我們逐步完成共同記帳。")

    st.warning(
        "這是基礎測試版：尚未提供共同記帳、"
        "旅伴邀請、私人帳目或分帳結算。"
    )

    with st.form("login_form"):
        email = st.text_input("電子郵件")
        password = st.text_input("密碼", type="password")

        submitted = st.form_submit_button(
            "登入",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return

    if not email.strip() or not password:
        st.warning("請輸入電子郵件和密碼。")
        return

    try:
        client = get_supabase_client()

        result = client.auth.sign_in_with_password(
            {
                "email": email.strip(),
                "password": password,
            }
        )

        if not result.session or not result.user:
            st.error("登入未完成，請確認帳號狀態。")
            return

        st.session_state["client"] = client
        st.session_state["user_email"] = result.user.email

        st.rerun()

    except Exception:
        st.error(
            "登入失敗。請確認帳號、密碼、"
            "信箱驗證狀態及 Supabase 設定。"
        )


def show_trips(client):
    st.subheader("我的旅程")
    st.caption("目前只能建立及查看自己建立的測試旅程。")

    with st.expander("＋ 建立旅程"):
        with st.form("new_trip_form"):
            name = st.text_input(
                "旅程名稱",
                max_chars=40,
                placeholder="例如：日本關西旅行",
            )

            create = st.form_submit_button("建立旅程")

        if create:
            name = name.strip()

            if not name:
                st.warning("請輸入旅程名稱。")
            else:
                try:
                    session = client.auth.get_session()

                    if not session:
                        st.error("登入狀態已失效，請重新登入。")
                        return

                    client.table("prototype_trips").insert(
                        {"name": name}
                    ).execute()

                    st.success("旅程已建立。")
                    st.rerun()

                except Exception:
                    st.error(
                        "建立失敗。請檢查登入狀態、"
                        "資料表與權限設定。"
                    )

    try:
        session = client.auth.get_session()

        if not session:
            st.warning("登入狀態已失效，請重新登入。")
            return

        result = (
            client.table("prototype_trips")
            .select("id,name,created_at")
            .order("created_at", desc=True)
            .execute()
        )

        trips = result.data or []

    except Exception:
        st.error(
            "讀取旅程失敗。請檢查 Supabase 連線與權限。"
        )
        return

    if not trips:
        st.info("目前還沒有旅程，可以先建立一個。")
        return

    for trip in trips:
        with st.container(border=True):
            # 使用 Streamlit 原生文字元件，不把名稱當成 HTML。
            st.subheader(trip["name"])
            st.caption("測試旅程｜記帳功能尚未加入")


def show_rates():
    st.subheader("台灣銀行參考匯率")

    st.caption(
        "此處僅供查詢，不會寫入旅程或作為分帳匯率。"
        "實際交易匯率可能不同。"
    )

    if st.button("取得最新可用牌告", use_container_width=True):
        try:
            st.session_state["bot_rates"] = read_bot_rates()
        except Exception:
            st.error(
                "目前無法取得或解析台灣銀行資料。"
                "請稍後再試，或直接到台灣銀行官網確認。"
            )

    snapshot = st.session_state.get("bot_rates")

    if not snapshot:
        st.info("點選上方按鈕取得匯率。")
        return

    st.caption(f"銀行掛牌時間：{snapshot['quote_time']}")
    st.caption(f"程式取得時間：{snapshot['fetched_at']}（台北時間）")

    code = st.selectbox(
        "選擇幣別",
        list(CURRENCIES.keys()),
        format_func=lambda value: (
            f"{CURRENCIES[value]}（{value}）"
        ),
    )

    if code == "TWD":
        st.write("新台幣換算新台幣：1 TWD = 1 TWD")
        return

    rate_type = st.selectbox(
        "牌告種類",
        ["現金賣出", "即期賣出"],
    )

    rate = snapshot["rates"].get(code, {}).get(rate_type)

    if rate is None:
        st.warning(
            f"目前取得的資料沒有 {code} 的{rate_type}報價。"
            "請改選其他報價種類或到銀行官網確認。"
        )
        return

    st.metric(
        label=f"1 {code} 約為",
        value=f"NT$ {rate}",
    )

    amount_text = st.text_input(
        f"試算金額（{code}）",
        value="100",
    )

    try:
        amount = Decimal(amount_text.strip())

        if not amount.is_finite() or amount < 0:
            raise InvalidOperation

        estimate = amount * rate

        st.write(
            f"參考換算：{amount:,.2f} {code} "
            f"約為 NT$ {estimate:,.2f}"
        )

    except InvalidOperation:
        st.warning("請輸入有效、非負數的金額。")


def main():
    try:
        _ = st.secrets["SUPABASE_URL"]
        _ = st.secrets["SUPABASE_PUBLISHABLE_KEY"]
    except Exception:
        st.error(
            "缺少 Supabase 設定。"
            "請到 Streamlit 的 Secrets 設定填入連線資料。"
        )
        return

    client = st.session_state.get("client")

    if client is None:
        show_login()
        return

    st.caption("TRAVEL TOGETHER")
    st.title("旅伴帳本")
    st.caption(
        f"目前登入：{st.session_state.get('user_email', '')}"
    )

    if st.button("登出"):
        try:
            client.auth.sign_out()
        except Exception:
            pass

        st.session_state.pop("client", None)
        st.session_state.pop("user_email", None)
        st.session_state.pop("bot_rates", None)
        st.rerun()

    st.warning(
        "基礎測試版：尚未加入共同記帳、旅伴邀請、"
        "私人帳目、多人同步與分帳。請勿輸入正式旅遊資料。"
    )

    page = st.radio(
        "選擇功能",
        ["我的旅程", "參考匯率"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if page == "我的旅程":
        show_trips(client)
    else:
        show_rates()


if __name__ == "__main__":
    main()

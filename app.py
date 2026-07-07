from pathlib import Path
import os

import streamlit as st
from openai import OpenAI


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.yaml"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-2.0-flash"


st.set_page_config(page_title="住宅購入ナビAI", page_icon="🏠", layout="wide")
st.title("住宅購入ナビAI（MVP）")
st.caption("住宅購入の進行状況に応じて、次にやることとリスクをAIが整理します。")


def bool_to_text(value: bool) -> str:
    return "済" if value else "未"


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, str]:
    settings: dict[str, str] = {}
    if not path.exists():
        return settings

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue

        key, value = line.split(":", 1)
        settings[key.strip()] = value.strip().strip('"').strip("'")

    return settings


def get_api_key() -> str:
    settings = load_settings()
    return (
        settings.get("api_key", "")
        or os.getenv("GEMINI_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    )


def build_system_prompt(
    contract: bool,
    loan: bool,
    kinko: bool,
    insurance: bool,
    address: bool,
    date: str,
) -> str:
    return f"""あなたは住宅購入の専門ナビゲーターです。

以下の状況をもとに、ユーザーの質問に答えながら、次にやるべきこととリスクを整理してください。

# 状況

* 売買契約: {bool_to_text(contract)}
* 本審査: {bool_to_text(loan)}
* 金消: {bool_to_text(kinko)}
* 火災保険: {bool_to_text(insurance)}
* 住民票: {bool_to_text(address)}
* 決済日: {date}

# 出力形式

1. 次にやること（優先度順）
2. リスク（重要なものから）
3. 補足説明（簡潔に）

必要なら、前回までの会話を踏まえて補足してください。"""


def get_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)


def chat_with_gemini(api_key: str, messages: list[dict[str, str]]) -> str:
    client = get_client(api_key)
    response = client.chat.completions.create(
        model=GEMINI_MODEL,
        messages=messages,
        temperature=0.3,
    )
    content = response.choices[0].message.content or ""
    return content.strip()


if "messages" not in st.session_state:
    st.session_state.messages = []


left_col, center_col, right_col = st.columns([1, 1.2, 1.2])

with left_col:
    st.subheader("状態入力")
    contract = st.checkbox("売買契約済", value=False)
    loan = st.checkbox("本審査済", value=False)
    kinko = st.checkbox("金消済", value=False)
    insurance = st.checkbox("火災保険済", value=False)
    address = st.checkbox("住民票移動済", value=False)
    settlement_date = st.date_input("決済日")

    if st.button("会話をリセット"):
        st.session_state.messages = []
        st.rerun()

with center_col:
    st.subheader("チャット")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("今の状況で気になることを入力してください")

with right_col:
    st.subheader("出力表示")

    latest_assistant_message = next(
        (message["content"] for message in reversed(st.session_state.messages) if message["role"] == "assistant"),
        "ここにAIの回答が表示されます。",
    )
    st.markdown(latest_assistant_message)


if question:
    api_key = get_api_key()
    if not api_key:
        st.error("settings.yaml に api_key が設定されていません。settings_template.yaml を参考に設定してください。")
    else:
        try:
            st.session_state.messages.append({"role": "user", "content": question.strip()})
            prompt_messages = [
                {
                    "role": "system",
                    "content": build_system_prompt(
                        contract=contract,
                        loan=loan,
                        kinko=kinko,
                        insurance=insurance,
                        address=address,
                        date=str(settlement_date),
                    ),
                },
                *st.session_state.messages,
            ]
            answer = chat_with_gemini(api_key, prompt_messages)
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.rerun()
        except Exception as exc:
            st.session_state.messages.pop()
            st.error(f"AI呼び出しに失敗しました。時間をおいて再実行してください。\n\n詳細: {exc}")



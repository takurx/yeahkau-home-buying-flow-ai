from pathlib import Path
import json
import os
from urllib import error, request
from urllib.parse import urlencode

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.yaml"
DEFAULT_VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
DEFAULT_VERTEX_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_OPENAI_COMPAT_MODEL = os.getenv("OPENAI_COMPAT_MODEL", "anthropic/claude-opus-4.7")


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


def resolve_project_id(settings: dict[str, str]) -> str:
    project_name = settings.get("project_name", "")
    if project_name.startswith("projects/"):
        return project_name.split("/", 1)[1]

    return (
        settings.get("project_id", "")
        or settings.get("project_number", "")
        or os.getenv("VERTEX_PROJECT_ID", "")
    )


def get_vertex_config() -> dict[str, str]:
    settings = load_settings()
    return {
        "api_key": settings.get("api_key", "") or os.getenv("GEMINI_API_KEY", ""),
        "project_id": resolve_project_id(settings),
        "location": settings.get("location", "") or DEFAULT_VERTEX_LOCATION,
        "model": settings.get("model", "") or DEFAULT_VERTEX_MODEL,
    }


def _parse_model_options(model_options_text: str) -> list[str]:
    options = [item.strip() for item in model_options_text.split(",") if item.strip()]
    return options


def get_llm_config() -> dict[str, str | list[str]]:
    settings = load_settings()
    backend = (settings.get("llm_backend", "vertex") or "vertex").strip().lower()
    vertex_model = settings.get("model", "") or DEFAULT_VERTEX_MODEL
    model_options = _parse_model_options(settings.get("model_options", ""))

    if not model_options:
        model_options = [
            vertex_model,
            "anthropic/claude-opus-4.7",
            "x-ai/grok-4.20",
        ]

    return {
        "backend": backend,
        "vertex_api_key": settings.get("api_key", "") or os.getenv("GEMINI_API_KEY", ""),
        "vertex_project_id": resolve_project_id(settings),
        "vertex_location": settings.get("location", "") or DEFAULT_VERTEX_LOCATION,
        "vertex_model": vertex_model,
        "openai_compat_api_key": (
            settings.get("openai_compat_api_key", "")
            or settings.get("openrouter_api_key", "")
            or os.getenv("OPENAI_COMPAT_API_KEY", "")
            or os.getenv("OPENROUTER_API_KEY", "")
        ),
        "openai_compat_base_url": settings.get("openai_compat_base_url", "") or DEFAULT_OPENAI_COMPAT_BASE_URL,
        "openai_compat_model": settings.get("openai_compat_model", "") or DEFAULT_OPENAI_COMPAT_MODEL,
        "model_options": model_options,
    }


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


def _build_vertex_contents(messages: list[dict[str, str]]) -> list[dict]:
    contents: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "").strip()
        if not content or role not in {"user", "assistant"}:
            continue

        vertex_role = "model" if role == "assistant" else "user"
        contents.append({"role": vertex_role, "parts": [{"text": content}]})

    return contents


def _extract_vertex_text(response_json: dict) -> str:
    candidates = response_json.get("candidates", [])
    if not candidates:
        return ""

    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    return "\n".join(text for text in texts if text).strip()


def _build_openai_compat_messages(system_prompt: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    out = [{"role": "system", "content": system_prompt}]
    for message in messages:
        role = message.get("role")
        content = message.get("content", "").strip()
        if not content or role not in {"user", "assistant"}:
            continue
        out.append({"role": role, "content": content})
    return out


def _extract_error_message(body: str, fallback: str) -> str:
    try:
        parsed = json.loads(body)
        return parsed.get("error", {}).get("message", fallback)
    except json.JSONDecodeError:
        return body or fallback


def chat_with_vertex(
    api_key: str,
    project_id: str,
    location: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    url = (
        f"https://{host}/v1/projects/{project_id}/"
        f"locations/{location}/publishers/google/models/{model}:generateContent"
        f"?{urlencode({'key': api_key})}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": _build_vertex_contents(messages),
        "generationConfig": {"temperature": 0.3},
    }

    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as res:
            body = res.read().decode("utf-8")
            parsed = json.loads(body)
            content = _extract_vertex_text(parsed)
            return content or "回答を取得できませんでした。"
    except error.HTTPError as http_err:
        body = http_err.read().decode("utf-8", errors="ignore") if http_err.fp else ""
        message = _extract_error_message(body, f"HTTP {http_err.code}")
        raise RuntimeError(f"Error code: {http_err.code} - {message}") from http_err
    except error.URLError as url_err:
        raise RuntimeError(f"ネットワークエラー: {url_err.reason}") from url_err


def chat_with_openai_compatible(
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    base = base_url.rstrip("/")
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": _build_openai_compat_messages(system_prompt, messages),
        "temperature": 0.3,
    }
    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as res:
            body = res.read().decode("utf-8")
            parsed = json.loads(body)
            content = parsed.get("choices", [{}])[0].get("message", {}).get("content", "")
            return (content or "回答を取得できませんでした。").strip()
    except error.HTTPError as http_err:
        body = http_err.read().decode("utf-8", errors="ignore") if http_err.fp else ""
        message = _extract_error_message(body, f"HTTP {http_err.code}")
        raise RuntimeError(f"Error code: {http_err.code} - {message}") from http_err
    except error.URLError as url_err:
        raise RuntimeError(f"ネットワークエラー: {url_err.reason}") from url_err


if "messages" not in st.session_state:
    st.session_state.messages = []


llm_config = get_llm_config()
selected_backend = str(llm_config["backend"])
model_options = [str(item) for item in llm_config["model_options"]]
if "selected_model" not in st.session_state:
    if selected_backend == "openai_compatible":
        st.session_state.selected_model = str(llm_config["openai_compat_model"])
    else:
        st.session_state.selected_model = str(llm_config["vertex_model"])

if st.session_state.selected_model not in model_options:
    model_options = [st.session_state.selected_model, *model_options]


left_col, center_col, right_col = st.columns([1, 1.2, 1.2])

with left_col:
    st.subheader("状態入力")
    st.caption(f"バックエンド: {selected_backend}")
    st.session_state.selected_model = st.selectbox(
        "モデル",
        options=model_options,
        index=model_options.index(st.session_state.selected_model),
    )
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
    system_prompt = build_system_prompt(
        contract=contract,
        loan=loan,
        kinko=kinko,
        insurance=insurance,
        address=address,
        date=str(settlement_date),
    )

    try:
        st.session_state.messages.append({"role": "user", "content": question.strip()})
        selected_model = str(st.session_state.selected_model)

        if selected_backend == "openai_compatible":
            api_key = str(llm_config["openai_compat_api_key"])
            base_url = str(llm_config["openai_compat_base_url"])
            if not api_key:
                raise RuntimeError(
                    "settings.yaml に openai_compat_api_key を設定してください。"
                    "\nOpenRouter を使う場合は openrouter_api_key でも可。"
                )

            answer = chat_with_openai_compatible(
                api_key=api_key,
                base_url=base_url,
                model=selected_model,
                system_prompt=system_prompt,
                messages=st.session_state.messages,
            )
        else:
            api_key = str(llm_config["vertex_api_key"])
            project_id = str(llm_config["vertex_project_id"])
            location = str(llm_config["vertex_location"])

            if not api_key:
                raise RuntimeError("settings.yaml に api_key が設定されていません。settings_template.yaml を参考に設定してください。")
            if not project_id:
                raise RuntimeError(
                    "settings.yaml に project_id または project_number または project_name を設定してください。"
                    "\n例: project_id: your-gcp-project-id"
                )

            answer = chat_with_vertex(
                api_key=api_key,
                project_id=project_id,
                location=location,
                model=selected_model,
                system_prompt=system_prompt,
                messages=st.session_state.messages,
            )

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()
    except Exception as exc:
        st.session_state.messages.pop()
        st.error(f"AI呼び出しに失敗しました。時間をおいて再実行してください。\n\n詳細: {exc}")



# Product-grade visual identity (Neon P2, 2026-11-20)।
# apply_pro_theme() app শুরুর দিকে একবার call হবে; welcome screen শুধু
# খালি chat-এ দেখায় এবং বেছে নেওয়া starter prompt ফেরত দেয়।
import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
.stDeployButton { display: none; }
header[data-testid="stHeader"] {
    background: rgba(11,15,25,0.75);
    backdrop-filter: blur(12px);
}
.block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 1200px; }
[data-testid="stChatMessage"] {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: rgba(99,102,241,0.10);
    border: 1px solid rgba(99,102,241,0.25);
}
[data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,0.08); }
.stButton > button {
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.10);
    transition: all 0.2s ease;
}
.stButton > button:hover {
    border-color: #6366F1;
    background: rgba(99,102,241,0.12);
    transform: translateY(-1px);
}
.hero-title {
    font-size: 2.1rem; font-weight: 700; line-height: 1.25;
    background: linear-gradient(90deg, #FFFFFF, #A5B4FC);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.4rem;
}
.hero-sub { color: #9CA3AF; font-size: 0.98rem; margin-bottom: 1.8rem; }
</style>
"""


def apply_pro_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# Starter prompts — যেগুলো বর্তমান chat সত্যিই ভালোভাবে উত্তর দিতে পারে
STARTERS = [
    ("🧠 Memory থেকে উত্তর",
     "আমার CCTI কোর্স কবে শেষ হবে?"),
    ("📚 আমার সম্পর্কে কী জানো?",
     "তোমার long-term memory-তে আমার সম্পর্কে কী কী তথ্য আছে? "
     "সূত্রসহ তালিকা করে দাও।"),
    ("🎬 তুমি কী কী পারো?",
     "তুমি কী কী কাজ করতে পারো — তোমার সব tool আর ক্ষমতার তালিকা "
     "সহজ বাংলায় দাও।"),
    ("💡 Video বানানোর পরিকল্পনা",
     "আমি একটা faceless YouTube video বানাতে চাই। Production Studio "
     "কীভাবে ব্যবহার করব, ধাপে ধাপে বুঝিয়ে দাও।"),
]


def render_empty_welcome_screen():
    """খালি chat-এর welcome hero + starter cards।
    কোনো card চাপলে তার prompt ফেরত দেয়, নইলে None।"""
    st.markdown('<div class="hero-title">আজ কোন মিশনটি সম্পন্ন করব?</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">১৮টি autonomous tool, long-term '
                'memory ও media studio প্রস্তুত। নিচের যেকোনো একটা দিয়েও '
                'শুরু করতে পারো।</div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for idx, (title, prompt) in enumerate(STARTERS):
        with cols[idx % 2]:
            if st.button(f"**{title}**\n\n{prompt}", key=f"starter_{idx}",
                         use_container_width=True):
                return prompt
    return None

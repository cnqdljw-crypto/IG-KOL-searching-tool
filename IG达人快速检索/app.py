import streamlit as st
import requests
import pandas as pd
import statistics
import time
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ====== 读取 Secrets ======
API_TOKEN = st.secrets["APIFY_TOKEN"]
gcp_creds = st.secrets["gcp_service_account"]

# ====== Google Sheets连接 ======
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    dict(gcp_creds), scope
)

client = gspread.authorize(credentials)
sheet = client.open("KOL_DB").sheet1  # 你的表名字

# ====== 配置 ======
CPM_MIN = 10
CPM_MAX = 15
MIN_VIEWS = 10000

MAX_RETRIES = 3
RETRY_DELAY = 2


# ====== 通用请求（带重试）=====
def safe_request(url, payload):
    for _ in range(MAX_RETRIES):
        try:
            res = requests.post(url, json=payload, timeout=20)
            if res.status_code == 200:
                return res.json()
        except:
            pass
        time.sleep(RETRY_DELAY)
    return None


# ====== 读取数据库 ======
def load_db():
    data = sheet.get_all_records()
    return pd.DataFrame(data)


# ====== 写入数据库 ======
def save_to_sheet(row):
    sheet.append_row(row)


# ====== 搜索KOL ======
def search_profiles(keyword):
    url = f"https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    payload = {"hashtags": [keyword.replace(" ", "")], "resultsLimit": 10}

    data = safe_request(url, payload)

    if not isinstance(data, list):
        return []

    return list(set([
        item.get("ownerUsername")
        for item in data
        if isinstance(item, dict) and item.get("ownerUsername")
    ]))


# ====== 获取KOL数据 ======
def get_profile(username, db):

    # ===== 已存在直接用 =====
    if not db.empty and username in db["username"].values:
        return db[db["username"] == username].iloc[0].to_dict()

    # ===== Profile =====
    profile_url = f"https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    profile_data = safe_request(profile_url, {"usernames":[username]})

    if not isinstance(profile_data, list) or len(profile_data) == 0:
        return None

    bio = profile_data[0].get("biography","")
    followers = profile_data[0].get("followersCount",0)

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", bio)
    email = emails[0] if emails else "未找到"

    # ===== Reels =====
    post_url = f"https://api.apify.com/v2/acts/apify~instagram-post-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    posts = safe_request(post_url, {"username":username,"resultsLimit":20})

    if not isinstance(posts, list):
        return None

    views = [
        p.get("videoViewCount", 0)
        for p in posts
        if isinstance(p, dict) and p.get("videoViewCount")
    ]

    if len(views) < 5:
        return None

    avg_views = sum(views)/len(views)
    median_views = statistics.median(views)

    # ===== 写入 Google Sheets =====
    row = [
        username,
        f"https://www.instagram.com/{username}/",
        email,
        followers,
        int(avg_views),
        int(median_views),
        str(pd.Timestamp.now())
    ]

    save_to_sheet(row)

    return {
        "username": username,
        "url": row[1],
        "email": email,
        "followers": followers,
        "avg_views": avg_views,
        "median_views": median_views
    }


# ====== 页面 ======
st.title("📊 Instagram KOL投放工具（安全版）")

menu = st.sidebar.selectbox("功能", ["搜索KOL", "数据库"])

db = load_db()

# ====== 搜索 ======
if menu == "搜索KOL":

    keyword = st.text_input("关键词（如 AI tools）")
    price = st.number_input("达人报价（USD）", value=200)

    if st.button("开始筛选"):

        usernames = search_profiles(keyword)

        results = []

        for u in usernames:
            st.write(f"分析中: {u}")

            data = get_profile(u, db)
            if not data:
                continue

            if data["avg_views"] < MIN_VIEWS:
                continue

            cpm = (price / data["avg_views"]) * 1000
            suggested_price = (data["avg_views"]/1000)*12.5

            status = "✅可合作" if CPM_MIN <= cpm <= CPM_MAX else "❌不建议"

            results.append({
                "账号": f"[打开主页]({data['url']})",
                "邮箱": data["email"],
                "粉丝数": data["followers"],
                "平均播放": int(data["avg_views"]),
                "CPM": round(cpm,2),
                "建议报价": round(suggested_price,2),
                "合作建议": status
            })

            time.sleep(1)

        df = pd.DataFrame(results)
        st.markdown(df.to_markdown(), unsafe_allow_html=True)

# ====== 数据库 ======
elif menu == "数据库":
    st.dataframe(db, use_container_width=True)
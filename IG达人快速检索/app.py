import streamlit as st
import requests
import pandas as pd
import statistics
import time
import os
import re

# ====== API TOKEN（安全方式）======
API_TOKEN = os.getenv("APIFY_TOKEN")

# ====== 配置 ======
DB_FILE = "database.csv"

CPM_MIN = 10
CPM_MAX = 15
MIN_VIEWS = 10000

# ====== 初始化数据库 ======
def load_db():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    else:
        df = pd.DataFrame(columns=[
            "username","url","email","followers",
            "avg_views","median_views","last_updated"
        ])
        df.to_csv(DB_FILE, index=False)
        return df

def save_db(df):
    df.to_csv(DB_FILE, index=False)

db = load_db()

# ====== 搜索KOL ======
def search_profiles(keyword):
    url = f"https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    payload = {
        "hashtags": [keyword.replace(" ", "")],
        "resultsLimit": 10
    }
    res = requests.post(url, json=payload)
    data = res.json()
    return list(set([item["ownerUsername"] for item in data if "ownerUsername" in item]))

# ====== 获取数据（带数据库缓存）=====
def get_profile(username):
    global db

    # 👉 如果数据库已有，直接用（不花钱）
    if username in db["username"].values:
        return db[db["username"] == username].iloc[0].to_dict()

    # ====== API调用 ======
    profile_url = f"https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    res = requests.post(profile_url, json={"usernames":[username]})
    profile_data = res.json()

    if not profile_data:
        return None

    bio = profile_data[0].get("biography","")
    followers = profile_data[0].get("followersCount",0)

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", bio)
    email = emails[0] if emails else "未找到"

    # ====== Reels数据 ======
    post_url = f"https://api.apify.com/v2/acts/apify~instagram-post-scraper/run-sync-get-dataset-items?token={API_TOKEN}"
    res = requests.post(post_url, json={"username":username,"resultsLimit":20})
    posts = res.json()

    views = [p.get("videoViewCount",0) for p in posts if p.get("videoViewCount")]

    if len(views) < 5:
        return None

    avg_views = sum(views)/len(views)
    median_views = statistics.median(views)

    data = {
        "username": username,
        "url": f"https://www.instagram.com/{username}/",
        "email": email,
        "followers": followers,
        "avg_views": avg_views,
        "median_views": median_views,
        "last_updated": pd.Timestamp.now()
    }

    # 👉 写入数据库（关键）
    db = pd.concat([db, pd.DataFrame([data])], ignore_index=True)
    save_db(db)

    return data


# ====== 页面 ======
st.title("📊 Instagram KOL投放工具（AI）")

menu = st.sidebar.selectbox("功能", ["搜索KOL", "历史数据库"])

# ====== 搜索功能 ======
if menu == "搜索KOL":

    keyword = st.text_input("关键词（如 AI tools）")
    price = st.number_input("达人报价（USD）", value=200)

    if st.button("开始筛选"):

        if not API_TOKEN:
            st.error("❌ 请先在 Streamlit Secrets 里配置 APIFY_TOKEN")
            st.stop()

        st.write("🔍 正在搜索KOL...")
        usernames = search_profiles(keyword)

        results = []

        for u in usernames:
            st.write(f"分析中: {u}")

            data = get_profile(u)
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

        if results:
            df = pd.DataFrame(results)

            # 筛选
            show_good = st.checkbox("只看可合作", value=True)
            if show_good:
                df = df[df["合作建议"] == "✅可合作"]

            # 排序
            df = df.sort_values(by="平均播放", ascending=False)

            st.markdown(df.to_markdown(), unsafe_allow_html=True)

        else:
            st.warning("没有符合条件的KOL")


# ====== 数据库 ======
elif menu == "历史数据库":

    st.subheader("📚 KOL资源池")

    if len(db) == 0:
        st.warning("数据库为空")
    else:
        st.dataframe(db, use_container_width=True)
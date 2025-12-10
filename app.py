from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import os, json
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get("APP_SECRET", "super-secret-key")  # 自己換字串更安全


def login_required(fn):
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


DATA_DIR = "data/guild_default"
BOSS_FILE = os.path.join(DATA_DIR, "bosses.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
IMG_DIR = "static/images"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)


def load_bosses():
    if not os.path.exists(BOSS_FILE):
        return []
    try:
        return json.load(open(BOSS_FILE, "r", encoding="utf-8"))
    except:
        return []


def save_bosses(data):
    json.dump(data, open(BOSS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"admin_pw": "0000"}
    return json.load(open(SETTINGS_FILE, "r", encoding="utf-8"))


def save_settings(s):
    json.dump(s, open(SETTINGS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# =======================
#   ★★ 後台登入 ★★
# =======================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("pw")
        settings = load_settings()

        if pw == settings.get("admin_pw"):
            session["logged_in"] = True
            return redirect("/")
        else:
            error = "密碼錯誤"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# -----------------------------
# 時間格式化濾鏡
# -----------------------------
def format_time(t):
    if not t:
        return "00:00:00"
    try:
        h, m, s = map(int, t.split(":"))
        return f"{h:02d}:{m:02d}:{s:02d}"
    except:
        return "00:00:00"


app.jinja_env.filters["format_time"] = format_time


# -----------------------------
# 圖片上傳
# -----------------------------
def save_uploaded_file(file, old_filename=None):

    if not file or file.filename == "":
        return old_filename

    filename = secure_filename(file.filename)
    filepath = os.path.join(IMG_DIR, filename)

    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(filepath):
        filename = f"{base}_{counter}{ext}"
        filepath = os.path.join(IMG_DIR, filename)
        counter += 1

    file.save(filepath)

    if old_filename:
        old_path = os.path.join(IMG_DIR, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass

    return filename


# -----------------------------
# 後台首頁
# -----------------------------
@app.route("/")
@login_required
def index():
    bosses = load_bosses()
    return render_template("index.html", bosses=bosses)


# -----------------------------
# 新增王
# -----------------------------
@app.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":

        bosses = load_bosses()

        short_raw = request.form.get("shortname", "")
        short_list = [s.strip() for s in short_raw.split(",") if s.strip()]

        respawn_type = request.form.get("respawn_type")

        if respawn_type == "cycle":
            respawn_period = (
                f"{request.form.get('respawn_h') or '0'}:"
                f"{request.form.get('respawn_m') or '0'}:"
                f"{request.form.get('respawn_s') or '0'}"
            )
        else:
            fixed_raw = request.form.get("fixed_times", "").strip()
            respawn_period = [
                x.strip() for x in fixed_raw.split(",") if x.strip()
            ]

        new = {
            "name": request.form.get("name"),
            "desc": request.form.get("desc"),
            "shortname": short_list,
            "weekday": request.form.getlist("weekday"),
            "respawn_type": respawn_type,
            "respawn_period": respawn_period,
            "img": "",
            "last_kill": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "skip_count": 0
        }

        f = request.files.get("img_upload")
        if f and f.filename:
            new["img"] = save_uploaded_file(f)
        else:
            txt = request.form.get("img", "").strip()
            if txt:
                new["img"] = txt if txt.startswith("http") else os.path.basename(txt)

        bosses.append(new)
        save_bosses(bosses)
        return redirect("/")

    return render_template("create.html")


# -----------------------------
# 編輯
# -----------------------------
@app.route("/edit/<int:idx>", methods=["GET", "POST"])
@login_required
def edit(idx):
    bosses = load_bosses()
    if idx < 0 or idx >= len(bosses):
        return "Index error", 404

    boss = bosses[idx]

    if isinstance(boss.get("respawn_period"), str):
        boss["respawn_period"] = [boss["respawn_period"]]

    if request.method == "POST":

        boss["name"] = request.form.get("name")
        boss["desc"] = request.form.get("desc")

        short_raw = request.form.get("shortname", "")
        boss["shortname"] = [s.strip() for s in short_raw.split(",") if s.strip()]

        boss["weekday"] = request.form.getlist("weekday")
        boss["respawn_type"] = request.form.get("respawn_type")

        if boss["respawn_type"] == "cycle":
            boss["respawn_period"] = (
                f"{request.form.get('respawn_h') or '0'}:"
                f"{request.form.get('respawn_m') or '0'}:"
                f"{request.form.get('respawn_s') or '0'}"
            )
        else:
            fixed_raw = request.form.get("fixed_times", "").strip()
            boss["respawn_period"] = [
                x.strip() for x in fixed_raw.split(",") if x.strip()
            ]

        f = request.files.get("img_upload")
        if f and f.filename:
            boss["img"] = save_uploaded_file(f, old_filename=boss.get("img"))
        else:
            txt = request.form.get("img", "").strip()
            if txt:
                boss["img"] = txt if txt.startswith("http") else os.path.basename(txt)

        bosses[idx] = boss
        save_bosses(bosses)
        return redirect("/")

    try:
        if isinstance(boss.get("respawn_period"), list):
            h, m, s = 0, 0, 0
        else:
            h, m, s = map(int, boss.get("respawn_period", "0:0:0").split(":"))
    except:
        h, m, s = 0, 0, 0

    return render_template(
        "edit.html",
        boss=boss, idx=idx,
        respawn_h=h, respawn_m=m, respawn_s=s
    )


# -----------------------------
# API（也加保護）
# -----------------------------
@app.route("/api/bosses")
@login_required
def api_bosses():
    return jsonify(load_bosses())


# -----------------------------
# 刪除
# -----------------------------
@app.route("/delete/<int:idx>")
@login_required
def delete(idx):
    bosses = load_bosses()
    if idx < 0 or idx >= len(bosses):
        return "Index error", 404

    img = bosses[idx].get("img")
    if img and not img.startswith("http"):
        old = os.path.join(IMG_DIR, img)
        if os.path.exists(old):
            try:
                os.remove(old)
            except:
                pass

    bosses.pop(idx)
    save_bosses(bosses)
    return redirect("/")


# -----------------------------
# 啟動
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
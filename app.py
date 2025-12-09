from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import json
from datetime import datetime, date, time as dt_time
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')

DATA_DIR = "data/guild_default"
BOSS_FILE = os.path.join(DATA_DIR, "bosses.json")
IMG_DIR = "static/images"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)


# -----------------------------
# JSON 存取
# -----------------------------
def load_bosses():
    if not os.path.exists(BOSS_FILE):
        return []
    with open(BOSS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []


def save_bosses(data):
    with open(BOSS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
# 圖片上傳（只回傳檔名）
# -----------------------------
def save_uploaded_file(file, old_filename=None):

    if not file or file.filename == "":
        return old_filename

    filename = secure_filename(file.filename)
    filepath = os.path.join(IMG_DIR, filename)

    # 防止覆蓋 → 自動改名
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(filepath):
        filename = f"{base}_{counter}{ext}"
        filepath = os.path.join(IMG_DIR, filename)
        counter += 1

    # 儲存新檔
    file.save(filepath)

    # 刪除舊檔
    if old_filename:
        old_path = os.path.join(IMG_DIR, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass

    # ⭐ 回傳純檔名
    return filename


# -----------------------------
# 後台首頁
# -----------------------------
@app.route("/")
def index():
    bosses = load_bosses()
    return render_template("index.html", bosses=bosses)


# -----------------------------
# 新增王
# -----------------------------
@app.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":

        bosses = load_bosses()

        # shortname
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

        # ---圖片---
        f = request.files.get("img_upload")
        if f and f.filename:
            new["img"] = save_uploaded_file(f)
        else:
            txt = request.form.get("img", "").strip()
            if txt:
                if txt.startswith("http"):
                    new["img"] = txt
                else:
                    new["img"] = os.path.basename(txt)

        bosses.append(new)
        save_bosses(bosses)
        return redirect("/")

    return render_template("create.html")

# -----------------------------
# 編輯王
# -----------------------------
@app.route("/edit/<int:idx>", methods=["GET", "POST"])
def edit(idx):
    bosses = load_bosses()
    if idx < 0 or idx >= len(bosses):
        return "Index error", 404

    boss = bosses[idx]

    # respawn_period 若為字串 → 轉 list (避免 fixed 顯示錯誤)
    if isinstance(boss.get("respawn_period"), str):
        boss["respawn_period"] = [boss["respawn_period"]]

    if request.method == "POST":

        boss["name"] = request.form.get("name")
        boss["desc"] = request.form.get("desc")

        short_raw = request.form.get("shortname", "")
        boss["shortname"] = [s.strip() for s in short_raw.split(",") if s.strip()]

        boss["weekday"] = request.form.getlist("weekday")
        boss["respawn_type"] = request.form.get("respawn_type")

        # ===============================
        # cycle
        # ===============================
        if boss["respawn_type"] == "cycle":
            boss["respawn_period"] = (
                f"{request.form.get('respawn_h') or '0'}:"
                f"{request.form.get('respawn_m') or '0'}:"
                f"{request.form.get('respawn_s') or '0'}"
            )

        # ===============================
        # fixed
        # ===============================
        else:
            fixed_raw = request.form.get("fixed_times", "").strip()
            boss["respawn_period"] = [
                x.strip() for x in fixed_raw.split(",") if x.strip()
            ]

        # 上傳新圖
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

    # time slider (cycle 用)
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
# API：給 Discord Bot
# -----------------------------
@app.route("/api/bosses")
def api_bosses():
    return jsonify(load_bosses())


# -----------------------------
# API：設定開機時間 /0 0900
# -----------------------------
def _parse_hhmm(s):
    if not s:
        return None
    s = s.strip()
    if ":" in s:
        hh, mm = s.split(":")
    else:
        if len(s) == 4:
            hh, mm = s[:2], s[2:]
        elif len(s) == 3:
            hh, mm = s[0], s[1:]
        else:
            return None
    try:
        return int(hh) % 24, int(mm) % 60
    except:
        return None


@app.route("/api/set_open_time", methods=["POST"])
def api_set_open_time():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Missing JSON"}), 400

    parsed = _parse_hhmm(payload.get("time") or payload.get("t"))
    if not parsed:
        return jsonify({"error": "Invalid time"}), 400

    hh, mm = parsed
    bosses = load_bosses()

    today = date.today()
    dt_val = datetime.combine(today, dt_time(hh, mm))

    updated = []

    for i, b in enumerate(bosses):
        if b.get("respawn_type") == "fixed":
            continue
        if b.get("last_kill"):
            continue

        b["last_kill"] = dt_val.isoformat()
        b["skip_count"] = 0
        updated.append({"idx": i, "name": b["name"], "last_kill": b["last_kill"]})

    save_bosses(bosses)

    return jsonify({
        "message": f"Updated {len(updated)} bosses to {hh:02d}:{mm:02d}:00",
        "updated": updated
    })


# -----------------------------
# 刪除王
# -----------------------------
@app.route("/delete/<int:idx>", methods=["GET"])
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
# 匯入預設王表 (舊方法：GET)  ← 可留
# -----------------------------
@app.route("/load_default")
def load_default():
    bosses = load_bosses()

    default_list = [
        {
            "name": "古魯丁",
            "shortname": ["古"],
            "respawn_type": "fixed",
            "respawn_period": ["06:00:00", "12:00:00"],
            "weekday": [],
            "img": "",
            "last_kill": None,
            "skip_count": 0,
        },
        {
            "name": "肯特",
            "shortname": ["肯"],
            "respawn_type": "cycle",
            "respawn_period": "02:00:00",
            "weekday": [],
            "img": "",
            "last_kill": None,
            "skip_count": 0,
        }
    ]

    bosses.extend(default_list)
    save_bosses(bosses)
    return redirect("/")


# -----------------------------
# 匯入預設王表 (新版 AJAX：POST)
# -----------------------------
@app.route("/import_preset/<key>", methods=["POST"])
def import_preset(key):

    # 預設檔案路徑
    preset_file = os.path.join("presets", f"{key}.json")

    # 檔案不存在
    if not os.path.exists(preset_file):
        return jsonify({"message": f"找不到預設王表: {key}"}), 404

    # 讀取預設 JSON
    with open(preset_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 直接覆蓋 bosses.json
    save_bosses(data)

    return jsonify({"message": f"{key} 預設王表已成功載入"})


# -----------------------------
# 匯出所有王 → 下載 bosses.json
# -----------------------------
@app.route("/export_bosses")
def export_bosses():
    if not os.path.exists(BOSS_FILE):
        return jsonify({"error": "No file"}), 404

    with open(BOSS_FILE, "r", encoding="utf-8") as f:
        data = f.read()

    return app.response_class(
        data,
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=bosses.json"
        }
    )


# -----------------------------
# 啟動 Flask
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
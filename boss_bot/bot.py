# bot.py
# 注意：如果你之前把 token 放在程式中，請務必更換 token（不要公開）。
import os
import json
import asyncio
import random
import time
from datetime import datetime, timedelta

import discord
from discord import Embed, ui
from discord.ext import commands

# --------------------------
# CONFIG
# --------------------------
# 建議把 TOKEN 改成環境變數，或直接貼新的 token（請務必私密）
TOKEN = os.environ.get("DISCORD_TOKEN")
DATA_ROOT = "data"
API_HOST = os.environ.get("API_HOST", "http://127.0.0.1:5000")  # 後台網址根目錄

# --------------------------
# Intents & Bot
# --------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)  # prefix 仍保留，但使用 slash commands
tree = bot.tree

# --------------------------
# File helpers
# --------------------------
def ensure_guild_folder(guild_id):
    path = os.path.join(DATA_ROOT, f"guild_{guild_id}")
    os.makedirs(path, exist_ok=True)
    bosses = os.path.join(path, "bosses.json")
    settings = os.path.join(path, "settings.json")
    if not os.path.exists(bosses):
        with open(bosses, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    if not os.path.exists(settings):
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"admin_pw": "888888", "notify_channel_id": None, "boss_display": True, "boss_notify": True, "tts_notify": True}, f, ensure_ascii=False, indent=2)
    return path

def load_bosses(guild_id):
    ensure_guild_folder(guild_id)
    p = os.path.join(DATA_ROOT, f"guild_{guild_id}", "bosses.json")
    try:
        return json.load(open(p, "r", encoding="utf-8"))
    except Exception:
        return []

def save_bosses(guild_id, data):
    ensure_guild_folder(guild_id)
    p = os.path.join(DATA_ROOT, f"guild_{guild_id}", "bosses.json")
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def load_settings(guild_id):
    ensure_guild_folder(guild_id)
    p = os.path.join(DATA_ROOT, f"guild_{guild_id}", "settings.json")
    try:
        return json.load(open(p, "r", encoding="utf-8"))
    except Exception:
        return {"admin_pw": "888888", "notify_channel_id": None, "boss_display": True, "boss_notify": True, "tts_notify": True}

def save_settings(guild_id, data):
    ensure_guild_folder(guild_id)
    p = os.path.join(DATA_ROOT, f"guild_{guild_id}", "settings.json")
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# --------------------------
# Time utils
# --------------------------
def parse_time_str(timestr):
    """ 支援 '1251' 或 '12:51' 或 '905' """
    if timestr is None:
        return None
    s = timestr.strip()
    if ":" in s:
        parts = s.split(":")
    else:
        if len(s) in (3, 4):
            hh = s[:-2]
            mm = s[-2:]
            parts = [hh, mm]
        else:
            return None
    try:
        hh = int(parts[0]) % 24
        mm = int(parts[1]) % 60
        return hh, mm
    except:
        return None

def compose_datetime_from_hm(h, m):
    """ 把 h,m 與當前秒數組成一個 datetime """
    now = datetime.now()
    sec = now.second
    dt = now.replace(hour=h, minute=m, second=sec, microsecond=0)
    return dt

# --------------------------
# Find boss helper
# --------------------------
def find_boss_by_name_or_short(bosses, key):
    key_l = key.lower()
    for b in bosses:
        shortnames = [s.lower() for s in b.get("shortname", [])]
        if key_l == b.get("name", "").lower() or key_l in shortnames:
            return b
    return None

# --------------------------
# Reminder task & button handling
# --------------------------
class ResultView(ui.View):
    def __init__(self, guild_id, boss_idx, orig_last_kill, orig_skip, message_id=None, timeout=None):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.boss_idx = boss_idx
        self.orig_last_kill = orig_last_kill
        self.orig_skip = orig_skip
        self.message_id = message_id
        # will dynamically add cancel button after an action

    async def record_and_reply(self, interaction: discord.Interaction, action: str):
        """
        action: "success", "fail", "no_spawn"
        """
        guild_id = self.guild_id
        bosses = load_bosses(guild_id)
        if self.boss_idx < 0 or self.boss_idx >= len(bosses):
            await interaction.response.send_message("找不到該首領資料（可能已變動）。", ephemeral=True)
            return
        b = bosses[self.boss_idx]
        # save state for cancel
        prev_last = b.get("last_kill")
        prev_skip = b.get("skip_count", 0)

        if action in ("success", "fail"):
            # 討伐成功 / 討伐失敗 -> 都以當下時間記錄為 last_kill（如需區別可加 flag）
            now = datetime.now()
            b["last_kill"] = now.isoformat()
            b["skip_count"] = 0
            save_bosses(guild_id, bosses)
            kind = "討伐成功" if action == "success" else "討伐失敗"
            reply = f"已記錄：**{b['name']}** — {kind}（時間：{now.strftime('%Y-%m-%d %H:%M:%S')}）"
        elif action == "no_spawn":
            # 沒出 -> 增加 skip_count，不改 last_kill
            b["skip_count"] = b.get("skip_count", 0) + 1
            save_bosses(guild_id, bosses)
            reply = f"已記錄：**{b['name']}** — 沒出（輪空），已標註為過 {b['skip_count']} 次。"
        else:
            reply = "不支援的操作。"

        # add a cancel button (so使用者可還原)
        # disable original buttons to prevent重複
        for child in self.children:
            child.disabled = True
        # add cancel button
        cancel = ui.Button(label="🧹 取消紀錄", style=discord.ButtonStyle.secondary)
        async def cancel_cb(inter: discord.Interaction):
            # revert to orig
            bs = load_bosses(guild_id)
            if self.boss_idx < 0 or self.boss_idx >= len(bs):
                await inter.response.send_message("找不到該首領資料（可能已變動）。", ephemeral=True)
                return
            bb = bs[self.boss_idx]
            bb["last_kill"] = self.orig_last_kill
            bb["skip_count"] = self.orig_skip
            save_bosses(guild_id, bs)
            # respond and disable cancel button
            for c in self.children:
                c.disabled = True
            try:
                await inter.response.edit_message(content=f"已取消先前的操作，已還原 {bb['name']} 的紀錄。", embed=None, view=self)
            except:
                await inter.response.send_message("已取消並還原。", ephemeral=True)
        cancel.callback = cancel_cb
        self.add_item(cancel)

        # edit the message (disable original buttons and show check)
        try:
            await interaction.response.edit_message(content=reply, embed=None, view=self)
        except Exception:
            # fallback: send ephemeral reply
            await interaction.response.send_message(reply, ephemeral=True)

    @ui.button(label="✔ 討伐成功", style=discord.ButtonStyle.success)
    async def btn_success(self, button: ui.Button, interaction: discord.Interaction):
        await self.record_and_reply(interaction, "success")

    @ui.button(label="❌ 討伐失敗", style=discord.ButtonStyle.danger)
    async def btn_fail(self, button: ui.Button, interaction: discord.Interaction):
        await self.record_and_reply(interaction, "fail")

    @ui.button(label="🈳 沒出", style=discord.ButtonStyle.secondary)
    async def btn_nospawn(self, button: ui.Button, interaction: discord.Interaction):
        await self.record_and_reply(interaction, "no_spawn")


async def schedule_reminder(guild_id, channel_id, boss_idx, dt_recorded, note):
    """
    當收到一筆記錄 (dt_recorded) 後，安排在該時間 - 5 分鐘 發提醒。
    這裡 boss_idx 是 index（在載入的 bosses list 中）
    """
    remind_time = dt_recorded - timedelta(minutes=5)
    now = datetime.now()
    wait = (remind_time - now).total_seconds()
    if wait < 0:
        wait = 1
    await asyncio.sleep(wait)
    # 發送提醒（包含 TTS 嘗試）
    ch = bot.get_channel(int(channel_id)) if channel_id else None
    if not ch:
        print(f"[schedule_reminder] 找不到頻道 {channel_id} (guild {guild_id})")
        return
    bosses = load_bosses(guild_id)
    if boss_idx < 0 or boss_idx >= len(bosses):
        print("[schedule_reminder] boss index out of range")
        return
    b = bosses[boss_idx]
    # only cycle bosses have buttons
    respawn_type = b.get("respawn_type", "cycle")
    name = b.get("name", "—")
    # Build embed with boss info
    embed = Embed(title=f"{name} 即將重生", description=f"約 5 分鐘後重生", color=0xFF4500)
    # show recorded time if exists in friendly format
    embed.add_field(name="[重生時間]", value=dt_recorded.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    if b.get("desc"):
        embed.add_field(name="[補充說明]", value=b.get("desc"), inline=True)
    rp = b.get("respawn_period", "00:00:00")
    embed.add_field(name="[重生週期]", value=f"{rp} | 每天", inline=False)
    # attach image if present (assume static/images/ or relative static path)
    if b.get("img"):
        # If you host images via static folder in flask, the full url should be constructed.
        # We can't assume the correct URL here; we just attach the filename as embed thumbnail if discord can access it.
        try:
            embed.set_thumbnail(url=f"{API_HOST.rstrip('/')}/static/images/{b.get('img')}")
        except:
            pass

    tts_text = f"{name} 約 5 分鐘後重生"
    if note:
        tts_text += f" 備註：{note}"

    # prefer tts send first (if bot has permission), then send embed+buttons
    sent_msg = None
    try:
        await ch.send(tts_text, tts=True)
    except Exception:
        # ignore tts error
        pass

    if respawn_type == "cycle":
        # create a view with callback that knows which boss index to modify
        view = ResultView(guild_id=guild_id, boss_idx=boss_idx, orig_last_kill=b.get("last_kill"), orig_skip=b.get("skip_count", 0))
        sent_msg = await ch.send(embed=embed, view=view)
        # store message id in view for reference (optional)
        view.message_id = sent_msg.id
    else:
        # fixed boss -> no buttons, only embed
        sent_msg = await ch.send(embed=embed)

# --------------------------
# Slash commands (app commands)
# --------------------------

@tree.command(name="name", description="顯示所有 Boss 簡稱")
async def slash_name(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    bosses = load_bosses(guild_id)
    if not bosses:
        await interaction.response.send_message("王表為空，請至後台新增資料。", ephemeral=True)
        return
    lines = []
    for b in bosses:
        short = b.get("shortname", [])
        if short:
            lines.append(f"{b['name']} → {', '.join(short)}")
        else:
            lines.append(f"{b['name']}")
    text = "王表簡稱清單：\n" + "\n".join(lines)
    # 如果太長可改為檔案或 ephemeral
    await interaction.response.send_message(f"```{text}```")

@tree.command(name="b", description="顯示全部 Boss 時間（包含上次/下次）")
async def slash_b(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    bosses = load_bosses(guild_id)
    embed = Embed(title="王表列表", color=0x2f2f2f)
    if not bosses:
        await interaction.response.send_message("王表為空，請至後台新增資料。", ephemeral=True)
        return
    for idx, b in enumerate(bosses):
        last = b.get("last_kill")
        next_str = "-"
        extra = ""
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                rp = b.get("respawn_period", "00:00:00").split(":")
                delta = timedelta(hours=int(rp[0]), minutes=int(rp[1]), seconds=int(rp[2]))
                next_dt = last_dt + delta
                next_str = next_dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                next_str = "-"
        name = b.get("name", "—")
        shorts = ", ".join(b.get("shortname", []))
        sk = b.get("skip_count", 0)
        if sk and sk > 0:
            extra = f"\n#過{sk}"
        embed.add_field(name=f"{name}", value=f"簡稱: {shorts}\n上次: {last}\n下次: {next_str}{extra}", inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="k", description="記錄 Boss 死亡時間（可帶簡稱/時間/備註）")
@discord.app_commands.describe(target="Boss 名稱或簡稱", time="死亡時間，例如 1251 或 12:51", note="備註（可選）")
async def slash_k(interaction: discord.Interaction, target: str, time: str = None, note: str = None):
    # 1) /k shortname -> 記錄現在時間
    # 2) /k shortname 1251 -> 記錄指定 hhmm (秒使用現在秒)
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("請在伺服器內使用此指令。", ephemeral=True)
        return
    guild_id = guild.id
    bosses = load_bosses(guild_id)
    matched = find_boss_by_name_or_short(bosses, target)
    if not matched:
        await interaction.response.send_message(f"王表內找不到 **{target}**，請檢查簡稱或使用 /name 查詢。", ephemeral=True)
        return
    if time is None:
        dt = datetime.now()
    else:
        parsed = parse_time_str(time)
        if parsed is None:
            await interaction.response.send_message("時間格式錯誤，請輸入像 1251 或 12:51。", ephemeral=True)
            return
        h, m = parsed
        dt = compose_datetime_from_hm(h, m)
    matched["last_kill"] = dt.isoformat()
    if note:
        matched["note"] = note
    matched["skip_count"] = 0
    save_bosses(guild_id, bosses)

    # 計算下次
    rp = matched.get("respawn_period", "00:00:00").split(":")
    delta = timedelta(hours=int(rp[0]), minutes=int(rp[1]), seconds=int(rp[2]))
    next_dt = dt + delta

    embed = Embed(title=f"{matched['name']} 消滅時間 {dt.strftime('%Y-%m-%d %H:%M:%S')} 已經記錄", color=0xFF8C00)
    embed.add_field(name="下次重生", value=next_dt.strftime("%Y-%m-%d %H:%M:%S"))
    if matched.get("note"):
        embed.add_field(name="備註", value=matched.get("note"), inline=False)
    embed.set_footer(text=f"由 ( {interaction.user.display_name} ) 記錄")

    # 回覆使用者（非 ephemeral，方便大家看到）
    await interaction.response.send_message(embed=embed)

    # 安排提醒（如果有設定notify channel，並且開啟通知）
    settings = load_settings(guild_id)
    notify_channel_id = settings.get("notify_channel_id")
    if notify_channel_id:
        # 建立 background task：記得傳 boss index (找到 matched 在列表的 index)
        bosses_all = load_bosses(guild_id)
        try:
            boss_idx = bosses_all.index(matched)
        except ValueError:
            boss_idx = None
        if boss_idx is not None:
            bot.loop.create_task(schedule_reminder(guild_id, notify_channel_id, boss_idx, dt, matched.get("note", "")))

@tree.command(name="setpw", description="設定後台管理密碼（需要管理員權限）")
@discord.app_commands.describe(pw="你要設定的密碼")
async def slash_setpw(interaction: discord.Interaction, pw: str):
    # 需管理員權限（伺服器管理員），在 app command 裡無法用 decorator 直接判權，需自己檢查
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("你需要管理員權限才能設定後台密碼。", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    s = load_settings(guild_id)
    s["admin_pw"] = pw
    save_settings(guild_id, s)

    panel = f"{API_HOST}/?g={guild_id}"
    embed = Embed(
        title="🔐 密碼設定成功！",
        description="後台入口已啟動 🎉\n\n⚠ 密碼不會顯示，請自行記住。若忘記可重新設定新的密碼。",
        color=0xffa200
    )
    embed.set_footer(text="建議只提供給需要維護的盟友👀")

    view = ui.View()
    view.add_item(ui.Button(label="🔧 重生時間維護", url=panel))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

@tree.command(name="setnotify", description="設定本頻道為提醒頻道（需管理員）")
async def slash_setnotify(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("你需要管理員權限才能執行本指令。", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    s = load_settings(guild_id)
    s["notify_channel_id"] = interaction.channel.id
    save_settings(guild_id, s)
    await interaction.response.send_message(f"已設定提醒頻道為 {interaction.channel.mention}")

@tree.command(name="0", description="維修/重新開機：重算全部非固定王（需管理員）")
async def slash_reset(interaction: discord.Interaction, hhmm: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("你需要管理員權限才能執行本指令。", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    bosses = load_bosses(guild_id)
    for b in bosses:
        if b.get("respawn_type") == "fixed":
            continue
        else:
            b["last_kill"] = None
            b["skip_count"] = 0
    if hhmm:
        parsed = parse_time_str(hhmm)
        if parsed:
            h, m = parsed
            dt = compose_datetime_from_hm(h, m)
            for b in bosses:
                if b.get("respawn_type") != "fixed":
                    b["last_kill"] = dt.isoformat()
    save_bosses(guild_id, bosses)
    await interaction.response.send_message("已執行 /0，非固定王已清空時間或依指定時間重算。")

@tree.command(name="home", description="編輯後請輸入 /home 讓機器人在頻道顯示最新王表（更新顯示）")
async def slash_home(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("此指令只能在伺服器內使用。", ephemeral=True)
        return
    guild_id = guild.id
    bosses = load_bosses(guild_id)
    if not bosses:
        await interaction.response.send_message("王表為空，請至後台新增資料。", ephemeral=True)
        return
    embed = Embed(title="王表列表（更新顯示）", color=0x2f2f2f)
    for b in bosses:
        last = b.get("last_kill")
        next_str = "-"
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                rp = b.get("respawn_period", "00:00:00").split(":")
                delta = timedelta(hours=int(rp[0]), minutes=int(rp[1]), seconds=int(rp[2]))
                next_dt = last_dt + delta
                next_str = next_dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                next_str = "-"
        name = b.get("name", "—")
        shorts = ", ".join(b.get("shortname", []))
        sk = b.get("skip_count", 0)
        extra = f"\n#過{sk}" if sk and sk > 0 else ""
        embed.add_field(name=f"{name}", value=f"簡稱: {shorts}\n上次: {last}\n下次: {next_str}{extra}", inline=False)
    await interaction.response.send_message("已更新王表顯示：", embed=embed)

@tree.command(name="lottery", description="簡單抽獎：最後一個參數以逗號分隔參與者，或直接一個參與者")
@discord.app_commands.describe(prize="獎品名稱", participants="參與者，逗號隔開或空白分隔")
async def slash_lottery(interaction: discord.Interaction, prize: str, participants: str):
    parts = [p.strip() for p in participants.replace(",", " ").split() if p.strip()]
    if not parts:
        await interaction.response.send_message("沒有提供參與者。格式：/lottery 獎品 名稱 參與者1,參與者2", ephemeral=True)
        return
    winner = random.choice(parts)
    embed = Embed(title="抽獎結果 🎉", color=0x00AAFF)
    embed.add_field(name="獎品", value=prize, inline=False)
    embed.add_field(name="參與者", value=", ".join(parts), inline=False)
    embed.add_field(name="得獎者", value=winner, inline=False)
    await interaction.response.send_message(embed=embed)

# --------------------------
# Events: guild join / ready
# --------------------------
async def find_or_create_boss_channel(guild: discord.Guild):
    wanted_names = ["🎮boss機器人🤖", "boss機器人", "王表時間表", "boss-機器人"]
    found = None
    for ch in guild.text_channels:
        if ch.name in wanted_names:
            found = ch
            break
    if found:
        return found
    try:
        ch = await guild.create_text_channel("🎮boss機器人🤖")
        return ch
    except Exception as e:
        print(f"[find_or_create_boss_channel] 無法建立頻道: {e}")
        for ch in guild.text_channels:
            return ch
    return None

@bot.event
async def on_guild_join(guild: discord.Guild):
    ch = await find_or_create_boss_channel(guild)
    if not ch:
        print(f"[on_guild_join] 無法找到或建立頻道於 guild {guild.id}")
        return
    s = load_settings(guild.id)
    s["notify_channel_id"] = ch.id
    save_settings(guild.id, s)

    embed = Embed(
        title="🎉 歡迎使用 Boss 機器人",
        description="已自動建立王表頻道！\n\n📌 請輸入：`/setpw 0000` 設定後台密碼\n\n設定後即可開始記錄死亡時間、提醒、固定王管理",
        color=0xffa200
    )
    embed.add_field(
        name="📘 指令教學 (必看)",
        value=(
            "/setpw 密碼  ← 設定後台密碼\n"
            "/k 王名稱或簡稱  ← 記錄死亡時間 (時分秒)\n"
            "/k 王名稱或簡稱 死亡時間  ← 記錄指定死亡時間\n"
            "/k 王名稱或簡稱 死亡時間 備註  ← 記錄指定死亡時間 (含備註)\n"
            "/b  ← 顯示全部 Boss 時間\n"
            "/name  ← 顯示 Boss 簡稱\n"
            "/0 HHMM  ← 維修或重新開機時重算全部王\n"
            "/home  ← 後台新增/編輯/刪除 Boss 後請輸入更新王表\n"
            "/lottery 獎品名稱 參與者  ← 抽獎\n"
        ),
        inline=False
    )
    embed.set_footer(text="輸入 /setpw 後會出現後台按鈕")

    panel = f"{API_HOST}/?g={guild.id}"
    view = ui.View()
    view.add_item(ui.Button(label="🔧 重生時間維護", url=panel))

    try:
        await ch.send(embed=embed, view=view)
    except Exception:
        try:
            await guild.system_channel.send(embed=embed, view=view)
        except:
            print("[on_guild_join] 無法發送歡迎訊息")

@bot.event
async def on_ready():
    print(f"Bot Ready! Logged in as {bot.user} (id: {bot.user.id})")
    # sync commands
    try:
        await tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Sync error:", e)
    # 為已在的 guilds 呼叫歡迎檢查（只發一次）
    for guild in bot.guilds:
        try:
            ch = await find_or_create_boss_channel(guild)
            skip = False
            try:
                async for m in ch.history(limit=50):
                    if m.author == bot.user and m.embeds:
                        for e in m.embeds:
                            if e.title and "歡迎使用 Boss 機器人" in e.title:
                                skip = True
                                break
                    if skip:
                        break
            except Exception:
                skip = True
            if not skip:
                s = load_settings(guild.id)
                s["notify_channel_id"] = ch.id
                save_settings(guild.id, s)
                panel = f"{API_HOST}/?g={guild.id}"
                embed = Embed(
                    title="🎉 歡迎使用 Boss 機器人",
                    description="已自動建立王表頻道！\n\n📌 請輸入：`/setpw 0000` 設定後台密碼\n\n設定後即可開始記錄死亡時間、提醒、固定王管理",
                    color=0xffa200
                )
                embed.add_field(
                    name="📘 指令教學 (必看)",
                    value=(
                        "/setpw 密碼  ← 設定後台密碼\n"
                        "/k 王名稱或簡稱  ← 記錄死亡時間 (時分秒)\n"
                        "/k 王名稱或簡稱 死亡時間  ← 記錄指定死亡時間\n"
                        "/k 王名稱或簡稱 死亡時間 備註  ← 記錄指定死亡時間 (含備註)\n"
                        "/b  ← 顯示全部 Boss 時間\n"
                        "/name  ← 顯示 Boss 簡稱\n"
                        "/0 HHMM  ← 維修或重新開機時重算全部王\n"
                        "/home  ← 後台新增/編輯/刪除 Boss 後請輸入更新王表\n"
                        "/lottery 獎品名稱 參與者  ← 抽獎\n"
                    ),
                    inline=False
                )
                embed.set_footer(text="輸入 /setpw 後會出現後台按鈕")
                view = ui.View()
                view.add_item(ui.Button(label="🔧 重生時間維護", url=panel))
                try:
                    await ch.send(embed=embed, view=view)
                except Exception:
                    pass
        except Exception as e:
            print("on_ready per guild error:", e)

# --------------------------
# Error handler for app commands
# --------------------------
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.errors.MissingPermissions):
        await interaction.response.send_message("你沒有權限執行這個指令。", ephemeral=True)
    else:
        try:
            await interaction.response.send_message(f"指令錯誤: {str(error)}", ephemeral=True)
        except:
            print("Error when sending app command error:", error)

# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    if TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE" or not TOKEN:
        print("請先設定 DISCORD_TOKEN（或直接在程式中貼 token），再啟動機器人。")
    else:
        bot.run(TOKEN)
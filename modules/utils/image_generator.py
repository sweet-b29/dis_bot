import discord
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path
from functools import lru_cache

# Пути к файлам
BASE_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_base.png"
OUTPUT_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_dynamic.png"
FONT_PATH = Path(__file__).resolve().parents[1] / "static" / "fonts" / "Inter-SemiBold.ttf"
RANK_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "ranks"
MAP_DIRS = [
    Path(__file__).resolve().parents[1] / "maps",
    Path(__file__).resolve().parents[1] / "pictures" / "maps",
]

CANDIDATE_FONT_PATHS = [
    FONT_PATH,
    Path(__file__).resolve().parents[1] / "pictures" / "Montserrat-Bold.ttf",
    Path(__file__).resolve().parents[2] / "static" / "fonts" / "Inter-SemiBold.ttf",
    Path(__file__).resolve().parents[1] / "fonts" / "Inter-SemiBold.ttf",
]

def _norm(s: str) -> str:
    return (s or "").lower().replace(" ", "").replace("-", "").replace("_", "")

def _find_map_image(map_name: str) -> Path | None:
    """Находим файл карты (webp/png/jpg) в MAP_DIRS, без учёта регистра."""
    name = _norm(map_name)
    # 1) прямые попытки с разными расширениями
    exts = ("webp", "png", "jpg", "jpeg")
    for d in MAP_DIRS:
        for ext in exts:
            p = d / f"{map_name}.{ext}"       # с исходным регистром (Ascent.webp)
            if p.exists():
                return p
    # 2) поиск по нормализованному имени
    for d in MAP_DIRS:
        if not d.exists():
            continue
        for p in d.glob("*.*"):
            if _norm(p.stem) == name:
                return p
    return None

COLOR_GOLD   = (255, 210, 77)
COLOR_SILVER = (197, 203, 212)
COLOR_BRONZE = (205, 127, 50)

def _color_for_top(pid: int | None, top_ids: list[int] | None):
    if not pid or not top_ids:
        return None
    try:
        i = top_ids.index(int(pid))
    except ValueError:
        return None
    return (COLOR_GOLD, COLOR_SILVER, COLOR_BRONZE)[i] if i < 3 else None

@lru_cache(maxsize=8)
def get_font(size: int):
    # 1) пробуем Inter из проекта
    for p in CANDIDATE_FONT_PATHS:
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    # 2) пробуем системный DejaVuSans (обычно есть с Pillow)
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        # 3) безопасный фоллбэк — встроенный bitmap-шрифт
        return ImageFont.load_default()

# Сопоставление "Immortal" → "Immortal_3_Rank.png"
def get_icon_path(rank: str):
    rank_map = {
        "Iron": "Iron_3_Rank.png",
        "Bronze": "Bronze_3_Rank.png",
        "Silver": "Silver_3_Rank.png",
        "Gold": "Gold_3_Rank.png",
        "Platinum": "Platinum_3_Rank.png",
        "Diamond": "Diamond_3_Rank.png",
        "Ascendant": "Ascendant_3_Rank.png",
        "Immortal": "Immortal_3_Rank.png",
        "Radiant": "Radiant_Rank.png",
        "Unranked": None
    }

    filename = rank_map.get(rank)
    if not filename:
        return None
    path = RANK_ICONS_PATH / filename
    return path if path.exists() else None

def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_px: int, start: int, min_size: int = 28):
    """Подбирает размер шрифта так, чтобы текст влезал по ширине max_px."""
    size = start
    font = get_font(size)
    while draw.textlength(text, font=font) > max_px and size > min_size:
        size -= 2
        font = get_font(size)
    return font

def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill="white", stroke: int = 2):
    """Рисует текст с тонкой чёрной обводкой для контраста."""
    draw.text(xy, text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 220))

def _rank_icon_path(rank: str) -> Path | None:
    """Находим файл иконки ранга по префиксу (без учёта регистра)."""
    ranks_dir = Path(__file__).resolve().parents[1] / "pictures" / "ranks"
    # частые варианты имён файлов
    cand = ranks_dir / f"{rank}_Rank.png"
    if cand.exists():
        return cand
    # ищем первый файл, начинающийся с названия ранга
    rank_lower = (rank or "").lower()
    for p in ranks_dir.glob("*.png"):
        if p.name.lower().startswith(rank_lower):
            return p
    return None

def generate_lobby_image(players: list[dict], top_ids: list[int] | None = None) -> Path:
    top_ids = top_ids or []

    pictures_dir = Path(__file__).resolve().parents[1] / "pictures"
    base_path = pictures_dir / "lobby_base.png"
    output_path = pictures_dir / "lobby_dynamic.png"

    base_img = Image.open(base_path).convert("RGBA") if base_path.exists() \
        else Image.new("RGBA", (1024, 1280), (20, 20, 20, 255))
    draw = ImageDraw.Draw(base_img)
    width, height = base_img.size

    # ===== разметка «как на макете» =====
    PADDING_X = 96         # левый край колонки с контентом
    LIST_TOP  = 320        # старт списка (под заголовком из шаблона)
    ROW_H     = 120        # высота строки
    GAP       = 24
    NUM_W     = 56         # ширина колонки под номер

    ICON_W    = 72
    ICON_COL_X_RATIO = 0.62
    ICON_X = min(int(width * ICON_COL_X_RATIO), width - PADDING_X - ICON_W)

    number_font = get_font(48)

    # область под имя: от «после номера» до колонки иконки
    name_x = PADDING_X + NUM_W + GAP
    name_w = ICON_X - name_x - GAP

    for idx, p in enumerate(players, start=1):
        username = str(p.get("username") or "—")
        rank     = str(p.get("rank") or "Unranked")
        pid      = p.get("id")
        is_top   = pid in top_ids

        y = LIST_TOP + (idx - 1) * ROW_H

        # номер
        _draw_text(draw, (PADDING_X, y), f"{idx}", number_font, fill="white")

        # имя: крупно, но не выходя за name_w
        name_font  = _fit_font(draw, username, name_w, start=64, min_size=32)
        pid = p.get("discord_id") or p.get("id")
        name_color = _color_for_top(pid, top_ids) or "white"
        _draw_text(draw, (name_x, y), username, name_font, fill=name_color)

        # иконка ранга — в фиксированной колонке
        icon_y = y + (ROW_H - ICON_W) // 2
        icon_path = _rank_icon_path(rank)
        if icon_path and icon_path.exists():
            try:
                icon = Image.open(icon_path).resize((ICON_W, ICON_W)).convert("RGBA")
                base_img.paste(icon, (ICON_X, icon_y), icon)
            except Exception:
                rank_font = get_font(32)
                _draw_text(draw, (ICON_X, y), rank, rank_font, fill="#B3B3B3")
        else:
            rank_font = get_font(32)
            _draw_text(draw, (ICON_X, y), rank, rank_font, fill="#B3B3B3")

    base_img.save(output_path)
    return output_path

def generate_draft_image(players: list[dict], captain_1_id: int, captain_2_id: int, top_ids: list[int] | None = None):
    # Картинка подложка
    DRAFT_BASE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "draft_base.png"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "draft_dynamic.png"
    image = Image.open(DRAFT_BASE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Шрифты и размеры
    nickname_font_size = 54
    line_spacing = 85
    rank_size = 48

    font = get_font(nickname_font_size)

    # Команды
    team_1 = [p for p in players if p["team"] == "captain_1"]
    team_2 = [p for p in players if p["team"] == "captain_2"]

    def draw_team(team_data, x_text, x_rank, align="left", captain_id=None):
        total_height = len(team_data) * line_spacing
        start_y = (image.height - total_height) // 2 + 40
        y = start_y

        for player in team_data:
            name = player.get("username", "—")
            rank = player.get("rank", "Unranked")
            is_captain = player.get("id") == captain_id
            pid = player.get("discord_id") or player.get("id")
            top_color = _color_for_top(pid, top_ids)
            color = top_color or ("#FFD23F" if is_captain else "white")
            draw.text((x_text, y), name, font=font, fill=color, anchor="la" if align == "left" else "ra")
            icon_path = get_icon_path(rank)

            if icon_path:
                try:
                    icon = Image.open(icon_path).resize((rank_size, rank_size)).convert("RGBA")
                    image.paste(icon, (x_rank, y), icon)
                except:
                    pass

            y += line_spacing

    # Левая колонка
    draw_team(team_1, x_text=80, x_rank=300, align="left", captain_id=captain_1_id)

    # Правая колонка
    draw_team(team_2, x_text=830, x_rank=730, align="right", captain_id=captain_2_id)

    image.save(output_path)
    return output_path


def generate_map_ban_image(available_maps: list[str], banned_maps: list[str], current_captain: str) -> Path:
    WIDTH, HEIGHT = 1280, 720
    PADDING = 40
    GRID_COLS = 4
    GRID_HGAP = 16
    GRID_VGAP = 16
    CELL_WIDTH = (WIDTH - PADDING*2 - GRID_HGAP*(GRID_COLS-1)) // GRID_COLS
    CELL_HEIGHT = 160
    TITLE_Y = 24

    MAP_DIRS = [
        Path(__file__).resolve().parents[1] / "maps",
        Path(__file__).resolve().parents[1] / "pictures" / "maps",
    ]
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "map_draft_dynamic.png"

    image = Image.new("RGBA", (WIDTH, HEIGHT), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)

    title_font = get_font(48)
    draw.text((PADDING, TITLE_Y), f"Бан карт — Ход: {current_captain}", font=title_font, fill="white")

    all_maps = ["Ascent","Bind","Haven","Split","Icebox","Breeze","Fracture","Lotus","Sunset","Abyss","Pearl"]
    font = get_font(26)


    for idx, map_name in enumerate(all_maps):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = PADDING + col * (CELL_WIDTH + GRID_HGAP)
        y = 120 + row * (CELL_HEIGHT + GRID_VGAP)

        icon_path = _find_map_image(map_name)
        if icon_path:
            try:
                tile = Image.open(icon_path).convert("RGB").resize((CELL_WIDTH, CELL_HEIGHT), Image.LANCZOS)
                if map_name in banned_maps:
                    tile = ImageEnhance.Brightness(tile).enhance(0.30)
                image.paste(tile, (x, y))
            except Exception as e:
                print(f"⚠ Ошибка загрузки карты {map_name}: {e}")

        if map_name in banned_maps:
            draw.line((x, y, x + CELL_WIDTH, y + CELL_HEIGHT), fill="red", width=5)
            draw.line((x, y + CELL_HEIGHT, x + CELL_WIDTH, y), fill="red", width=5)

        draw.text((x + 12, y + CELL_HEIGHT - 30), map_name, font=font, fill="white")

    image.save(output_path)
    return output_path


def generate_final_match_image(
    selected_map: str,
    attack_players: list[str],
    defense_players: list[str],
) -> Path:
    pictures_dir = Path(__file__).resolve().parents[1] / "pictures"
    out_path = pictures_dir / "final_match_dynamic.png"

    # Холст 1280×720 — Discord покажет крупно
    W, H = 1280, 720
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # Фон карты (cover)
    mp = _find_map_image(selected_map)
    if mp:
        try:
            bg = Image.open(mp).convert("RGBA")
            bw, bh = bg.size
            k = max(W / bw, H / bh)
            bg = bg.resize((int(bw * k), int(bh * k)), Image.LANCZOS)
            x = (bg.size[0] - W) // 2
            y = (bg.size[1] - H) // 2
            bg = bg.crop((x, y, x + W, y + H))
            canvas.paste(bg, (0, 0))
        except Exception:
            pass

    draw = ImageDraw.Draw(canvas)

    # Тёмный слой для читабельности
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    canvas.paste(overlay, (0, 0), overlay)

    # Заголовок
    title = f"КАРТА: {selected_map}"
    title_font = get_font(72)
    tw = draw.textlength(title, font=title_font)
    _draw_text(draw, ((W - tw) // 2, 36), title, title_font, fill="white", stroke=3)

    # Разметка колонок
    PAD = 40
    COL_W = (W - PAD * 3) // 2
    COL_H = H - 180
    TOP = 140

    box_fill = (20, 20, 22, 160)
    draw.rounded_rectangle([PAD, TOP, PAD + COL_W, TOP + COL_H], radius=24, fill=box_fill)
    draw.rounded_rectangle([PAD*2 + COL_W, TOP, PAD*2 + COL_W*2, TOP + COL_H], radius=24, fill=box_fill)

    h_font = get_font(44)
    _draw_text(draw, (PAD + 28, TOP + 16), "АТАКА", h_font, fill="#ff5555", stroke=2)
    _draw_text(draw, (PAD*2 + COL_W + 28, TOP + 16), "ЗАЩИТА", h_font, fill="#5aa3ff", stroke=2)

    # Списки игроков
    row_font_start = 40
    line_h = 56
    y0 = TOP + 84

    def draw_list(x0: int, players: list[str]):
        y = y0
        for name in players:
            name = str(name or "—")
            font = _fit_font(draw, name, COL_W - 56, start=row_font_start, min_size=28)
            _draw_text(draw, (x0 + 28, y), f"• {name}", font, fill="white")
            y += line_h

    draw_list(PAD, attack_players)
    draw_list(PAD*2 + COL_W, defense_players)

    canvas.save(out_path)
    return out_path


def generate_leaderboard_image(players: list[dict]) -> Path:
    base_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard.png"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard_dynamic.png"
    image = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Настройки
    font = get_font(40)
    icon_size = 54
    step_y = 90
    start_y = 180
    number_x = 70
    name_x = 150
    rank_icon_x = 660
    wins_x = 780

    for idx, player in enumerate(players):
        y = start_y + idx * step_y
        username = player.get("username", "—")
        rank = player.get("rank", "Unranked")
        wins = player.get("wins", 0)
        matches = player.get("matches", 1)
        winrate = int(wins / matches * 100) if matches > 0 else 0

        # Номер
        draw.text((number_x, y), f"{idx+1}.", font=font, fill="white")

        # Ник
        draw.text((name_x, y), username, font=font, fill="white")

        # Иконка ранга
        icon_path = get_icon_path(rank)
        if icon_path:
            try:
                icon = Image.open(icon_path).resize((icon_size, icon_size)).convert("RGBA")
                image.paste(icon, (rank_icon_x, y), icon)
            except Exception as e:
                print(f"⚠ Ошибка иконки ранга: {e}")

        # Победы и винрейт
        draw.text((wins_x, y), f"{wins}W | {winrate}%", font=font, fill="white")

    image.save(output_path)
    return output_path


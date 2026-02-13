from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from functools import lru_cache
import re
from io import BytesIO


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



def _rank_base(rank: str) -> str:
    r = str(rank or "").strip()
    if not r:
        return "Unranked"
    # "Immortal 3" -> "Immortal"
    return r.split()[0].capitalize()

def _player_label(p: dict) -> str:
    return format_username(p.get("username"), p.get("display_name"))

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

def _place_color(place: int) -> tuple[int, int, int]:
    if place == 1:
        return COLOR_GOLD
    if place == 2:
        return COLOR_SILVER
    if place == 3:
        return COLOR_BRONZE
    return (255, 255, 255)

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

def get_symbol_font(size: int):
    """
    Шрифт для символов типа ♥. Inter может не содержать глиф.
    DejaVuSans обычно есть в окружении Pillow.
    """
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        # если вдруг DejaVuSans нет — откатываемся на обычный
        return get_font(size)


# Сопоставление "Immortal" → "Immortal_3_Rank.png"
_RANK_ALIASES = {
    "plat": "Platinum",
    "platinum": "Platinum",
    "dia": "Diamond",
    "diamond": "Diamond",
    "asc": "Ascendant",
    "ascendant": "Ascendant",
    "immo": "Immortal",
    "immortal": "Immortal",
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
    "iron": "Iron",
    "radiant": "Radiant",
}

_ROMAN_TO_TIER = {"i": "1", "ii": "2", "iii": "3"}

def _parse_rank_icon(rank: str) -> tuple[str | None, str | None]:
    raw = (rank or "").strip()
    if not raw:
        return None, None
    cleaned = re.sub(r"[^\w\s]", " ", raw)
    parts = cleaned.replace("_", " ").replace("-", " ").split()
    if not parts:
        return None, None

    base_raw = parts[0].lower()
    base = _RANK_ALIASES.get(base_raw, base_raw.capitalize())

    tier = None
    for part in parts[1:]:
        p = part.lower()
        if p in {"1", "2", "3"}:
            tier = p
            break
        if p in _ROMAN_TO_TIER:
            tier = _ROMAN_TO_TIER[p]
            break

    return base, tier
    
def get_icon_path(rank: str):
    """
    Принимает:
      - "Immortal 1/2/3", "Ascendant 1/2/3", ...
      - или просто "Immortal" (тогда по умолчанию берём 3)
    Возвращает Path к файлу иконки либо None.
    """
    base, tier = _parse_rank_icon(rank or "Unranked")
    if not base:
        return None

    if base in {"Unranked", "Unrated"}:
        return None

    if base == "Radiant":
        filename = "Radiant_Rank.png"
    else:
        filename = f"{base}_{tier or '3'}_Rank.png"

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

def format_username(username: str, display_name: str | None = None) -> str:
    """
    Делает ровно 'nick(name)' без дублей.
    Если username уже содержит '(...)' в конце — удаляет это (сколько угодно раз).
    display_name можно не передавать: тогда возьмём имя из скобок, если оно было.
    """
    u = str(username or "—").strip()
    dn = str(display_name or "").strip()

    # Забираем ВСЕ хвостовые скобки: "nick (a) (a)" -> base="nick", groups=["a","a"]
    groups = []
    while True:
        m = re.search(r"\s*\(\s*([^)]+?)\s*\)\s*$", u)
        if not m:
            break
        groups.append(m.group(1).strip())
        u = u[:m.start()].strip()

    # Что поставить в скобки:
    suffix = dn if dn else (groups[0] if groups else "")

    # Если нет suffix — возвращаем как есть (base либо исходное)
    if not suffix:
        return u or "—"

    # Если base пустой — возвращаем только suffix
    if not u:
        return suffix

    # Если base == suffix — не дублируем
    if u.lower() == suffix.lower():
        return u

    # Итог без пробела: sweet(Юрачка)
    return f"{u}({suffix})"

def generate_lobby_image(players: list[dict], top_ids: list[int] | None = None) -> Path:
    top_ids = top_ids or []

    pictures_dir = Path(__file__).resolve().parents[1] / "pictures"
    base_path = pictures_dir / "lobby_base.png"
    output_path = pictures_dir / "lobby_dynamic.png"

    base_img = Image.open(base_path).convert("RGBA") if base_path.exists() \
        else Image.new("RGBA", (1024, 1280), (20, 20, 20, 255))
    draw = ImageDraw.Draw(base_img)
    width, height = base_img.size

    # -------- стиль/разметка --------
    PADDING_X = 88
    LIST_MIN_TOP = 300

    ROW_H = 96
    ROW_GAP = 14

    NUM_W = 48
    ICON_SIZE = 60
    ICON_PAD = 8

    CONTENT_LEFT = PADDING_X
    CONTENT_RIGHT = width - PADDING_X

    ICON_X = CONTENT_RIGHT - ICON_SIZE
    NAME_X = CONTENT_LEFT + NUM_W + 18
    NAME_W = (ICON_X - 16) - NAME_X

    number_font = get_font(40)

    def _text_h(text: str, font) -> int:
        try:
            b = draw.textbbox((0, 0), text, font=font)
            return b[3] - b[1]
        except Exception:
            try:
                b = font.getbbox(text)
                return b[3] - b[1]
            except Exception:
                return getattr(font, "size", 36)

    # центрируем список по вертикали (но не выше заголовка)
    n = max(len(players), 1)
    list_h = n * ROW_H + (n - 1) * ROW_GAP
    start_y = max(LIST_MIN_TOP, (height - list_h) // 2)

    # если игроков нет — рисуем заглушку
    if not players:
        empty_font = get_font(44)
        txt = "Нет участников"
        tw = draw.textlength(txt, font=empty_font)
        _draw_text(draw, ((width - tw) // 2, start_y + 20), txt, empty_font, fill="#D0D0D0", stroke=3)
        base_img.save(output_path)
        return output_path

    for idx, p in enumerate(players, start=1):
        display_name = str(p.get("display_name") or "").strip()
        label = format_username(p.get("username"), display_name)

        rank_raw = str(p.get("rank") or "Unranked").strip()
        icon_path = get_icon_path(rank_raw) or _rank_icon_path(_rank_base(rank_raw))

        pid = p.get("discord_id") or p.get("id")
        name_color = _color_for_top(pid, top_ids) or "white"

        y = start_y + (idx - 1) * (ROW_H + ROW_GAP)

        # карточка строки
        row_box = (CONTENT_LEFT - 18, y - 6, CONTENT_RIGHT + 12, y + ROW_H)
        draw.rounded_rectangle(
            row_box,
            radius=18,
            fill=(0, 0, 0, 110),
            outline=(255, 255, 255, 28),
            width=2
        )

        # номер (по центру строки)
        num_y = y + (ROW_H - _text_h(str(idx), number_font)) // 2 - 2
        _draw_text(draw, (CONTENT_LEFT, num_y), f"{idx}", number_font, fill="white", stroke=2)

        # ник (по центру строки)
        name_font = _fit_font(draw, label, NAME_W, start=54, min_size=30)
        name_y = y + (ROW_H - _text_h(label, name_font)) // 2 - 3
        _draw_text(draw, (NAME_X, name_y), label, name_font, fill=name_color, stroke=2)

        # подложка под иконку (чтобы она читалась на любом фоне)
        icon_y = y + (ROW_H - ICON_SIZE) // 2
        bg_box = (ICON_X - ICON_PAD, icon_y - ICON_PAD, ICON_X + ICON_SIZE + ICON_PAD, icon_y + ICON_SIZE + ICON_PAD)
        draw.rounded_rectangle(bg_box, radius=16, fill=(0, 0, 0, 140), outline=(255, 255, 255, 35), width=2)

        # иконка ранга (качественный ресайз!)
        if icon_path and Path(icon_path).exists():
            try:
                icon = Image.open(icon_path).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                base_img.paste(icon, (ICON_X, icon_y), icon)
            except Exception:
                pass

    base_img.save(output_path)
    return output_path


def generate_draft_image(
    players: list[dict],
    captain_1_id: int,
    captain_2_id: int,
    top_ids: list[int] | None = None
) -> Path:
    top_ids = top_ids or []

    base_path = Path(__file__).resolve().parents[1] / "pictures" / "draft_base.png"
    out_path  = Path(__file__).resolve().parents[1] / "pictures" / "draft_dynamic.png"
    image = Image.open(base_path).convert("RGBA")
    draw  = ImageDraw.Draw(image)

    # ===== разметка колонок =====
    PAD_X     = 80
    CENTER_X  = image.width // 2

    LINE_H    = 92
    ROW_GAP   = 8

    # слот под иконку (в шаблоне у тебя есть рамки — мы просто ставим иконку аккуратно внутрь)
    ICON_SLOT_W = 86          # сколько места “отъедаем” справа под рамку/иконку
    ICON_GUTTER = 18          # дистанция между текстом и иконкой
    ICON_SIZE   = 48          # сама иконка (меньше рамки — выглядит чище)

    # Левая колонка
    L_LEFT   = PAD_X
    L_RIGHT  = CENTER_X - PAD_X
    L_TEXT_X = L_LEFT + 16
    L_ICON_X = L_RIGHT - ICON_SLOT_W + (ICON_SLOT_W - ICON_SIZE) // 2  # центрируем иконку в слоте

    # Правая колонка
    R_LEFT   = CENTER_X + PAD_X
    R_RIGHT  = image.width - PAD_X
    R_TEXT_X = R_LEFT + 16
    R_ICON_X = R_RIGHT - ICON_SLOT_W + (ICON_SLOT_W - ICON_SIZE) // 2

    # Пределы шрифта (фикс “Sanya на пол-экрана”)
    NICK_START = 44
    NICK_MIN   = 24

    team_1 = [p for p in players if p.get("team") == "captain_1"]
    team_2 = [p for p in players if p.get("team") == "captain_2"]

    def _text_h(text: str, font) -> int:
        try:
            b = draw.textbbox((0, 0), text, font=font)
            return b[3] - b[1]
        except Exception:
            return getattr(font, "size", 30)

    def _ellipsis(text: str, font, max_w: int) -> str:
        """Если даже на минимальном шрифте не влезает — режем и ставим …"""
        if draw.textlength(text, font=font) <= max_w:
            return text
        ell = "…"
        t = text
        while t and draw.textlength(t + ell, font=font) > max_w:
            t = t[:-1]
        return (t + ell) if t else ell

    def draw_column(team_data, x_text, x_icon, x_right, captain_id=None):
        total_h = len(team_data) * (LINE_H + ROW_GAP) - (ROW_GAP if team_data else 0)
        y = (image.height - total_h) // 2 + 40

        # реальная ширина под ник: до правого края колонки минус слот под иконку
        name_max_w = (x_right - ICON_SLOT_W - ICON_GUTTER) - x_text

        for p in team_data:
            # имя всегда через твой форматтер (ник + имя в скобках, без дублей)
            name = _player_label(p)

            # нормализуем ранг под маппинг иконок
            rank_raw = str(p.get("rank") or "Unranked").strip()
            icon_path = get_icon_path(rank_raw)

            pid = p.get("discord_id") or p.get("id")
            top_color = _color_for_top(pid, top_ids)
            color = top_color or "white"

            # 1) сначала рисуем иконку (чтобы текст всегда был поверх, если что)
            if icon_path:
                try:
                    icon = Image.open(icon_path).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                    icon_y = y + (LINE_H - ICON_SIZE) // 2
                    image.paste(icon, (x_icon, icon_y), icon)
                except Exception:
                    pass

            # 2) шрифт под ширину, но с верхним лимитом, чтобы короткие ники не были огромными
            font = _fit_font(draw, name, name_max_w, start=NICK_START, min_size=NICK_MIN)
            name = _ellipsis(name, font, name_max_w)

            text_y = y + (LINE_H - _text_h(name, font)) // 2 - 2
            _draw_text(draw, (x_text, text_y), name, font=font, fill=color)

            y += (LINE_H + ROW_GAP)

    draw_column(team_1, L_TEXT_X, L_ICON_X, L_RIGHT, captain_id=captain_1_id)
    draw_column(team_2, R_TEXT_X, R_ICON_X, R_RIGHT, captain_id=captain_2_id)

    image.save(out_path)
    return out_path

def generate_map_ban_image(available_maps: list[str], banned_maps: list[str], current_captain: str) -> Path:
    WIDTH, HEIGHT = 1280, 720
    PADDING = 40
    GRID_COLS = 4
    GRID_HGAP = 16
    GRID_VGAP = 16
    CELL_WIDTH = (WIDTH - PADDING * 2 - GRID_HGAP * (GRID_COLS - 1)) // GRID_COLS
    CELL_HEIGHT = 160
    TITLE_Y = 24

    output_path = Path(__file__).resolve().parents[1] / "pictures" / "map_draft_dynamic.png"

    image = Image.new("RGBA", (WIDTH, HEIGHT), (18, 18, 18, 255))
    draw = ImageDraw.Draw(image)

    title_font = get_font(52)
    draw.text((PADDING, TITLE_Y), f"Бан карт — Ход: {current_captain}", font=title_font, fill="white")

    # порядок/набор карт: оставляем фиксированный, чтобы сетка была всегда одинаковая
    all_maps = ["Ascent","Bind","Haven","Split","Icebox","Breeze","Fracture","Lotus","Sunset","Abyss","Pearl", "Corrode"]

    name_font = get_font(28)
    badge_font = get_font(22)
    order_font = get_font(20)

    banned_set = {m for m in banned_maps}
    def apply_bottom_gradient(tile_rgba: Image.Image, max_alpha: int = 190, start_frac: float = 0.58) -> Image.Image:
        """Чёрный градиент снизу для читабельности названия."""
        w, h = tile_rgba.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        start_y = int(h * start_frac)
        denom = max(1, h - start_y)
        for yy in range(start_y, h):
            a = int(max_alpha * ((yy - start_y) / denom))
            od.line([(0, yy), (w, yy)], fill=(0, 0, 0, a))

        return Image.alpha_composite(tile_rgba, overlay)

    def draw_badge(x: int, y: int, text: str, fill=(220, 60, 60, 220)):
        """Бейдж в левом верхнем углу."""
        pad_x = 10
        tw = draw.textlength(text, font=badge_font)
        bx1, by1 = x + 10, y + 10
        bx2, by2 = int(bx1 + tw + pad_x * 2), by1 + 34

        draw.rounded_rectangle((bx1, by1, bx2, by2), radius=10, fill=fill, outline=(255, 255, 255, 35), width=2)
        _draw_text(draw, (bx1 + pad_x, by1 + 5), text, badge_font, fill="white", stroke=2)

    def draw_order(x: int, y: int, n: int):
        """Номер бана (1,2,3...) справа сверху."""
        r = 14
        cx, cy = x + CELL_WIDTH - 22, y + 22
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 160), outline=(255, 255, 255, 40), width=2)
        t = str(n)
        tw = draw.textlength(t, font=order_font)
        _draw_text(draw, (cx - tw / 2, cy - 10), t, order_font, fill="white", stroke=2)

    def draw_thin_x(x: int, y: int):
        """Тонкий полупрозрачный X (не режет глаза и не убивает читаемость)."""
        col = (255, 70, 70, 120)
        w = 5
        draw.line((x + 10, y + 10, x + CELL_WIDTH - 10, y + CELL_HEIGHT - 10), fill=col, width=w)
        draw.line((x + 10, y + CELL_HEIGHT - 10, x + CELL_WIDTH - 10, y + 10), fill=col, width=w)

    for idx, map_name in enumerate(all_maps):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = PADDING + col * (CELL_WIDTH + GRID_HGAP)
        y = 120 + row * (CELL_HEIGHT + GRID_VGAP)

        # фон-заглушка
        tile = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (35, 35, 35, 255))

        # картинка карты
        icon_path = _find_map_image(map_name)
        if icon_path:
            try:
                raw = Image.open(icon_path).convert("RGBA").resize((CELL_WIDTH, CELL_HEIGHT), Image.LANCZOS)
                tile = raw
            except Exception as e:
                print(f"⚠ Ошибка загрузки карты {map_name}: {e}")

        # градиент под текст
        tile = apply_bottom_gradient(tile)

        # если забанено — затемняем сильнее
        is_banned = map_name in banned_set
        if is_banned:
            overlay = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 150))
            tile = Image.alpha_composite(tile, overlay)

        # вставляем тайл
        image.paste(tile, (x, y))

        # рамка: доступные подсвечиваем, забаненные — нейтральная
        if is_banned:
            draw.rounded_rectangle((x, y, x + CELL_WIDTH, y + CELL_HEIGHT), radius=14,
                                   outline=(255, 255, 255, 40), width=2)
        else:
            # чуть ярче, чтобы выделить "живые" карты
            draw.rounded_rectangle((x, y, x + CELL_WIDTH, y + CELL_HEIGHT), radius=14,
                                   outline=(255, 255, 255, 90), width=3)

        # подпись карты (поверх градиента)
        _draw_text(draw, (x + 12, y + CELL_HEIGHT - 34), map_name, name_font, fill="white", stroke=2)

        # отметки бана
        if is_banned:
            draw_badge(x, y, "BANNED")
            # номер бана по порядку в banned_maps
            try:
                ban_n = banned_maps.index(map_name) + 1
                draw_order(x, y, ban_n)
            except ValueError:
                pass
            draw_thin_x(x, y)

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

    # ---- настройки прозрачности ----
    OVERLAY_ALPHA = 70  # было 120 — общий дым стал ~в 2 раза прозрачнее
    PANEL_ALPHA = 110  # было 160 — панели стали прозрачнее
    PANEL_RADIUS = 24
    PANEL_OUTLINE = (255, 255, 255, 60)  # тонкий светлый контур

    # Тёмный слой для читабельности
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, OVERLAY_ALPHA))
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

    box_fill = (20, 20, 22, PANEL_ALPHA)
    draw.rounded_rectangle([PAD, TOP, PAD + COL_W, TOP + COL_H], radius=PANEL_RADIUS, fill=box_fill, outline=PANEL_OUTLINE, width=2)
    draw.rounded_rectangle([PAD * 2 + COL_W, TOP, PAD * 2 + COL_W * 2, TOP + COL_H], radius=PANEL_RADIUS, fill=box_fill, outline=PANEL_OUTLINE, width=2)

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

    num_font   = get_font(42)
    stat_font  = get_font(36)

    icon_size  = 54
    row_h      = 86
    row_gap    = 10
    start_y    = 170

    number_x   = 70
    name_x     = 150
    rank_icon_x = 660
    wins_x     = 780

    def _text_h(text: str, font) -> int:
        try:
            b = draw.textbbox((0, 0), text, font=font)
            return b[3] - b[1]
        except Exception:
            return getattr(font, "size", 32)

    for place, player in enumerate(players, start=1):
        y = start_y + (place - 1) * (row_h + row_gap)

        display_name = str(player.get("display_name") or "").strip()
        username = format_username(player.get("username"), display_name)

        rank_raw = str(player.get("rank") or "Unranked").strip()
        wins = int(player.get("wins", 0))
        matches = int(player.get("matches", 0))

        winrate = round((wins / matches) * 100, 1) if matches > 0 else 0
        winrate_s = (f"{winrate:.1f}").rstrip("0").rstrip(".")

        c = _place_color(place)

        # фон строки
        row_left = 54
        row_right = image.width - 54
        draw.rounded_rectangle(
            (row_left, y - 6, row_right, y + row_h),
            radius=16,
            fill=(0, 0, 0, 100),
            outline=(255, 255, 255, 24),
            width=2
        )

        _draw_text(draw, (number_x, y + (row_h - _text_h(f"{place}.", num_font)) // 2 - 2), f"{place}.", num_font, fill=c, stroke=2)

        name_max_w = (rank_icon_x - 24) - name_x
        name_font  = _fit_font(draw, username, name_max_w, start=40, min_size=26)
        _draw_text(draw, (name_x, y + (row_h - _text_h(username, name_font)) // 2 - 2), username, name_font, fill=c, stroke=2)

        icon_path = get_icon_path(rank_raw)
        if icon_path:
            try:
                icon = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size), Image.LANCZOS)
                icon_y = y + (row_h - icon_size) // 2
                image.paste(icon, (rank_icon_x, icon_y), icon)
            except Exception:
                pass

        _draw_text(draw, (wins_x, y + (row_h - _text_h("0W | 0%", stat_font)) // 2 - 2), f"{wins}W | {winrate_s}%", stat_font, fill="white", stroke=2)

    image.save(output_path)
    return output_path

def _rank_base_text(rank: str) -> str:
    r = str(rank or "").strip()
    if not r:
        return "Unranked"
    return r.split()[0].capitalize()


def generate_profile_card(
    discord_name: str,
    riot_username: str,
    rank: str,
    wins: int,
    matches: int,
    avatar_bytes: bytes | None = None,
    theme: str = "default",
    win_streak: int | None = None,
    favorite_map: str | None = None,
) -> Path:
    """
    Генерирует красивую профиль-карту 1280x720:
    - фон + панели
    - круглый аватар
    - иконка ранга (из твоей папки ranks)
    - статистика
    """
    WIDTH, HEIGHT = 1280, 720
    out_path = Path(__file__).resolve().parents[1] / "pictures" / "profile_card_dynamic.png"

    # ---------- базовый фон ----------
    img = Image.new("RGBA", (WIDTH, HEIGHT), (10, 10, 12, 255))
    draw = ImageDraw.Draw(img)

    # градиент
    top = (14, 14, 18)
    bot = (7, 7, 10)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))

    # лёгкий шум
    try:
        noise = Image.effect_noise((WIDTH, HEIGHT), 18).convert("L")
        noise_rgba = Image.merge("RGBA", (noise, noise, noise, noise.point(lambda a: 24)))
        img = Image.alpha_composite(img, noise_rgba)
        draw = ImageDraw.Draw(img)
    except Exception:
        pass


    # ---------- стиль ----------
    THEMES = {
        "default": {
            "accent": (255, 170, 60, 255),
            "panel_fill": (0, 0, 0, 120),
            "panel_out": (255, 255, 255, 35),
        },
        "valentine": {
            "accent": (255, 90, 160, 255),
            "panel_fill": (0, 0, 0, 120),
            "panel_out": (255, 255, 255, 35),
        }
    }
    cfg = THEMES.get((theme or "default").lower(), THEMES["default"])

    ACCENT = cfg["accent"]
    PANEL_FILL = cfg["panel_fill"]
    PANEL_OUT = cfg["panel_out"]

    title_font = get_font(86)
    small_font = get_font(34)
    value_font = get_font(46)
    name_font = get_font(64)

    # ---------- заголовок ----------
    _draw_text(draw, (70, 40), "VALORANT", title_font, fill="white", stroke=4)
    # тонкая линия под заголовком
    draw.line([(70, 150), (WIDTH - 70, 150)], fill=(255, 255, 255, 35), width=2)

    # ---------- панели ----------
    # Левая панель (статы)
    left_x1, left_y1 = 70, 190
    left_x2, left_y2 = 430, 630
    draw.rounded_rectangle((left_x1, left_y1, left_x2, left_y2), radius=26, fill=PANEL_FILL, outline=PANEL_OUT, width=2)

    # Центральная панель (аватар + ник)
    mid_x1, mid_y1 = 460, 190
    mid_x2, mid_y2 = 860, 630
    draw.rounded_rectangle((mid_x1, mid_y1, mid_x2, mid_y2), radius=26, fill=PANEL_FILL, outline=PANEL_OUT, width=2)

    # Правая панель (ранг)
    right_x1, right_y1 = 890, 190
    right_x2, right_y2 = 1210, 630
    draw.rounded_rectangle((right_x1, right_y1, right_x2, right_y2), radius=26, fill=PANEL_FILL, outline=PANEL_OUT, width=2)

    # ---------- расчёты ----------
    wins = int(wins or 0)
    matches = int(matches or 0)
    losses = max(matches - wins, 0)
    winrate = 0.0 if matches <= 0 else (wins / matches) * 100.0

    # ---------- левая панель: статистика ----------
    rows = [
        ("Matches", str(matches)),
        ("Winrate", (f"{winrate:.1f}".rstrip("0").rstrip(".") + "%") if matches > 0 else "—"),
        ("Wins", str(wins)),
        ("Loses", str(losses)),
    ]

    ry = left_y1 + 26
    for label, value in rows:
        # мини-карточка строки
        draw.rounded_rectangle((left_x1 + 20, ry, left_x2 - 20, ry + 86), radius=18,
                               fill=(0, 0, 0, 110), outline=(255, 255, 255, 25), width=2)
        _draw_text(draw, (left_x1 + 40, ry + 20), label, small_font, fill=(220, 220, 220, 255), stroke=2)
        _draw_text(draw, (left_x2 - 40 - int(draw.textlength(value, font=value_font)), ry + 18),
                   value, value_font, fill="white", stroke=2)
        ry += 98

    # ---------- центр: аватар круглый ----------
    avatar_size = 250
    cx = (mid_x1 + mid_x2) // 2
    cy = mid_y1 + 165

    # рамка
    draw.ellipse((cx - avatar_size//2 - 8, cy - avatar_size//2 - 8, cx + avatar_size//2 + 8, cy + avatar_size//2 + 8),
                 outline=(255, 255, 255, 55), width=6)

    if avatar_bytes:
        try:
            av = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((avatar_size, avatar_size), Image.LANCZOS)

            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

            img.paste(av, (cx - avatar_size//2, cy - avatar_size//2), mask)
        except Exception:
            # если аватар сломался — рисуем заглушку
            draw.ellipse((cx - avatar_size//2, cy - avatar_size//2, cx + avatar_size//2, cy + avatar_size//2),
                         fill=(0, 0, 0, 160), outline=(255, 255, 255, 35), width=2)
            _draw_text(draw, (cx - 22, cy - 40), "?", get_font(96), fill="white", stroke=4)
    else:
        draw.ellipse((cx - avatar_size//2, cy - avatar_size//2, cx + avatar_size//2, cy + avatar_size//2),
                     fill=(0, 0, 0, 160), outline=(255, 255, 255, 35), width=2)
        _draw_text(draw, (cx - 22, cy - 40), "?", get_font(96), fill="white", stroke=4)

    # Ник Discord / Riot
    dn = (discord_name or "").strip()
    rn = (riot_username or "—").strip()

    # Discord name
    dn_w = draw.textlength(dn, font=name_font)
    _draw_text(draw, (cx - int(dn_w)//2, mid_y2 - 150), dn, name_font, fill="white", stroke=3)

    # Riot username
    rfont = get_font(40)
    rn_w = draw.textlength(rn, font=rfont)
    _draw_text(draw, (cx - int(rn_w)//2, mid_y2 - 86), rn, rfont, fill=(210, 210, 210, 255), stroke=2)

    # ---------- доп. инфо (streak / fav map) ----------
    # ВАЖНО: win_streak может быть 0 — это валидное значение
    info_color = (210, 210, 210, 255)

    streak_txt = f"Win streak: {win_streak}" if win_streak is not None else "Win streak: —"
    fav_txt = f"Fav map: {favorite_map}" if favorite_map else "Fav map: —"

    # рисуем 2 строки аккуратно внутри центральной панели (по центру снизу)
    panel_center_x = (mid_x1 + mid_x2) // 2
    bottom_pad = 34
    line_gap = 30

    # подбираем шрифт под ширину центральной панели
    max_w = (mid_x2 - mid_x1) - 72
    streak_font = _fit_font(draw, streak_txt, max_w, start=30, min_size=22)
    fav_font = _fit_font(draw, fav_txt, max_w, start=30, min_size=22)

    # Y так, чтобы обе строки гарантированно влезали
    sy = mid_y2 - bottom_pad - (line_gap + 22)

    sw = draw.textlength(streak_txt, font=streak_font)
    fw = draw.textlength(fav_txt, font=fav_font)

    _draw_text(draw, (panel_center_x - int(sw) // 2, sy), streak_txt, streak_font, fill=info_color, stroke=2)
    _draw_text(draw, (panel_center_x - int(fw) // 2, sy + line_gap), fav_txt, fav_font, fill=info_color, stroke=2)

    # ---------- правая панель: ранг ----------
    rank_raw = str(rank or "Unranked").strip()
    rb = _rank_base_text(rank_raw)
    icon_path = get_icon_path(rank_raw) or _rank_icon_path(rb)

    icx = (right_x1 + right_x2) // 2
    panel_w = (right_x2 - right_x1)
    pad = 26
    max_text_w = panel_w - pad * 2

    # 1) Ранг — сверху, но шрифт подгоняем под ширину панели
    rname = rank_raw if rank_raw else rb
    rname_font = _fit_font(draw, rname, max_text_w, start=56, min_size=30)
    rw = draw.textlength(rname, font=rname_font)
    _draw_text(draw, (icx - int(rw) // 2, right_y1 + 32), rname, rname_font, fill=ACCENT, stroke=3)

    # 2) Иконка ранга — строго по центру правой панели
    icon_size = 132
    icy = (right_y1 + right_y2) // 2 - 10

    ring = 10
    draw.ellipse(
        (icx - icon_size // 2 - ring, icy - icon_size // 2 - ring,
         icx + icon_size // 2 + ring, icy + icon_size // 2 + ring),
        fill=(0, 0, 0, 120),
        outline=(255, 255, 255, 45),
        width=4
    )

    if icon_path and Path(icon_path).exists():
        try:
            icon = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size), Image.LANCZOS)
            img.paste(icon, (icx - icon_size // 2, icy - icon_size // 2), icon)
        except Exception:
            _draw_text(draw, (icx - 18, icy - 52), "?", get_font(96), fill="white", stroke=4)
    else:
        _draw_text(draw, (icx - 18, icy - 52), "?", get_font(96), fill="white", stroke=4)

    # 3) Wins + цифра — внизу, с нормальными отступами
    label_font = get_font(34)
    value_font_big = get_font(96)

    wins_label_y = right_y2 - 190
    wins_value_y = right_y2 - 150

    _w = draw.textlength("Wins", font=label_font)
    _draw_text(draw, (icx - int(_w) // 2, wins_label_y), "Wins", label_font, fill=(220, 220, 220, 255), stroke=2)

    big = str(wins)
    bw = draw.textlength(big, font=value_font_big)
    _draw_text(draw, (icx - int(bw) // 2, wins_value_y), big, value_font_big, fill="white", stroke=4)

    # ---------- Valentine overlay (ПОСЛЕ панелей, чтобы не перекрывалось) ----------
    if (theme or "").lower() == "valentine":
        try:
            overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)

            heart = "♥"
            hf_big = get_symbol_font(64)
            hf_small = get_symbol_font(42)

            # ставим сердца в "свободных" зонах (фон), чтобы не мешали читабельности
            hearts = [
                (90, 170, 28, hf_big),
                (1150, 165, 24, hf_big),
                (80, 610, 22, hf_small),
                (1180, 600, 18, hf_small),
                (1040, 80, 16, hf_small),
                (180, 90, 14, hf_small),
            ]
            for x, y, a, f in hearts:
                od.text((x, y), heart, font=f, fill=(255, 90, 160, a))

            img = Image.alpha_composite(img, overlay)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    img.save(out_path)
    return out_path

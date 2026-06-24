from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
from functools import lru_cache
import re
from io import BytesIO
import random
from datetime import datetime
import os


# ---------- Themes registry (профиль/лидерборд) ----------
THEMES: dict[str, dict] = {
    "default": {
        "accent": (255, 170, 60, 255),
        "panel_fill": (0, 0, 0, 120),
        "panel_out": (255, 255, 255, 35),
    },
    "valentine": {
        "accent": (255, 90, 160, 255),
        "panel_fill": (0, 0, 0, 120),
        "panel_out": (255, 255, 255, 35),
    },
    "new_year": {
        "accent": (180, 230, 255, 255),
        "panel_fill": (0, 0, 0, 120),
        "panel_out": (255, 255, 255, 35),
    },
    "halloween": {
        "accent": (255, 148, 59, 255),
        "panel_fill": (0, 0, 0, 120),
        "panel_out": (255, 255, 255, 35),
    },
}

def resolve_theme_key(theme: str | None) -> str:
    key = (theme or "default").strip().lower()

    if key in {"auto", "seasonal"}:
        key = _seasonal_theme_key()

    return key if key in THEMES else "default"

def _seasonal_theme_key() -> str:
    d = datetime.utcnow().date()
    md = (d.month, d.day)

    # окна можно менять как угодно
    if (12, 24) <= md or md <= (1, 10):
        return "new_year"
    if (10, 20) <= md <= (11, 5):
        return "halloween"
    if (2, 10) <= md <= (2, 16):
        return "valentine"
    return "default"

def get_theme_cfg(theme: str | None) -> dict:
    return THEMES[resolve_theme_key(theme)]


def _rect_intersects(a, b) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 <= bx1 or ax1 >= bx2 or ay2 <= by1 or ay1 >= by2)

def _make_heart_sprite(size: int, color_rgba: tuple[int, int, int, int]) -> Image.Image:
    """
    Аккуратное сердечко как RGBA-спрайт.
    """
    size = max(12, int(size))
    s = size
    spr = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(spr)

    r = int(s * 0.28)
    cx1, cy = int(s * 0.35), int(s * 0.28)
    cx2 = int(s * 0.65)

    d.ellipse((cx1 - r, cy - r, cx1 + r, cy + r), fill=color_rgba)
    d.ellipse((cx2 - r, cy - r, cx2 + r, cy + r), fill=color_rgba)

    top_y = cy + int(r * 0.45)
    d.polygon(
        [(int(s * 0.10), top_y), (int(s * 0.90), top_y), (s // 2, int(s * 0.95))],
        fill=color_rgba
    )
    return spr

def _make_text_sprite(symbol: str, size: int,
                      fill: tuple[int, int, int, int],
                      stroke_fill: tuple[int, int, int, int],
                      stroke_width: int) -> Image.Image:
    """
    Рендерит символ в RGBA-спрайт (чтобы можно было вращать и paste).
    """
    size = max(12, int(size))
    font = get_font(size)

    canvas = Image.new("RGBA", (size * 3, size * 3), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    bbox = d.textbbox((0, 0), symbol, font=font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    x = (canvas.size[0] - w) // 2 - bbox[0]
    y = (canvas.size[1] - h) // 2 - bbox[1]

    d.text((x, y), symbol, font=font, fill=fill, stroke_fill=stroke_fill, stroke_width=stroke_width)

    bb = canvas.getbbox()
    if not bb:
        return canvas

    pad = 6
    x1 = max(0, bb[0] - pad)
    y1 = max(0, bb[1] - pad)
    x2 = min(canvas.size[0], bb[2] + pad)
    y2 = min(canvas.size[1], bb[3] + pad)
    return canvas.crop((x1, y1, x2, y2))


def _apply_default_question_marks(
    img: Image.Image,
    safe_rects: list[tuple[int, int, int, int]] | None,
    accent: tuple[int, int, int, int],
) -> Image.Image:
    """
    Default тема: вопросики в случайных местах.
    """
    WIDTH, HEIGHT = img.size
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    safe_rects = safe_rects or []
    count = random.randint(6, 14)
    tries = 0
    placed = 0

    while placed < count and tries < 350:
        tries += 1

        size = random.randint(22, 54)
        angle = random.randint(-28, 28)
        alpha = random.randint(80, 150)

        fill = (255, 255, 255, alpha)
        stroke = (accent[0], accent[1], accent[2], min(255, alpha + 70))
        sw = max(2, size // 10)

        spr = _make_text_sprite("?", size, fill=fill, stroke_fill=stroke, stroke_width=sw)
        spr = spr.rotate(angle, resample=Image.BICUBIC, expand=True)

        w, h = spr.size
        x = random.randint(10, max(10, WIDTH - w - 10))
        y = random.randint(10, max(10, HEIGHT - h - 10))
        rect = (x, y, x + w, y + h)

        if any(_rect_intersects(rect, r) for r in safe_rects):
            continue

        overlay.paste(spr, (x, y), spr)
        placed += 1

    return Image.alpha_composite(img, overlay)


def _apply_valentine_hearts(img: Image.Image, safe_rects: list[tuple[int, int, int, int]] | None) -> Image.Image:
    """
    Сердечки по краям/в пустых местах, рандомно.
    safe_rects — зоны, куда нельзя залезать (контент).
    """
    WIDTH, HEIGHT = img.size
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    safe_rects = safe_rects or []
    count = random.randint(6, 14)
    tries = 0
    placed = 0

    while placed < count and tries < 300:
        tries += 1

        size = random.randint(22, 54)
        angle = random.randint(-28, 28)
        alpha = random.randint(90, 170)

        inner = (255, 90, 160, alpha)
        outer = (255, 90, 160, min(255, alpha + 40))

        heart_out = _make_heart_sprite(size + 6, outer).rotate(angle, resample=Image.BICUBIC, expand=True)
        heart_in  = _make_heart_sprite(size, inner).rotate(angle, resample=Image.BICUBIC, expand=True)

        w, h = heart_out.size
        x = random.randint(10, max(10, WIDTH - w - 10))
        y = random.randint(10, max(10, HEIGHT - h - 10))
        rect = (x, y, x + w, y + h)

        if any(_rect_intersects(rect, r) for r in safe_rects):
            continue

        overlay.paste(heart_out, (x, y), heart_out)

        ix = x + (heart_out.size[0] - heart_in.size[0]) // 2
        iy = y + (heart_out.size[1] - heart_in.size[1]) // 2
        overlay.paste(heart_in, (ix, iy), heart_in)

        placed += 1

    return Image.alpha_composite(img, overlay)


def apply_theme_overlay(
    img: Image.Image,
    theme: str | None,
    safe_rects: list[tuple[int, int, int, int]] | None = None
) -> Image.Image:
    key = resolve_theme_key(theme)

    if key == "valentine":
        return _apply_valentine_hearts(img, safe_rects)

    # default (и всё неизвестное, т.к. resolve_theme_key вернёт default)
    accent = get_theme_cfg(key)["accent"]
    return _apply_default_question_marks(img, safe_rects, accent=accent)



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

# Theme overlays (profile card)
def _rect_intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 <= bx1 or ax1 >= bx2 or ay2 <= by1 or ay1 >= by2)



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


def generate_leaderboard_image(players: list[dict], theme: str = "default") -> Path:
    base_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard.png"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard_dynamic.png"
    image = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    cfg = get_theme_cfg(theme)

    num_font = get_font(42)
    stat_font = get_font(36)

    icon_size = 54
    row_h = 86
    row_gap = 10
    start_y = 170

    number_x = 70
    name_x = 150
    rank_icon_x = 660
    wins_x = 780

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

        _draw_text(draw, (number_x, y + (row_h - _text_h(f"{place}.", num_font)) // 2 - 2), f"{place}.", num_font,
                   fill=c, stroke=2)

        name_max_w = (rank_icon_x - 24) - name_x
        name_font = _fit_font(draw, username, name_max_w, start=40, min_size=26)
        _draw_text(draw, (name_x, y + (row_h - _text_h(username, name_font)) // 2 - 2), username, name_font, fill=c,
                   stroke=2)

        # ---- иконка ранга ----
        icon_path = get_icon_path(rank_raw)
        if icon_path:
            try:
                icon = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size), Image.LANCZOS)
                icon_y = y + (row_h - icon_size) // 2
                image.paste(icon, (rank_icon_x, icon_y), icon)
            except Exception:
                pass

        # ---- статистика справа ----
        _draw_text(draw, (wins_x, y + (row_h - _text_h("0W | 0%", stat_font)) // 2 - 2), f"{wins}W | {winrate_s}%", stat_font, fill="white", stroke=2)

    try:
        # защищаем основной блок таблицы, чтобы сердечки не лезли на строки
        row_left = 54
        row_right = image.width - 54
        start_y = 170
        row_h = 86
        row_gap = 10
        last_y = start_y + (len(players) - 1) * (row_h + row_gap)

        safe_rects = [
            (0, 0, image.width, 160),
            (row_left - 10, start_y - 10, row_right + 10, last_y + row_h + 10),
        ]
        image = apply_theme_overlay(image, theme, safe_rects=safe_rects)
        draw = ImageDraw.Draw(image)
    except Exception:
        pass

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
    Генерирует летнюю профиль-карту на готовом шаблоне.
    Основа:
        modules/pictures/profile_summer_base.png

    Что делает:
    - использует твой шаблон как базу;
    - вставляет аватар внутрь готового круга;
    - рисует премиальную статистику;
    - рисует улучшенный блок ранга;
    - добавляет атмосферу и блики поверх фона.
    """
    pictures_dir = Path(__file__).resolve().parents[1] / "pictures"
    base_path = pictures_dir / "profile_summer_base.png"
    out_path = pictures_dir / "profile_card_dynamic.png"

    # ---------- Загружаем основу ----------
    if base_path.exists():
        img = Image.open(base_path).convert("RGBA")
    else:
        img = Image.new("RGBA", (1672, 941), (15, 15, 20, 255))

    draw = ImageDraw.Draw(img)
    W, H = img.size

    # ---------- Данные ----------
    discord_name = str(discord_name or "Player").strip()
    riot_username = str(riot_username or "—").strip()
    rank_raw = str(rank or "Unranked").strip()

    wins = int(wins or 0)
    matches = int(matches or 0)
    loses = max(matches - wins, 0)

    if matches <= 0:
        winrate_text = "—"
    else:
        winrate = round((wins / matches) * 100, 1)
        winrate_text = f"{winrate}%"

    # ---------- Масштаб ----------
    sx = W / 1672
    sy = H / 941
    scale = min(sx, sy)

    def SBOX(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
        return int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)

    left_panel = SBOX((92, 244, 555, 814))
    center_panel = SBOX((593, 244, 1108, 814))
    right_panel = SBOX((1146, 244, 1558, 814))

    # ---------- Вспомогательные функции ----------
    def text_h(text: str, font) -> int:
        try:
            b = draw.textbbox((0, 0), text, font=font)
            return b[3] - b[1]
        except Exception:
            return getattr(font, "size", 32)

    def center_text(
            text: str,
            box: tuple[int, int, int, int],
            font: object,
            fill: object = (255, 255, 255, 255),
            stroke_width: int = 2,
            stroke_fill: object = (0, 0, 0, 220),
    ) -> None:
        x1, y1, x2, y2 = box
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]

        x = x1 + ((x2 - x1) - bw) // 2 - bbox[0]
        y = y1 + ((y2 - y1) - bh) // 2 - bbox[1]

        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )

    def fit_font(text: str, max_width: int, start_size: int, min_size: int = 24):
        size = start_size
        font = get_font(size)

        while draw.textlength(text, font=font) > max_width and size > min_size:
            size -= 2
            font = get_font(size)

        return font

    def tracked_center_text(
        text: str,
        box: tuple[int, int, int, int],
        font,
        tracking: int = 6,
        fill=(255, 255, 255, 255),
        stroke_width: int = 2,
        stroke_fill=(0, 0, 0, 220),
    ):
        x1, y1, x2, y2 = box
        chars = list(text)

        widths = [draw.textlength(ch, font=font) for ch in chars]
        total_w = int(sum(widths) + tracking * max(0, len(chars) - 1))
        th = text_h(text, font)

        x = x1 + ((x2 - x1) - total_w) // 2
        y = y1 + ((y2 - y1) - th) // 2

        for i, ch in enumerate(chars):
            draw.text(
                (x, y),
                ch,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            x += int(widths[i]) + tracking

    def draw_glow_text_xy(
        text: str,
        xy: tuple[int, int],
        font,
        fill=(255, 255, 255, 255),
        glow_color=(255, 100, 200, 90),
        glow_radius: int = 8,
        stroke_width: int = 2,
        stroke_fill=(0, 0, 0, 220),
    ):
        tx, ty = int(xy[0]), int(xy[1])

        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        pad = glow_radius * 3 + 6
        glow_mask = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
        gmd = ImageDraw.Draw(glow_mask)
        gmd.text(
            (pad - bbox[0], pad - bbox[1]),
            text,
            font=font,
            fill=255,
            stroke_width=stroke_width,
        )

        glow_img = Image.new("RGBA", glow_mask.size, glow_color)
        glow_alpha = glow_mask.filter(ImageFilter.GaussianBlur(radius=glow_radius))
        glow_img.putalpha(glow_alpha)

        img.paste(glow_img, (tx - pad, ty - pad), glow_img)

        draw.text(
            (tx, ty),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )

    def center_glow_text(
        text: str,
        box: tuple[int, int, int, int],
        font,
        fill=(255, 255, 255, 255),
        glow_color=(255, 95, 190, 95),
        glow_radius: int = 10,
        stroke_width: int = 3,
        stroke_fill=(0, 0, 0, 220),
    ):
        x1, y1, x2, y2 = box
        tw = draw.textlength(text, font=font)
        th = text_h(text, font)

        tx = x1 + ((x2 - x1) - int(tw)) // 2
        ty = y1 + ((y2 - y1) - th) // 2

        draw_glow_text_xy(
            text=text,
            xy=(tx, ty),
            font=font,
            fill=fill,
            glow_color=glow_color,
            glow_radius=glow_radius,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )

    def draw_gradient_text(
            text: str,
            box: tuple[int, int, int, int],
            font,
            top_color=(255, 235, 145, 255),
            bottom_color=(145, 86, 25, 255),
            glow_color=(255, 185, 70, 70),
            stroke_width: int = 3,
            stroke_fill=(0, 0, 0, 220),
    ):
        x1, y1, x2, y2 = box

        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]

        pad = stroke_width * 4 + 8

        mask = Image.new("L", (bw + pad * 2, bh + pad * 2), 0)
        md = ImageDraw.Draw(mask)
        md.text(
            (pad - bbox[0], pad - bbox[1]),
            text,
            font=font,
            fill=255,
            stroke_width=stroke_width,
        )

        grad = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)

        gh = grad.size[1]
        for yy in range(gh):
            t = yy / max(1, gh - 1)

            r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
            g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
            b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
            a = int(top_color[3] * (1 - t) + bottom_color[3] * t)

            gd.line((0, yy, grad.size[0], yy), fill=(r, g, b, a))

        tx = x1 + ((x2 - x1) - bw) // 2
        ty = y1 + ((y2 - y1) - bh) // 2

        # Свечение
        glow_mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, int(6 * scale))))
        glow_img = Image.new("RGBA", mask.size, glow_color)
        glow_img.putalpha(glow_mask)
        img.paste(glow_img, (tx - pad, ty - pad), glow_img)

        # Тёмная обводка
        draw.text(
            (tx - bbox[0], ty - bbox[1]),
            text,
            font=font,
            fill=(255, 255, 255, 35),
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )

        # Сам текст
        img.paste(grad, (tx - pad, ty - pad), mask)

        # Лёгкий блик
        shine = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shine)
        sd.line(
            (
                int(mask.size[0] * 0.10),
                int(mask.size[1] * 0.30),
                int(mask.size[0] * 0.90),
                int(mask.size[1] * 0.20),
            ),
            fill=(255, 255, 255, 70),
            width=max(1, int(2 * scale)),
        )

        shine = shine.filter(ImageFilter.GaussianBlur(radius=max(1, int(1.5 * scale))))
        img.paste(shine, (tx - pad, ty - pad), shine)

    def rank_text_palette(rank_text: str) -> tuple[
        tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]]:
        """
        Возвращает цвета текста под базовый ранг.
        Формат:
        - верх градиента
        - низ градиента
        - цвет свечения
        """
        base = _rank_base_text(rank_text).lower()

        palettes = {
            "iron": (
                (165, 170, 176, 255),
                (72, 76, 82, 255),
                (150, 155, 165, 70),
            ),
            "bronze": (
                (205, 145, 72, 255),
                (105, 63, 28, 255),
                (190, 112, 50, 75),
            ),
            "silver": (
                (245, 248, 246, 255),
                (135, 145, 148, 255),
                (220, 230, 230, 70),
            ),
            "gold": (
                (255, 226, 92, 255),
                (184, 112, 24, 255),
                (255, 190, 60, 85),
            ),
            "platinum": (
                (105, 230, 245, 255),
                (22, 118, 138, 255),
                (70, 210, 240, 85),
            ),
            "diamond": (
                (210, 145, 255, 255),
                (105, 62, 190, 255),
                (185, 110, 255, 90),
            ),
            "ascendant": (
                (105, 255, 175, 255),
                (20, 130, 82, 255),
                (80, 240, 150, 90),
            ),
            "immortal": (
                (255, 115, 160, 255),
                (138, 24, 55, 255),
                (255, 70, 120, 95),
            ),
            "radiant": (
                (255, 245, 205, 255),
                (208, 168, 76, 255),
                (255, 225, 140, 95),
            ),
            "unranked": (
                (215, 215, 220, 255),
                (110, 110, 120, 255),
                (190, 190, 200, 70),
            ),
        }

        return palettes.get(base, palettes["unranked"])

    def add_panel_depth(box: tuple[int, int, int, int]):
        """
        Тёмный фиолетово-чёрный градиент внутри панели
        + стеклянный внутренний кант
        + мягкие цветовые отражения по краям.
        """
        x1, y1, x2, y2 = box
        w = x2 - x1
        h = y2 - y1
        radius = int(26 * scale)

        panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)

        for yy in range(h):
            t = yy / max(1, h - 1)
            r = int(28 * (1 - t) + 5 * t)
            g = int(10 * (1 - t) + 4 * t)
            b = int(42 * (1 - t) + 10 * t)
            a = int(55 * (1 - t) + 108 * t)
            pd.line((0, yy, w, yy), fill=(r, g, b, a))

        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)

        img.paste(panel, (x1, y1), mask)

        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=radius,
            outline=(255, 255, 255, 82),
            width=max(1, int(2 * scale)),
        )

        draw.rounded_rectangle(
            (x1 + 4, y1 + 4, x2 - 4, y2 - 4),
            radius=max(8, radius - 4),
            outline=(255, 255, 255, 24),
            width=max(1, int(1 * scale)),
        )

        draw.line(
            (x1 + int(22 * scale), y1 + int(7 * scale), x2 - int(22 * scale), y1 + int(7 * scale)),
            fill=(255, 255, 255, 22),
            width=max(1, int(2 * scale)),
        )

        draw.line(
            (x1 + int(3 * scale), y1 + int(24 * scale), x1 + int(3 * scale), y2 - int(24 * scale)),
            fill=(255, 95, 190, 22),
            width=max(1, int(2 * scale)),
        )
        draw.line(
            (x2 - int(3 * scale), y1 + int(24 * scale), x2 - int(3 * scale), y2 - int(24 * scale)),
            fill=(255, 165, 90, 18),
            width=max(1, int(2 * scale)),
        )

    def add_avatar_inner_glow(base_img: Image.Image, outer_box: tuple[int, int, int, int]) -> Image.Image:
        """
        Мягкое внутреннее свечение для круга аватара.
        Без жёстких колец, чтобы не было эффекта "затмения".
        """
        x1, y1, x2, y2 = outer_box
        w = x2 - x1
        h = y2 - y1

        glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)

        # Внутренний мягкий пурпурный ореол
        inner_margin = int(8 * scale)
        gd.ellipse(
            (
                x1 + inner_margin,
                y1 + inner_margin,
                x2 - inner_margin,
                y2 - inner_margin,
            ),
            outline=(255, 105, 205, 80),
            width=max(1, int(10 * scale)),
        )

        # Более глубокая тень внутри, чтобы круг выглядел как часть интерфейса
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        shadow_margin = int(4 * scale)
        sd.ellipse(
            (
                x1 + shadow_margin,
                y1 + shadow_margin,
                x2 - shadow_margin,
                y2 - shadow_margin,
            ),
            fill=(8, 0, 18, 12),
        )

        # Лёгкий блик сверху
        shine_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh = ImageDraw.Draw(shine_layer)
        sh.arc(
            (
                x1 + int(24 * scale),
                y1 + int(20 * scale),
                x2 - int(24 * scale),
                y2 - int(52 * scale),
            ),
            start=205,
            end=332,
            fill=(255, 220, 245, 82),
            width=max(1, int(4 * scale)),
        )

        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=max(2, int(10 * scale))))
        shine_layer = shine_layer.filter(ImageFilter.GaussianBlur(radius=max(1, int(2 * scale))))

        base_img = Image.alpha_composite(base_img, glow_layer)
        base_img = Image.alpha_composite(base_img, shadow_layer)
        base_img = Image.alpha_composite(base_img, shine_layer)

        return base_img

    def add_background_atmosphere(base_img: Image.Image) -> Image.Image:
        """
        Усиливает ощущение дорогого фона:
        - больше падающих звёзд;
        - лёгкий призм-блик в верхней зоне;
        - мягкие отражения цвета на карточках.
        """
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        # Призматический блик в верхней зоне заголовка
        header_streaks = [
            (90, 68, 520, 58, (255, 165, 225, 38), max(1, int(6 * scale))),
            (110, 88, 550, 98, (255, 255, 255, 18), max(1, int(3 * scale))),
            (130, 102, 500, 120, (255, 120, 180, 12), max(1, int(10 * scale))),
        ]
        for x1, y1, x2, y2, color, width in header_streaks:
            od.line((x1, y1, x2, y2), fill=color, width=width)

        # Падающие звёзды
        star_streaks = [
            (1010, 42, 1060, 94, (255, 180, 215, 110), 2),
            (1160, 68, 1218, 126, (255, 150, 210, 125), 2),
            (1325, 88, 1378, 142, (255, 175, 220, 105), 2),
            (1455, 114, 1510, 172, (255, 210, 235, 85), 2),
            (1190, 26, 1228, 64, (255, 150, 190, 78), 1),
            (1268, 56, 1306, 96, (255, 190, 240, 92), 1),
            (1398, 48, 1440, 90, (255, 175, 210, 85), 1),
            (1105, 36, 1148, 78, (255, 200, 230, 90), 1),
            (1510, 58, 1554, 104, (255, 160, 210, 82), 1),
        ]
        for x1, y1, x2, y2, color, width in star_streaks:
            od.line((x1, y1, x2, y2), fill=color, width=width)
            od.ellipse((x1 - 2, y1 - 2, x1 + 2, y1 + 2), fill=(255, 255, 255, 120))

        # Отражения по краям карточек
        for bx1, by1, bx2, by2 in (left_panel, center_panel, right_panel):
            od.line(
                (bx1 + int(10 * scale), by1 + int(20 * scale), bx1 + int(10 * scale), by2 - int(20 * scale)),
                fill=(255, 110, 190, 16),
                width=max(1, int(2 * scale)),
            )
            od.line(
                (bx2 - int(10 * scale), by1 + int(22 * scale), bx2 - int(10 * scale), by2 - int(22 * scale)),
                fill=(255, 170, 90, 14),
                width=max(1, int(2 * scale)),
            )

        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(1, int(1.5 * scale))))
        return Image.alpha_composite(base_img, overlay)

    def draw_soft_row(
            box: tuple[int, int, int, int],
            label: str,
            value: str,
            label_font,
            value_font,
    ):
        x1, y1, x2, y2 = box
        radius = int(18 * scale)

        # Лёгкая внешняя линия строки
        draw.rounded_rectangle(
            box,
            radius=radius,
            outline=(255, 255, 255, 92),
            width=max(1, int(2 * scale)),
        )

        # Тонкий внутренний блик сверху, без заливки
        draw.line(
            (
                x1 + int(16 * scale),
                y1 + int(4 * scale),
                x2 - int(16 * scale),
                y1 + int(4 * scale),
            ),
            fill=(255, 255, 255, 34),
            width=max(1, int(1 * scale)),
        )

        label_x = x1 + int(28 * sx)
        label_y = y1 + ((y2 - y1) - text_h(label, label_font)) // 2 - int(1 * scale)

        # Значения строго по правому краю
        value_w = draw.textlength(value, font=value_font)
        value_x = x2 - int(28 * sx) - int(value_w)

        # Цифры чуть поднимаем, чтобы они визуально стояли по центру строки
        value_y = y1 + ((y2 - y1) - text_h(value, value_font)) // 2 - int(3 * scale)

        draw.text(
            (label_x, label_y),
            label,
            font=label_font,
            fill=(220, 220, 228, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 220),
        )

        draw.text(
            (value_x, value_y),
            value,
            font=value_font,
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 220),
        )

    def paste_circle_avatar(
        base_img: Image.Image,
        avatar_raw: bytes | None,
        box: tuple[int, int, int, int],
    ):
        x1, y1, x2, y2 = box
        size = min(x2 - x1, y2 - y1)
        x2 = x1 + size
        y2 = y1 + size

        if avatar_raw:
            try:
                av = Image.open(BytesIO(avatar_raw)).convert("RGBA")

                side = min(av.width, av.height)
                left = (av.width - side) // 2
                top = (av.height - side) // 2
                av = av.crop((left, top, left + side, top + side))

                av = av.resize((size, size), Image.LANCZOS)

                mask = Image.new("L", (size, size), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, size, size), fill=255)

                base_img.paste(av, (x1, y1), mask)
                return
            except Exception:
                pass

        # Заглушка
        draw.ellipse(
            (x1, y1, x2, y2),
            fill=(0, 0, 0, 170),
        )

        q_font = get_font(int(110 * scale))
        center_text(
            "?",
            (x1, y1 - int(12 * scale), x2, y2 - int(12 * scale)),
            q_font,
            fill=(255, 255, 255, 255),
            stroke_width=4,
        )

        # subtle призматический блик по заглушке
        shine = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shine)
        sd.arc(
            (x1 + int(22 * scale), y1 + int(18 * scale), x2 - int(22 * scale), y2 - int(40 * scale)),
            start=205,
            end=330,
            fill=(255, 175, 225, 80),
            width=max(1, int(4 * scale)),
        )
        shine = shine.filter(ImageFilter.GaussianBlur(radius=max(1, int(2 * scale))))
        base_img.alpha_composite(shine)

    # ---------- Шрифты ----------
    title_font = get_font(int(46 * scale))

    # подписи в статистике
    label_font = get_font(int(29 * scale))

    # значения справа в статистике
    value_font = get_font(int(42 * scale))

    # центр
    name_font_start = int(66 * scale)
    riot_font_start = int(30 * scale)

    # ранг сверху справа
    rank_font_start = int(48 * scale)

    # ---------- Левая колонка: статистика ----------
    lx1, ly1, lx2, ly2 = left_panel

    row_left = lx1 + int(38 * sx)
    row_right = lx2 - int(38 * sx)
    row_h = int(58 * sy)
    row_gap = int(15 * sy)
    row_y = ly1 + int(58 * sy)

    rows = [
        ("Matches", str(matches)),
        ("Winrate", winrate_text),
        ("Wins", str(wins)),
        ("Loses", str(loses)),
        ("Streak", str(win_streak) if win_streak is not None else "—"),
        ("Fav map", favorite_map if favorite_map else "—"),
    ]

    for label, value in rows:
        draw_soft_row(
            (row_left, row_y, row_right, row_y + row_h),
            label,
            value,
            label_font,
            value_font,
        )
        row_y += row_h + row_gap

    # ---------- Центр: аватар ----------
    avatar_outer_box_base = SBOX((678, 281, 1022, 625))

    avatar_shift_x = int(8 * sx)
    avatar_shift_y = int(6 * sy)

    avatar_outer_box = (
        avatar_outer_box_base[0] + avatar_shift_x,
        avatar_outer_box_base[1] + avatar_shift_y,
        avatar_outer_box_base[2] + avatar_shift_x,
        avatar_outer_box_base[3] + avatar_shift_y,
    )

    avatar_inset = int(4 * scale)

    avatar_box = (
        avatar_outer_box[0] + avatar_inset,
        avatar_outer_box[1] + avatar_inset,
        avatar_outer_box[2] - avatar_inset,
        avatar_outer_box[3] - avatar_inset,
    )

    paste_circle_avatar(img, avatar_bytes, avatar_box)

    img = add_avatar_inner_glow(img, avatar_outer_box)
    draw = ImageDraw.Draw(img)

    # ---------- Центр: имена ----------
    cx1, cy1, cx2, cy2 = center_panel
    max_center_text_w = cx2 - cx1 - int(70 * sx)

    discord_font = fit_font(
        discord_name,
        max_center_text_w,
        name_font_start,
        min_size=int(30 * scale),
    )

    riot_font = fit_font(
        riot_username,
        max_center_text_w,
        riot_font_start,
        min_size=int(22 * scale),
    )

    # ---------- Центр: имена ----------
    cx1, cy1, cx2, cy2 = center_panel
    max_center_text_w = cx2 - cx1 - int(70 * sx)

    discord_font = fit_font(
        discord_name,
        max_center_text_w,
        name_font_start,
        min_size=int(30 * scale),
    )

    riot_font = fit_font(
        riot_username,
        max_center_text_w,
        riot_font_start,
        min_size=int(22 * scale),
    )

    name_shift_y = int(10 * sy)

    center_glow_text(
        discord_name,
        (
            cx1 + int(24 * sx),
            cy1 + int(378 * sy) + name_shift_y,
            cx2 - int(24 * sx),
            cy1 + int(456 * sy) + name_shift_y,
        ),
        discord_font,
        fill=(255, 255, 255, 255),
        glow_color=(255, 110, 205, 88),
        glow_radius=max(2, int(6 * scale)),
        stroke_width=4,
    )

    center_text(
        riot_username,
        (
            cx1 + int(28 * sx),
            cy1 + int(452 * sy) + name_shift_y,
            cx2 - int(28 * sx),
            cy1 + int(506 * sy) + name_shift_y,
        ),
        riot_font,
        fill=(188, 188, 198, 255),
        stroke_width=2,
    )

    # ---------- Правая колонка: ранг ----------
    rx1, ry1, rx2, ry2 = right_panel
    right_shift_x = int(12 * sx)
    right_cx = (rx1 + rx2) // 2 + right_shift_x

    # ---------- Название ранга ----------
    rank_top_color, rank_bottom_color, rank_glow_color = rank_text_palette(rank_raw)

    rank_title_font = fit_font(
        rank_raw,
        int(270 * sx),
        rank_font_start,
        min_size=int(26 * scale),
    )

    draw_gradient_text(
        rank_raw,
        (
            right_cx - int(145 * sx),
            ry1 + int(42 * sy),
            right_cx + int(145 * sx),
            ry1 + int(112 * sy),
        ),
        rank_title_font,
        top_color=rank_top_color,
        bottom_color=rank_bottom_color,
        glow_color=rank_glow_color,
        stroke_width=2,
    )

    # ---------- Иконка ранга ----------
    icon_path = get_icon_path(rank_raw) or _rank_icon_path(_rank_base_text(rank_raw))

    icon_size = int(176 * scale)
    icon_x = right_cx - icon_size // 2
    icon_y = ry1 + int(160 * sy)

    draw.ellipse(
        (
            icon_x - int(10 * sx),
            icon_y - int(10 * sy),
            icon_x + icon_size + int(10 * sx),
            icon_y + icon_size + int(10 * sy),
        ),
        fill=(0, 0, 0, 105),
        outline=(255, 255, 255, 36),
        width=max(1, int(2 * scale)),
    )

    if icon_path and Path(icon_path).exists():
        try:
            icon = Image.open(icon_path).convert("RGBA")
            icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
            img.paste(icon, (icon_x, icon_y), icon)
        except Exception:
            q_font = get_font(int(110 * scale))
            center_text(
                "?",
                (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
                q_font,
                fill=(255, 255, 255, 255),
                stroke_width=4,
            )
    else:
        q_font = get_font(int(110 * scale))
        center_text(
            "?",
            (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
            q_font,
            fill=(255, 255, 255, 255),
            stroke_width=4,
        )

    # ---------- Wins справа снизу ----------
    wins_label_font = get_font(int(34 * scale))

    # Делаем шрифт адаптивным, чтобы и 7, и 27, и 127 выглядели красиво
    wins_text = str(wins)
    wins_value_font = fit_font(
        wins_text,
        int(190 * sx),
        int(92 * scale),
        min_size=int(58 * scale),
    )

    center_text(
        "Wins",
        (
            right_cx - int(130 * sx),
            ry1 + int(365 * sy),
            right_cx + int(130 * sx),
            ry1 + int(420 * sy),
        ),
        wins_label_font,
        fill=(235, 235, 235, 235),
        stroke_width=2,
    )

    center_text(
        wins_text,
        (
            right_cx - int(140 * sx),
            ry1 + int(420 * sy),
            right_cx + int(140 * sx),
            ry1 + int(555 * sy),
        ),
        wins_value_font,
        fill=(255, 255, 255, 255),
        stroke_width=4,
    )

    # ---------- Сохраняем ----------
    img.save(out_path)
    return out_path

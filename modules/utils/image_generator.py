import discord
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path
from functools import lru_cache

# Пути к файлам
BASE_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_base.png"
OUTPUT_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_dynamic.png"
FONT_PATH = Path(__file__).resolve().parents[1] / "static" / "fonts" / "Inter-SemiBold.ttf"
RANK_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "ranks"
MAP_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "maps"

CANDIDATE_FONT_PATHS = [
    FONT_PATH,
    Path(__file__).resolve().parents[2] / "static" / "fonts" / "Inter-SemiBold.ttf",
    Path(__file__).resolve().parents[1] / "fonts" / "Inter-SemiBold.ttf",
]

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

def generate_lobby_image(players: list[dict], top_ids: list[int] = []):
    base_img = Image.open(BASE_IMAGE_PATH).convert("RGBA")
    width, height = base_img.size

    # Шрифты и размеры
    base_font_size = 52
    min_font_size = 28
    icon_size = 64
    step_y = 100
    top_margin = 200

    # Координаты
    number_x = 80
    nickname_x = 140
    rank_icon_x = 580

    # Динамическое центрирование
    total_height = len(players) * step_y
    start_y = (height - total_height) // 2
    draw = ImageDraw.Draw(base_img)

    for i, player in enumerate(players):
        y = start_y + i * step_y
        username = player.get("username", "—")
        rank = player.get("rank", "Unranked")

        # Номер игрока
        font_number = get_font(40)
        draw.text((number_x, y), str(i + 1), font=font_number, fill="white")

        # Подбор шрифта под ник
        font_size = base_font_size
        font = get_font(font_size)
        while font.getlength(username) > 400 and font_size > min_font_size:
            font_size -= 2
            font = get_font(font_size)

        fill_color = "gold" if player.get("id") in top_ids else "white"
        draw.text((nickname_x, y), username, font=font, fill=fill_color)

        # Ранг — иконка
        icon_path = get_icon_path(rank)
        if icon_path:
            try:
                icon = Image.open(icon_path).resize((icon_size, icon_size)).convert("RGBA")
                icon_y = y + (step_y - icon_size) // 2
                base_img.paste(icon, (rank_icon_x, icon_y), icon)
            except Exception as e:
                print(f"⚠ Ошибка загрузки иконки ранга {rank}: {e}")

    base_img.save(OUTPUT_IMAGE_PATH)
    return OUTPUT_IMAGE_PATH

def generate_draft_image(players: list[dict], captain_1_id: int, captain_2_id: int):
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
            color = "gold" if is_captain else "white"

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

    MAP_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "maps"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "map_draft_dynamic.png"

    image = Image.new("RGBA", (WIDTH, HEIGHT), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)

    title_font = get_font(48)
    draw.text((PADDING, TITLE_Y), f"🌍 Карта бана — Ход: {current_captain}", font=title_font, fill="white")

    all_maps = ["Ascent","Bind","Haven","Split","Icebox","Breeze","Fracture","Lotus","Sunset","Abyss","Pearl"]
    font = get_font(26)


    for idx, map_name in enumerate(all_maps):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = PADDING + col * (CELL_WIDTH + GRID_HGAP)
        y = 120 + row * (CELL_HEIGHT + GRID_VGAP)

        icon_path = MAP_ICONS_PATH / f"{map_name}.png"
        if not icon_path.exists():
            icon_path = MAP_ICONS_PATH / f"{map_name}.webp"
        if icon_path.exists():
            try:
                icon = get_map_icon(map_name, CELL_WIDTH, CELL_HEIGHT)
                if map_name in banned_maps:
                    icon = ImageEnhance.Brightness(icon).enhance(0.3)
                image.paste(icon, (x, y))
            except Exception as e:
                print(f"⚠ Ошибка загрузки карты {map_name}: {e}")

        if map_name in banned_maps:
            draw.line((x, y, x + CELL_WIDTH, y + CELL_HEIGHT), fill="red", width=5)
            draw.line((x, y + CELL_HEIGHT, x + CELL_WIDTH, y), fill="red", width=5)

        draw.text((x + 12, y + CELL_HEIGHT - 30), map_name, font=font, fill="white")

    image.save(output_path)
    return output_path


def generate_final_match_image(selected_map: str, team_sides: dict[int, str], captains: list[discord.Member]) -> Path:
    # Путь к карте
    MAP_PATH = Path(__file__).resolve().parents[1] / "maps" / f"{selected_map}.webp"
    if not MAP_PATH.exists():
        return None

    base_img = Image.open(MAP_PATH).convert("RGBA")
    draw = ImageDraw.Draw(base_img)

    font_big = get_font(60)
    font_small = get_font(42)

    # Верхний текст: Название карты
    draw.text((40, 20), f"Карта: {selected_map}", font=font_big, fill="white")

    # Стороны
    left = team_sides.get(captains[0].id, "—")
    right = team_sides.get(captains[1].id, "—")

    draw.text((40, 100), f"{captains[0].display_name} → {left}", font=font_small, fill="cyan")
    draw.text((40, 170), f"{captains[1].display_name} → {right}", font=font_small, fill="orange")

    output = Path(__file__).resolve().parents[1] / "pictures" / "final_match_dynamic.png"
    base_img.save(output)
    return output

def generate_leaderboard_image(players: list[dict]) -> Path:
    base_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard.png"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "leaderboard_dynamic.png"
    image = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Настройки
    font_path = FONT_PATH
    font = ImageFont.truetype(str(font_path), 40)
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


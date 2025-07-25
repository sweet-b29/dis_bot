import discord
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

# Пути к файлам
BASE_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_base.png"
OUTPUT_IMAGE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "lobby_dynamic.png"
FONT_PATH = Path(__file__).resolve().parents[1] / "pictures" / "Montserrat-Bold.ttf"
RANK_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "ranks"

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
        font_number = ImageFont.truetype(str(FONT_PATH), 40)
        draw.text((number_x, y), str(i + 1), font=font_number, fill="white")

        # Подбор шрифта под ник
        font_size = base_font_size
        font = ImageFont.truetype(str(FONT_PATH), font_size)
        while font.getlength(username) > 400 and font_size > min_font_size:
            font_size -= 2
            font = ImageFont.truetype(str(FONT_PATH), font_size)

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

    try:
        font = ImageFont.truetype(str(FONT_PATH), nickname_font_size)
    except:
        font = ImageFont.load_default()

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
    WIDTH, HEIGHT = 1000, 700
    PADDING = 40
    GRID_COLS = 4
    CELL_WIDTH = 200
    CELL_HEIGHT = 150

    MAP_ICONS_PATH = Path(__file__).resolve().parents[1] / "pictures" / "maps"
    output_path = Path(__file__).resolve().parents[1] / "pictures" / "map_draft_dynamic.png"

    image = Image.new("RGBA", (WIDTH, HEIGHT), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)

    # Заголовок
    title_font = ImageFont.truetype(str(FONT_PATH), 42)
    draw.text((PADDING, 20), f"🌍 Карта бана — Ход: {current_captain}", font=title_font, fill="white")

    all_maps = [
        "Ascent", "Bind", "Haven", "Split", "Icebox",
        "Breeze", "Fracture", "Lotus", "Sunset", "Abyss", "Pearl"
    ]
    font = ImageFont.truetype(str(FONT_PATH), 24)

    for idx, map_name in enumerate(all_maps):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = PADDING + col * (CELL_WIDTH + 10)
        y = 100 + row * (CELL_HEIGHT + 10)

        # Иконка карты
        icon_path = MAP_ICONS_PATH / f"{map_name}.png"
        if not icon_path.exists():
            icon_path = MAP_ICONS_PATH / f"{map_name}.webp"
        if icon_path.exists():
            try:
                icon = Image.open(icon_path).resize((CELL_WIDTH, CELL_HEIGHT)).convert("RGBA")

                # Если карта забанена — делаем иконку тёмной
                if map_name in banned_maps:
                    enhancer = ImageEnhance.Brightness(icon)
                    icon = enhancer.enhance(0.3)

                image.paste(icon, (x, y))
            except Exception as e:
                print(f"⚠ Ошибка загрузки карты {map_name}: {e}")

        # Перечёркиваем, если карта забанена
        if map_name in banned_maps:
            draw.line((x, y, x + CELL_WIDTH, y + CELL_HEIGHT), fill="red", width=4)
            draw.line((x, y + CELL_HEIGHT, x + CELL_WIDTH, y), fill="red", width=4)

        # Название карты
        draw.text((x + 10, y + CELL_HEIGHT - 28), map_name, font=font, fill="white")

    image.save(output_path)
    return output_path


def generate_final_match_image(selected_map: str, team_sides: dict[int, str], captains: list[discord.Member]) -> Path:
    # Путь к карте
    MAP_PATH = Path(__file__).resolve().parents[1] / "maps" / f"{selected_map}.webp"
    if not MAP_PATH.exists():
        return None

    base_img = Image.open(MAP_PATH).convert("RGBA")
    draw = ImageDraw.Draw(base_img)

    font_big = ImageFont.truetype(str(FONT_PATH), 60)
    font_small = ImageFont.truetype(str(FONT_PATH), 42)

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

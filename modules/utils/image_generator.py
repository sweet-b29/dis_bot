from PIL import Image, ImageDraw, ImageFont
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
    DRAFT_BASE_PATH = Path(__file__).resolve().parents[1] / "pictures" / "draft_base.png"
    image = Image.open(DRAFT_BASE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.truetype(str(FONT_PATH), 46)
    name_font = ImageFont.truetype(str(FONT_PATH), 40)

    left_x = 80
    right_x = 580
    start_y = 160
    step_y = 100

    start_y = 160  # отступ от заголовков на картинке
    left_x = 120
    right_x = 540

    team_1 = [p for p in players if p["team"] == "captain_1"]
    team_2 = [p for p in players if p["team"] == "captain_2"]

    def draw_team(team, x, label):
        rank_icon_offset = 320
        for i, player in enumerate(team):
            y = start_y + i * step_y
            username = player.get("username", "—")
            rank = player.get("rank", "Unranked")
            is_captain = player["id"] == (captain_1_id if label == "captain_1" else captain_2_id)

            # Если капитан — выделяем цветом
            color = "gold" if is_captain else "white"
            draw.text((x, y), username, font=name_font, fill=color)

            # Иконка ранга
            icon_path = get_icon_path(rank)
            if icon_path:
                try:
                    icon = Image.open(icon_path).resize((56, 56)).convert("RGBA")
                    image.paste(icon, (x + rank_icon_offset, y), icon)
                except:
                    pass

    draw_team(team_1, left_x, "captain_1")
    draw_team(team_2, right_x, "captain_2")

    output_path = Path(__file__).resolve().parents[1] / "pictures" / "draft_dynamic.png"
    image.save(output_path)
    return output_path

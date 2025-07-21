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

def generate_lobby_image(players: list[dict]):
    image = Image.open(BASE_IMAGE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(image)

    base_font_size = 52
    min_font_size = 28
    icon_size = 64

    number_x = 80
    nickname_x = 140
    rank_icon_x = 580

    step_y = 100
    start_y = 220

    for i, player in enumerate(players):
        y = start_y + i * step_y
        username = player.get("username", "—")
        rank = player.get("rank", "Unranked")

        # Рисуем номер
        font_number = ImageFont.truetype(str(FONT_PATH), 40)
        draw.text((number_x, y), str(i + 1), font=font_number, fill="white")

        # Подбираем размер шрифта под ник
        font_size = base_font_size
        font = ImageFont.truetype(str(FONT_PATH), font_size)
        while font.getlength(username) > 400 and font_size > min_font_size:
            font_size -= 2
            font = ImageFont.truetype(str(FONT_PATH), font_size)

        # Рисуем ник
        draw.text((nickname_x, y), username, font=font, fill="white")

        # Рисуем иконку ранга
        icon_path = get_icon_path(rank)
        if icon_path:
            try:
                icon = Image.open(icon_path).resize((icon_size, icon_size)).convert("RGBA")
                icon_y = y - 6  # немного подровнять по вертикали
                image.paste(icon, (rank_icon_x, icon_y), icon)
            except Exception as e:
                print(f"⚠ Ошибка загрузки иконки ранга {rank}: {e}")

    image.save(OUTPUT_IMAGE_PATH)
    return OUTPUT_IMAGE_PATH
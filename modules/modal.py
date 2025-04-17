# import discord
# from modules.database import save_game_nickname
#
# class NicknameModal(discord.ui.Modal, title="Введите игровой никнейм"):
#     nickname = discord.ui.TextInput(label="Ник в игре", placeholder="Введите никнейм", required=True, max_length=32)
#
#     def __init__(self, lobby, user):
#         super().__init__()
#         self.lobby = lobby
#         self.user = user
#
#     async def on_submit(self, interaction: discord.Interaction):
#         await save_game_nickname(self.user.id, self.nickname.value)
#         await self.lobby.add_member(self.user)
#
#         await interaction.response.send_message(
#             f"✅ Никнейм сохранён! Вы добавлены в лобби: {self.lobby.channel.mention}",
#             ephemeral=True
#         )

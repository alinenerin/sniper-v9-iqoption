import telebot, os
from telebot import types

TOKEN = '8655491627:AAGaL2VorC2Ow6TExkUJo96gJQZ0_qwwABs'
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add('🎯 Gerar Lista', '📊 Verificar', '🔍 Filtrar')
    bot.reply_to(message, '💎 *SNIPER ONLINE* 💎

Agora vai, amiga! Escolha abaixo:', parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, 'Recebido! Estou processando seu comando no motor principal.')

if __name__ == '__main__':
    bot.infinity_polling()

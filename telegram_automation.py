# telegram_automation.py
import os
import json
import pandas as pd
from flask import Flask
from threading import Thread
from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, ConversationHandler, filters, CallbackQueryHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Estados da conversa
(AGUARDANDO_CSV, AGUARDANDO_CONFIRMACAO_CONTA, AGUARDANDO_CATEGORIA_DESPESA, RECEBER_FONTE_DESPESA) = range(4)

# ---- KEEP ALIVE (Replit) ----
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot online!"

def keep_alive():
    Thread(target=lambda: app_flask.run(host='0.0.0.0', port=8080)).start()

# ---- Google Sheets Credentials ----
def credenciais_google():
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    info = json.loads(json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scopes)
    client = gspread.authorize(creds)

    planilha_completa = client.open(
        title="Financas Casal",
        folder_id="1Wds3IEWyt8F6WvQKKSVumpHoA8pnZLi5"
    )

    return planilha_completa.get_worksheet(2)

# ---- Bot Handlers ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    planilha = credenciais_google()
    ids_nubank = planilha.col_values(14)
    filtrados = [v.strip() for v in ids_nubank if v.strip() and v.strip() != 'Id Nubank']
    context.user_data["ids_nubank"] = filtrados
    await update.message.reply_text("Olá! Envie um arquivo CSV.")
    return AGUARDANDO_CSV

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Processo cancelado.")
    return ConversationHandler.END

async def receber_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document: Document = update.message.document
    if document.mime_type not in ["text/csv", "text/comma-separated-values"]:
        await update.message.reply_text("Por favor, envie um arquivo CSV.")
        return AGUARDANDO_CSV

    file_path = f"./{document.file_name}"
    arquivo = await context.bot.get_file(document.file_id)
    await arquivo.download_to_drive(file_path)

    try:
        df = pd.read_csv(file_path)
        os.remove(file_path)

        dados_raw = df.to_dict(orient="records")
        ids_nubank = context.user_data["ids_nubank"]

        dados_csv = [
            {**linha, "Valor": -linha["Valor"]}
            for linha in dados_raw
            if str(linha.get("Identificador", "")).strip() not in ids_nubank
            and isinstance(linha.get("Valor", None), (int, float))
            and linha["Valor"] < 0
            and "fatura" not in str(linha.get("Descrição", "")).lower()
        ]

        context.user_data["dados_csv"] = dados_csv
        context.user_data["indice"] = 0
        context.user_data["respostas"] = []

        if not dados_csv:
            await update.message.reply_text("O CSV está vazio ou sem despesas não publicadas.")
            return ConversationHandler.END

        linha = dados_csv[0]
        await update.message.reply_text(
            f"Processando linha 1:\n{linha}\n\nInforme a conta:\n1. Furone\n2. Sâmia\n3. Casal"
        )
        return AGUARDANDO_CONFIRMACAO_CONTA

    except Exception:
        await update.message.reply_text("Erro ao ler o arquivo. Verifique se é um CSV válido.")
        return ConversationHandler.END

async def receber_confirmacao_conta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resposta = update.message.text
    indice = context.user_data["indice"]
    dados = context.user_data["dados_csv"]
    respostas = context.user_data["respostas"]

    conta = {"1": "Furone", "2": "Sâmia", "3": "Casal"}.get(resposta)
    if not conta:
        indice += 1
        context.user_data["indice"] = indice
        if indice < len(dados):
            linha = dados[indice]
            await update.message.reply_text(f"Processando linha {indice+1}:\n{linha}\n\nInforme a conta:")
            return AGUARDANDO_CONFIRMACAO_CONTA
        else:
            await update.message.reply_text("Todas as linhas foram processadas.")
            return ConversationHandler.END

    respostas.append({"id": dados[indice]["Identificador"], "conta": conta})

    botoes = [[InlineKeyboardButton(c, callback_data=c)] for c in [
        "Assinaturas", "Casa", "Compras", "Delivery", "Dia a dia", "Mercado", "Saúde", "Transporte"
    ]]
    markup = InlineKeyboardMarkup(botoes)
    await update.message.reply_text("Qual a categoria da transação?", reply_markup=markup)
    return AGUARDANDO_CATEGORIA_DESPESA

async def receber_categoria_despesa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    resposta = query.data

    indice = context.user_data["indice"]
    respostas = context.user_data["respostas"]
    respostas[indice]["categoria_despesa"] = resposta

    botoes = [[InlineKeyboardButton(c, callback_data=c)] for c in [
        "Salário Mensal", "13º", "14º", "Investimentos / Pessoais"
    ]]
    markup = InlineKeyboardMarkup(botoes)
    await query.message.reply_text("De onde vai sair o dinheiro?", reply_markup=markup)
    return RECEBER_FONTE_DESPESA

async def receber_fonte_despesa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    resposta = query.data

    indice = context.user_data["indice"]
    dados = context.user_data["dados_csv"]
    respostas = context.user_data["respostas"]
    respostas[indice]["fonte"] = resposta

    enviar_para_planilha(respostas[indice], dados[indice])

    indice += 1
    context.user_data["indice"] = indice

    if indice < len(dados):
        linha = dados[indice]
        await query.message.reply_text("Transação salva! Próxima:")
        await query.message.reply_text(f"Processando linha {indice+1}:\n{linha}\nInforme a conta:")
        return AGUARDANDO_CONFIRMACAO_CONTA
    else:
        await query.message.reply_text("Todas as linhas foram processadas.")
        return ConversationHandler.END

def enviar_para_planilha(respostas, dados_csv):
    planilha = credenciais_google()
    dados_p_planilha = [
        None, 'Despesa', respostas['conta'], dados_csv['Descrição'], 'Nubank / Furone',
        dados_csv['Valor'], dados_csv['Data'], respostas['categoria_despesa'],
        'Pix' if 'pix' in dados_csv['Descrição'].lower() else 'Débito',
        None, None, respostas['fonte'], None, dados_csv['Identificador']
    ]
    col_b = planilha.col_values(2)
    proxima_linha = len(col_b) + 1
    planilha.update([dados_p_planilha], f"A{proxima_linha}")

# ---- Main ----
if __name__ == "__main__":
    keep_alive()  # Manter ativo no Replit
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AGUARDANDO_CSV: [MessageHandler(filters.Document.ALL, receber_csv)],
            AGUARDANDO_CONFIRMACAO_CONTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_confirmacao_conta)],
            AGUARDANDO_CATEGORIA_DESPESA: [CallbackQueryHandler(receber_categoria_despesa)],
            RECEBER_FONTE_DESPESA: [CallbackQueryHandler(receber_fonte_despesa)]
        },
        fallbacks=[CommandHandler("cancel", cancelar)],
    )

    app.add_handler(conv_handler)
    print("Bot rodando...")
    app.run_polling()

import os
import asyncio
import io
import pdfplumber
import logging
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from analyzer import analyze_resume
from cv_generator import generate_cv
from pdf_generator import markdown_to_pdf

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# REPLACE WITH YOUR BOT TOKEN
BOT_TOKEN = "8629055112:AAFLgD_ejhpUoWRHoa9CfLqmVmjxmtEREwE"
bot = telebot.TeleBot(BOT_TOKEN)

# In-memory session store for users
# format: { chat_id: { "step": int, "resume_text": str, "jd_text": str, "analysis": dict } }
user_sessions = {}

# Constants for Steps
STEP_UPLOAD_RESUME = 1
STEP_PASTE_JD = 2
STEP_ASK_GENERATE = 3

def get_session(chat_id):
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {"step": STEP_UPLOAD_RESUME, "resume_text": "", "jd_text": "", "analysis": {}}
    return user_sessions[chat_id]

def reset_session(chat_id):
    user_sessions[chat_id] = {"step": STEP_UPLOAD_RESUME, "resume_text": "", "jd_text": "", "analysis": {}}

@bot.message_handler(commands=['start', 'reset'])
def send_welcome(message):
    reset_session(message.chat.id)
    bot.reply_to(
        message, 
        "🤖 *Welcome to the AI Resume Optimizer!* 🤖\n\n"
        "Let's get started. Please upload your current **Resume** as a `.pdf` file.",
        parse_mode="Markdown"
    )

import docx

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    chat_id = message.chat.id
    session = get_session(chat_id)

    if session["step"] != STEP_UPLOAD_RESUME:
        bot.send_message(chat_id, "I wasn't expecting a file right now. Use /reset if you want to start over.")
        return

    try:
        file_name = message.document.file_name.lower()
        if not (file_name.endswith('.pdf') or file_name.endswith('.doc') or file_name.endswith('.docx')):
            bot.send_message(chat_id, "⚠️ **Format not allowed!**\n\nPlease upload your resume strictly in **PDF** (`.pdf`) or **Word** (`.docx` / `.doc`) format.", parse_mode="Markdown")
            return

        bot.send_message(chat_id, "📥 Downloading and extracting resume... Please wait.")
        
        # Download file
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        resume_text = ""
        
        # Extract based on file type
        if file_name.endswith('.pdf'):
            with pdfplumber.open(io.BytesIO(downloaded_file)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        resume_text += text + "\n"
        elif file_name.endswith('.docx') or file_name.endswith('.doc'):
            doc = docx.Document(io.BytesIO(downloaded_file))
            resume_text = "\n".join([para.text for para in doc.paragraphs])
        
        if not resume_text.strip():
            bot.send_message(chat_id, "⚠️ Could not extract text from this file. Please try a different one.")
            return

        session["resume_text"] = resume_text.strip()
        session["step"] = STEP_PASTE_JD
        
        bot.send_message(
            chat_id, 
            "✅ **Resume processed successfully!**\n\n"
            "Now, please paste the **Job Description (JD)** you are targeting.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        bot.send_message(chat_id, "❌ Error processing the PDF file. Please try again.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    text = message.text.strip()

    if session["step"] == STEP_UPLOAD_RESUME:
        bot.send_message(chat_id, "Please upload your **Resume (PDF)** first. Send /reset to start over.", parse_mode="Markdown")
        return

    if session["step"] == STEP_PASTE_JD:
        if len(text) < 50:
            bot.send_message(chat_id, "⚠️ That looks too short to be a Job Description. Please paste the full JD.")
            return

        session["jd_text"] = text
        bot.send_message(chat_id, "🧠 Let me analyze your resume against this job description. This usually takes around 30 seconds... ⏳")
        
        # Run async analysis sync wrapper
        try:
            results = asyncio.run(analyze_resume(session["jd_text"], session["resume_text"]))
            session["analysis"] = results
            
            def clean_md(t):
                if not t: return ""
                return str(t).replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')

            # Format results for Telegram
            score = results.get('match_score', 0)
            score_emoji = "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")
            
            summary = clean_md(results.get('summary', ''))
            gaps = "\n".join([f"❌ {clean_md(g)}" for g in results.get('gap_analysis', [])]) or "✅ No missing skills!"
            
            neg_list = results.get('negative_points', [])
            weaknesses = "\n\n".join([f"⚠️ {clean_md(n.get('issue', ''))}\n💡 *Fix:* {clean_md(n.get('recommendation', ''))}" for n in neg_list[:3]]) or "✅ No major weaknesses!"

            report = (
                f"📊 *ANALYSIS COMPLETE*\n\n"
                f"*Match Score:* {score_emoji} {score}/100\n\n"
                f"*Summary:*\n{summary}\n\n"
                f"*Missing Skills:*\n{gaps}\n\n"
                f"*Key Weaknesses:*\n{weaknesses}"
            )
            
            bot.send_message(chat_id, report, parse_mode="Markdown")

            # Setup Yes/No Keyboard
            markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(KeyboardButton("Yes, write me a CV!"), KeyboardButton("No thanks"))
            
            session["step"] = STEP_ASK_GENERATE
            bot.send_message(chat_id, "✨ Do you want me to write a **new, optimized CV** completely tailored for this job using the STAR method?", reply_markup=markup, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            bot.send_message(chat_id, "❌ Sorry, the analysis engine encountered an error. Please try again later.")
            
        return

    if session["step"] == STEP_ASK_GENERATE:
        text_lower = text.lower()
        if text_lower in ["yes, write me a cv!", "yes", "y", "sure", "ok", "yeah", "do it", "generate"]:
            # Remove custom keyboard
            markup = telebot.types.ReplyKeyboardRemove()
            bot.send_message(chat_id, "⏳ Generating your optimized CV... This may take up to a minute.", reply_markup=markup)
            
            try:
                # 1. Generate Markdown
                cv_markdown = asyncio.run(generate_cv(
                    jd_text=session["jd_text"],
                    resume_text=session["resume_text"],
                    analysis_results=session["analysis"]
                ))
                
                # 2. Convert to PDF Bytes
                pdf_bytes = markdown_to_pdf(cv_markdown)
                
                # 3. Send PDF back to user
                bot.send_document(
                    chat_id, 
                    document=(f"Optimized_Resume.pdf", pdf_bytes),
                    caption="🎉 Here is your **Optimized CV** ready to download!",
                    parse_mode="Markdown"
                )
                
                bot.send_message(chat_id, "Type /start or /reset if you'd like to analyze another job description!")
                reset_session(chat_id)

            except Exception as e:
                logger.error(f"Generation failed: {e}")
                bot.send_message(chat_id, "❌ Failed to generate the CV. Something went wrong on the backend.")

        elif text_lower in ["no thanks", "no", "n", "nope", "cancel"]:
            markup = telebot.types.ReplyKeyboardRemove()
            bot.send_message(chat_id, "No problem! You can type /start anytime to analyze another job.", reply_markup=markup)
            reset_session(chat_id)
        else:
            bot.send_message(chat_id, "Please select an option from the keyboard, or just type 'yes' or 'no'.")

print("🤖 Telegram Bot is polling and ready to answer...")
bot.infinity_polling()

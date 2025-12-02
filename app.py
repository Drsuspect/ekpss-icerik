import streamlit as st
from streamlit_mic_recorder import speech_to_text
import pdfplumber
import asyncio
import edge_tts
import base64
import os
import re
import time
import json
import sqlite3
import sys
import asyncio

# Windows beep ayarı
if sys.platform == "win32":
    import winsound
    # Windows için event loop fix
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
else:
    winsound = None

# ==============================================================================
# 1. SAYFA AYARLARI VE GÖRÜNÜM
# ==============================================================================
st.set_page_config(page_title="EKPSS Sesli Asistan", layout="centered")

# Görme engelliler için yüksek kontrast ve büyük butonlar
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        height: 80px;
        font-size: 24px;
        font-weight: bold;
        border-radius: 12px;
        background-color: #f0f2f6;
        border: 2px solid #000;
    }
    .big-text {
        font-size: 26px;
        font-weight: 600;
        line-height: 1.6;
        color: #ffffff;
        background-color: #0e1117;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
    }
    .info-box {
        font-size: 18px;
        padding: 10px;
        background-color: #262730;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- OTURUM DURUMLARI ---
if 'page' not in st.session_state: st.session_state.page = "GIRIS"
if 'data' not in st.session_state: st.session_state.data = []
if 'index' not in st.session_state: st.session_state.index = 0
if 'score' not in st.session_state: st.session_state.score = {"dogru": 0, "yanlis": 0}
if 'last_read' not in st.session_state: st.session_state.last_read = ""

# ==============================================================================
# 2. SES MOTORU (WEB UYUMLU)
# ==============================================================================
async def metni_sese_cevir(metin):
    """Metni Edge TTS ile MP3'e çevirir"""
    hiz = "+10%"
    # Tek heceli veya sayısal ifadeler için yavaşlatma
    if len(metin) < 8 or metin.strip().isdigit():
        metin = f". . {metin} . ."
        hiz = "-10%"

    communicate = edge_tts.Communicate(metin, "tr-TR-AhmetNeural", rate=hiz)
    await communicate.save("temp_audio.mp3")

def ses_cal_otomatik(metin):
    """Sesi oluşturur ve tarayıcıda gizli oynatıcı ile çalar"""
    if metin == st.session_state.last_read:
        return
    
    try:
        asyncio.run(metni_sese_cevir(metin))
        
        if os.path.exists("temp_audio.mp3"):
            with open("temp_audio.mp3", "rb") as f:
                audio_bytes = f.read()
            audio_base64 = base64.b64encode(audio_bytes).decode()
            
            # HTML5 Audio Player (Autoplay)
            audio_html = f"""
                <audio autoplay="true">
                <source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3">
                </audio>
            """
            st.markdown(audio_html, unsafe_allow_html=True)
            st.session_state.last_read = metin
    except Exception as e:
        st.error(f"Ses hatası: {e}")

def pdf_analiz_et(uploaded_file, mod="TEST"):
    """PDF'i okur ve temizler"""
    ham_metin = ""
    data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for i, page in enumerate(pdf.pages):
                extracted = page.extract_text()
                if extracted:
                    lines = extracted.split('\n')
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue

                        low = line.lower()

                        # Gereksiz sayfa numaraları
                        if low.startswith("sayfa ") and len(line) < 20:
                            continue

                        # Tek başına numara olan satırlar
                        if re.fullmatch(r'\d+', line):
                            continue

                        # Çöp metinler
                        if any(x in low for x in [
                            "bu doküman",
                            "telif",
                            "ekpss",
                            "ösym",
                            "copyright",
                            "report",
                            "scan",
                            "scanner"
                        ]):
                            continue

                        ham_metin += line + "\n"

    except Exception as e:
        return [{"hata": str(e)}]

    # ==========================
    #  DERS MODU PARÇALAMA
    # ==========================
    if mod == "DERS":
        buffer = ""
        for line in ham_metin.split('\n'):
            line = line.strip()
            if not line:
                continue

            is_header = False
            if line.startswith("(") or line.endswith(":"):
                is_header = True

            if is_header:
                if buffer:
                    data.append({"tip": "icerik", "text": buffer.strip()})
                data.append({"tip": "baslik", "text": line.strip()})
                buffer = ""
            else:
                if buffer.endswith("-"):
                    buffer = buffer[:-1] + line
                else:
                    buffer += " " + line

        if buffer:
            data.append({"tip": "icerik", "text": buffer.strip()})

    # ==========================
    #  TEST MODU PARÇALAMA
    # ==========================
    elif mod == "TEST":
        parts = re.split(r'\n(\d{1,3}[\.\)])', ham_metin)

        cevap_anahtari = {}
        if "CEVAP ANAHTARI" in ham_metin:
            try:
                key_part = ham_metin.split("CEVAP ANAHTARI")[-1]
                matches = re.findall(r'(\d{1,3})[\.\-\s]+([A-E])', key_part)
                for n, a in matches:
                    cevap_anahtari[str(n)] = a
            except:
                pass

        for i in range(1, len(parts), 2):
            q_no = parts[i].replace(".", "").replace(")", "").strip()
            q_body_raw = parts[i + 1]

            if "A)" in q_body_raw:
                q_text = q_body_raw.split("A)")[0].strip()
            else:
                q_text = q_body_raw.strip()

            opts = {}
            opt_matches = list(re.finditer(
                r'([A-E])[\)\.]\s+(.*?)(?=\s[A-E][\)\.]\s|$)',
                q_body_raw,
                re.DOTALL
            ))

            for m in opt_matches:
                opts[m.group(1)] = m.group(2).strip()

            if q_text:
                data.append({
                    "no": q_no,
                    "text": q_text,
                    "opts": opts,
                    "correct": cevap_anahtari.get(q_no, "?")
                })

    return data

# ==============================================================================
# 4. ARAYÜZ VE AKIŞ
# ==============================================================================

st.title("🎙️ EKPSS Çalışma Odası")

# --- SAYFA: GİRİŞ ---
if st.session_state.page == "GIRIS":
    st.info("Lütfen çalışmak istediğiniz PDF dosyasını yükleyin.")
    ses_cal_otomatik("Merhaba. Lütfen çalışmak istediğiniz PDF dosyasını yükleyin.")
    
    uploaded_file = st.file_uploader("PDF Seçin", type="pdf")
    
    if uploaded_file:
        col1, col2 = st.columns(2)
        if col1.button("📖 Ders Modu"):
            raw = pdf_analiz_et(uploaded_file)
            st.session_state.data = veriyi_yapilandir(raw, "DERS")
            st.session_state.page = "DERS"
            st.session_state.index = 0
            st.session_state.last_read = ""
            st.rerun()
            
        if col2.button("📝 Test Modu"):
            raw = pdf_analiz_et(uploaded_file)
            st.session_state.data = veriyi_yapilandir(raw, "TEST")
            st.session_state.page = "TEST"
            st.session_state.index = 0
            st.session_state.last_read = ""
            st.rerun()

# --- SAYFA: DERS MODU ---
elif st.session_state.page == "DERS":
    idx = st.session_state.index
    items = st.session_state.data
    
    if idx < len(items):
        item = items[idx]
        text = item['text']
        
        # Görsel Gösterim
        st.markdown(f"<div class='big-text'>{text}</div>", unsafe_allow_html=True)
        
        # Sesli Okuma (Otomatik)
        ses_cal_otomatik(text)
        
        # Sesli Komut Butonu
        st.write("---")
        st.info("Komutlar: 'Devam', 'Tekrar', 'Geri', 'Bitir'")
        
        col_mic, col_btn = st.columns([1, 1])
        
        with col_mic:
            komut = speech_to_text(language='tr', start_prompt="🎙️ BAS KONUŞ", stop_prompt="DURDUR", just_once=True, key=f"mic_d_{idx}")
        
        with col_btn:
            if st.button("Devam Et (Manuel)"):
                st.session_state.index += 1
                st.session_state.last_read = ""
                st.rerun()

        # Komut İşleme
        if komut:
            cmd = komut.lower()
            if "devam" in cmd or "geç" in cmd or "sonraki" in cmd:
                st.session_state.index += 1
                st.session_state.last_read = ""
                st.rerun()
            elif "tekrar" in cmd or "oku" in cmd:
                st.session_state.last_read = ""
                st.rerun()
            elif "geri" in cmd and idx > 0:
                st.session_state.index -= 1
                st.session_state.last_read = ""
                st.rerun()
            elif "bitir" in cmd:
                st.session_state.page = "GIRIS"
                st.rerun()
                
    else:
        st.success("Ders Bitti!")
        ses_cal_otomatik("Ders bitti. Ana menüye dönülüyor.")
        time.sleep(3)
        st.session_state.page = "GIRIS"
        st.rerun()

# --- SAYFA: TEST MODU ---
elif st.session_state.page == "TEST":
    idx = st.session_state.index
    questions = st.session_state.data
    
    if idx < len(questions):
        q = questions[idx]
        
        st.subheader(f"Soru {q['no']}")
        st.markdown(f"<div class='big-text'>{q['text']}</div>", unsafe_allow_html=True)
        
        # Okunacak Metni Hazırla
        okunacak = f"Soru {q['no']}. {q['text']}. "
        for k, v in q['opts'].items():
            okunacak += f"{k} şıkkı , , {v}. "
            
        ses_cal_otomatik(okunacak)
        
        # --- CEVAP ALANI ---
        st.write("---")
        st.info("Cevabınızı söyleyin (A, B...) veya butona basın.")
        
        komut = speech_to_text(language='tr', start_prompt="🎙️ CEVAPLA", stop_prompt="DURDUR", just_once=True, key=f"mic_q_{idx}")
        
        # Manuel Butonlar
        cols = st.columns(5)
        manual_secim = None
        for i, opt in enumerate(["A", "B", "C", "D", "E"]):
            if cols[i].button(opt):
                manual_secim = opt

        # Cevap Kontrolü
        secim = manual_secim
        if komut:
            cmd = komut.lower()
            secim = None
            for opt in ["a", "b", "c", "d", "e"]:
                if opt in cmd.split():
                    secim = opt.upper()
                    break
            
            if "tekrar" in cmd:
                st.session_state.last_read = ""
                st.rerun()
            elif "pas" in cmd or "geç" in cmd:
                st.session_state.index += 1
                st.session_state.last_read = ""
                st.rerun()
            elif "bitir" in cmd:
                st.session_state.index = len(questions)
                st.rerun()

        if secim:
            dogru = q['correct']
            if secim == dogru:
                st.success("DOĞRU!")
                ses_cal_otomatik("Doğru cevap!")
                st.session_state.score["dogru"] += 1
            else:
                st.error(f"YANLIŞ! Doğru: {dogru}")
                dogru_metin = q['opts'].get(dogru, "")
                ses_cal_otomatik(f"Yanlış. Doğru cevap {dogru} şıkkı , , {dogru_metin}")
            
            time.sleep(3)
            st.session_state.index += 1
            st.session_state.last_read = ""
            st.rerun()

    else:
        # Test Sonu
        d = st.session_state.score["dogru"]
        y = st.session_state.score["yanlis"]
        msg = f"Test tamamlandı. {d} doğru, {y} yanlış yaptınız."
        st.success(msg)
        ses_cal_otomatik(msg)
        time.sleep(4)
        st.session_state.page = "GIRIS"

        st.rerun()

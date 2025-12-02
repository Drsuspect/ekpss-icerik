# ==============================================================================
# EKPSS SESLİ ASİSTAN (Platform bağımsız & Streamlit Cloud uyumlu)
# ==============================================================================

import sys
import asyncio
import os
import re
import time
import base64
import pdfplumber
import streamlit as st
from streamlit_mic_recorder import speech_to_text
import edge_tts

# --- Cloud Ortamı İçin Asyncio Fix (Gerekirse) ---
# Streamlit Cloud (Linux) genellikle buna ihtiyaç duymaz,
# ama Windows'tan kaynaklanan bir sorunu çözmek için eklenmişti.
if sys.platform == "win32":
    # Windows için event loop fix (Streamlit Cloud'da çalışmaz, yerel test için bırakılabilir)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ==============================================================================
# 1. SAYFA AYARLARI VE STYLING
# ==============================================================================
st.set_page_config(page_title="EKPSS Sesli Asistan", layout="centered")

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
if 'mod' not in st.session_state: st.session_state.mod = "TEST" # Başlangıç modu

# ==============================================================================
# 2. SES MOTORU
# ==============================================================================
async def metni_sese_cevir("Merhaba, test"):
    communicate = edge_tts.Communicate(metin, "tr-TR-AhmetNeural")
    await communicate.save("temp_audio.mp3")

def ses_cal_otomatik(metin):
    """Sesi oluşturur ve tarayıcıda çalar"""
    
    # 🌟 GÜVENLİK KONTROLÜ: Metin boşsa veya sadece boşluksa çık
    if not metin or metin.strip() == "":
        st.warning("Ses motoruna boş metin gönderildi. İşlem atlanıyor.")
        return
        
    if metin == st.session_state.last_read:
        return
    
    # ... (Geri kalan kodunuz aynı kalır)
    
    # Hata durumunda uygulama kilitlemesin diye deneme bloğu
    try:
        # edge-tts'in senkron çalışması için asyncio.run kullanılır
        asyncio.run(metni_sese_cevir(metin))
        
        if os.path.exists("temp_audio.mp3"):
            # Sesi oku ve base64'e dönüştür
            with open("temp_audio.mp3", "rb") as f:
                audio_bytes = f.read()
            
            # Geçici dosyayı sil (temizlik için)
            os.remove("temp_audio.mp3")
                
            audio_base64 = base64.b64encode(audio_bytes).decode()
            
            # HTML audio etiketi ile otomatik çalmayı sağla
            audio_html = f"""
                <audio autoplay="true">
                <source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3">
                </audio>
            """
            st.markdown(audio_html, unsafe_allow_html=True)
            st.session_state.last_read = metin
            
    except Exception as e:
        # Streamlit arayüzünde hatayı göster
        st.error(f"Ses oluşturma hatası: {e}")

# ==============================================================================
# 3. PDF ANALİZİ
# ==============================================================================
def pdf_analiz_et(uploaded_file, mod):
    """PDF'i okur, gereksiz satırları temizler ve veri yapısını oluşturur"""
    ham_metin = ""
    data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    for line in extracted.split('\n'):
                        line = line.strip()
                        if not line:
                            continue

                        low = line.lower()

                        # Sayfa numaralarını at
                        if low.startswith("sayfa ") and len(line) < 20:
                            continue

                        # Tek başına numara
                        if re.fullmatch(r'\d+', line):
                            continue

                        # Çöp metinleri at (telif/kaynak bilgileri)
                        if any(x in low for x in ["bu doküman","telif","ekpss","ösym","copyright","report","scan","scanner","tarama"]):
                            continue

                        ham_metin += line + "\n"

    except Exception as e:
        return [{"hata": str(e)}]

    # --- DERS MODU ---
    if mod == "DERS":
        buffer = ""
        for line in ham_metin.split('\n'):
            line = line.strip()
            if not line: continue

            # Başlıkları ayırt etmek için basit kural
            is_header = line.startswith("(") or line.endswith(":") or re.match(r'^\d+\.', line)
            
            if is_header and buffer:
                data.append({"tip": "icerik", "text": buffer.strip()})
                data.append({"tip": "baslik", "text": line.strip()})
                buffer = ""
            elif is_header and not buffer:
                data.append({"tip": "baslik", "text": line.strip()})
            else:
                # Satır sonu tireyi (hipen) kaldır ve birleştir
                if buffer.endswith("-"):
                    buffer = buffer[:-1] + line
                else:
                    buffer = buffer + " " + line

        if buffer:
            data.append({"tip": "icerik", "text": buffer.strip()})
            
    # --- TEST MODU ---
    elif mod == "TEST":
        parts = re.split(r'\n(\d{1,3}[\.\)])', ham_metin)
        cevap_anahtari = {}
        
        # Cevap Anahtarını PDF'in sonundan çek
        if "CEVAP ANAHTARI" in ham_metin:
            try:
                key_part = ham_metin.split("CEVAP ANAHTARI")[-1]
                matches = re.findall(r'(\d{1,3})[\.\-\s]+([A-E])', key_part)
                for n, a in matches:
                    cevap_anahtari[str(n)] = a
            except: pass

        for i in range(1, len(parts), 2):
            q_no = parts[i].replace(".", "").replace(")", "").strip()
            q_body_raw = parts[i+1]

            # Soru metni
            q_text = q_body_raw.split("A)")[0].strip() if "A)" in q_body_raw else q_body_raw.strip()

            # Seçenekleri çek
            opts = {}
            # Regex: (A-E) + ) veya . + boşluk(lar) + içeriği yakala + (?= Lookahead: bir sonraki seçeneğe bak VEYA $ sonuna bak)
            for m in re.finditer(r'([A-E])[\)\.]\s+(.*?)(?=\s[A-E][\)\.]\s|$)', q_body_raw, re.DOTALL):
                opts[m.group(1)] = m.group(2).strip()

            if q_text and opts:
                data.append({
                    "no": q_no,
                    "text": q_text,
                    "opts": opts,
                    "correct": cevap_anahtari.get(q_no, "?")
                })
        
        if not data:
             st.warning("TEST modunda soru/cevap çıkarılamadı. PDF formatını kontrol edin.")
        
    return data

# ==============================================================================
# 4. SAYFA YÖNETİM FONKSİYONLARI
# ==============================================================================

def sayfa_degistir(yeni_sayfa):
    st.session_state.page = yeni_sayfa

def reset_uygulama():
    """Tüm oturum durumlarını sıfırla"""
    st.session_state.page = "GIRIS"
    st.session_state.data = []
    st.session_state.index = 0
    st.session_state.score = {"dogru": 0, "yanlis": 0}
    st.session_state.last_read = ""
    st.rerun()
    
def cevabi_kontrol_et(cevap):
    """Kullanıcının verdiği cevabı kontrol et ve puanı güncelle"""
    
    if st.session_state.mod == "TEST":
        current_q = st.session_state.data[st.session_state.index]
        if cevap == current_q['correct']:
            st.session_state.score['dogru'] += 1
            st.success(f"✅ Doğru! Cevap: {current_q['correct']}")
        else:
            st.session_state.score['yanlis'] += 1
            st.error(f"❌ Yanlış! Doğru cevap: {current_q['correct']}")

        # Bir sonraki soruya geç
        time.sleep(1.5) # Kullanıcının cevabını görmesi için kısa bekleme
        st.session_state.index += 1
        st.session_state.last_read = "" # Yeni metin okutulması için resetle

# ==============================================================================
# 5. ARAYÜZ SAYFALARI
# ==============================================================================

def giris_sayfasi():
    """Giriş ve dosya yükleme arayüzü"""
    st.title("🗣️ EKPSS Sesli Asistan")
    st.markdown("---")

    st.markdown("""
        <div class="info-box">
        Bu uygulama, yüklediğiniz PDF dosyasını okuyarak size **Sesli Test Çözme** veya **Sesli Ders Çalışma** imkanı sunar.
        </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "📚 PDF Dosyası Yükleyin (Tercihen metin tabanlı PDF)",
        type="pdf"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔴 TEST ÇÖZ (Soru/Cevap)", key="test_mod_btn"):
            st.session_state.mod = "TEST"
            
    with col2:
        if st.button("🔵 DERS ÇALIŞ (Metin Oku)", key="ders_mod_btn"):
            st.session_state.mod = "DERS"


    if uploaded_file is not None:
        st.info(f"Seçilen Mod: **{st.session_state.mod}**")
        
        # Dosya analizi butonu
        if st.button("🚀 Analizi Başlat ve Uygulamayı Yükle", type="primary"):
            with st.spinner("PDF Analiz Ediliyor... Lütfen Bekleyiniz."):
                st.session_state.data = pdf_analiz_et(uploaded_file, st.session_state.mod)
                st.session_state.index = 0 # Sayacı sıfırla
                st.session_state.score = {"dogru": 0, "yanlis": 0}
                st.session_state.last_read = "" # Okuma geçmişini sıfırla

                if st.session_state.data and 'hata' not in st.session_state.data[0]:
                    sayfa_degistir("UYGULAMA")
                elif st.session_state.data and 'hata' in st.session_state.data[0]:
                    st.error(f"Analiz Hatası: {st.session_state.data[0]['hata']}")
                else:
                    st.error("PDF'ten geçerli metin veya soru çıkarılamadı. Farklı bir PDF deneyin.")


def uygulama_sayfasi():
    """Soru/Ders gösterim ve etkileşim arayüzü"""
    
    # ----------------------------------------------------
    # BAŞLIK ve DURUM GÖSTERİMİ
    # ----------------------------------------------------
    if st.session_state.mod == "TEST":
        st.title("🎤 Sesli Test Çözme Modu")
        # Skor Tablosu
        col1, col2, col3 = st.columns([1, 1, 1])
        toplam_soru = len(st.session_state.data)
        col1.metric("Soru No", f"{st.session_state.index + 1} / {toplam_soru}")
        col2.metric("✅ Doğru", st.session_state.score['dogru'], delta_color="normal")
        col3.metric("❌ Yanlış", st.session_state.score['yanlis'], delta_color="inverse")
        st.markdown("---")
    
    else: # DERS Modu
        st.title("📘 Sesli Ders Çalışma Modu")
        toplam_icerik = len(st.session_state.data)
        st.info(f"İçerik No: **{st.session_state.index + 1} / {toplam_icerik}**")
        st.markdown("---")
        
    # ----------------------------------------------------
    # İÇERİK GÖSTERİMİ VE ETKİLEŞİM
    # ----------------------------------------------------
    
    if st.session_state.index < len(st.session_state.data):
        current_item = st.session_state.data[st.session_state.index]
        
        if st.session_state.mod == "TEST":
            
            # Soru Metni
            soru_metni = f"Soru {current_item['no']}: {current_item['text']}"
            st.markdown(f'<div class="big-text">{soru_metni}</div>', unsafe_allow_html=True)
            ses_cal_otomatik(soru_metni)
            
            st.markdown("---")
            st.subheader("Seçenekler:")
            
            # Seçenekler ve Butonlar
            cols = st.columns(len(current_item['opts']))
            option_keys = sorted(current_item['opts'].keys())
            
            for i, opt_key in enumerate(option_keys):
                option_text = current_item['opts'][opt_key]
                full_option_text = f"{opt_key}) {option_text}"
                
                with cols[i]:
                    if st.button(full_option_text, key=f"opt_{opt_key}"):
                        cevabi_kontrol_et(opt_key)
                        
            st.markdown("---")
            
            # Sesli Yanıt Etkileşimi
            st.subheader("🗣️ Sesli Yanıt (Mikrofon):")
            st.caption("Cevabınız (A, B, C, D veya E) mikrofon ile söylenmelidir.")
            
            mic_result = speech_to_text(
                language='tr',
                start_prompt="Mikrofonu Başlat",
                stop_prompt="Kaydı Durdur",
                just_once=True,
                use_container_width=True,
                callback=None,
                args=(),
                kwargs={},
                key="speech_to_text_key"
            )
            
            if mic_result and isinstance(mic_result, str):
                mic_text = mic_result.strip().upper()
                # Yanıtı A, B, C, D veya E olarak temizle
                cleaned_answer = re.sub(r'[^A-E]', '', mic_text).replace("E)", "E").replace("D)", "D")
                
                if cleaned_answer in option_keys:
                    st.warning(f"Sesli algılanan cevap: **{cleaned_answer}**")
                    cevabi_kontrol_et(cleaned_answer)
                elif cleaned_answer:
                    st.error(f"Sesli yanıt anlaşılamadı veya geçersiz: {mic_text}")

        # DERS MODU İÇİN
        elif st.session_state.mod == "DERS":
            
            if current_item['tip'] == 'baslik':
                st.subheader(f"***{current_item['text']}***")
            else:
                st.markdown(f'<div class="info-box">{current_item["text"]}</div>', unsafe_allow_html=True)
                
            ses_cal_otomatik(current_item['text'])
            
            st.markdown("---")
            
            # Sonraki/Önceki Butonları
            col_prev, col_next = st.columns(2)
            with col_prev:
                if st.button("⬅️ Önceki Sayfa", key="prev_ders", disabled=(st.session_state.index == 0)):
                    st.session_state.index -= 1
                    st.session_state.last_read = ""
                    st.rerun()
            
            with col_next:
                if st.button("➡️ Sonraki Sayfa", key="next_ders"):
                    st.session_state.index += 1
                    st.session_state.last_read = ""
                    st.rerun()


    # ----------------------------------------------------
    # BİTİŞ EKRANI
    # ----------------------------------------------------
    else:
        st.balloons()
        
        if st.session_state.mod == "TEST":
            st.header("🎉 Test Bitti!")
            toplam = st.session_state.score['dogru'] + st.session_state.score['yanlis']
            st.subheader(f"Toplam Soru: {toplam}")
            st.metric("✅ Toplam Doğru", st.session_state.score['dogru'])
            st.metric("❌ Toplam Yanlış", st.session_state.score['yanlis'])
            
            if toplam > 0:
                basari_orani = (st.session_state.score['dogru'] / toplam) * 100
                st.progress(basari_orani / 100, text=f"Başarı Oranı: **{basari_orani:.2f}%**")
        
        else: # DERS Bitti
            st.header("🎉 Ders İçeriği Tükendi!")
            st.info("PDF'in sonuna ulaştınız.")

        # Giriş sayfasına dönme butonu
        if st.button("🏠 Yeniden Başlat / Yeni Dosya Yükle", type="primary"):
            reset_uygulama()


# ==============================================================================
# 6. ANA UYGULAMA DÖNGÜSÜ
# ==============================================================================
if __name__ == "__main__":
    if st.session_state.page == "GIRIS":
        giris_sayfasi()
    elif st.session_state.page == "UYGULAMA":
        uygulama_sayfasi()







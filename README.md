# ◯ Antigravity Remote (`agy-remote`)

**PC'de açık olan Google Antigravity ile telefondan (Wi-Fi / LAN üzerinden) canlı mesajlaşma, sesli konuşma (Live Mode), dosya düzenleme ve uzaktan kontrol köprüsü.**

Bilgisayar başından kalktığınızda PC ekranında çalışan **Antigravity** ajanınızın ne yaptığını telefondan canlı takip edin, sesli veya yazılı mesaj gönderin, çoklu görsel paylaşın, çalıştırılan terminal komutlarını inceleyin, proje dosyalarını telefondan düzenleyin ve aktif modeli değiştirin!

---

## ✨ Özellikler (Features)

- 🔒 **Otomatik HTTPS & PWA Mobil Arayüz:** Telefon tarayıcılarında (iOS Safari & Android Chrome) mikrofon ve ses özelliklerinin sorunsuz çalışması için yerel IP adresiniz adına otomatik kendinden imzalı SSL sertifikası (`https://<IP>:8443`) üretir ve `http://<IP>:8765` isteklerini otomatik HTTPS'e yönlendirir.
- 🎧 **Canlı Sesli Sohbet (Live Mode) & Sesli Yanıt (MP3 TTS):**
  - **🎧 Canlı Sohbet:** Eller serbest modda konuşun; söyledikleriniz otomatik PC'deki Antigravity'ye gönderilir, Antigravity yanıtı bitirdiğinde doğal Türkçe sesle (`/api/tts` MP3 akışı) telefonunuzda okunur ve tekrar sizi dinlemeye geçer.
  - **🎙️ Sesli Yazma & 🔊 Sesli Dinleme:** Mesaj kutusundaki mikrofonla konuşarak yazın veya her mesajın üstündeki **`🔊 Dinle`** butonuyla yanıtları sesli dinleyin.
- ☑️ **Çoktan Seçmeli Soru Kartları (`ask_question`):** Antigravity size çoktan seçmeli soru sorduğunda şıklar doğrudan telefon ekranına tıklanabilir kart olarak gelir; seçiminizi telefondan gönderdiğinizde PC'de otomatik işaretlenir.
- 🖼️ **Çoklu Görsel Gönderme (`＋`):** Telefondan birden fazla fotoğraf veya ekran görüntüsü seçip tek dokunuşla PC'deki Antigravity sohbetine (`CF_DIB` pano + `Ctrl+V`) gönderin.
- 💻 **Çalıştırılan Komutlar & Çıktılar (`Komutlar` Sekmesi):** Antigravity'nin çalıştırdığı tüm terminal komutlarını (`run_command`), çıkış kodlarını (`Exit Code`) ve oluşturduğu/düzenlediği dosyaları canlı inceleyin.
- 📁 **Proje Dosya Gezgini & Kod Düzenleyici (`Dosyalar` Sekmesi):** Projedeki tüm klasör ve dosyaları telefondan gezin, kodları görüntüleyin, telefondan düzenleyip **`💾 Kaydet`** ile doğrudan PC'ye kaydedin veya **`＋ Yeni Dosya`** oluşturun.
- 🤖 **Doğrudan Model Seçimi & Limit Takibi (`Model & Limit` Sekmesi):** Telefondan doğrudan model seçin (`Gemini 4 Pro (High)`, `Gemini 3.8 Flash`, `Claude Opus 5.5` vb.) ve bağlam (Context 1M) doluluk yüzdesini, önbellek (Cache) oranını ve son 24 saatlik token kullanımını takip edin.

---

## 🛠️ Kurulum ve Başlatma

### 1. Gereksinimleri Yükleyin

```bash
pip install -r requirements.txt
```

### 2. Uygulamayı Başlatın

**Masaüstü Kontrol Merkezi (GUI - Önerilen):**
```bash
python run.py
```
*(Windows'ta doğrudan `Baslat.bat` dosyasına çift tıklayarak da açabilirsiniz.)*

**Terminal (CLI) Modu:**
```bash
python run.py --cli
```

---

## 📖 Nasıl Kullanılır?

1. Bilgisayarınızda **Antigravity** açıkken `Baslat.bat` (veya `python run.py`) ile **Antigravity Remote** uygulamasını açın.
2. Telefonunuzdan sol paneldeki **QR Kodu** okutun veya verilen **`https://192.168.1.X:8443`** adresine girin.
   - *Not (İlk Giriş):* Yerel ağ sertifikası olduğu için Safari/Chrome ilk açılışta *"Bağlantı gizli değil"* uyarısı gösterirse **Ayrıntıları Göster → Bu web sitesini ziyaret et** seçeneğine dokunun.
3. Ekrandaki 4 haneli PIN kodunu girin (QR kod okuttuysanız otomatik giriş yapar).
4. Artık telefondan yazılı, görselli veya **🎧 Canlı Sohbet** moduyla PC'deki Antigravity ile konuşabilirsiniz!

---

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) ile açık kaynaklı olarak lisanslanmıştır.

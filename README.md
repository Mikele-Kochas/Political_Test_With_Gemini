# Test Poglądów Politycznych z Gemini

Aplikacja internetowa umożliwiająca ocenę poglądów politycznych za pomocą interaktywnego quizu, wykorzystująca model Gemini AI do generowania pytań i podsumowań.

## Wymagania

- Python 3.9+
- Flask
- Google Generative AI API
- Plotly
- Gunicorn (do wdrożenia)

## Konfiguracja

1. Sklonuj repozytorium
2. Zainstaluj zależności: `pip install -r requirements.txt`
3. Utwórz plik `.env` z kluczem API Google: `GOOGLE_API_KEY=your_api_key`
4. Uruchom aplikację: `python flask_app.py`

## Wdrożenie

Aplikacja jest skonfigurowana do wdrożenia na platformie Render.

## Licencja

Projekt jest dostępny na licencji MIT. 
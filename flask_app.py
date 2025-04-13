import os
import json
import datetime # Import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
import google.generativeai as genai
import plotly.graph_objects as go
import plotly.io as pio # For converting Plotly fig to JSON

# --- Initial Setup ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("Nie znaleziono klucza API Google. Upewnij się, że plik .env istnieje i zawiera GOOGLE_API_KEY.")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-lite') # Keep user-specified model

app = Flask(__name__)
# IMPORTANT: Set a secret key for session management!
# In a real app, use a strong, randomly generated key and store it securely.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-replace-in-prod")

# --- Inject current year into template context ---
@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

# --- Configuration (Copied from Gradio app) ---
CATEGORIES = [
    "Polityka Fiskalna (Podatki, Wydatki)",
    "Rola Państwa w Gospodarce (Regulacje, Interwencje)",
    "Prawa i Wolności Obywatelskie",
    "Rola Religii i Tradycji",
    "Polityka Zagraniczna i Bezpieczeństwo",
    "Środowisko i Klimat"
]
QUESTIONS_PER_CATEGORY = 5
LIKERT_SCALE = [
    "1: Zdecydowanie się nie zgadzam",
    "2: Nie zgadzam się",
    "3: Nie mam zdania",
    "4: Zgadzam się",
    "5: Zdecydowanie się zgadzam"
]
LIKERT_SCALE_VALUES = {choice: i + 1 for i, choice in enumerate(LIKERT_SCALE)}
TOTAL_QUESTIONS = len(CATEGORIES) * QUESTIONS_PER_CATEGORY

# --- New 5 Axes Definition (approx. 60 questions total) ---
AXES_DEFINITIONS = [
    {
        # 1. Economic Policy: Focuses on state intervention vs. free market (14 questions)
        "axis_name": "Polityka Gospodarcza",
        "pole_left": "Równość Społeczna",
        "pole_right": "Wolność Rynkowa",
        "sub_topics": [
            "Progresja podatkowa i obciążenia fiskalne firm", # More specific
            "Wysokość i dostępność świadczeń socjalnych", # More specific
            "Regulacje rynku pracy (płaca minimalna, związki zawodowe)", # More specific
            "Rola państwa we własności kluczowych sektorów (energia, bankowość)", # More specific
            "Wolny handel międzynarodowy vs ochrona rynku wewnętrznego",
            "Akceptacja długu publicznego dla finansowania inwestycji/programów"
        ],
        "num_general_questions": 8 # 6 sub-topics + 8 general = 14 questions
    },
    {
        # 2. Social Policy: Focuses on individual freedoms vs. traditional values (14 questions)
        "axis_name": "Polityka Społeczna",
        "pole_left": "Konserwatyzm",
        "pole_right": "Liberalizm",
        "sub_topics": [
            "Prawa osób LGBTQ+ (małżeństwa, adopcja)", # More specific
            "Dostępność i refundacja aborcji/antykoncepcji",
            "Rozdział kościoła od państwa i wpływ religii na prawo", # More specific
            "Model rodziny i edukacja seksualna w szkołach", # More specific
            "Granice wolności słowa (mowa nienawiści, bluźnierstwo)",
            "Polityka narkotykowa (legalizacja, dekryminalizacja)"
        ],
        "num_general_questions": 8 # 6 sub-topics + 8 general = 14 questions
    },
    {
        # 3. National Policy: Focuses on sovereignty vs. international integration (12 questions)
        "axis_name": "Polityka Narodowa",
        "pole_left": "Nacjonalizm",
        "pole_right": "Globalizm",
        "sub_topics": [
            "Głębokość integracji z Unią Europejską (suwerenność vs współpraca)", # More specific
            "Otwartość na imigrację zarobkową i polityka azylowa", # More specific
            "Rola państwa w ochronie kultury i języka narodowego",
            "Nacjonalizm gospodarczy (preferowanie krajowych firm/produktów)",
            "Stosunek do międzynarodowych trybunałów i prawa"
        ],
        "num_general_questions": 7 # 5 sub-topics + 7 general = 12 questions
    },
    {
        # 4. Environmental Policy: Focuses on ecology vs. economic development (8 questions)
        "axis_name": "Polityka Środowiskowa",
        "pole_left": "Rozwój",
        "pole_right": "Ekologizm",
        "sub_topics": [
            "Rygorystyczność norm środowiskowych dla przemysłu", # More specific
            "Tempo i koszt transformacji energetycznej (odejście od węgla)", # More specific
            "Ochrona obszarów naturalnych (parki narodowe, wycinka drzew)",
            "Indywidualna odpowiedzialność vs systemowe rozwiązania w ekologii"
        ],
        "num_general_questions": 4 # 4 sub-topics + 4 general = 8 questions
    },
    {
        # 5. Authority & Order: Focuses on state power vs. individual liberty/privacy (12 questions)
        "axis_name": "Władza i Porządek",
        "pole_left": "Wolność",
        "pole_right": "Bezpieczeństwo",
        "sub_topics": [
            "Zakres uprawnień policji i służb (kontrole, użycie siły)", # More specific
            "Stopień inwigilacji cyfrowej (monitoring internetu, dane)",
            "Surowość karania przestępstw (system więziennictwa)",
            "Prawo do posiadania broni", # New specific sub-topic
            "Balans między wolnością zgromadzeń a porządkiem publicznym"
        ],
        "num_general_questions": 7 # 5 sub-topics + 7 general = 12 questions
    }
]

# Calculate total questions based on the new structure (should be 60)
TOTAL_QUESTIONS = sum(len(axis.get("sub_topics", [])) + axis.get("num_general_questions", 0) for axis in AXES_DEFINITIONS)

# --- Helper Functions (Adapted from Gradio app) ---

def generate_questions(axis_definition: dict) -> list[str]:
    """Generates diverse & specific questions for sub-topics and general axis concepts, oriented towards poles."""
    axis_name = axis_definition["axis_name"]
    sub_topics = axis_definition.get("sub_topics", [])
    num_subtopic_questions = len(sub_topics)
    num_general_questions = axis_definition.get("num_general_questions", 0)
    total_axis_questions = num_subtopic_questions + num_general_questions
    pole_left = axis_definition["pole_left"]
    pole_right = axis_definition["pole_right"]

    if total_axis_questions == 0:
        return []

    # Build the prompt dynamically
    prompt_parts = []
    prompt_parts.append(f"Dla osi politycznej '{axis_name}' ('{pole_left}' vs '{pole_right}'), wygeneruj łącznie {total_axis_questions} **RÓŻNORODNYCH i SPECYFICZNYCH** stwierdzeń.")
    prompt_parts.append("Wszystkie stwierdzenia muszą spełniać następujące warunki:")
    prompt_parts.append("1. Dotyczyć **konkretnych aspektów** ogólnych postaw i wartości, być prostymi, jednoznacznymi opiniami.")
    prompt_parts.append(f"2. Być sformułowane tak, aby ZGODA (wynik 5: '{LIKERT_SCALE[-1]}') oznaczała silne poparcie dla bieguna '{pole_right}', a NIEZGODA (wynik 1: '{LIKERT_SCALE[0]}') oznaczała silne poparcie dla bieguna '{pole_left}'.")
    prompt_parts.append("3. Zmuszać do zajęcia stanowiska na 5-stopniowej skali Likerta.")
    prompt_parts.append("4. **Unikać powtarzania tej samej myśli** w różnych sformułowaniach. Każde pytanie powinno wnosić **nowy niuans** lub dotyczyć **innego dylematu** w ramach osi.")
    prompt_parts.append("5. Powinny badać **potencjalne konsekwencje lub trudniejsze aspekty** danego stanowiska, nie tylko proste deklaracje.")

    # Add section for sub-topic questions
    if num_subtopic_questions > 0:
        prompt_parts.append(f"\nPierwsze {num_subtopic_questions} stwierdzeń musi dotyczyć następujących podtematów (po jednym na podtemat, eksplorując ich **specyfikę**):")
        prompt_parts.append(chr(10).join([f'- {st}' for st in sub_topics]))

    # Add section for general questions
    if num_general_questions > 0:
        if num_subtopic_questions > 0:
            prompt_parts.append(f"\nPozostałe {num_general_questions} stwierdzeń powinno dotyczyć osi '{axis_name}' bardziej ogólnie, eksplorując **RÓŻNE jej aspekty i dylematy** nieujęte w powyższych podtematach. **Zadbaj o różnorodność tych pytań.**")
        else:
             prompt_parts.append(f"\nWygeneruj {num_general_questions} **RÓŻNORODNYCH** stwierdzeń dotyczących osi '{axis_name}' ogólnie, eksplorując różne jej aspekty i dylematy.")

    prompt_parts.append("\nPrzykład formatowania ZGODY na prawy biegun (Wolność Rynkowa): \"Niskie podatki są ważniejsze dla gospodarki niż wysokie wydatki socjalne.\"")
    prompt_parts.append(f"\nZwróć **tylko listę {total_axis_questions} stwierdzeń**, każde w nowej linii. Bez numeracji, wstępów, nazw podtematów czy formatowania markdown.")

    prompt = "\n".join(prompt_parts)

    print(f"--- Generating {total_axis_questions} questions for axis: {axis_name} (Diverse & Specific Prompt) ---")
    # print(f"--- Prompt Start ---\n{prompt}\n--- Prompt End ---") # Uncomment for debugging prompt

    try:
        response = model.generate_content(prompt)
        questions = [q.strip().lstrip('- ').lstrip('* ') for q in response.text.strip().split('\n') if q.strip()]
        if len(questions) != total_axis_questions:
            print(f"Warning: LLM returned {len(questions)} questions instead of {total_axis_questions} for {axis_name}.")
            questions = questions[:total_axis_questions]
            while len(questions) < total_axis_questions:
                questions.append(f"Placeholder - Generation Error {len(questions)+1} for {axis_name}")
        print(f"--- Generated {len(questions)} questions for {axis_name} ---")
        return questions
    except Exception as e:
        print(f"Error generating questions for {axis_name}: {e}")
        return [f"API Error - question {i+1} ({axis_name})" for i in range(total_axis_questions)]

def generate_summary(answers_by_index: dict) -> str:
    """Generates a synthesized, personalized summary as a single block of text based on deep analysis."""
    print("--- Generating summary (Flowing Narrative Prompt) --- ")
    formatted_answers_for_prompt = ""
    questions_from_session = session.get('questions', {}) # Get questions
    for axis_name, indexed_answers in answers_by_index.items():
        formatted_answers_for_prompt += f"Oś: {axis_name}\n"
        axis_questions = questions_from_session.get(axis_name, [])
        for q_idx, answer_text in sorted(indexed_answers.items()):
            answer_value = LIKERT_SCALE_VALUES.get(str(answer_text), "Unknown")
            question_text = axis_questions[q_idx] if q_idx < len(axis_questions) else f"(Pytanie {q_idx+1})"
            formatted_answers_for_prompt += f"  Pytanie {q_idx+1}: Odpowiedź {answer_value} ({answer_text}) - {question_text[:50]}...\n" 
        formatted_answers_for_prompt += "\n"

    # Revised prompt for a flowing, consistent narrative summary
    prompt = f"""
Przeanalizuj **dogłębnie** poniższe odpowiedzi użytkownika (skala 1-5, 1=Zdecydowanie się nie zgadzam, 5=Zdecydowanie się zgadzam), szukając **najbardziej dominujących i spójnych wzorców myślenia, wartości oraz ewentualnych wewnętrznych napięć**.

Odpowiedzi:
{formatted_answers_for_prompt}

Twoim zadaniem jest napisanie **spersonalizowanego, płynnego podsumowania** (ok. 120-180 słów) w formie **JEDNEGO AKAPITU**, które trafnie opisuje profil polityczny użytkownika. Pisz bezpośrednio do użytkownika ('Ty', 'Twoje').

**Instrukcje:**
1.  **Rozpocznij BEZPOŚREDNIO** od zdania identyfikującego **główną myśl przewodnią lub kluczowy dylemat** widoczny w odpowiedziach (np. "Twoje odpowiedzi malują obraz osoby konsekwentnie stawiającej na wolność indywidualną..." lub "Charakteryzuje Cię poszukiwanie równowagi między pragmatyzmem gospodarczym a wrażliwością społeczną...").
2.  **Rozwiń tę główną myśl**, ilustrując ją **1-2 innymi znaczącymi tendencjami** zaobserwowanymi w odpowiedziach (np. "...co przejawia się zarówno w Twoim podejściu do kwestii obyczajowych, jak i w sceptycyzmie wobec nadmiernych regulacji."). **NIE WYMIENIAJ KONKRETNYCH ODPOWIEDZI ANI OSI.** Skup się na syntezie ogólnych postaw.
3.  Wpleć subtelne wskazanie na **1-2 nurty ideologiczne**, z którymi zaobserwowane wzorce mogą **rezonować**, używając sformułowań typu: "...takie podejście często spotyka się w ramach [nazwa nurtu]." lub "...co może sytuować Twoje poglądy blisko [nazwa nurtu]." **Unikaj definitywnego etykietowania.**
4.  **Zadbaj o naturalny, angażujący język.** Unikaj formalnego, raportowego tonu.
5.  **ABSOLUTNIE NIE używaj żadnych zdań wstępnych** typu "Oto podsumowanie..." ani nie opisuj struktury odpowiedzi.

**Przykład początku:** "Twoje odpowiedzi sugerują, że wolność jednostki jest dla Ciebie kluczową wartością, co widać w liberalnym podejściu do spraw społecznych i niechęci do ograniczeń gospodarczych. Jednocześnie dostrzegasz rolę państwa w zapewnieniu podstawowego bezpieczeństwa..."

Zwróć **TYLKO gotowy tekst podsumowania** jako jeden akapit.
"""
    
    try:
        response = model.generate_content(prompt)
        summary_text = response.text.strip()
        
        # Basic checks
        if not summary_text or len(summary_text) < 30: 
            print("Warning: Summary seems too short or empty.")
            return "Nie udało się wygenerować poprawnego podsumowania. Spróbuj ponownie."
        
        # Check for axis names (still potentially useful check)
        if any(axis_def["axis_name"] in summary_text for axis_def in AXES_DEFINITIONS):
             print("Warning: Summary might still contain axis names despite instructions.")
        
        # Check for unwanted preamble (optional but potentially useful)
        if summary_text.lower().startswith("oto podsumowanie") or summary_text.lower().startswith("analiza twoich"):
            print("Warning: Summary seems to start with a preamble.")
            # Attempt to remove common preambles (simple approach)
            lines = summary_text.split('\n')
            if len(lines) > 1 and (lines[0].lower().startswith("oto") or lines[0].lower().startswith("analiza")):
                summary_text = '\n'.join(lines[1:]).strip()

        return summary_text
    except Exception as e:
        print(f"Error generating summary: {e}")
        return f"Wystąpił błąd podczas generowania podsumowania: {e}"

def create_axes_data(answers_by_index: dict) -> list:
    """Calculates scores from answers stored by index."""
    print("--- Creating axes data (from indexed answers) --- ")
    axes_results = []
    for axis_def in AXES_DEFINITIONS:
        axis_name = axis_def["axis_name"]
        # Get answers for this axis using axis_name
        indexed_answers = answers_by_index.get(axis_name, {})
        axis_result = {
            "axis_name": axis_name,
            "pole_left": axis_def["pole_left"],
            "pole_right": axis_def["pole_right"],
            "value_percent": 50.0 # Default to neutral 50%
        }

        if not indexed_answers:
            print(f"Warning: No indexed answers found for axis {axis_name}.")
            axes_results.append(axis_result) # Append default 50%
            continue

        cat_values = []
        # Iterate through the answer texts directly from the indexed dict values
        for answer_text in indexed_answers.values():
            value = LIKERT_SCALE_VALUES.get(str(answer_text))
            if value is not None:
                cat_values.append(value)
            else:
                print(f"Warning: Invalid answer '{answer_text}' for axis {axis_name}.")
        
        if cat_values:
             average_score = sum(cat_values) / len(cat_values)
             value_percent = max(0, min(100, ((average_score - 1) / 4) * 100))
             axis_result["value_percent"] = round(value_percent, 1)
             print(f"Axis: {axis_name}, Avg Score: {average_score:.2f}, Percent: {value_percent:.1f}%")
        else:
             print(f"Warning: No valid numeric answers for axis {axis_name}.")
        
        axes_results.append(axis_result)

    return axes_results

# --- Flask Routes ---

@app.route('/')
def index():
    session.clear()
    return render_template('index.html', total_questions=TOTAL_QUESTIONS)

@app.route('/start', methods=['POST'])
def start():
    session['current_axis_index'] = 0
    session['current_question_within_axis_index'] = 0
    session['questions'] = {} # {axis_name: [q1, q2...]}
    # *** Store answers by index ***
    session['answers'] = {} # {axis_name: {question_index: answer_text}}
    print("--- Quiz started, session initialized --- ")
    return redirect(url_for('quiz'))

@app.route('/quiz')
def quiz():
    """Display the current question."""
    if 'current_axis_index' not in session:
        flash("Sesja wygasła lub quiz nie został rozpoczęty.", "error")
        return redirect(url_for('index'))

    axis_idx = session['current_axis_index']
    q_within_axis_idx = session['current_question_within_axis_index']

    if axis_idx >= len(AXES_DEFINITIONS):
        return redirect(url_for('summary'))

    current_axis_def = AXES_DEFINITIONS[axis_idx]
    axis_name = current_axis_def["axis_name"]
    # Calculate expected number of questions for this specific axis
    num_questions_for_this_axis = len(current_axis_def.get("sub_topics", [])) + current_axis_def.get("num_general_questions", 0)

    # Generate questions if not already generated
    if axis_name not in session.get('questions', {}):
        print(f"--- Generating questions for axis {axis_name} on the fly ---")
        # Pass the full definition including sub_topics and num_general_questions
        generated_q = generate_questions(current_axis_def)

        # Ensure the correct number of questions were generated (including placeholders)
        if len(generated_q) != num_questions_for_this_axis:
            print(f"Error: Mismatch in expected ({num_questions_for_this_axis}) vs generated ({len(generated_q)}) question count for {axis_name}")
            # Handle this critical error - maybe flash message and redirect?
            flash(f"Krytyczny błąd podczas generowania pytań dla osi: {axis_name}.", "error")
            session.clear()
            return redirect(url_for('index'))

        session_questions = session.get('questions', {})
        session_questions[axis_name] = generated_q
        session['questions'] = session_questions

        session_answers = session.get('answers', {})
        session_answers[axis_name] = {}
        session['answers'] = session_answers

        # Check for actual API errors indicated by placeholders
        if any("API Error" in q for q in generated_q):
            flash(f"Błąd API podczas generowania pytań dla osi: {axis_name}.", "error")
            return redirect(url_for('index'))

    # Get current question text
    try:
        question_text = session['questions'][axis_name][q_within_axis_idx]
    except (KeyError, IndexError):
        flash("Błąd ładowania pytania.", "error")
        session.clear()
        return redirect(url_for('index'))

    # Calculate overall question number accurately
    questions_in_previous_axes = sum(len(AXES_DEFINITIONS[i].get("sub_topics", [])) + AXES_DEFINITIONS[i].get("num_general_questions", 0) for i in range(axis_idx))
    current_q_num_overall = questions_in_previous_axes + q_within_axis_idx + 1

    return render_template('quiz.html',
                           category_name=axis_name,
                           question_text=question_text,
                           likert_scale=LIKERT_SCALE,
                           current_q_num=current_q_num_overall,
                           total_questions=TOTAL_QUESTIONS)

@app.route('/answer', methods=['POST'])
def answer():
    """Process the answer and redirect to the next question or summary."""
    if 'current_axis_index' not in session:
        flash("Sesja wygasła.", "error")
        return redirect(url_for('index'))

    user_answer = request.form.get('answer')
    if not user_answer:
        flash("Proszę wybrać odpowiedź.", "warning")
        return redirect(url_for('quiz'))

    axis_idx = session['current_axis_index']
    q_within_axis_idx = session['current_question_within_axis_index']
    current_axis_def = AXES_DEFINITIONS[axis_idx]
    axis_name = current_axis_def["axis_name"]
    # Calculate expected number of questions for this axis again
    num_questions_for_this_axis = len(current_axis_def.get("sub_topics", [])) + current_axis_def.get("num_general_questions", 0)

    # *** Store answer using question index as key ***
    try:
        # Get questions for the current axis to ensure consistency (though not strictly needed for storing answer)
        # current_questions = session['questions'][axis_name]
        # question_text = current_questions[q_within_axis_idx]
        session_answers = session.get('answers', {})
        if axis_name not in session_answers:
            session_answers[axis_name] = {}
        # Use the index q_within_axis_idx as the key
        session_answers[axis_name][q_within_axis_idx] = user_answer
        session['answers'] = session_answers
        print(f"Stored answer for {axis_name}[{q_within_axis_idx}]: {user_answer}")
    except (KeyError, IndexError):
        flash("Wystąpił błąd podczas zapisywania odpowiedzi. Spróbuj ponownie.", "error")
        return redirect(url_for('quiz'))

    # Determine next indices
    next_q_within_axis_idx = q_within_axis_idx + 1
    next_axis_idx = axis_idx

    # Check if it was the last question for the current axis
    if next_q_within_axis_idx >= num_questions_for_this_axis:
        next_q_within_axis_idx = 0
        next_axis_idx += 1

    # Update session state
    session['current_axis_index'] = next_axis_idx
    session['current_question_within_axis_index'] = next_q_within_axis_idx

    if next_axis_idx >= len(AXES_DEFINITIONS):
        print("--- Quiz finished, redirecting to summary --- ")
        return redirect(url_for('summary'))
    else:
        return redirect(url_for('quiz'))

@app.route('/summary')
def summary():
    """Display the summary page."""
    if 'answers' not in session or not session['answers']:
        flash("Brak odpowiedzi do wygenerowania podsumowania. Rozpocznij quiz ponownie.", "warning")
        return redirect(url_for('index'))

    # Generate text summary
    summary_text = generate_summary(session['answers'])

    # Generate axes data (list of dicts)
    axes_data = create_axes_data(session['answers']) # Changed function name and return type

    return render_template('summary.html',
                           summary_text=summary_text,
                           axes_data=axes_data # Pass the list directly
                           )

if __name__ == '__main__':
    # Remove debug run for production deployment
    # app.run(debug=True) 
    # Consider adding a simple print or placeholder if needed for local execution structure
    pass # Or keep the block empty 
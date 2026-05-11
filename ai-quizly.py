from flask import Flask, render_template, send_file, request, redirect, url_for, session, flash, jsonify, send_from_directory
import nltk
from nltk.corpus import stopwords
from text_utils import clean_text, fuzzy_match
import copy, re, random, requests, sys, os, json, socket, threading, webbrowser
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
from pydub import AudioSegment
import io
from openai import OpenAI

random.seed()

# 1. Define the path helper first
def resource_path(relative_path):
    import os, sys
    base = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base, relative_path)

# 2. Initialize the app with the paths
app = Flask(__name__, 
            template_folder=resource_path("templates"), 
            static_folder=resource_path("static"))

# 3. Set the security key
app.secret_key = "supersecret"
            
def resource_path(relative_path):
    """ Get absolute path to resource for dev and Render """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
    
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        if '__file__' in globals():
            base_path = os.path.abspath(os.path.dirname(__file__))
        else:
            base_path = os.getcwd()
    return os.path.join(base_path, relative_path)

def get_questions_history_path():
    return resource_path("questions_history.json")

def load_questions_history():
    path = get_questions_history_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"asked_questions": [], "used_subtopics": {}}
    return {"asked_questions": [], "used_subtopics": {}}

def save_questions_history(history):
    path = get_questions_history_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"⚠️ Failed to save questions history: {e}")

def add_to_history(question_text, category, subtopic, subsubtopic, difficulty):
    history = load_questions_history()
    history["asked_questions"].append({
        "question": question_text,
        "category": category,
        "subtopic": subtopic,
        "subsubtopic": subsubtopic,
        "difficulty": difficulty,
        "timestamp": datetime.now().isoformat()
    })
    
    # Keep only last 150 questions
    if len(history["asked_questions"]) > 150:
        history["asked_questions"] = history["asked_questions"][-150:]
    
    save_questions_history(history)
    save_questions_history(history)

def last_half(text):
    """Return the last half of a question's words."""
    words = text.split()
    if len(words) < 4:
        return text  # too short to split meaningfully
    midpoint = len(words) // 2
    return " ".join(words[midpoint:])

def is_duplicate_fuzzy(question_text, category, threshold=0.75):
    """Check if a question is similar to any previously asked question IN THE SAME CATEGORY,
       using only the last 35% of the text for comparison."""
    from difflib import SequenceMatcher

    history = load_questions_history()

    def last_35(text):
        words = clean_text(text).split()
        if len(words) < 6:
            return " ".join(words)
        cut = int(len(words) * 0.65)  # keep last 35%
        return " ".join(words[cut:])

    current_clean = last_35(question_text).lower()

    for historical_q in history.get("asked_questions", []):
        if historical_q.get("category") != category:
            continue

        historical_clean = last_35(historical_q["question"]).lower()

        # Optional: prevent false positives when lengths differ a lot
        if abs(len(current_clean) - len(historical_clean)) > 50:
            continue

        similarity = SequenceMatcher(None, current_clean, historical_clean).ratio()

        if similarity >= threshold:
            print(f"⚠️ DUPLICATE CAUGHT (similarity: {similarity:.2f}): {question_text[:50]}...")
            return True

    print(f"DEBUG: No duplicates found in {category} category")
    return False
            
def get_used_subtopics_for_category(category):
    history = load_questions_history()
    used = history.get("used_subtopics", {}).get(category, [])
    return used

def mark_subtopic_as_used(category, subtopic, subsubtopic):
    history = load_questions_history()
    if "used_subtopics" not in history:
        history["used_subtopics"] = {}
    if category not in history["used_subtopics"]:
        history["used_subtopics"][category] = []
    pair = f"{subtopic}|{subsubtopic}"
    if pair not in history["used_subtopics"][category]:
        history["used_subtopics"][category].append(pair)
    save_questions_history(history)

def reset_used_subtopics_for_category(category):
    history = load_questions_history()
    if "used_subtopics" in history and category in history["used_subtopics"]:
        history["used_subtopics"][category] = []
        save_questions_history(history)

def get_next_unused_subtopic(category):
    pairs = get_subtopic_pairs(category)
    if not pairs:
        return None, None
    used_subtopics = get_used_subtopics_for_category(category)
    for sub, subsub in pairs:
        pair = f"{sub}|{subsub}"
        if pair not in used_subtopics:
            return sub, subsub
    reset_used_subtopics_for_category(category)
    if pairs:
        return pairs[0][0], pairs[0][1]
    return None, None

FALLBACK_QUESTIONS_POOL = [
    {
        "question": "What is the first step in any home repair project?",
        "options": [
            {"letter": "A", "text": "Assess the problem"},
            {"letter": "B", "text": "Buy all tools"},
            {"letter": "C", "text": "Call a professional"},
            {"letter": "D", "text": "Start repairs immediately"}
        ],
        "correct_answer": "A",
        "question_type": "multiple_choice",
        "points": 1
    },
    {
        "question": "Before starting any electrical work, what should you always do?",
        "options": [
            {"letter": "A", "text": "Turn off the power at the breaker"},
            {"letter": "B", "text": "Wear rubber gloves"},
            {"letter": "C", "text": "Call your electrician"},
            {"letter": "D", "text": "Test with a voltmeter first"}
        ],
        "correct_answer": "A",
        "question_type": "multiple_choice",
        "points": 1
    },
    {
        "question": "What is the most important safety tool for any home repair?",
        "options": [
            {"letter": "A", "text": "A hammer"},
            {"letter": "B", "text": "Proper protective equipment"},
            {"letter": "C", "text": "A cell phone"},
            {"letter": "D", "text": "A power drill"}
        ],
        "correct_answer": "B",
        "question_type": "multiple_choice",
        "points": 1
    }
]

fallback_index = 0

def create_fallback_question():
    global fallback_index
    question_data = FALLBACK_QUESTIONS_POOL[fallback_index % len(FALLBACK_QUESTIONS_POOL)]
    fallback_index += 1
    return [(question_data["question"], question_data["options"], question_data["correct_answer"], question_data["question_type"], question_data["points"])]

if os.path.exists('/opt/render'):
    nltk_data_dir = '/opt/render/nltk_data'
else:
    nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')

if not os.path.exists(os.path.join(nltk_data_dir, 'corpora', 'wordnet')):
    nltk.download('stopwords', download_dir=nltk_data_dir)
    nltk.download('punkt', download_dir=nltk_data_dir)
    nltk.download('wordnet', download_dir=nltk_data_dir)

nltk.data.path.append(nltk_data_dir)

def get_openai_api_key():
    key_path = resource_path("openai_key.txt")
    try:
        with open(key_path, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
            if api_key:
                return api_key
    except FileNotFoundError:
        pass
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key
    print("⚠️ No API key found! Set OPENAI_API_KEY environment variable or create openai_key.txt")
    return None

# Insert this right after app = Flask(__name__)
print("\n--- STARTING SERVER ---")
print("Registered Routes:")
for rule in app.url_map.iter_rules():
    print(f"URL: {rule.endpoint} --> Path: {rule}")
print("-----------------------\n")

@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(resource_path("static/images"), filename)

@app.route("/categories/<path:filename>")
def serve_category(filename):
    return send_from_directory(resource_path("static/categories"), filename)

@app.route("/sounds/<path:filename>")
def serve_sound(filename):
    return send_from_directory(resource_path("static/sounds"), filename)

def get_all_categories():
    with open(resource_path("topics.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.keys())

def get_category_hierarchy():
    with open(resource_path("topics.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    hierarchy = defaultdict(lambda: defaultdict(list))
    for cat, subs in data.items():
        for sub, subsubs in subs.items():
            for subsub in subsubs:
                hierarchy[cat][sub].append(subsub)
    return {cat: dict(subs) for cat, subs in hierarchy.items()}

def get_subtopics_for_category(category):
    with open(resource_path("topics.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get(category, {}).keys())

def get_subtopic_pairs(category):
    with open(resource_path("topics.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    pairs = []
    for sub, subsubs in data.get(category, {}).items():
        for subsub in subsubs:
            pairs.append((sub, subsub))
    return pairs

def generate_prompt(category, difficulty, subtopic, subsubtopic, question_type):
    """Generate a focused prompt with strong category enforcement and single-question requirement."""

    # ---------------- MULTIPLE CHOICE ----------------
    if question_type == "multiple_choice":
        prompt = f"""
Generate ONE SINGLE {difficulty}-level {category} repair multiple-choice question.

CRITICAL CATEGORY RULES:
- The question MUST be specific to the category: {category}
- It MUST involve the subtopic: {subtopic}
- It MUST involve the detail: {subsubtopic}
- GENERAL home-repair questions are NOT allowed.
- The scenario must ONLY make sense within this category.

QUALITY RULES:
- Include a realistic symptom, condition, or situation.
- Avoid generic questions like "What is the first step in any repair?"
- Avoid vague or overly simple questions.
- Avoid repeating the same structure (not always "What is...").
- Keep the question under 45 words.
- Keep each option under 12 words.
- Only ONE option may be correct.
- Do NOT include explanations or commentary.
- Do NOT generate multiple questions.

FORMAT EXACTLY:

Question: [Your question here]

A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]

Correct Answer: [A/B/C/D]
"""

    # ---------------- YES / NO ----------------
    elif question_type == "yes_no":
        prompt = f"""
Generate ONE SINGLE {difficulty}-level {category} repair YES/NO question.

CRITICAL CATEGORY RULES:
- The question MUST be specific to the category: {category}
- It MUST involve the subtopic: {subtopic}
- It MUST involve the detail: {subsubtopic}
- GENERAL home-repair questions are NOT allowed.
- The scenario must ONLY make sense within this category.

QUALITY RULES:
- Include a realistic symptom, condition, or situation.
- Avoid generic questions like "Is it safe to start repairs?"
- Avoid vague or overly simple questions.
- Avoid repeating the same structure (not always "Can...").
- Keep the question under 45 words.
- Only YES or NO may be correct.
- Do NOT include commentary or explanations.
- Do NOT generate multiple questions.

FORMAT EXACTLY:

Question: [Your yes/no question here]

Correct Answer: [YES or NO]
"""

    return prompt

def validate_question_structure(qa, question_type):
    if question_type == "multiple_choice":
        required_fields = ["question", "options", "correct_answer"]
        has_fields = all(field in qa for field in required_fields)
        if has_fields:
            is_valid_answer = qa["correct_answer"].upper() in ["A", "B", "C", "D"]
            has_4_options = len(qa.get("options", [])) == 4
            return has_4_options and is_valid_answer
        return False
    elif question_type == "yes_no":
        required_fields = ["question", "correct_answer"]
        has_fields = all(field in qa for field in required_fields)
        if has_fields:
            is_valid_answer = qa["correct_answer"].upper() in ["YES", "NO"]
            return is_valid_answer
        return False
    return False

def shuffle_multiple_choice_options(qa):
    """Shuffle multiple choice options and update correct answer letter."""
    if not qa.get("options"):
        return qa
    
    options = qa.get("options", [])
    correct_answer = qa.get("correct_answer", "").strip().upper()
    
    if len(options) != 4 or not correct_answer:
        return qa
    
    # Detect if correct answer is MULTIPLE letters (e.g., "A and C")
    multi_letters = re.findall(r"[A-D]", correct_answer)
    is_multi = len(multi_letters) > 1

    # Find the correct option text (single-answer case)
    correct_option_text = None
    if not is_multi:
        for option in options:
            if option["letter"] == correct_answer:
                correct_option_text = option["text"]
                break
    
    # Shuffle the options
    shuffled_options = options.copy()
    random.shuffle(shuffled_options)
    
    # Update letters to A, B, C, D
    letter_map = ["A", "B", "C", "D"]
    for i, option in enumerate(shuffled_options):
        option["letter"] = letter_map[i]

    # ⭐ CASE 1 — MULTIPLE CORRECT ANSWERS (e.g., "A and C") ⭐
    if is_multi:
        # Build a clean label like "Both A and C"
        label = "Both " + " and ".join(multi_letters)

        # Create the combined option
        combined_option = {"letter": "D", "text": label}

        # Replace option D with the combined option
        shuffled_options[-1] = combined_option

        # Correct answer is now D
        qa["correct_answer"] = "D"
        qa["options"] = shuffled_options
        return qa

    # ⭐ CASE 2 — "All of the above" is the correct answer ⭐
    if correct_option_text and correct_option_text.lower() == "all of the above":
        # Find where it ended up after shuffle
        for i, opt in enumerate(shuffled_options):
            if opt["text"].lower() == "all of the above":
                idx = i
                break
        
        # Move it to the end
        all_opt = shuffled_options.pop(idx)
        shuffled_options.append(all_opt)

        # Reassign letters again
        for i, opt in enumerate(shuffled_options):
            opt["letter"] = letter_map[i]

        # Correct answer is now D
        qa["correct_answer"] = "D"
        qa["options"] = shuffled_options
        return qa

    # ⭐ CASE 3 — Normal single-letter correct answer ⭐
    for option in shuffled_options:
        if option["text"] == correct_option_text:
            qa["correct_answer"] = option["letter"]
            break
    
    qa["options"] = shuffled_options
    return qa

    
def parse_multiple_choice_response(response_text):
    """Parse multiple-choice question from OpenAI response"""
    result = {"question": "", "options": [], "correct_answer": ""}
    lines = response_text.strip().split("\\n")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.lower().startswith("question:"):
            result["question"] = line.split(":", 1)[1].strip()
            
        elif line and line[0] in "ABCD" and ")" in line:
            # Format: "A) Option text"
            option_letter = line[0]
            option_text = line.split(")", 1)[1].strip()
            result["options"].append({"letter": option_letter, "text": option_text})
            
        elif line.lower().startswith("correct answer:"):
            answer_text = line.split(":", 1)[1].strip()
            # Extract just the letter from responses like "B) Joint compound"
            if answer_text and answer_text[0] in "ABCD":
                result["correct_answer"] = answer_text[0].upper()

    return result if result["question"] and len(result["options"]) == 4 and result["correct_answer"] else None
    
def parse_yes_no_response(response_text):
    """Parse yes/no question from OpenAI response"""
    result = {"question": "", "correct_answer": "", "explanation": ""}
    lines = response_text.strip().split("\\n")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.lower().startswith("question:"):
            result["question"] = line.split(":", 1)[1].strip()
            
        elif line.lower().startswith("correct answer:"):
            answer_text = line.split(":", 1)[1].strip().upper()
            # Extract just YES or NO from responses like "Yes" or "Yes, water lines can..."
            if "YES" in answer_text:
                result["correct_answer"] = "YES"
            elif "NO" in answer_text:
                result["correct_answer"] = "NO"
                
        elif line.lower().startswith("explanation:"):
            result["explanation"] = line.split(":", 1)[1].strip()

    return result if result["question"] and result["correct_answer"] else None
    
def parse_openai_response_enhanced(response_text, question_type):
    """Parse OpenAI response cleanly for both MC and YES/NO formats."""
    print("DEBUG: THIS IS THE NEW FILE")
    try:
        lines = [line.strip() for line in response_text.strip().split("\n") if line.strip()]

        # ---------------------------------------------------------
        # MULTIPLE CHOICE PARSING
        # ---------------------------------------------------------
        if question_type == "multiple_choice":
            result = {"question": "", "options": [], "correct_answer": ""}

            for line in lines:
                lower = line.lower()

                if lower.startswith("question:"):
                    result["question"] = line.split(":", 1)[1].strip()

                elif lower.startswith(("a)", "b)", "c)", "d)")):
                    letter = line[0].upper()
                    text = line[2:].strip()
                    result["options"].append({"letter": letter, "text": text})

                elif lower.startswith("correct answer:"):
                    ans = line.split(":", 1)[1].strip().upper()
                    if ans and ans[0] in "ABCD":
                        result["correct_answer"] = ans[0]

            if result["question"] and len(result["options"]) == 4 and result["correct_answer"]:
                return result
            return None

        # ---------------------------------------------------------
        # YES / NO PARSING
        # ---------------------------------------------------------
        elif question_type == "yes_no":
            result = {"question": "", "correct_answer": ""}

            for line in lines:
                lower = line.lower()

                if lower.startswith("question:"):
                    result["question"] = line.split(":", 1)[1].strip()

                elif lower.startswith("correct answer:"):
                    ans = line.split(":", 1)[1].strip().upper()
                    if "YES" in ans:
                        result["correct_answer"] = "YES"
                    elif "NO" in ans:
                        result["correct_answer"] = "NO"

            if result["question"] and result["correct_answer"]:
                return result
            return None

    except Exception as e:
        print(f"ERROR in parse_openai_response_enhanced: {e}")
        return None

    return None


def check_answer(user_answer, correct_answer, question_type):
    user_answer = user_answer.strip().upper()
    correct_answer = correct_answer.strip().upper()
    if user_answer == correct_answer:
        return (True, 1)
    else:
        return (False, 0)

def get_openai_question_answer(prompt: str, question_type: str = "multiple_choice", temperature: float = 0.8) -> dict:
    """
    Unified OpenAI caller. 
    Supports dynamic temperature for variety and robust multi-format parsing.
    """
    api_key = get_openai_api_key()
    if not api_key:
        print("⚠️ ERROR: No OpenAI API key found!")
        return None

    # Use a slightly longer timeout for complex 'experienced' scenarios
    client = OpenAI(api_key=api_key, timeout=10.0)

    try:
        print(f"DEBUG: Calling OpenAI (Model: gpt-3.5-turbo, Temp: {temperature})")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=temperature,
            top_p=0.9
        )

        text = response.choices[0].message.content.strip()
        print(f"\n--- AI RAW RESPONSE ---\n{text}\n-----------------------")

        # --- Manual Parsing Logic ---
        result = {"question": "", "options": [], "correct_answer": ""}
        lines = text.splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 1. Parse Question
            if line.lower().startswith("question:"):
                result["question"] = line.split(":", 1)[1].strip()
            
            # 2. Parse Multiple Choice Options (e.g., "A) Option text")
            elif len(line) > 2 and line[0].upper() in "ABCD" and (line[1] == ")" or line[1] == "."):
                option_text = line[2:].strip()
                result["options"].append({"letter": line[0].upper(), "text": option_text})
            
            # 3. Parse Correct Answer
            elif line.lower().startswith("correct answer:"):
                ans_part = line.split(":", 1)[1].strip().upper()
                
                if question_type == "yes_no":
                    if "YES" in ans_part: result["correct_answer"] = "YES"
                    elif "NO" in ans_part: result["correct_answer"] = "NO"
                else:
                    # Look for the letter A, B, C, or D at the start of the answer string
                    match = re.search(r"[A-D]", ans_part)
                    if match:
                        result["correct_answer"] = match.group(0)

        # --- Validation ---
        if not result["question"]:
            print("DEBUG: Parsing failed - No question text found.")
            return None

        if question_type == "multiple_choice" and len(result["options"]) < 2:
            print("DEBUG: Parsing failed - Not enough options for MC.")
            return None

        if not result["correct_answer"]:
            print("DEBUG: Parsing failed - No correct answer found.")
            return None

        return result

    except Exception as e:
        print(f"⚠️ OpenAI Call Error: {e}")
        return None
        
def generate_question(category, difficulty, subtopic=None, subsubtopic=None, source="openai"):
    """
    SINGLE UNIFIED GENERATOR
    Levels: 'beginner', 'experienced'
    Features: 0.70 Fuzzy Threshold, 0.8 Temperature, Subtopic Rotation
    """
    # 1. Subtopic rotation
    if not subtopic or not subsubtopic:
        subtopic, subsubtopic = get_next_unused_subtopic(category)

    if not subtopic or not subsubtopic:
        pairs = get_subtopic_pairs(category)
        subtopic, subsubtopic = random.choice(pairs) if pairs else ("general", "general")

    # 2. Difficulty Logic
    last_qt = session.get("last_question_type")
    if difficulty == "beginner":
        # Beginners get 20% Yes/No, but never twice in a row
        if last_qt == "yes_no":
            question_type = "multiple_choice"
        else:
            question_type = "yes_no" if random.random() < 0.2 else "multiple_choice"
    else:
        # Experienced is ALWAYS Multiple Choice
        question_type = "multiple_choice"

    # 3. Build Prompt
    base_prompt = f"""
Generate ONE clear, practical home-repair question about {category}, 
focused on the subtopic "{subtopic}" and detail "{subsubtopic}".
GENERAL REQUIREMENTS:
- Use natural homeowner-friendly language. Specific and realistic.
- Do NOT include explanations, reasoning, or extra commentary.
"""

    if question_type == "yes_no":
        base_prompt += "\nFormat:\nQuestion: [question]\nCorrect Answer: YES or NO"
    else:
        if difficulty == "experienced":
            base_prompt += """
EXPERIENCED REQUIREMENTS:
- Require multi-step reasoning/diagnosis.
- Include a scenario with specific symptoms or constraints.
- Correct answer should not be obvious; rule out simple safety steps.
"""
        base_prompt += "\nMULTIPLE-CHOICE FORMAT:\nQuestion: [question]\nA) [opt]\nB) [opt]\nC) [opt]\nD) [opt]\nCorrect Answer: [A/B/C/D]"

    # 4. Generation Loop
    attempts = 0
    while attempts < 3:
        # We pass 0.8 temperature here
        qa = get_openai_question_answer(base_prompt.strip(), question_type, temperature=0.8)

        if not qa or "correct_answer" not in qa:
            attempts += 1
            continue

        # --- Normalize Answer ---
        raw_ans = str(qa["correct_answer"]).strip().upper()
        if question_type == "multiple_choice":
            match = re.match(r"^[A-D]", raw_ans)
            if not match: 
                attempts += 1
                continue
            qa["correct_answer"] = match.group(0)
        else:
            if raw_ans not in ("YES", "NO"):
                attempts += 1
                continue
            qa["correct_answer"] = raw_ans

        # --- Fuzzy Check (0.70) ---
        if is_duplicate_fuzzy(qa["question"], category, threshold=0.70):
            print(f"DEBUG: Similarity too high in {category}, retrying...")
            attempts += 1
            continue

        # --- Success ---
        if validate_question_structure(qa, question_type):
            if question_type == "multiple_choice":
                qa = shuffle_multiple_choice_options(qa)

            add_to_history(qa["question"], category, subtopic, subsubtopic, difficulty)
            mark_subtopic_as_used(category, subtopic, subsubtopic)
            session["last_question_type"] = question_type
            
            return [(qa["question"], qa.get("options", []), qa["correct_answer"], question_type, 1)]
        
        attempts += 1

    return create_fallback_question()
    
def get_openai_expanded_answer(question: str, correct_answer: str = None) -> dict:
    api_key = get_openai_api_key()
    if not api_key:
        return {"text": "⚠️ Missing API key", "youtube_url": None}
    client = OpenAI(api_key=api_key, timeout=3.0)
    try:
        answer_context = ""
        if correct_answer:
            answer_context = f"\\n\\nThe correct answer to this question is: {correct_answer}\\n\\nPlease explain why this answer is correct."
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": f"Provide a brief explanation for: {question}{answer_context} Keep it to 5-6 sentences max (~625 characters)."}],
            max_tokens=400,
            temperature=0.7
        )
        expanded_text = response.choices[0].message.content.strip()
        if len(expanded_text) > 1125:
            expanded_text = expanded_text[:1122] + "..."
        
        return {"text": expanded_text, "youtube_url": None}
    except Exception as e:
        print("⚠️ Expanded AI call failed:", e)
        return {"text": "Error retrieving expanded info.", "youtube_url": None}
        
@app.route("/learn_more")
def learn_more():
    # --- Extract parameters from URL ---
    question = request.args.get("question", "").strip()
    answer_letter = request.args.get("answer_letter", "").strip().upper()
    answer_text = request.args.get("answer_text", "").strip()
    next_url = request.args.get("next", "/game")
    print("DEBUG RAW ARGS:", request.args)
    # --- Validate question ---
    if not question or len(question) < 5:
        print("DEBUG: Learn More missing or malformed question")
        return render_template(
            "learn_more.html",
            question="(No question available)",
            answer=answer_letter,
            explanation="No additional information is available for this question.",
            next_url=next_url
        )

    # --- Validate answer letter ---
    valid_letters = ["A", "B", "C", "D", "YES", "NO"]
    if answer_letter not in valid_letters:
        print(f"DEBUG: Learn More received invalid answer letter: {answer_letter}")
        return render_template(
            "learn_more.html",
            question=question,
            answer=answer_letter,
            explanation="No additional information is available for this answer.",
            next_url=next_url
        )

    # --- Validate full answer text ---
    if not answer_text or len(answer_text) < 3:
        print(f"DEBUG: Learn More missing answer text for letter {answer_letter}")
        return render_template(
            "learn_more.html",
            question=question,
            answer=answer_letter,
            explanation="Additional details are not available because the answer text was not provided.",
            next_url=next_url
        )

    # --- Build explanation prompt ---
    prompt = f"""
Provide a clear, accurate, homeowner-friendly explanation for the correct answer to this question.

Question:
{question}

Correct Answer:
{answer_text}

REQUIREMENTS:
- Explain WHY this answer is correct.
- Keep the explanation practical and easy to understand.
- Do NOT mention the other answer choices.
- Do NOT restate the question.
- Do NOT add extra steps or unrelated advice.
- 3–6 sentences max.
"""

    # --- Generate explanation ---
    try:
        client = OpenAI(api_key=get_openai_api_key(), timeout=6.0)

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=180,
            temperature=0.4
        )

        explanation = response.choices[0].message.content.strip()

    except Exception as e:
        print(f"DEBUG: Learn More generation failed: {e}")
        explanation = "Additional details are not available right now."

    # --- Render page ---
    return render_template(
        "learn_more.html",
        question=question,
        answer=answer_letter,
        explanation=explanation,
        next_url=next_url
    )

def has_every_team_answered_once():
    teams = session.get("teams", [])
    team_progress = session.get("team_progress", {})
    for team in teams:
        team_name = team["name"]
        if team_progress.get(team_name, 0) < 1:
            return False
    return True

# --- GAME SELECTION / LANDING PAGES ---
# 1. THE LANDING PAGE (The "Front Door")
@app.route('/')
def index():
    # This renders the new welcome.html with the two cards
    return render_template('welcome.html')

# 2. THE FIXIT WELCOME (The Intro/Instructions)
@app.route('/fixit_intro')
def fixit_intro():
    # This renders index.html (your original FixIt welcome text)
    return render_template('index.html')

# 3. THE FIXIT GAME LOGIC (The Team Setup)
@app.route("/fixit", methods=["GET", "POST"])
def fixit_setup():
    # If the user is just arriving from the Hub (GET)
    if request.method == "GET":
        num_teams = request.args.get('num_teams', 1, type=int)
        return render_template("team_setup.html", 
                               num_teams=num_teams, 
                               categories=get_all_categories())

    # If the user is submitting the form (POST)
    session.clear()
    num_teams = int(request.form.get("num_teams", 1))
    session["num_teams"] = num_teams
    session["team_names"] = [""] * num_teams
    return redirect(url_for("team_setup"))

# 4. THE MUSIC RECALL GAME
@app.route('/music_recall')
def music_recall():
    return render_template('music_recall.html')

# --- HELPER FUNCTIONS ---
def choose_category_no_recent(categories, history, window=6):
    recent = history[-window:]
    available = [c for c in categories if c not in recent]

    if not available:
        available = categories  # fallback if all were used

    choice = random.choice(available)

    # update history
    history.append(choice)
    if len(history) > window:
        history[:] = history[-window:]

    return choice

@app.route("/team_setup", methods=["GET", "POST"])
def team_setup():
    if request.method == "POST":
        # 1. Get basic game settings
        try:
            num_teams = int(request.args.get("num_teams", 1))
            points_to_win = int(request.form.get("points_to_win", 5))
        except ValueError:
            num_teams = 1
            points_to_win = 5

        teams = []
        
        # 2. Process each team
        for i in range(num_teams):
            team_name = request.form.get(f"team_{i}", f"Team {i+1}")
            # This 'category' variable must remain "random" if chosen from dropdown
            category = request.form.get(f"category_{i}", "random")
            difficulty = request.form.get(f"difficulty_{i}", "beginner")

            # We DO NOT pick a category here. We save the 'instruction' (random or specific)
            teams.append({
                "name": team_name,
                "category": category,
                "difficulty": difficulty
            })

        # 3. Initialize/Reset Session for a clean game
        session.clear() # Optional: clears old game data entirely
        session["teams"] = teams
        session["points_to_win"] = points_to_win
        session["current_team_index"] = 0
        session["team_scores"] = {t["name"]: 0 for t in teams}
        session["team_progress"] = {t["name"]: 0 for t in teams}
        
        # CRITICAL: Initialize the history list as empty for the new game
        session["recent_categories"] = []
        
        return redirect(url_for("game"))

    # GET Request: Display the setup page
    categories = get_all_categories()
    num_teams = int(request.args.get("num_teams", 1))
    return render_template("team_setup.html", 
                           categories=categories, 
                           num_teams=num_teams)
                           
@app.route("/get_subtopics/<category>")
def get_subtopics(category):
    try:
        subtopics = get_subtopics_for_category(category)
        return jsonify(subtopics or [])
    except Exception as e:
        print(f"Error fetching subtopics for {category}: {e}")
        return jsonify([]), 500

@app.route("/game")
def game():
    if "last_feedback" in session:
        fb = session.pop("last_feedback")
        return render_template("feedback.html", **fb)

    # If a winner has been declared, redirect to winner screen
    if session.get("winner"):
        return redirect(url_for("winner_then_prompt"))

    teams = session.get("teams", [])
    current_team_index = session.get("current_team_index", 0)

    # Safety check: no teams → go back to setup
    if not teams or current_team_index >= len(teams):
        return redirect(url_for("team_setup"))

    team = teams[current_team_index]
    team_name = team["name"]
    difficulty = team["difficulty"]
    
    # 1. Determine the category mode (Static name or "random")
    assigned_category = team["category"] 

    # 2. Logic to pick the category for THIS specific turn
    if assigned_category == "random":
        recent = session.get("recent_categories", [])
        fallback_categories = get_all_categories()
        
        # Pick a fresh category for THIS turn
        current_turn_category = choose_category_no_recent(
            fallback_categories,
            recent,
            window=6
        )
        # Save the updated history back to the session
        session["recent_categories"] = recent
        session.modified = True 
    else:
        # User chose a specific category or used Roll Dice
        current_turn_category = assigned_category

    # 3. Generate a new AI question using the turn-specific category
    qa = generate_question(current_turn_category, difficulty, source="openai")

    if not qa or not qa[0]:
        flash(f"No AI question generated for {team_name} in category {current_turn_category}.")
        session["current_team_index"] = (current_team_index + 1) % len(teams)
        return redirect(url_for("game"))

    # Unpack the question data
    question, options, correct_answer, question_type, points = qa[0]

    # 4. Update session (Ensure we use current_turn_category everywhere here)
    import copy
    session.update({
        "current_team_index": current_team_index,
        "current_category": current_turn_category, 
        "current_question_text": question,
        "current_options": copy.deepcopy(options),
        "current_correct_answer": correct_answer,
        "current_question_type": question_type,
        "current_points": points,
        "last_feedback": "",
        "difficulty": difficulty,
    })

    # 5. Render template with the specific chosen category
    return render_template(
        "game.html",
        current_team=team_name,
        category=current_turn_category, # This shows "History" instead of "random"
        question=question,
        options=session["current_options"],
        question_type=question_type,
        current_answer=correct_answer,
        feedback=""
    )
    
@app.route("/winner-then-prompt")
def winner_then_prompt():
    raw_scores = session.get("team_scores", {})
    display_scores = {name: int(total) for name, total in raw_scores.items()}
    return render_template("winner.html", winner=session.get("winner"), teams=session.get("teams", []), team_scores=display_scores, team_progress=session.get("team_progress", {}))

@app.route("/submit-answer", methods=["POST"])
def submit_answer():
    user_answer = request.form.get("user_answer", "").strip()
    current_team_index = session.get("current_team_index", 0)
    teams = session.get("teams", [])
    team_scores = session.get("team_scores", {})
    team_progress = session.get("team_progress", {})

    if not teams or current_team_index >= len(teams):
        return redirect(url_for("team_setup"))

    current_team = teams[current_team_index]
    team_name = current_team["name"]
    category = current_team["category"]
    difficulty = current_team["difficulty"]
    progress = team_progress.get(team_name, 0)

    session["last_answer_team_name"] = team_name
    question_text = session.get("current_question_text", "")
    correct_answer = session.get("current_correct_answer", "")
    question_type = session.get("current_question_type", "multiple_choice")
    options = session.get("current_options", [])
    is_correct, points_awarded = check_answer(user_answer, correct_answer, question_type)
    team_scores[team_name] = int(team_scores.get(team_name, 0)) + points_awarded

    session["team_scores"] = team_scores
    current_total = int(team_scores.get(team_name, 0))
    points_to_win = int(session.get("points_to_win", 5))

    session["last_feedback"] = {
        "team": team_name,
        "question": question_text,
        "options": options,
        "question_type": question_type,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "points_awarded": points_awarded,
        "current_total": current_total
    }

    sorted_scores = dict(sorted(team_scores.items(), key=lambda x: x[1], reverse=True))
    session["last_feedback"]["leaderboard"] = sorted_scores

    return redirect(url_for("game"))

@app.route("/feedback")
def feedback():
    last_feedback = session.get("last_feedback", {})
    team_scores = session.get("team_scores", {})
    sorted_scores = dict(sorted(team_scores.items(), key=lambda x: x[1], reverse=True))
    leading_team = max(sorted_scores, key=sorted_scores.get) if sorted_scores else None
    return render_template("feedback.html", team=last_feedback.get("team", ""), question=last_feedback.get("question", ""), options=last_feedback.get("options", []), question_type=last_feedback.get("question_type", "multiple_choice"), user_answer=last_feedback.get("user_answer", ""), correct_answer=last_feedback.get("correct_answer", ""), is_correct=last_feedback.get("is_correct", False), points_awarded=last_feedback.get("points_awarded", 0), leaderboard=last_feedback.get("leaderboard", sorted_scores), leading_team=leading_team, current_category=session.get("current_category", "general"))

@app.route("/next_turn", methods=["POST"])
def next_turn():
    team_scores = session.get("team_scores", {})
    teams = session.get("teams", [])
    current_team_index = session.get("current_team_index", 0)
    team_progress = session.get("team_progress", {})
    current_round = session.get("current_round", 1)

    if session.get("winner"):
        return redirect(url_for("winner_then_prompt"))

    session.pop("show_trivia", None)

    # Increment progress for the team that just answered
    last_team_name = session.get("last_answer_team_name")
    if last_team_name:
        team_progress[last_team_name] = team_progress.get(last_team_name, 0) + 1
        session["team_progress"] = team_progress

    # Move to next team
    current_team_index = (current_team_index + 1) % len(teams) if teams else 0

    # Check if we've completed a full round
    round_complete = (current_team_index == 0)
    if round_complete:
        current_round += 1
        session["current_round"] = current_round

        points_to_win = int(session.get("points_to_win", 5))
        winner = next(
            (t["name"] for t in teams if int(team_scores.get(t["name"], 0)) >= points_to_win),
            None
        )
        if winner:
            session["winner"] = winner
            session["team_scores"] = team_scores
            return redirect(url_for("winner_then_prompt"))

    session["current_team_index"] = current_team_index

    if not teams or current_team_index >= len(teams):
        return redirect(url_for("team_setup"))

    # Generate next question
    current_team = teams[current_team_index]
    team_name = current_team["name"]
    category = current_team["category"]
    difficulty = current_team["difficulty"]

    # NEW: handle "each question a different category"
    if category == "random":
        recent = session.setdefault("recent_categories", [])
        fallback_categories = get_all_categories()
        category = choose_category_no_recent(
            fallback_categories,
            recent,
            window=6
        )
        session["recent_categories"] = recent

    subtopics = get_subtopics_for_category(category)
    subtopic = random.choice(subtopics) if subtopics else None

    # Always OpenAI now — no branching
    qa = generate_question(category, difficulty, source="openai", subtopic=subtopic)
    if not qa or not qa[0]:
        flash(f"No AI question generated for {team_name}.")
        return redirect(url_for("game"))

    question, options, correct_answer, question_type, points = qa[0]

    # Deep copy options to prevent mutation
    import copy
    session.update({
        "current_question_text": question,
        "current_options": copy.deepcopy(options),
        "current_correct_answer": correct_answer,
        "current_question_type": question_type,
        "current_points": points,
        "current_team_index": current_team_index,
        "current_category": category,
        "current_subtopic": subtopic,
        "difficulty": difficulty,
        "team_progress": team_progress
    })

    return redirect(url_for("game"))

@app.route("/results")
def results():
    winner = session.get("winner", "Unknown Team")
    scores = session.get("team_scores", {})
    feedback = session.pop('last_feedback', None)
    return render_template("results.html", scores=scores, winner=winner, feedback=feedback)

@app.route("/restart_game")
def restart_game():
    session.pop("team_names", None)
    session.pop("team_difficulties", None)
    session.pop("team_order", None)
    session.pop("teams", None)
    session.pop("categories", None)
    session.pop("questions", None)
    session.pop("team_scores", None)
    session.pop("team_progress", None)
    session.pop("current_team_index", None)
    session.pop("question_bank", None)
    session.pop("scores", None)
    session.pop("leaderboard", None)
    session.pop("feedback", None)
    session.pop("last_feedback", None)
    session.pop("points_to_win", None)
    session.pop("used_questions", None)
    session.pop("winner", None)
    session.pop("current_question", None)
    session.pop("current_answer", None)
    session.pop("difficulty", None)
    session.pop("current_category", None)
    return redirect(url_for("team_setup"))

@app.route("/play_again_prompt")
def play_again_prompt():
    winner = session.get("winner", "Unknown Team")
    return render_template("play_again.html", winner=winner)

@app.route("/end_game")
def end_game():
    team_scores = session.get("team_scores", {})
    teams = session.get("teams", [])
    team_progress = session.get("team_progress", {})
    if not team_scores:
        winner = "No teams"
    else:
        winner = max(team_scores, key=team_scores.get)
    session['winner'] = winner
    session['teams'] = teams
    session['team_scores'] = team_scores
    session['team_progress'] = team_progress
    return redirect(url_for("winner_then_prompt"))

@app.route("/get_trivia")
def get_trivia():
    category = request.args.get("category", "general")

    # --- Decide once per turn whether trivia should appear ---
    if "show_trivia" not in session:
        # Adjust probability here (0.35 = 35% chance)
        session["show_trivia"] = (random.random() < 0.35)

    # If trivia is disabled for this turn, return None immediately
    if not session["show_trivia"]:
        return jsonify({"trivia": None}), 200

    # --- If trivia IS enabled, generate it ---
    api_key = get_openai_api_key()
    if not api_key:
        return jsonify({"trivia": "💡 Keep learning about home maintenance!"}), 200

    try:
        client = OpenAI(api_key=api_key, timeout=4.0)

        category_descriptions = {
            "electrical": "electrical work, wiring, circuits, breakers, outlets, safety",
            "plumbing": "plumbing, pipes, fixtures, water pressure, leaks, drainage",
            "interior": "interior design, drywall, painting, flooring, walls, windows",
            "exterior": "exterior work, roofing, siding, gutters, landscaping, decks",
            "appliances": "appliances, refrigerators, ovens, washing machines, maintenance",
            "hvac": "heating, ventilation, air conditioning, thermostats, filters",
            "yard": "yard work, gardening, lawn care, landscaping, outdoor maintenance",
            "tools": "tools, equipment, tool maintenance, safety gear, tool selection",
            "services": "home services, contractor tips, hiring professionals, budgeting",
            "general": "home repair, DIY, maintenance, home improvement"
        }

        category_focus = category_descriptions.get(category, category_descriptions["general"])

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{
                "role": "user",
                "content": (
                    f"Generate ONE short, fun, and unique home DIY trivia fact about {category_focus}. "
                    "Make it 1–2 sentences max, interesting, and actionable. "
                    "Start with a fun relevant emoji. "
                    "IMPORTANT: Make sure this is a UNIQUE fact that hasn't been shared before. "
                    "Just give me the trivia fact, nothing else."
                )
            }],
            max_tokens=100,
            temperature=0.9
        )

        trivia = response.choices[0].message.content.strip()
        return jsonify({"trivia": trivia}), 200

    except Exception as e:
        print(f"⚠️ Trivia generation failed: {e}")
        return jsonify({"trivia": "💡 Keep learning about home maintenance!"}), 200

@app.route("/goodbye")
def goodbye():
    session.clear()
    return render_template("goodbye.html")

# --- ---------------------------------------------------------------
# --- BEGIN MUSIC GAME SECTION ---
# --- ---------------------------------------------------------------
@app.route('/get_music_turn', methods=['POST'])
def get_music_turn():
    # Use request.get_json() to handle the incoming JavaScript data
    data = request.get_json()
    genre = data.get('genre', 'Country')

    # Initialize history in the session if it doesn't exist
    if 'history' not in session:
        session['history'] = []

    # Try up to 3 times to get a unique song
    for _ in range(3):
        song_data = generate_music_challenge(genre)
        song_title = song_data.get('Song', '').strip().lower()

        # Only return the song if it's NOT in our recent history
        if song_title not in session['history']:
            history = session['history']
            history.append(song_title)
            session['history'] = history[-10:] # Keep the last 10 songs
            session.modified = True
            return jsonify(song_data)

    # If it still repeats after 3 tries, return it anyway to avoid an infinite loop
    return jsonify(song_data)
  
# --- MUSIC RECALL ENGINE ---
def generate_music_challenge(genre):
    api_key = get_openai_api_key()
    if not api_key:
        return {"Beat": "API Key Missing", "Lowdown": "Check your configuration."}
        
    client = OpenAI(api_key=api_key)

    # --- ENHANCED RANDOMNESS PROMPT ---
    prompt = f"""
    You are a music historian. Generate ONE high-quality music trivia challenge for a {genre} song.
    
    CHRONOLOGICAL VARIETY: 
    - Randomly select a song from any year between 1950 and 2024. 
    - Do NOT always pick the #1 hit; rotate between legendary classics, hidden gems, and era-defining tracks.
    
    SPECIAL INSTRUCTIONS FOR GENRES:
    - If {genre} is Classical: 'Lyric' should be a description of a famous melody or a movement nickname.
    - If {genre} is Jazz: 'Lyric' can be a description of a famous solo or vocal line.
    - If {genre} is Latin: Focus on the specific dance rhythm (e.g.,Cha Cha, Songo, Montuno).

    IMPORTANT: All fields (Beat, Lowdown, Lyric, Song, Artist) MUST refer to the SAME single work.
    
    FORMAT EXACTLY:
    Beat: [Technical rhythmic description]
    Lowdown: [Insider fact]
    Lyric: [Iconic line or melody description]
    Song: [Title]
    Artist: [Composer or Artist]
    Year: [Year]
    """
    try:
        # --- TEMPERATURE INCREASED TO 0.9 ---
        # 0.4 makes it repetitive; 0.9 forces it to be more creative and random.
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9  
        )
        text = response.choices[0].message.content.strip()
        
        # Robust Parsing using Regular Expressions
        data = {}
        patterns = {
            "Beat": r"Beat:\s*(.*)",
            "Lowdown": r"Lowdown:\s*(.*)",
            "Lyric": r"Lyric:\s*(.*)",
            "Song": r"Song:\s*(.*)",
            "Artist": r"Artist:\s*(.*)",
            "Year": r"Year:\s*(.*)"
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            data[key] = match.group(1).strip() if match else f"No {key} found."
            
        return data

    except Exception as e:
        print(f"Music Engine Error: {e}")
        return {"Beat": "Connection Error", "Lowdown": "The signal was interrupted."}

@app.route('/get_audio_clue/<song_name>/<artist_name>')
def get_audio_clue(song_name, artist_name):
    # 1. Prepare the search for iTunes
    search_url = "https://itunes.apple.com/search"
    query = f"{song_name} {artist_name}"
    
    params = {
        "term": query,
        "limit": 1,        # We only want the best match
        "media": "music"
    }
    
    try:
        # 2. Ask iTunes for the song data
        response = requests.get(search_url, params=params)
        data = response.json()
        
        if data.get("resultCount", 0) > 0:
            # 3. Get the 30-second preview URL from the first result
            preview_url = data["results"][0]["previewUrl"]
            
            # 4. Redirect the browser to play this audio stream
            return redirect(preview_url)
        else:
            return "Audio snippet not found for this track.", 404
            
    except Exception as e:
        print(f"Connection Error: {e}")
        return "Internal Server Error", 500
    
@app.route("/music_recall")
def music_recall_route():
    print("DEBUG: User is attempting to load /music_recall")
    return render_template("music_recall.html")

if __name__ == "__main__":
    import webbrowser
    # This specifically looks for Chrome. If it fails, it defaults to your system default.
    url = "http://127.0.0.1:5000"
    try:
        # Try to open in Chrome specifically
        webbrowser.get('chrome').open(url)
    except:
        # Fallback to default browser if Chrome isn't found in the path
        webbrowser.open(url)
        
    app.run(
        host="0.0.0.0", port=5000, 
        debug=False, use_reloader=False)

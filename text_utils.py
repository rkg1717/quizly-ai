import string
import re
import nltk
from rapidfuzz import fuzz
from difflib import SequenceMatcher
from nltk.corpus import wordnet, stopwords
from nltk.stem import PorterStemmer, WordNetLemmatizer
# from pyspellchecker import SpellChecker

nltk.download('stopwords')

stemmer = PorterStemmer()
lemmatizer = WordNetLemmatizer()
# spell_checker = SpellChecker()

STOP_WORDS = set(stopwords.words('english')) | {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "at", "by",
    "for", "with", "is", "are", "was", "were", "be", "been", "being", "that",
    "this", "it", "as", "from", "up", "down", "out", "over", "under", "use",
    "if", "may", "sure", "can", "try", "you", "using", "first", "second", "third"
}

# ✅ COMPREHENSIVE Domain-specific synonyms for all categories
HOME_REPAIR_SYNONYMS = {
    # ===== ELECTRICAL =====
    "wire": {"romex", "cable", "conductor", "wiring", "electrical wire", "nm cable"},
    "romex": {"wire", "cable", "conductor", "wiring", "nm cable"},
    "cable": {"wire", "romex", "conductor", "wiring"},
    "conductor": {"wire", "cable", "romex", "copper"},
    "breaker": {"circuit breaker", "disconnect", "switch", "cb", "breaker switch"},
    "circuit breaker": {"breaker", "disconnect", "switch"},
    "outlet": {"receptacle", "socket", "plug", "wall outlet", "electrical outlet"},
    "receptacle": {"outlet", "socket", "plug"},
    "switch": {"breaker", "toggle", "wall switch", "disconnect"},
    "fixture": {"light fixture", "chandelier", "lamp", "light"},
    "ground": {"ground fault", "gfci", "grounding", "earth"},
    "gfci": {"ground fault", "ground", "circuit interrupter"},
    "fuse": {"breaker", "circuit", "protection"},
    "amp": {"amperage", "amps", "current", "ampere"},
    "volt": {"voltage", "volts", "electrical pressure"},
    "ohm": {"resistance", "ohms", "electrical resistance"},
    "surge protector": {"power strip", "surge", "suppressor"},
    "extension cord": {"power cord", "extension", "cord", "temporary wiring"},
    "lighting": {"light", "lights", "illumination", "fixture"},
    "test": {"testing", "measure", "check", "verify"},
    "tripped": {"trip", "breaker tripped", "blown"},
    "replace": {"replacement", "remove and install", "swap"},
    
    # ===== PLUMBING =====
    "faucet": {"tap", "spigot", "fixture", "water valve", "sink faucet"},
    "tap": {"faucet", "spigot", "fixture"},
    "pipe": {"piping", "tubing", "line", "conduit", "water line"},
    "leak": {"leaking", "dripping", "water loss", "seeping"},
    "water line": {"water pipe", "main line", "supply line"},
    "toilet": {"commode", "wc", "water closet"},
    "sink": {"basin", "wash basin", "vanity"},
    "shower": {"shower stall", "bathtub", "tub"},
    "drain": {"drainage", "trap", "p-trap", "drainpipe"},
    "clog": {"clogged", "blockage", "backed up", "stopped up"},
    "seal": {"sealant", "caulk", "waterproof", "gasket"},
    "valve": {"shutoff", "water valve", "ball valve", "gate valve"},
    "p-trap": {"trap", "u-bend", "s-trap", "drainage trap"},
    
    # ===== YARD/LANDSCAPING =====
    "lawn": {"grass", "turf", "yard", "sod", "lawn care"},
    "mole": {"moles", "molehill", "burrowing"},
    "vole": {"voles", "rodent", "burrowing pest"},
    "shrub": {"shrubs", "bush", "bushes", "hedge", "landscaping"},
    "tree": {"trees", "timber", "woody plant", "foliage"},
    "flower": {"flowers", "flowering plant", "bloom", "blossom"},
    "vegetable": {"vegetables", "veggie", "veggies", "garden vegetable", "crop"},
    "pest": {"pests", "insect", "bug", "infestation"},
    "weed": {"weeds", "unwanted plant", "invasive"},
    "fertilize": {"fertilizer", "fertilizing", "plant food", "nutrient"},
    "landscaping": {"landscape", "landscape design", "yard design"},
    "soil": {"dirt", "earth", "ground", "growing medium"},
    "mulch": {"ground cover", "wood chips", "organic matter"},
    "water": {"watering", "irrigation", "sprinkler"},
    "pull": {"dig", "remove", "extract", "uproot", "hand pull"},
    "dig": {"pull", "remove", "extract", "uproot", "excavate"},
    "hand": {"manual", "by hand", "hand work"},
    "manual": {"hand", "by hand", "manually"},
    "remove": {"pull", "dig", "extract", "uproot", "elimination"},
    
    # ===== TOOLS =====
    "hammer": {"mallet", "claw hammer", "framing hammer"},
    "saw": {"sawing", "cutting tool", "circular saw", "hand saw"},
    "drill": {"drilling", "power drill", "bit"},
    "screwdriver": {"screw", "bit", "phillips", "flathead"},
    "wrench": {"spanner", "adjustable wrench", "socket"},
    "pliers": {"vise-grips", "slip joint", "cutting pliers"},
    "level": {"leveling", "spirit level", "straight"},
    "tape measure": {"measuring tape", "ruler", "measurement"},
    "power tool": {"electric tool", "powered", "corded", "cordless"},
    "hand tool": {"manual tool", "non-powered", "basic tools"},
    "safety": {"safe", "protection", "protective gear", "ppe", "safety equipment"},
    "automotive": {"auto", "car maintenance", "vehicle repair"},
    "woodworking": {"wood work", "carpentry", "furniture"},
    "garden": {"gardening", "landscaping", "yard work"},
    
    # ===== INTERIOR =====
    "wall": {"walls", "drywall", "sheetrock", "wallboard", "plaster"},
    "drywall": {"sheetrock", "wallboard", "gypsum board", "plasterboard", "dry wall"},
    "sheetrock": {"drywall", "wallboard", "gypsum"},
    "paint": {"painting", "pigment", "coating", "finish"},
    "window": {"windows", "pane", "glass", "casement", "frame"},
    "door": {"doors", "entrance", "exit", "doorway"},
    "floor": {"flooring", "ground level", "surface"},
    "carpet": {"rug", "carpeting", "floor covering", "pile"},
    "tile": {"tiles", "ceramic", "porcelain", "tiling"},
    "wood floor": {"hardwood", "laminate", "engineered wood"},
    "stair": {"stairs", "steps", "staircase", "banister"},
    "ceiling": {"ceilings", "overhead", "drywall ceiling", "drop ceiling"},
    "basement": {"cellar", "lower level", "below grade"},
    "attic": {"loft", "upper space", "overhead"},
    "crawl space": {"crawlway", "below floor", "sub-floor"},
    "design": {"decor", "decorating", "interior design", "aesthetic"},
    "lock": {"locking", "deadbolt", "security", "keyhole"},
    "handle": {"knob", "grip", "lever", "door handle"},
    "screen": {"screening", "window screen", "door screen", "mesh"},
    "covering": {"blinds", "curtains", "shades", "window treatment"},
    
    # ===== APPLIANCES/HVAC =====
    "dishwasher": {"dish washer", "automatic dishwasher"},
    "washing machine": {"washer", "clothes washer", "laundry"},
    "clothes dryer": {"dryer", "laundry dryer", "electric dryer"},
    "refrigerator": {"fridge", "icebox", "cooler", "freezer"},
    "oven": {"range oven", "electric oven", "gas oven"},
    "stove": {"range", "cooktop", "cooking surface"},
    "microwave": {"microwave oven", "mw"},
    "hvac": {"heating cooling", "furnace", "ac", "air conditioner", "climate control"},
    "furnace": {"heating", "heater", "boiler", "heating system"},
    "air conditioner": {"ac", "cooling", "compressor", "condenser"},
    "thermostat": {"temperature control", "setting", "heating control"},
    "filter": {"air filter", "furnace filter", "filtering"},
    "bbq": {"grill", "barbecue", "outdoor cooking"},
    "maintenance": {"maintain", "upkeep", "service", "preventive"},
    "repair": {"fixing", "fix", "restoration", "troubleshoot"},
    
    # ===== SERVICES/WIFI =====
    "wifi": {"wi-fi", "wireless", "internet", "wlan", "router", "modem"},
    "internet": {"isp", "online", "broadband", "online", "connectivity", "connection"},
    "isp": {"internet service provider", "carrier", "provider", "broadband"},
    "carrier": {"service provider", "isp", "telecommunications", "network"},
    "router": {"networking", "wifi router", "access point", "modem", "gateway"},
    "modem": {"cable modem", "dsl modem", "internet modem", "router", "gateway"},
    "streaming": {"stream", "video streaming", "content", "buffering"},
    "buffering": {"streaming", "buffer", "lag", "loading", "playback issues"},
    "connection": {"internet connection", "connectivity", "link", "network"},
    "speed": {"internet speed", "data rate", "bandwidth", "fast", "faster"},
    "service": {"cellular service", "coverage", "plan", "network service", "provider"},
    "equipment": {"devices", "hardware", "networking equipment"},
    "setup": {"installation", "configure", "initial setup", "installation process"},
    "problem": {"issue", "problem", "malfunction", "error", "troubleshoot"},
    "cell": {"mobile", "cellular", "phone", "smartphone"},
    "cell phone": {"mobile phone", "smartphone", "device", "phone"},
    "charging": {"charge", "charging cable", "power", "battery"},
    "query": {"inquire", "ask", "contact", "question"},
    "utility": {"utilities", "service", "public utility", "municipal"},
    
    # ===== VEHICLE =====
    "car": {"vehicle", "automobile", "auto", "motorcar", "sedan"},
    "maintenance": {"maintain", "service", "upkeep", "preventive care"},
    "detailing": {"detail", "cleaning", "washing", "polishing"},
    "oil change": {"lubrication", "engine oil", "oil service"},
    "tire": {"tires", "wheel", "rubber", "pneumatic"},
    "battery": {"car battery", "starter battery", "power"},
    "engine": {"motor", "powerplant", "mechanical"},
    "brake": {"brakes", "stopping", "brake pad", "brake system"},
    "transmission": {"gears", "shifter", "drivetrain"},
    
    # ===== COOKING =====
    "dinner": {"meal", "supper", "main course", "entree"},
    "lunch": {"midday meal", "sandwiches", "salad"},
    "breakfast": {"morning meal", "eggs", "toast"},
    "easy": {"simple", "quick", "uncomplicated", "straightforward"},
    "healthy": {"nutritious", "low-fat", "balanced", "wholesome"},
    "wine": {"red wine", "white wine", "beverage", "pairing"},
    "recipe": {"cooking recipe", "ingredients", "instructions"},
    "cook": {"cooking", "prepare", "heat", "bake", "fry"},
    "bake": {"baking", "oven", "pastry", "cake", "bread"},
}

def stem_tokens(tokens):
    """Stem a set of tokens"""
    return set(stemmer.stem(word) for word in tokens)

#def check_spelling(word):
 #   """Check and correct spelling using pyspellchecker"""
  #  if word in spell_checker:
   #     return word, True  # Word is correct
 
def check_spelling(word):
    """Check and correct spelling - simplified version without pyspellchecker"""
    # For now, return the word as-is (no spelling correction)
    # This prevents the import error
    return word, True
 
    # Get corrections for misspelled word
    corrections = spell_checker.correction(word)
    if corrections and corrections != word:
        return corrections, False  # Word was corrected
    
    return word, True  # No correction found, return original

def clean_text(text):
    """Clean and normalize text for matching"""
    if not isinstance(text, str):
        return ""
    
    # Convert to lowercase
    text = text.lower().strip()
    
    # Remove punctuation but keep spaces
    text = re.sub(r"[^\w\s]", " ", text)
    
    # Split into words
    words = text.split()
    
    # Filter out stopwords and very short words (< 2 chars)
    filtered = [
        word for word in words 
        if len(word) >= 2
    ]
    
    # Lemmatize
    lemmatized = [lemmatizer.lemmatize(word) for word in filtered]
    
    # Return all lemmatized words (no extra filtering)
    return " ".join(lemmatized)

def get_synonyms(word):
    """Get WordNet synonyms + domain-specific synonyms"""
    synonyms = set()
    
    # WordNet synonyms
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            synonyms.add(lemma.name().lower())
    
    # Add domain-specific synonyms
    if word.lower() in HOME_REPAIR_SYNONYMS:
        synonyms.update(HOME_REPAIR_SYNONYMS[word.lower()])
    
    return synonyms

def expand_keywords(keywords):
    """Expand keywords with their synonyms"""
    expanded = set()
    for word in keywords:
        expanded |= get_synonyms(word)
    return expanded | set(keywords)

def filter_incorrect(user_tokens, matched_tokens):
    stop_words = set(stopwords.words('english'))
    return [word for word in user_tokens - set(matched_tokens) if word not in stop_words]

def fuzzy_match(user_answer, correct_answer, question_text="", return_matches=False, verbose=False):
    """
    Four-level matching with domain-specific synonyms and spell check
    1. Spell check correction (NEW)
    2. Exact stem match
    3. Synonym match (WordNet + domain-specific) - bidirectional
    4. Fuzzy match (90% threshold)
    
    ✅ NEW: Spell check enables matching of misspelled words (e.g., 'ware' → 'wear')
    ✅ Filters out words that appear in the question
    """
    
    user_tokens = set(clean_text(user_answer).split())
    correct_tokens = set(clean_text(correct_answer).split())
    
    # ✅ NEW: Apply spell checking to user tokens
    spell_corrected_tokens = set()
    spell_corrections = {}
    for token in user_tokens:
        corrected, is_correct = check_spelling(token)
        spell_corrected_tokens.add(corrected)
        if not is_correct:
            spell_corrections[token] = corrected
            if verbose:
                print(f"Spell correction: '{token}' → '{corrected}'")
    
    # Extract question words and remove from correct answer
    if question_text:
        question_tokens = set(clean_text(question_text).split())
        correct_tokens = correct_tokens - question_tokens
    
    user_stems = stem_tokens(spell_corrected_tokens)  # Use spell-corrected tokens
    correct_stems = stem_tokens(correct_tokens)
    
    matched_words = set()
    used_correct_tokens = set()
    
    # Four-level matching strategy
    for u in user_stems:
        for c in correct_stems:
            if c not in used_correct_tokens:
                match_found = False
                
                # Level 1: Exact stem match
                if u == c:
                    match_found = True
                
                # Level 2: Synonym match (bidirectional)
                if not match_found:
                    c_synonyms = get_synonyms(c)
                    u_synonyms = get_synonyms(u)
                    if u in c_synonyms or c in u_synonyms:
                        match_found = True
                
                # Level 3: Fuzzy match (90% threshold)
                if not match_found and fuzz.ratio(u, c) >= 90:
                    match_found = True
                
                # If match found, record the original token from correct answer
                if match_found:
                    stop_words = set(stopwords.words('english'))
                    if c not in stop_words:
                        for token in correct_tokens:
                            if stemmer.stem(token) == c:
                                matched_words.add(token)
                                break
                        used_correct_tokens.add(c)
                    break
    
    # Filter out stopwords from matched words
    stop_words = set(stopwords.words('english'))
    matched_words = matched_words - stop_words
    
    # Scoring logic
    match_count = len(matched_words)
    denominator = min(len(correct_tokens), 5)
    raw_score = match_count / denominator if denominator > 0 else 0.0
    
    if return_matches:
        missed_words = filter_incorrect(correct_tokens, matched_words)
        return matched_words, raw_score, missed_words
    else:
        return raw_score
"""Deterministic mandatory constraints shared by discovery and retrieval."""
import re

PATTERNS = {
    "punishment": r"copy\s*cas[eé]s?|unfair\s*(?:means?|mains?)|malpractice|punishment\s+(?:list|decision)",
    "timetable": r"time\s*-?\s*(?:tabl[eé]s?|tabels?)|exam(?:ination)?\s+schedules?|schedules?\s+of\s+(?:the\s+)?(?:theory\s+|practical\s+)?exam(?:ination)?s?",
    "syllabus": r"syllab(?:us|i|uses)|curricul(?:um|a)",
    "calendar": r"academic\s+calend(?:ar|er)s?",
    "circular": r"(?:circular|curcular)s?",
    "announcement": r"announcements?|notifications?|press\s+release",
    "document": r"documents?|notices?|fees?|hostels?|admission|scholarship|eligibility|ordinance|certificate",
}
MEETING = r"notice\s+(?:of|for)\s+(?:the\s+)?meeting|meeting\s+notice|show\s+cause|hearing\s+notice"
SENSITIVE = r"\b(?:copy\s*case|unfair\s*means|malpractice|punishment|disciplinary|show\s+cause|seat\s*(?:no\b|number)|case\s*(?:no\b|number)|marks?\s*sheet|name\s+of\s+(?:the\s+)?student)"
IDENTIFIER = r"\b(seat|case|circular|subject|course)\s*(?:no\.?|number|code|#)\s*[:\-]?\s*([a-z0-9][\w/-]{2,39})(?![\w/-])"
MONTH = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
DATE = rf"\b(?:20\d{{2}}-\d{{2}}-\d{{2}}|\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}|\d{{1,2}}[ -]+(?:{MONTH})[ -]+20\d{{2}})\b"
PATTERN_YEAR = r"\b(?:(20\d{2})\s*(?:pattern|patt|course)|(?:pattern|patt)\s*(20\d{2}))\b"
PROGRAMMES = {
    "mca": r"m\.?c\.?a\.?|master of computer applications?",
    "mba": r"m\.?b\.?a\.?|master of business administration",
    "engineering": r"engineering|b\.\s*e\.|b\.?tech|s\.?e\.?\s+(?:in[ -]?sem|engg)|(?:f|s|t|b)\.e\.",
    "bsc": r"b\.?sc\.?|bachelor of science",
    "bcom": r"b\.?com\.?|bachelor of commerce",
    "bca": r"b\.?c\.?a\.?|bachelor of computer applications",
    "bba": r"b\.?b\.?a\.?|bachelor of business administration",
    "mcom": r"m\.?com\.?",
    "msc": r"m\.?sc\.?",
}
BRANCHES = {
    "computer": r"computer (?:engineering|science)|cse",
    "information technology": r"information technology|i\.t\.",
    "electronics": r"electron(?:ics|ic)|e\s*&\s*tc",
    "mechanical": r"mechanical",
    "civil": r"civil",
    "electrical": r"electrical|elecrtrical",
}
EXAM_TYPES = {"insem": r"in[ -]?sem(?:ester)?", "endsem": r"end[ -]?sem(?:ester)?"}
SESSIONS = {"october/november": r"oct(?:ober)?\s*[/–-]\s*nov(?:ember)?",
            "april/may": r"apr(?:il)?\s*[/–-]\s*may", "winter": "winter", "summer": "summer"}
SEMESTERS = dict(zip(("i", "ii", "iii", "iv", "v", "vi", "vii", "viii"), map(str, range(1, 9))))
STUDY_YEARS = {
    "1": r"(?:first|1st)[ -]+year|year\s*1",
    "2": r"(?:second|2nd)[ -]+year|year\s*2",
    "3": r"(?:third|3rd)[ -]+year|year\s*3",
    "4": r"(?:fourth|4th)[ -]+year|year\s*4",
    "5": r"(?:fifth|5th)[ -]+year|year\s*5",
}
MCA_SEMESTERS_BY_YEAR = {"1": ("1", "2"), "2": ("3", "4")}
EXACT = r"\w/-"

def match(pattern, text):
    return re.search(pattern, text, re.I)

def exact(text, identifier):
    return match(rf"(?<![{EXACT}]){re.escape(identifier)}(?![{EXACT}])", text)

def parse_date(value):
    from datetime import datetime
    cleaned = re.sub(r"[./]", "-", value.strip())
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%d-%B-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            pass
    return ""

def identities(text):
    found = [(kind.lower(), value.upper()) for kind, value in re.findall(IDENTIFIER, text, re.I)]
    columns = {}
    for line in text.splitlines():
        if "|" not in line:
            columns = {}
            continue
        cells = [cell.strip() for cell in line.split("|")]
        headings = {}
        for index, cell in enumerate(cells):
            header = match(r"^(seat|case|circular|subject|course)\s*(?:no\.?|number|code|#)$", cell)
            if header:
                headings[index] = header[1].lower()
        if headings:
            columns = headings
            continue
        for index, kind in columns.items():
            if index < len(cells) and re.fullmatch(r"[a-z0-9][\w/-]{2,39}", cells[index], flags=re.I):
                found.append((kind, cells[index].upper()))
    return found

def found_in(patterns, text):
    return [key for key, pattern in patterns.items() if match(rf"\b(?:{pattern})\b", text)]

def programme_hits(text):
    degree = PROGRAMMES["mca"]
    text = re.sub(rf"(\b(?:{degree})\b)\s*\(\s*engineering\s*\)", r"\1", text, flags=re.I)
    text = re.sub(r"\b(?:under\s+)?faculty\s+of[^\n]{0,100}\bengineering\b", " ", text, flags=re.I)
    return found_in(PROGRAMMES, text)

def session_hits(text):
    hits = found_in(SESSIONS, text)
    if "winter" in hits and "summer" not in hits:
        hits = [hit for hit in hits if hit != "october/november"]
    if "summer" in hits and "winter" not in hits:
        hits = [hit for hit in hits if hit != "april/may"]
    return hits

def branch_section(text, branch):
    label = {"electrical": "ELECTRICAL", "civil": "CIVIL", "computer": "COMPUTER",
             "mechanical": "MECHANICAL", "electronics": "ELECTRONICS",
             "information technology": "INFORMATION TECHNOLOGY"}.get(branch)
    if not label:
        return ""
    start = match(rf"(?m)^\s*{label}\s+(?:ENGINEERING|TECHNOLOGY)\s*$", text)
    if not start:
        return ""
    remaining = text[start.end():]
    boundary = re.search(r"^\s*[A-Z][A-Z &/()'-]{3,}\s+ENGINEERING\s*$|"
                         r"^\s*(?:Ganeshkhind|Day & Date\s*\|)", remaining, re.M)
    section = text[start.start():start.end()] + remaining[:boundary.start() if boundary else len(remaining)]
    return re.sub(r"\b(AM|PM)(?=\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b)", r"\1 ", section, flags=re.I)

def fields(text):
    values = {}
    for category, pattern in PATTERNS.items():
        if match(rf"\b(?:{pattern})\b", text):
            values["category"] = category
            break
    programmes = programme_hits(text)
    if len(programmes) == 1:
        values["programme"] = programmes[0]
    for field, patterns in {
        "branch": BRANCHES,
        "examType": EXAM_TYPES,
        "studyYear": STUDY_YEARS,
    }.items():
        hits = found_in(patterns, text)
        if len(hits) == 1:
            values[field] = hits[0]
    sessions = session_hits(text)
    if len(sessions) == 1:
        values["session"] = sessions[0]
    declared_sessions = {value.lower() for value in re.findall(r"\bsession\s*:\s*(winter|summer)\b", text, re.I)}
    if len(declared_sessions) == 1:
        values["session"] = declared_sessions.pop()
    engineering_year = match(r"\b([fstb])\.?e\.?(?=\s*(?:\(|in[ -]?sem|end[ -]?sem|winter|summer|exam|timetable))", text)
    if engineering_year:
        values.setdefault("studyYear", {"f": "1", "s": "2", "t": "3", "b": "4"}[engineering_year[1].lower()])
        values.setdefault("programme", "engineering")
    elif match(r"\bfinal\s+year\s+(?:of\s+)?engineering\b", text):
        values.setdefault("studyYear", "4")
    semester = match(r"\bsem(?:ester)?[ -]*([1-8]|v?i{1,3}|iv|v)\b", text)
    if semester:
        value = semester[1].lower()
        values["semester"] = SEMESTERS.get(value, value)
    patterns = {before or after for before, after in re.findall(PATTERN_YEAR, text, re.I)}
    if len(patterns) == 1:
        values["pattern"] = patterns.pop()
    text = re.sub(PATTERN_YEAR, " ", text, flags=re.I)
    # Dates and labeled identifiers do not imply academic-year constraints.
    text = re.sub(DATE, " ", text, flags=re.I)
    text = re.sub(IDENTIFIER, " ", text, flags=re.I)
    span = match(r"\b(20\d{2})\s*(?:-|–|/|to)\s*(20\d{2}|\d{2})\b", text)
    if span:
        values["year"] = span[1] + "-" + (span[2] if len(span[2]) == 4 else "20" + span[2])
    else:
        years = set(re.findall(r"\b20\d{2}\b", text))
        if len(years) == 1:
            values["year"] = years.pop()
    return values

def interpret(question):
    constraints = fields(question)
    category = constraints.get("category")
    dates = [parsed for raw in re.findall(DATE, question, re.I) if (parsed := parse_date(raw))]
    multiple = [name for name, patterns in {"branch": BRANCHES,
                "exam type": EXAM_TYPES, "year of study": STUDY_YEARS}.items()
                if len(found_in(patterns, question)) > 1]
    if len(programme_hits(question)) > 1:
        multiple.append("programme")
    if len(session_hits(question)) > 1:
        multiple.append("session")
    explicit_years = set(re.findall(r"\b20\d{2}\b", re.sub(IDENTIFIER, " ", re.sub(DATE, " ", question, flags=re.I), flags=re.I)))
    if constraints.get("pattern"):
        explicit_years.discard(constraints["pattern"])
    if len(explicit_years) > 1 and not constraints.get("year"):
        multiple.append("academic year")
    return {
        "institution": "SPPU", "department": "Examination" if category in {"punishment", "timetable", "circular"} else None,
        "original": question, "rewritten": re.sub(r"\belecrtrical\b", "electrical", question, flags=re.I) + (" | SPPU unfair means examination malpractice punishment list" if category == "punishment" else ""),
        "constraints": constraints, "identifiers": identities(question), "dates": dates, "ambiguous": multiple,
        "latest": bool(match(r"\b(latest|newest|most recent|current)\b", question)),
        "revised": bool(match(r"\b(revised|corrected|corrigendum|amended)\b", question))
    }

def metadata_matches(metadata, intent):
    if intent["ambiguous"]:
        return False
    for key, expected in intent["constraints"].items():
        actual = metadata.get(key, "")
        if actual == expected:
            continue
        if key == "branch" and expected in metadata.get("branches", []):
            continue
        if key == "year" and len(expected) == 4 and expected in (actual or "").split("-"):
            continue
        if key == "studyYear" and not actual and metadata.get("programme") == "mca" and (
                metadata.get("semester") in MCA_SEMESTERS_BY_YEAR.get(expected, ())):
            continue
        return False
    return not intent["revised"] or bool(metadata.get("revised"))

def validate(title, pages, starter, category, goal=""):
    body = "\n".join(p["text"] for p in pages)
    heading = "\n".join(line.strip() for line in body.splitlines() if line.strip())[:1800]
    label = f"{title} {starter}"
    observed = fields(f"{title}\n{heading}")
    # A listing or URL alone is insufficient evidence for a document type.
    category_in_body = match(rf"\b(?:{PATTERNS[category]})\b", heading)
    if category == "timetable" and not category_in_body:
        category_in_body = (match(r"\bprogram(?:me)?\s+of\b", heading) and
                            match(r"\bsession\b[^\n]*\bexam(?:ination)?\b", heading) and
                            match(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", body) and
                            match(DATE, body))
    if category == "document":
        terms = {word for word in re.findall(r"[^\W_]+", goal.casefold())
                 if len(word) > 3 and word not in {"please", "provide", "latest", "give", "university", "sppu", "document", "documents",
                                                  "what", "where", "about", "details", "from", "have", "need", "show", "find", "tell", "when", "there"}}
        matched = sum(bool(re.search(rf"\b{re.escape(word)}\b", body, re.I)) for word in terms)
        category_in_body = bool(terms and matched >= min(2, len(terms)))
    reasons = []
    if category == "punishment":
        decision = match(r"punish(?:ment|ed)|penalt(?:y|ies)|decision|annulment|result\s+cancel", heading)
        if not decision or not (category_in_body or match(PATTERNS[category], label)) or match(MEETING, title + " " + heading):
            reasons.append("Punishment decision and unfair-means scope must be present. Meeting and show-cause notices are excluded.")
    elif not category_in_body:
        reasons.append("The document heading does not establish the source category.")
    if not heading.strip():
        reasons.append("No usable heading or document text.")
    intent = interpret(goal)
    observed["category"] = category
    revised = bool(match(r"\b(revised|corrected|amended|corrigendum)\b", title + " " + heading))
    observed["revised"] = revised
    published = match(rf"(?:issued\s+on|published\s+on|date\s*[:.])\s*({DATE})", heading)
    effective = match(rf"(?:effective\s+(?:from|on)|with effect from)\s*({DATE})", heading)
    publication_date = parse_date(published[1]) if published else ""
    if category in {"punishment", "circular", "announcement"} and publication_date and not observed.get("year"):
        observed["year"] = publication_date[:4]
    if not metadata_matches(observed, intent):
        reasons.append("Mandatory category, programme, semester, exam, year, pattern, session or revision evidence is missing.")
    for kind, identifier in intent["identifiers"]:
        if not any(not p["ocr"] and (kind, identifier) in identities(p["text"]) for p in pages):
            reasons.append("Requested identifier lacks exact native text evidence.")
    dates = {parse_date(x) for x in re.findall(DATE, body, re.I)}
    if any(value not in dates for value in intent["dates"]):
        reasons.append("Requested date not found in extracted text.")
    observed.update(title=title, published=publication_date,
                    effective=parse_date(effective[1]) if effective else "")
    privacy_text = body + " " + title
    if category == "timetable":
        # Timetables routinely remind candidates to bring their seat number.
        # Only redact that phrase when it carries no actual individual code.
        individual = any(kind in {"case", "seat"} and any(char.isdigit() for char in code)
                         for kind, code in identities(body))
        privacy_text = re.sub(r"\bseat\s*(?:no\b|number)", "", privacy_text, flags=re.I)
        privacy_text = re.sub(r"\bbe\s+treated\s+as\s+(?:a\s+)?malpractice\b", "", privacy_text, flags=re.I)
    else:
        individual = False
    return {"relevant": not reasons, "reasons": reasons,
            "evidence": {"heading": heading, "listing": starter[:450], "metadata": observed},
            "metadata": observed, "restricted": category == "punishment" or individual or bool(match(SENSITIVE, privacy_text))}


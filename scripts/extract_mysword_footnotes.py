"""
Extract footnotes from a MySword .bbl.mybible database and merge them
into the KJV source JSON.

The MySword format stores footnotes inline in the Scripture text using
<RF>...<Rf> tags. This script extracts those footnotes, determines the
catch word (the word the note attaches to), classifies the note type,
and merges them into KJV.json.

By default it only adds NT footnotes (books 40-66) since the OT footnotes
were already extracted from the SWORD module. Use --all to replace all
footnotes from the MySword source instead.

Usage:
    python extract_mysword_footnotes.py
    python extract_mysword_footnotes.py --all
"""

import sys
import os
import json
import re
import sqlite3
import argparse


# MySword book number (1-66) -> project book name
BOOK_NAMES = {
    1: "Genesis", 2: "Exodus", 3: "Leviticus", 4: "Numbers",
    5: "Deuteronomy", 6: "Joshua", 7: "Judges", 8: "Ruth",
    9: "I Samuel", 10: "II Samuel", 11: "I Kings", 12: "II Kings",
    13: "I Chronicles", 14: "II Chronicles", 15: "Ezra", 16: "Nehemiah",
    17: "Esther", 18: "Job", 19: "Psalms", 20: "Proverbs",
    21: "Ecclesiastes", 22: "Song of Solomon", 23: "Isaiah",
    24: "Jeremiah", 25: "Lamentations", 26: "Ezekiel", 27: "Daniel",
    28: "Hosea", 29: "Joel", 30: "Amos", 31: "Obadiah", 32: "Jonah",
    33: "Micah", 34: "Nahum", 35: "Habakkuk", 36: "Zephaniah",
    37: "Haggai", 38: "Zechariah", 39: "Malachi",
    40: "Matthew", 41: "Mark", 42: "Luke", 43: "John", 44: "Acts",
    45: "Romans", 46: "I Corinthians", 47: "II Corinthians",
    48: "Galatians", 49: "Ephesians", 50: "Philippians",
    51: "Colossians", 52: "I Thessalonians", 53: "II Thessalonians",
    54: "I Timothy", 55: "II Timothy", 56: "Titus", 57: "Philemon",
    58: "Hebrews", 59: "James", 60: "I Peter", 61: "II Peter",
    62: "I John", 63: "II John", 64: "III John", 65: "Jude",
    66: "Revelation of John",
}


def extract_catch_word(text_before_note):
    """
    Extract the catch word from the text immediately before a <RF> tag.

    The text may contain Strong's number tags (<WH1234>, <WG5678>),
    red-letter tags (<FR>...<Fr>), OT quote tags (<FO>...<Fo>),
    italic tags (<FI>...<Fi>), and punctuation.

    We want the last English word(s) before the footnote marker.
    """
    # Strip all MySword markup tags
    clean = re.sub(r'<W[HG]\d+>', '', text_before_note)  # Strong's numbers
    clean = re.sub(r'</?F[ROIA]>', '', clean)  # Formatting tags (FR, FO, FI, FA)
    clean = re.sub(r'</?Fr>', '', clean)
    clean = re.sub(r'</?Fo>', '', clean)
    clean = re.sub(r'</?Fi>', '', clean)
    clean = re.sub(r'</?Fa>', '', clean)
    clean = re.sub(r'<CM>', '', clean)  # Carriage marks
    clean = re.sub(r'¶\s*', '', clean)  # Pilcrow
    clean = clean.strip()

    # Remove trailing punctuation
    clean = clean.rstrip(':;,.')

    if not clean:
        return ""

    # Get the last word (or last few words for multi-word catch phrases)
    # Usually just the last word
    words = clean.split()
    if words:
        return words[-1]
    return ""


def classify_note_type(note_text):
    """
    Classify the note as literal, alternate, or mixed based on its content.

    - literal: Hebrew/Greek literal translations ("Heb. ...", "Gr. ...")
    - alternate: Alternative English readings ("Or, ...")
    - mixed: Contains both types of information
    """
    has_literal = False
    has_alternate = False

    text_lower = note_text.lower()

    # Check for literal translation markers
    if any(marker in text_lower for marker in [
        'heb.', 'gr.', 'chald.', 'greek',
        'the word in the original',
        'that is,',
    ]):
        has_literal = True

    # Check for alternate reading markers
    if any(marker in text_lower for marker in [
        'or,', 'or ',
        'some read,', 'some copies read',
    ]):
        has_alternate = True

    if has_literal and has_alternate:
        return "mixed"
    elif has_literal:
        return "literal"
    elif has_alternate:
        return "alternate"
    else:
        # Default: if it's explaining meaning, treat as literal;
        # otherwise alternate
        return "alternate"


def clean_note_text(raw_note):
    """
    Clean the raw note text from inside <RF>...<Rf> tags.

    Removes HTML-like formatting tags but preserves the text content.
    """
    text = raw_note
    # Remove <i>...</i> tags but keep content
    text = re.sub(r'</?i>', '', text)
    # Remove <b>...</b> tags but keep content
    text = re.sub(r'</?b>', '', text)
    # Remove any other HTML-like tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&c', '&c')
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove trailing period if present (we'll let the consumer decide formatting)
    # Actually, keep punctuation as-is for faithfulness to the source
    return text


def extract_footnotes_from_mysword(db_path, nt_only=True):
    """
    Extract footnotes from a MySword .bbl.mybible SQLite database.

    Returns a dict mapping (book_name, chapter, verse) -> [footnote, ...]
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    min_book = 40 if nt_only else 1

    cursor.execute(
        "SELECT Book, Chapter, Verse, Scripture FROM Bible "
        "WHERE Book >= ? AND Scripture LIKE '%<RF>%' "
        "ORDER BY Book, Chapter, Verse",
        (min_book,)
    )

    footnotes = {}
    total_notes = 0

    for book_num, chapter, verse, scripture in cursor:
        book_name = BOOK_NAMES.get(book_num)
        if not book_name:
            print(f"  Warning: Unknown book number {book_num}, skipping")
            continue

        # Find all <RF>...<Rf> pairs and the text before each
        # We split the scripture at each <RF> to get the context before each note
        parts = re.split(r'(<RF>.*?<Rf>)', scripture)

        text_so_far = ""
        for part in parts:
            note_match = re.match(r'<RF>(.*?)<Rf>', part)
            if note_match:
                raw_note = note_match.group(1)
                catch_word = extract_catch_word(text_so_far)
                note_text = clean_note_text(raw_note)
                note_type = classify_note_type(note_text)

                key = (book_name, chapter, verse)
                if key not in footnotes:
                    footnotes[key] = []

                footnotes[key].append({
                    "catch_word": catch_word,
                    "note_text": note_text,
                    "note_type": note_type,
                })
                total_notes += 1
            else:
                text_so_far = part  # Update context for next note's catch word

    conn.close()

    testament = "NT" if nt_only else "OT+NT"
    print(f"  Extracted {total_notes} {testament} footnotes from {len(footnotes)} verses")
    return footnotes


def merge_footnotes_into_json(json_path, new_footnotes, nt_only=True):
    """
    Merge extracted footnotes into the KJV source JSON.

    If nt_only=True, preserves existing OT footnotes and adds NT ones.
    If nt_only=False, replaces all footnotes.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    nt_book_names = set(BOOK_NAMES[i] for i in range(40, 67))

    # Add/update inline footnotes on verse objects
    verses_updated = 0
    for book in data['books']:
        book_name = book['name']

        # If NT-only mode, skip OT books (leave their existing footnotes)
        if nt_only and book_name not in nt_book_names:
            continue

        for chapter in book['chapters']:
            ch_num = chapter['chapter']
            for verse in chapter['verses']:
                v_num = verse['verse']
                key = (book_name, ch_num, v_num)

                if key in new_footnotes:
                    verse['footnotes'] = new_footnotes[key]
                    verses_updated += 1
                elif not nt_only:
                    # In full-replace mode, remove footnotes from verses
                    # that don't have any in the new source
                    verse.pop('footnotes', None)

    # Rebuild the flat top-level footnotes array
    flat_footnotes = []
    footnote_id = 1
    for book in data['books']:
        book_name = book['name']
        for chapter in book['chapters']:
            ch_num = chapter['chapter']
            for verse in chapter['verses']:
                v_num = verse['verse']
                if 'footnotes' in verse:
                    for fn in verse['footnotes']:
                        flat_footnotes.append({
                            "id": footnote_id,
                            "book": book_name,
                            "chapter": ch_num,
                            "verse": v_num,
                            "catch_word": fn['catch_word'],
                            "note_text": fn['note_text'],
                            "note_type": fn['note_type'],
                        })
                        footnote_id += 1

    data['footnotes'] = flat_footnotes

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"  Updated {verses_updated} verses with inline footnotes")
    print(f"  Total footnotes in JSON: {len(flat_footnotes)}")
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Extract KJV footnotes from a MySword .bbl.mybible database"
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Replace ALL footnotes (OT+NT) from MySword source, '
             'instead of only adding NT footnotes'
    )
    parser.add_argument(
        '--db', type=str, default=None,
        help='Path to the MySword .bbl.mybible file '
             '(default: sword/akjvpce.bbl.mybible)'
    )
    args = parser.parse_args()

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    db_path = args.db or os.path.join(base_dir, 'sword', 'akjvpce.bbl.mybible')
    json_path = os.path.join(base_dir, 'sources', 'en', 'KJV', 'KJV.json')

    if not os.path.exists(db_path):
        print(f"Error: MySword database not found at {db_path}")
        sys.exit(1)

    if not os.path.exists(json_path):
        print(f"Error: Source JSON not found at {json_path}")
        sys.exit(1)

    nt_only = not args.all

    if nt_only:
        print(f"Extracting NT footnotes from {db_path}...")
    else:
        print(f"Extracting ALL footnotes from {db_path}...")

    footnotes = extract_footnotes_from_mysword(db_path, nt_only=nt_only)

    print(f"\nMerging footnotes into {json_path}...")
    merge_footnotes_into_json(json_path, footnotes, nt_only=nt_only)

    if nt_only:
        print("\nDone! KJV source JSON now includes NT footnotes from MySword.")
    else:
        print("\nDone! KJV source JSON footnotes fully replaced from MySword.")


if __name__ == "__main__":
    main()

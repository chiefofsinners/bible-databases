"""
Extract footnotes from a SWORD module and add them to the source JSON.

This script parses the raw OSIS markup from a SWORD module to extract
footnote data (marginal notes) and writes them into the translation's
source JSON under a top-level "footnotes" key.

Usage:
    python extract_sword_footnotes.py

By default it processes the KJV module at sources/en/KJV/KJV.zip.
"""

import sys
import os
import json
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pysword.modules import SwordModules


# Map SWORD book names to the names used in this project's JSON sources.
# Most names match; only override the ones that differ.
SWORD_TO_PROJECT_BOOK_NAMES = {
    # SWORD and the JSON source both use Roman numeral prefixes (I, II, III)
    # and "Revelation of John", so no overrides are needed for those.
    # Add overrides here only if a SWORD name differs from the JSON source name.
}


def parse_note_text(note_xml):
    """
    Parse an OSIS <note> element and return a clean, human-readable footnote
    string plus structured data.

    Returns a dict with:
        - catch_word: the word/phrase in the verse the note references
        - note_text: a clean human-readable rendering of the note
        - note_type: 'literal' for Hebrew/Greek literal translations,
                     'alternate' for alternative English readings,
                     'mixed' for notes that contain both
    """
    # Extract catch word
    catch_match = re.search(r'<catchWord>(.*?)</catchWord>', note_xml)
    catch_word = catch_match.group(1).replace('…', '...') if catch_match else ""

    # Extract reading types
    literals = re.findall(r'<rdg type="x-literal">(.*?)</rdg>', note_xml)
    alternates = re.findall(r'<rdg type="alternate">(.*?)</rdg>', note_xml)

    # Determine the note type
    if literals and alternates:
        note_type = "mixed"
    elif literals:
        note_type = "literal"
    else:
        note_type = "alternate"

    # Build a clean human-readable note text from the raw XML
    # Remove all XML tags but keep their text content
    text = re.sub(r'<catchWord>.*?</catchWord>', '', note_xml)
    text = re.sub(r'<note[^>]*>', '', text)
    text = re.sub(r'</note>', '', text)
    text = re.sub(r'<rdg[^>]*>', '', text)
    text = re.sub(r'</rdg>', '', text)
    text = text.strip().lstrip(':').strip()
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)

    return {
        "catch_word": catch_word,
        "note_text": text,
        "note_type": note_type,
    }


def extract_footnotes(source_zip):
    """
    Extract all footnotes from a SWORD module, returning them keyed
    by (book_name, chapter, verse).
    """
    modules = SwordModules(source_zip)
    modules.parse_modules()
    bible = modules.get_bible_from_module(list(modules.parse_modules().keys())[0])

    books_ot = bible.get_structure()._books['ot']
    books_nt = bible.get_structure()._books['nt']
    all_books = books_ot + books_nt

    footnotes = {}  # (book_name, chapter, verse) -> [footnote, ...]
    total_notes = 0

    for book in all_books:
        project_name = SWORD_TO_PROJECT_BOOK_NAMES.get(book.name, book.name)
        print(f"  Extracting footnotes from {project_name}...")

        for ch in range(1, book.num_chapters + 1):
            indices = book.get_indicies(ch)
            for v in range(1, len(indices) + 1):
                raw = bible.get(books=[book.name], chapters=[ch], verses=[v], clean=False)
                if not raw or '<note' not in raw:
                    continue

                notes = re.findall(r'<note[^>]*>.*?</note>', raw)
                for note_xml in notes:
                    parsed = parse_note_text(note_xml)
                    key = (project_name, ch, v)
                    if key not in footnotes:
                        footnotes[key] = []
                    footnotes[key].append(parsed)
                    total_notes += 1

    print(f"  Total footnotes extracted: {total_notes}")
    return footnotes


def add_footnotes_to_json(json_path, footnotes):
    """
    Load the source JSON, add a 'footnotes' field to each verse that has
    footnotes, and also add a top-level 'footnotes' array for easy DB import.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Add footnotes inline to each verse
    verses_updated = 0
    for book in data['books']:
        book_name = book['name']
        for chapter in book['chapters']:
            ch_num = chapter['chapter']
            for verse in chapter['verses']:
                v_num = verse['verse']
                key = (book_name, ch_num, v_num)
                if key in footnotes:
                    verse['footnotes'] = footnotes[key]
                    verses_updated += 1

    # Also build a flat top-level footnotes array for easy DB import
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
    print(f"  Added {len(flat_footnotes)} entries to top-level footnotes array")
    return data


def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    source_zip = os.path.join(base_dir, 'sources', 'en', 'KJV', 'KJV.zip')
    json_path = os.path.join(base_dir, 'sources', 'en', 'KJV', 'KJV.json')

    if not os.path.exists(source_zip):
        print(f"Error: SWORD module not found at {source_zip}")
        sys.exit(1)

    if not os.path.exists(json_path):
        print(f"Error: Source JSON not found at {json_path}")
        sys.exit(1)

    print(f"Extracting footnotes from {source_zip}...")
    footnotes = extract_footnotes(source_zip)

    print(f"\nAdding footnotes to {json_path}...")
    add_footnotes_to_json(json_path, footnotes)

    print("\nDone! KJV source JSON now includes footnotes.")


if __name__ == "__main__":
    main()

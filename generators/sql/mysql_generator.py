import os
import json
import unicodedata
import pymysql

class MySQLGenerator:
    def __init__(self, source_dir, format_dir):
        self.source_dir = source_dir
        self.format_dir = format_dir

    def generate(self, language, translation):
        data = self.load_json(language, translation)
        translation_name = self.get_readme_title(language, translation)
        license_info = self.get_license_info(language, translation)
        prepared_data = self.prepare_data(data)
        sql_path = os.path.join(self.format_dir, 'sql', f'{translation}.sql')

        with open(sql_path, 'w', encoding='utf-8') as sqlfile:
            # Write the SQL header
            sqlfile.write(f"-- SQL Dump for {translation_name} ({translation})\n")
            sqlfile.write(f"-- License: {license_info}\n\n")

            # Drop existing tables
            sqlfile.write(f"DROP TABLE IF EXISTS `{translation}_books`;\n")
            sqlfile.write(f"DROP TABLE IF EXISTS `{translation}_verses`;\n")
            sqlfile.write("DROP TABLE IF EXISTS `translations`;\n\n")

            # Create translations table if it doesn't exist
            sqlfile.write("""
            CREATE TABLE IF NOT EXISTS `translations` (
                `translation` VARCHAR(255) PRIMARY KEY,
                `title` VARCHAR(255),
                `license` TEXT
            );
            \n""")
            sqlfile.write(f"""
            INSERT INTO `translations` (`translation`, `title`, `license`)
            SELECT '{translation}', '{translation_name}', '{license_info}'
            WHERE NOT EXISTS (
                SELECT 1 FROM `translations` WHERE `translation` = '{translation}'
            );
            \n""")

            # Create books table
            sqlfile.write(f"""
            CREATE TABLE `{translation}_books` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `name` VARCHAR(255)
            );
            \n""")

            # Insert books
            for book in prepared_data['books']:
                sqlfile.write(f"INSERT INTO `{translation}_books` (`name`) VALUES ('{book['name']}');\n")

            # Create verses table
            sqlfile.write(f"""
            CREATE TABLE `{translation}_verses` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `book_id` INT,
                `chapter` INT,
                `verse` INT,
                `text` TEXT,
                FOREIGN KEY (book_id) REFERENCES `{translation}_books`(id)
            );
            \n""")

            # Insert verses
            for book_index, book in enumerate(prepared_data['books'], start=1):
                for chapter in book['chapters']:
                    for verse in chapter['verses']:
                        escaped_text = pymysql.converters.escape_string(normalize_text(verse['text']))
                        sqlfile.write(f"INSERT INTO `{translation}_verses` (`book_id`, `chapter`, `verse`, `text`) VALUES ({book_index}, {chapter['chapter']}, {verse['verse']}, '{escaped_text}');\n")

            # Generate footnotes table if the source data has footnotes
            if 'footnotes' in prepared_data and len(prepared_data['footnotes']) > 0:
                sqlfile.write(f"\nDROP TABLE IF EXISTS `{translation}_footnotes`;\n")
                sqlfile.write(f"""
            CREATE TABLE `{translation}_footnotes` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `book` VARCHAR(255),
                `chapter` INT,
                `verse` INT,
                `catch_word` VARCHAR(255),
                `note_text` TEXT,
                `note_type` VARCHAR(50),
                INDEX (`book`)
            );
            \n""")

                for fn in prepared_data['footnotes']:
                    escaped_catch = pymysql.converters.escape_string(fn['catch_word'])
                    escaped_note = pymysql.converters.escape_string(fn['note_text'])
                    escaped_book = pymysql.converters.escape_string(fn['book'])
                    sqlfile.write(f"INSERT INTO `{translation}_footnotes` (`book`, `chapter`, `verse`, `catch_word`, `note_text`, `note_type`) VALUES ('{escaped_book}', {fn['chapter']}, {fn['verse']}, '{escaped_catch}', '{escaped_note}', '{fn['note_type']}');\n")

        print(f"SQL dump for {translation_name} ({translation}) generated at {sql_path}")

    def get_license_info(self, language, translation):
        readme_path = os.path.join(self.source_dir, language, translation, "README.md")
        with open(readme_path, 'r', encoding='utf-8') as file:
            for line in file:
                if line.startswith("**License:**"):
                    return line.split("**License:** ")[1].strip()
        return "Unknown"

    def load_json(self, language, translation):
        json_path = os.path.join(self.source_dir, language, translation, f"{translation}.json")
        with open(json_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def get_readme_title(self, language, translation):
        readme_path = os.path.join(self.source_dir, language, translation, "README.md")
        with open(readme_path, 'r', encoding='utf-8') as file:
            return file.readline().strip()

    def prepare_data(self, data):
        # This method should prepare and return the data in the required format
        return data

def normalize_text(text):
    # Replace common characters
    text = text.replace("Æ", "'")
    
    # Unicode normalization
    text = unicodedata.normalize('NFKD', text)
    
    return text

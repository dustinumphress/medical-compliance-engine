import sqlite3
import csv
import glob
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DB is in parent directory of 'execution'
DB_PATH = os.path.join(BASE_DIR, '../coding_rules.db')

INPUT_DIR = 'inputs'
if not os.path.exists(INPUT_DIR):
    os.makedirs(INPUT_DIR)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # NCCI Edits Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS ncci_edits (
            column1_code TEXT,
            column2_code TEXT,
            effective_date TEXT,
            deletion_date TEXT,
            modifier_indicator TEXT,
            rationale TEXT,
            PRIMARY KEY (column1_code, column2_code)
        )
    ''')
    
    # MUE Limits Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS mue_limits (
            hcpcs_code TEXT PRIMARY KEY,
            max_units INTEGER,
            mai TEXT,
            rationale TEXT
        )
    ''')
    
    # CPT Descriptions Table (NEW)
    c.execute('''
        CREATE TABLE IF NOT EXISTS cpt_codes (
            code TEXT PRIMARY KEY,
            short_desc TEXT
        )
    ''')
    
    conn.commit()
    return conn

def ingest_mue(conn, csv_path):
    print(f"Ingesting MUE from {csv_path}...")
    cursor = conn.cursor()
    count = 0
    
    try:
        # Try cp1252 (common for Excel/Windows CSVs) if utf-8 fails
        with open(csv_path, 'r', encoding='cp1252', errors='replace') as f:
            reader = csv.reader(f)
            
            for row in reader:
                if len(row) < 3: continue
                code = row[0].strip()
                
                # Loose heuristic: HCPCS/CPT codes are 5 chars long.
                # headers are usually long strings.
                if len(code) != 5: continue
                
                # Ensure it looks like a code (digit or char start)
                if not code[0].isalnum(): continue
                
                try:
                    # Corrected Schema based on inspection:
                    # Col 0: Code
                    # Col 1: MUE Value (Int)
                    # Col 2: MAI (String/Int)
                    # Col 3: Rationale
                    mue = int(row[1].strip())
                    mai = row[2].strip()
                    rationale = row[3].strip() if len(row) > 3 else ""
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO mue_limits (hcpcs_code, max_units, mai, rationale)
                        VALUES (?, ?, ?, ?)
                    ''', (code, mue, mai, rationale))
                    count += 1
                except ValueError:
                    continue 
        conn.commit()
        print(f"  Imported {count} MUE records.")
    except Exception as e:
        print(f"Error reading MUE: {e}")

def ingest_ncci(conn, txt_patterns):
    print("Ingesting NCCI Edits...")
    cursor = conn.cursor()
    total_count = 0
    
    files = []
    for pattern in txt_patterns:
        files.extend(glob.glob(pattern))
        
    for file_path in files:
        print(f"  Reading {file_path}...")
        file_count = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # NCCI files are often tab or space delimited.
                # Format: Col1 Col2 EffDate DelDate ModInd ...
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 5: continue
                    
                    c1 = parts[0]
                    c2 = parts[1]
                    
                    # Basic validation: codes are 5 chars
                    if len(c1) != 5 or len(c2) != 5: continue
                    
                    # 20220101 format date check to verify it's a data row
                    if not parts[2].isdigit(): continue

                    eff_date = parts[2]
                    del_date = parts[3]
                    mod_ind = parts[4]
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO ncci_edits 
                        (column1_code, column2_code, effective_date, deletion_date, modifier_indicator)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (c1, c2, eff_date, del_date, mod_ind))
                    file_count += 1
            
            print(f"    - Added {file_count} edits.")
            total_count += file_count
            conn.commit()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            
    print(f"Total NCCI Edits imported: {total_count}")

def ingest_cpt_descriptions(conn):
    filename = os.path.join(BASE_DIR, "PPRRVU2026_Jan_nonQPP.txt")
    if not os.path.exists(filename):
        print(f"Skipping CPT Descriptions: {filename} not found.")
        return

    print(f"Ingesting CPT Descriptions from {filename}...")
    c = conn.cursor()
    
    import re
    # Pattern: Code (5 chars) + Space + Desc (variable) + Space + Status (1 char)
    pattern = re.compile(r"^(\w{5})\s+(.+?)\s{2,}")
    
    count = 0
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith("HDR"): continue
            
            match = pattern.search(line)
            if match:
                code = match.group(1)
                desc = match.group(2).strip()
                
                try:
                    c.execute("INSERT OR REPLACE INTO cpt_codes VALUES (?, ?)", (code, desc))
                    count += 1
                except sqlite3.Error:
                    pass

    conn.commit()
    print(f"Inserted {count} CPT descriptions.")

if __name__ == "__main__":
    conn = init_db()
    
    # 1. Ingest MUE
    mue_files = glob.glob("MCR_MUE_*.csv")
    if mue_files:
        ingest_mue(conn, mue_files[0])
    
    # 2. Ingest NCCI
    # Matches ccipra-v320r0-f1.TXT etc.
    ingest_ncci(conn, ["ccipra-*.TXT", "ccipra-*.txt"])
    
    # 3. Ingest CPT Descriptions (NEW)
    ingest_cpt_descriptions(conn)
    
    conn.close()
    print("Database build complete.")

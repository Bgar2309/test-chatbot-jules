import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# --- Environment and Client Initialization ---
load_dotenv()

# --- Constants ---
NEW_FILES_DIR = "nouveaux_fichiers/"
ARCHIVE_DIR = "archives/"
REVIEW_DIR = "for_review/"
FINAL_COLUMNS = ["STENCIL", "ORIENTATION", "INVOICE #", "CONE SIZE", "# OF LINES", "MISC. INFO", "DATE", "SILKSCREEN"]

# --- Core Functions ---

def clean_dataframe(df):
    df.dropna(how='all', inplace=True)
    if df.empty:
        return df
    df.columns = [str(col).strip().upper() for col in df.columns]
    if 'STENCILS' in df.columns:
        df.rename(columns={'STENCILS': 'STENCIL'}, inplace=True)
    return df

def find_new_file():
    try:
        files = [os.path.join(NEW_FILES_DIR, f) for f in os.listdir(NEW_FILES_DIR) if f.endswith(('.xlsx', '.xls'))]
        if not files:
            return None
        return min(files, key=os.path.getmtime)
    except FileNotFoundError:
        print(f"Error: The directory '{NEW_FILES_DIR}' was not found.")
        return None

def load_and_clean_excel_file(excel_path):
    all_cleaned_dfs = []
    with pd.ExcelFile(excel_path) as xls:
        sheets_to_process = xls.sheet_names[1:]
        print(f"Processing sheets: {sheets_to_process}")
        for sheet in sheets_to_process:
            df = pd.read_excel(xls, sheet_name=sheet)
            if not df.empty:
                cleaned_df = clean_dataframe(df)
                if not cleaned_df.empty:
                    all_cleaned_dfs.append(cleaned_df)
    if not all_cleaned_dfs:
        return pd.DataFrame(columns=FINAL_COLUMNS)
    combined_df = pd.concat(all_cleaned_dfs, ignore_index=True)
    final_df = pd.DataFrame()
    for col in FINAL_COLUMNS:
        final_df[col] = combined_df.get(col)
    return final_df

def create_unique_ids(df, source_name_for_debug=""):
    if df.empty:
        return df
    df['item_identifier'] = df['STENCIL'].fillna(df['SILKSCREEN'])
    df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')
    df.dropna(subset=['item_identifier', 'DATE'], inplace=True)

    # Normalize the identifier AFTER dropping NaNs to prevent 'nan' strings.
    df['item_identifier'] = df['item_identifier'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip().str.replace(r'\.0$', '', regex=True)

    df['date_str'] = df['DATE'].dt.strftime('%Y-%m-%d')
    df['unique_id'] = df['item_identifier'] + '_' + df['date_str']

    # Save the intermediate data for debugging if a source name is provided
    if source_name_for_debug:
        debug_filename = f"donnees_{source_name_for_debug}.csv"
        # Include item_identifier to make debugging easier
        df.to_csv(debug_filename, index=False, columns=['item_identifier', 'date_str', 'unique_id'])
        print(f"Generated debug file: {debug_filename}")

    df.drop(columns=['item_identifier', 'date_str'], inplace=True)
    return df

def get_existing_data_from_supabase_for_debug():
    print("Fetching existing data from Supabase for debugging...")
    try:
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            print("Error: Supabase credentials not found in .env file.")
            return None
        supabase = create_client(supabase_url, supabase_key)
        response = supabase.table('inventory').select('stencil', 'silkscreen', 'date_of_inventory').execute()
        if response.data:
            db_df = pd.DataFrame(response.data).rename(columns={'stencil': 'STENCIL', 'silkscreen': 'SILKSCREEN', 'date_of_inventory': 'DATE'})
            # Pass a source name to generate debug file
            create_unique_ids(db_df, source_name_for_debug="supabase")
            return True # Indicate success
        else:
            print("No data found in Supabase table 'inventory'.")
            # Create an empty debug file for consistency
            pd.DataFrame().to_csv("donnees_supabase.csv", index=False)
            return True
    except Exception as e:
        print(f"An error occurred while fetching data from Supabase: {e}")
        return None

# --- Main Execution Logic for Debugging ---
def main_debug():
    print("--- Running in DEBUG mode ---")

    # 1. Generate debug file from Supabase
    if not get_existing_data_from_supabase_for_debug():
        print("Could not generate debug file from Supabase. Aborting.")
        return

    # 2. Generate debug file from local Excel file
    new_file_path = find_new_file()
    if not new_file_path:
        print("No new Excel file found to process.")
        return
    print(f"Found new file: {new_file_path}")

    try:
        data_from_excel = load_and_clean_excel_file(new_file_path)
        # Pass a source name to generate debug file
        create_unique_ids(data_from_excel, source_name_for_debug="excel")
    except Exception as e:
        print(f"An error occurred while processing the Excel file: {e}")

    print("\n--- Debug file generation complete. ---")
    print("Please provide the contents of 'donnees_supabase.csv' and 'donnees_excel.csv'.")

if __name__ == "__main__":
    os.makedirs(NEW_FILES_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    main_debug()

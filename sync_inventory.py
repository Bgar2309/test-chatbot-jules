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

def create_unique_ids(df):
    if df.empty:
        return df
    df['item_identifier'] = df['STENCIL'].fillna(df['SILKSCREEN'])
    df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')
    df.dropna(subset=['item_identifier', 'DATE'], inplace=True)

    # Normalize the identifier AFTER dropping NaNs to prevent 'nan' strings.
    # This handles multiple whitespace characters, leading/trailing spaces, and trailing '.0'
    df['item_identifier'] = df['item_identifier'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip().str.replace(r'\.0$', '', regex=True)

    df['date_str'] = df['DATE'].dt.strftime('%Y-%m-%d')
    df['unique_id'] = df['item_identifier'] + '_' + df['date_str']
    df.drop(columns=['item_identifier', 'date_str'], inplace=True)
    return df

def get_existing_data_from_supabase():
    print("Fetching existing data from Supabase...")
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
            db_df_with_ids = create_unique_ids(db_df)
            return set(db_df_with_ids['unique_id'])
        else:
            return set()
    except Exception as e:
        print(f"An error occurred while fetching data from Supabase: {e}")
        return None

def filter_new_entries(df, existing_ids_set):
    if df.empty:
        return df
    new_entries_df = df[~df['unique_id'].isin(existing_ids_set)].copy()
    print(f"Comparison complete. Found {len(new_entries_df)} new entries.")
    return new_entries_df

def insert_data_to_supabase(df):
    if df.empty:
        print("No data to insert.")
        return
    df_to_insert = df.drop(columns=['unique_id']).rename(columns={"STENCIL": "stencil", "ORIENTATION": "orientation", "INVOICE #": "invoice_number", "CONE SIZE": "cone_size", "# OF LINES": "number_of_lines", "MISC. INFO": "misc_info", "DATE": "date_of_inventory", "SILKSCREEN": "silkscreen"})
    records = df_to_insert.where(pd.notna(df_to_insert), None).to_dict(orient="records")
    try:
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            print("Error: Supabase credentials not found in .env file.")
            return
        supabase = create_client(supabase_url, supabase_key)
        print(f"Inserting {len(records)} new records...")
        response = supabase.table("inventory").insert(records).execute()
        if response.data:
            print(f"Successfully inserted {len(response.data)} records.")
    except Exception as e:
        print(f"An error occurred during data insertion: {e}")

def request_user_validation(new_entries_df):
    if new_entries_df.empty:
        print("No new entries to insert.")
        return False
    os.makedirs(REVIEW_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_filepath = os.path.join(REVIEW_DIR, f"new_entries_for_review_{timestamp}.csv")
    new_entries_df.to_csv(review_filepath, index=False)
    print(f"\n--- User Validation Required ---\nFound {len(new_entries_df)} new entries. Review file: {review_filepath}")
    print("\nPreview of new entries:\n", new_entries_df.to_string())
    try:
        user_response = input("\nDo you want to insert these entries? (yes/no): ").lower().strip()
        if user_response == 'yes':
            return True
        return False
    except KeyboardInterrupt:
        return False

def archive_processed_file(file_path):
    if not os.path.exists(file_path):
        return
    filename = os.path.basename(file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(ARCHIVE_DIR, f"{timestamp}_{filename}")
    try:
        os.rename(file_path, archive_path)
        print(f"Successfully archived processed file to: {archive_path}")
    except OSError as e:
        print(f"Error archiving file {file_path}: {e}")

def main():
    print("--- Starting Inventory Sync Process ---")

    existing_ids = get_existing_data_from_supabase()
    if existing_ids is None:
        return
    print(f"Found {len(existing_ids)} existing unique entries in the database.")

    new_file_path = find_new_file()
    if not new_file_path:
        print("No new files to process.")
        return
    print(f"Found new file: {new_file_path}")

    try:
        data_from_excel = load_and_clean_excel_file(new_file_path)
        data_with_ids = create_unique_ids(data_from_excel)

        new_entries = filter_new_entries(data_with_ids, existing_ids)

        if request_user_validation(new_entries):
            insert_data_to_supabase(new_entries)

    except Exception as e:
        print(f"An error occurred while processing the file {new_file_path}: {e}")
        return

    archive_processed_file(new_file_path)
    print("--- Sync Process Finished ---")

if __name__ == "__main__":
    os.makedirs(NEW_FILES_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    main()
